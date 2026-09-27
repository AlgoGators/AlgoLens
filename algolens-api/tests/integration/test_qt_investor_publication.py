"""Separate explicit investor release; real owned SQL, HTTP and native processing."""
from copy import deepcopy
from pathlib import Path
import psycopg2
import pytest
from algolens.application.portfolio.qt_investor_publication import QtInvestorPublicationService
from algolens.infrastructure.portfolio.qt_investor_publication import QtInvestorPublicationRepository
from tests.integration.test_qt_connected_workflow import (
    connected_db, preview_db, a3_db, prepare, observe, desk, query)


@pytest.fixture
def release_db(connected_db, monkeypatch):
    query(connected_db, (Path(__file__).resolve().parents[2] /
                        'migrations/006_qt_investor_publication.sql').read_text())
    import algolens.adapters.http.qt_workflow as routes
    monkeypatch.setattr(routes, '_publication_service', lambda: QtInvestorPublicationService(
        routes._read_service(), QtInvestorPublicationRepository(lambda: psycopg2.connect(connected_db))))
    return connected_db


def grant(dsn, actor=101, public=False):
    query(dsn, "INSERT INTO trading.qt_investor_publication_policy(book_id,enabled,public_read_enabled,version) "
               "VALUES('BOOK',true,%s,1)", (public,))
    query(dsn, "INSERT INTO trading.qt_investor_publish_grants(book_id,user_id,active,version) "
               "VALUES('BOOK',%s,true,1)", (actor,))


def release(http, decision, **body):
    return http['browser'].post(
        '/portfolio/qt-decisions/' + decision['decision_id'] + '/publish',
        headers=http['headers'], json={
            'action': 'publish_qt_snapshot',
            'expected_selected_book_digest': decision['selected_book_digest'],
            **body,
        })


def public(http, preview):
    return http['browser'].get('/portfolio/qt-published-books/BOOK/' + preview['source_day'])


def process(dsn, preview, decision):
    observe(dsn, preview, decision, '7')
    result = desk(decision)
    assert result.returncode == 0, result.stdout + result.stderr


def test_desk_confirmation_does_not_grant_investor_publish(release_db, monkeypatch):
    http, preview, decision = prepare(release_db, '7', monkeypatch)
    response = release(http, decision)
    assert response.status_code == 403, response.json
    assert response.json['error']['code'] == 'authorization_changed'
    assert query(release_db, 'SELECT count(*) FROM trading.qt_desk_receipts') == [(0,)]
    assert query(release_db, 'SELECT count(*) FROM trading.qt_investor_publications') == [(0,)]


def test_confirmation_and_processing_do_not_implicitly_release(release_db, monkeypatch):
    http, preview, decision = prepare(release_db, '7', monkeypatch)
    grant(release_db, public=True)
    assert release(http, decision).status_code == 409
    assert public(http, preview).status_code == 404
    process(release_db, preview, decision)
    assert public(http, preview).status_code == 404
    assert query(release_db, 'SELECT count(*) FROM trading.qt_investor_publications') == [(0,)]


def test_explicit_release_freezes_exact_quantity_without_changing_existing_rows(release_db, monkeypatch):
    http, preview, decision = prepare(release_db, '7', monkeypatch)
    grant(release_db)
    process(release_db, preview, decision)
    tables = ('positions', 'position_overrides', 'qt_drafts', 'qt_previews', 'qt_decisions',
              'qt_desk_receipts', 'qt_desk_results', 'qt_execution_observations')
    before = {name: query(release_db, 'SELECT to_jsonb(t) FROM trading.' + name +
                         ' t ORDER BY to_jsonb(t)::text') for name in tables}
    response = release(http, decision)
    assert response.status_code == 200, response.json
    frozen = deepcopy(response.json)
    assert [row['quantity_exact'] for row in frozen['snapshot']['positions']] == ['7']
    assert frozen['portfolio_type'] == 'qt'
    assert public(http, preview).status_code == 404  # public audience remains separately disabled
    assert query(release_db, 'SELECT published_by,policy_version,grant_version FROM trading.qt_investor_publications') == [(101, 1, 1)]
    assert {name: query(release_db, 'SELECT to_jsonb(t) FROM trading.' + name +
                       ' t ORDER BY to_jsonb(t)::text') for name in tables} == before
    query(release_db, "UPDATE trading.qt_investor_publication_policy SET public_read_enabled=true,version=2")
    public_response = public(http, preview)
    assert public_response.status_code == 200 and public_response.json == frozen
    assert public_response.headers['Cache-Control'] == 'no-store'
    assert release(http, decision).json == frozen
    assert query(release_db, 'SELECT count(*) FROM trading.qt_investor_publications') == [(1,)]
    # Subsequent mutable desk activity never rewrites the released audience view.
    query(release_db, "UPDATE trading.positions SET quantity=9 WHERE portfolio_type='qt'")
    assert public(http, preview).json == frozen
    assert release(http, decision).json == frozen
    assert not http['browser'].get('/portfolio/qt-decisions/' + decision['decision_id']).json['report_ready']


@pytest.mark.parametrize('mutation', [
    "UPDATE trading.positions SET quantity=9 WHERE portfolio_type='qt'",
    "UPDATE trading.qt_source_policies SET enabled=false,version=version+1 WHERE purpose='execution'",
])
def test_stale_processing_evidence_cannot_be_released(release_db, monkeypatch, mutation):
    http, preview, decision = prepare(release_db, '7', monkeypatch)
    grant(release_db, public=True)
    process(release_db, preview, decision)
    query(release_db, mutation)
    response = release(http, decision)
    assert response.status_code == 409, response.json
    assert query(release_db, 'SELECT count(*) FROM trading.qt_investor_publications') == [(0,)]
    assert public(http, preview).status_code == 404


def test_dedicated_publisher_requires_current_grant_but_no_desk_edit_grant(release_db, monkeypatch):
    http, preview, decision = prepare(release_db, '7', monkeypatch)
    process(release_db, preview, decision)
    # The owned fixture recreates trading but deliberately retains auth.users.
    # Establish this case's explicit role even after another case used actor303.
    query(release_db, "INSERT INTO auth.users(id,role) VALUES(303,'admin') "
                      "ON CONFLICT(id) DO UPDATE SET role=excluded.role")
    assert query(release_db, "SELECT count(*) FROM trading.qt_action_grants WHERE user_id=303") == [(0,)]
    grant(release_db, actor=303, public=True)
    browser, headers = http['clients'](303)
    publisher = {'browser': browser, 'headers': headers}
    assert release(http, decision).status_code == 403
    response = release(publisher, decision)
    assert response.status_code == 200, response.json
    assert query(release_db, 'SELECT published_by FROM trading.qt_investor_publications') == [(303,)]
    query(release_db, 'UPDATE trading.qt_investor_publish_grants SET active=false,version=2')
    assert release(publisher, decision).status_code == 403
    query(release_db, 'UPDATE trading.qt_investor_publication_policy SET public_read_enabled=false,version=2')
    assert public(http, preview).status_code == 404


def test_release_requires_csrf_exact_request_and_matching_decision(release_db, monkeypatch):
    http, preview, decision = prepare(release_db, '7', monkeypatch)
    grant(release_db)
    process(release_db, preview, decision)
    path = '/portfolio/qt-decisions/' + decision['decision_id'] + '/publish'
    assert http['browser'].post(path, json={}).status_code == 401
    assert release(http, decision, recipient='someone').status_code == 400
    assert release(http, decision, expected_selected_book_digest='0' * 64).status_code == 409
    assert query(release_db, 'SELECT count(*) FROM trading.qt_investor_publications') == [(0,)]
    assert release(http, decision).status_code == 200


def test_released_snapshot_replay_survives_retired_registry(release_db, monkeypatch):
    http, preview, decision = prepare(release_db, '7', monkeypatch)
    grant(release_db, public=True)
    process(release_db, preview, decision)
    response = release(http, decision)
    assert response.status_code == 200, response.json
    query(release_db, 'UPDATE trading.strategy_registry SET is_active=false')
    replay = release(http, decision)
    assert replay.status_code == 200, replay.json
    assert replay.json == response.json


@pytest.mark.parametrize('statement', [
    "UPDATE trading.qt_investor_publications SET published_by=101",
    "DELETE FROM trading.qt_investor_publications",
    "TRUNCATE trading.qt_investor_publications",
])
def test_released_day_is_append_only(release_db, monkeypatch, statement):
    http, preview, decision = prepare(release_db, '7', monkeypatch)
    grant(release_db, public=True)
    process(release_db, preview, decision)
    response = release(http, decision)
    assert response.status_code == 200, response.json
    with pytest.raises(psycopg2.Error, match='immutable'):
        query(release_db, statement)
    assert public(http, preview).json == response.json
