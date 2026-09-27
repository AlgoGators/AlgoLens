"""Actual owned SQL and verified native preview through cookie/CSRF HTTP.

The reusable harness runs Flask's test client in process; it starts no server.
All account, grant and mapping rows are explicitly synthetic owned fixtures.
"""
from datetime import date
from types import SimpleNamespace
from uuid import uuid4
import psycopg2
from psycopg2.extras import Json
import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token, get_csrf_token
from algolens.domain.identity.models import user_from_row
from algolens.infrastructure.config.dependencies import create_qt_decision_read_service
from algolens.infrastructure.portfolio.qt_decision_read_repository import QtDecisionReadRepository
from algolens.domain.portfolio.position_edit import validate_position_payload
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.portfolio.repositories import PostgresPortfolioRepository
from tests.integration.test_qt_preview_evaluator import preview_db, saved_draft, authority, query
from tests.integration.test_qt_a3_read_set_postgres import a3_db


def seed_http_approvers(dsn):
    query(dsn, """INSERT INTO auth.users(id,role) VALUES(202,'general_member')
        ON CONFLICT(id) DO UPDATE SET role=excluded.role;
        INSERT INTO trading.qt_action_grants(user_id,capability,active,version)
          VALUES(101,'qt_approve',true,1),(202,'qt_approve',true,1);
        INSERT INTO trading.qt_approver_allowlist(person_id,display_label,user_id,active,mapping_version)
          VALUES('eric_shwartz','eric shwartz',101,true,1),('john_riley','john riley',202,true,1);""")


def http_harness(dsn, service, monkeypatch):
    """Reusable real-session HTTP app and actor client factory for root E2E."""
    import algolens.adapters.http.qt_workflow as routes
    class OwnedUsers:
        def find_by_id(self, identity):
            rows = query(dsn, 'SELECT id,role FROM auth.users WHERE id=%s', (identity,))
            return user_from_row({'id': rows[0][0], 'role': rows[0][1], 'email': 'synthetic@owned.test'}) if rows else None
    monkeypatch.setattr(routes, 'create_identity_dependencies', lambda: (OwnedUsers(), None, None))
    monkeypatch.setattr(routes, '_workflow_service', lambda: service)
    reader = create_qt_decision_read_service(QtDecisionReadRepository(lambda: psycopg2.connect(dsn)),
                                   evaluator_bundle_directory=service.evaluator_bundle_directory)
    monkeypatch.setattr(routes, '_read_service', lambda: reader)
    app = Flask(__name__)
    app.config.update(TESTING=True, JWT_SECRET_KEY='synthetic-owned-pg-session-key-' * 3,
        JWT_TOKEN_LOCATION=['cookies'], JWT_COOKIE_CSRF_PROTECT=True, DEV_MODE=True,
        QT_EVALUATOR_BUNDLE_DIR=service.evaluator_bundle_directory)
    JWTManager(app)
    app.register_blueprint(routes.qt_workflow_bp, url_prefix='/portfolio')
    def actor_client(actor_id):
        with app.app_context():
            token = create_access_token(identity=str(actor_id))
            csrf = get_csrf_token(token)
        browser = app.test_client()
        browser.set_cookie('access_token_cookie', token)
        return browser, {'X-CSRF-TOKEN': csrf}
    return app, actor_client, reader


def confirm_http(browser, headers, preview):
    return browser.post('/portfolio/qt-previews/' + preview['preview_id'] + '/confirm', headers=headers,
        json={'action': 'confirm_selected_book', 'expected_digest': preview['payload_digest'],
              'idempotency_key': str(uuid4()), 'acknowledge_warnings': preview['requires_override']})


def test_actual_cookie_csrf_and_readonly_book_discovery(preview_db, monkeypatch):
    service, request = saved_draft(preview_db)
    authority(preview_db)
    _, clients, _ = http_harness(preview_db, service, monkeypatch)
    browser, headers = clients(101)
    for suffix in ('proposal', 'draft'):
        assert browser.get('/portfolio/qt-books/BOOK/' + suffix).status_code == 200
    source_day = query(preview_db, "SELECT (clock_timestamp() AT TIME ZONE 'UTC')::date")[0][0].isoformat()
    empty = browser.get('/portfolio/qt-books/BOOK/decision?source_day=' + source_day)
    assert empty.status_code == 200, empty.json
    assert empty.json == {'schema_version': 'qt-workflow/v1', 'book_id': 'BOOK', 'source_day': source_day,
                          'decision': None, 'preview': None}
    assert browser.post('/portfolio/qt-previews', json=request).status_code == 401
    assert query(preview_db, 'SELECT count(*) FROM trading.qt_previews') == [(0,)]
    response = browser.post('/portfolio/qt-previews', json=request, headers=headers)
    assert response.status_code == 200, response.json
    preview = response.json
    assert preview['confirmable'] is True
    assert browser.post('/portfolio/qt-previews/' + preview['preview_id'] + '/confirm', json={}).status_code == 401
    confirmed = confirm_http(browser, headers, preview)
    assert confirmed.status_code == 200, confirmed.json
    decision = confirmed.json
    view = browser.get('/portfolio/qt-books/BOOK/decision?source_day=' + source_day)
    assert view.status_code == 200, view.json
    assert view.json['preview'] == preview
    assert view.json['decision']['decision_id'] == decision['decision_id']
    assert view.json['decision']['report_ready'] is False
    assert query(preview_db, 'SELECT count(*) FROM trading.position_overrides') == [(0,)]


def test_actual_two_people_approve_known_breach_then_discover_same_immutable_preview(preview_db, monkeypatch):
    seed_http_approvers(preview_db)
    service, request = saved_draft(preview_db)
    authority(preview_db, case='allowed_breach')
    _, clients, _ = http_harness(preview_db, service, monkeypatch)
    first, first_headers = clients(101)
    second, second_headers = clients(202)
    preview_response = first.post('/portfolio/qt-previews', json=request, headers=first_headers)
    assert preview_response.status_code == 200, preview_response.json
    preview = preview_response.json
    assert preview['requires_override'] is True
    pending_response = confirm_http(first, first_headers, preview)
    assert pending_response.status_code == 200, pending_response.json
    pending = pending_response.json
    day = preview['source_day']
    discovered = second.get('/portfolio/qt-books/BOOK/decision?source_day=' + day)
    assert discovered.status_code == 200, discovered.json
    assert discovered.json['decision']['decision_id'] == pending['decision_id']
    assert discovered.json['decision']['can_approve'] is True
    assert discovered.json['preview'] == preview
    assert second.get('/portfolio/qt-books/BOOK/draft').status_code == 200
    assert second.post('/portfolio/qt-previews', json=request, headers=second_headers).status_code == 403
    positions = query(preview_db, 'SELECT row_to_json(p)::text FROM trading.positions p ORDER BY symbol,portfolio_type')
    path = '/portfolio/qt-override-requests/' + pending['request_id'] + '/approvals'
    approved = first.post(path, headers=first_headers, json={'action': 'approve', 'idempotency_key': str(uuid4())})
    assert approved.status_code == 200, approved.json
    assert approved.json['approvals_count'] == 1
    assert second.post(path, json={'action': 'approve', 'idempotency_key': str(uuid4())}).status_code == 401
    approved = second.post(path, headers=second_headers, json={'action': 'approve', 'idempotency_key': str(uuid4())})
    assert approved.status_code == 200, approved.json
    assert approved.json['status'] == 'confirmed_decision' and approved.json['approvals_count'] == 2
    assert query(preview_db, 'SELECT status FROM trading.qt_decisions') == [('confirmed_decision',)]
    assert query(preview_db, 'SELECT state FROM trading.qt_previews') == [('confirmed_decision',)]
    discovered = second.get('/portfolio/qt-books/BOOK/decision?source_day=' + day)
    assert discovered.status_code == 200, discovered.json
    assert discovered.json['preview'] == preview and discovered.json['decision']['report_ready'] is False
    assert query(preview_db, 'SELECT row_to_json(p)::text FROM trading.positions p ORDER BY symbol,portfolio_type') == positions
    query(preview_db, 'INSERT INTO trading.qt_desk_receipts '
        '(decision_id,attempt_id,status,published_book_digest,processed_at,publication_payload,report_eligibility_status,report_reason_codes,row_manifest_digest) '
        "VALUES(%s,%s,'processed',%s,clock_timestamp(),%s,'eligible','[]',%s)",
        (pending['decision_id'], str(uuid4()), pending['selected_book_digest'], Json({}), '0' * 64))
    def saved_state():
        tables = ('positions', 'position_overrides', 'qt_drafts', 'qt_draft_heads',
                  'qt_idempotency', 'qt_previews', 'qt_decisions', 'qt_override_requests',
                  'qt_override_approvals', 'qt_desk_receipts', 'qt_desk_results',
                  'qt_execution_observations')
        return {table: query(preview_db, 'SELECT to_jsonb(t)::text FROM trading.' + table +
                             ' t ORDER BY to_jsonb(t)::text') for table in tables}

    # A processed receipt without an observation identity cannot establish
    # source lineage. Refuse the workflow before advertising report readiness.
    before_malformed_read = saved_state()
    malformed = second.get('/portfolio/qt-decisions/' + pending['decision_id'])
    assert malformed.status_code == 503, malformed.json
    assert malformed.json['error']['code'] == 'workflow_unavailable'
    assert 'report_ready' not in malformed.json
    assert saved_state() == before_malformed_read


@pytest.mark.parametrize('mutation', ['role', 'grant'])
def test_actual_current_session_authority_revocation_blocks_get(preview_db, monkeypatch, mutation):
    service, _ = saved_draft(preview_db)
    _, clients, _ = http_harness(preview_db, service, monkeypatch)
    browser, _ = clients(101)
    sql = "UPDATE auth.users SET role='guest' WHERE id=101" if mutation == 'role' else "UPDATE trading.qt_action_grants SET active=false WHERE user_id=101"
    query(preview_db, sql)
    assert browser.get('/portfolio/qt-books/BOOK/proposal').status_code == 403


def test_actual_capability_change_after_adapter_check_blocks_repository_before_write(preview_db, monkeypatch):
    service, _ = saved_draft(preview_db)
    _, _, reader = http_harness(preview_db, service, monkeypatch)
    query(preview_db, 'UPDATE trading.qt_workflow_capabilities SET enabled=false,version=2')
    reader.ensure_legacy_disabled('BOOK', 101)
    query(preview_db, 'UPDATE trading.qt_workflow_capabilities SET enabled=true,version=3')
    before = query(preview_db, 'SELECT row_to_json(p)::text FROM trading.positions p ORDER BY symbol,portfolio_type')
    normalized = validate_position_payload({'strategy_id': 'ui-one', 'portfolio_id': 'BOOK', 'symbol': 'SYN',
        'quantity': '5', 'average_price': '100', 'reason': 'synthetic legacy race'})
    with pytest.raises(QtWorkflowError) as exc:
        PostgresPortfolioRepository(lambda: psycopg2.connect(preview_db)).write_qt_position(
            'engine-one', 'BOOK', normalized, '101', lambda *a: pytest.fail('risk reached before cutover gate'))
    assert exc.value.code == 'preview_required'
    assert query(preview_db, 'SELECT row_to_json(p)::text FROM trading.positions p ORDER BY symbol,portfolio_type') == before
    assert query(preview_db, 'SELECT count(*) FROM trading.position_overrides') == [(0,)]
