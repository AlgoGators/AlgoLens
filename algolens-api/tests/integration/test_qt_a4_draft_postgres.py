"""A4 draft CAS on the owned disposable PostgreSQL schema."""

import psycopg2
import pytest

from algolens.infrastructure.config.dependencies import create_qt_workflow_service
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.portfolio.qt_workflow_repository import QtWorkflowRepository
from tests.integration.test_qt_a3_read_set_postgres import a3_db


def _query(dsn, sql, params=()):
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall() if cursor.description else None


@pytest.fixture
def draft_db(a3_db):
    _query(a3_db, '''CREATE SCHEMA IF NOT EXISTS metadata;
        CREATE TABLE IF NOT EXISTS metadata.contract_metadata (
            "Databento Symbol" text, "IB Symbol" text, "Asset Type" text);
        TRUNCATE metadata.contract_metadata;
        INSERT INTO metadata.contract_metadata VALUES
          ('SYN', 'SYN', 'FUTURE'), ('NEW', 'NEW', 'EQUITY');''')
    return a3_db


def _choice(key, quantity):
    return {"key": key, "quantity_exact": quantity}


def test_draft_save_cas_replay_and_physical_position_invariance(draft_db):
    service = create_qt_workflow_service(QtWorkflowRepository(lambda: psycopg2.connect(draft_db)))
    initial = service.get_draft("BOOK", 101).to_wire()
    assert initial["state"] == "absent"
    proposal = initial["selection_rows"][0]["key"]
    new = {**proposal, "symbol": "NEW"}
    before_positions = _query(draft_db, "SELECT row_to_json(p)::text FROM trading.positions p ORDER BY symbol, portfolio_type")
    before_audits = _query(draft_db, "SELECT count(*) FROM trading.position_overrides")
    request = {
        "expected_source_digest": initial["source_digest"],
        "expected_provenance_digest": initial["provenance_digest"],
        "expected_draft_revision": 0,
        "idempotency_key": "00000000-0000-4000-8000-000000000044",
        "rationale": "Exercise exact draft persistence.",
        "selection_rows": [_choice(proposal, "2"), _choice(new, "0.125")],
    }
    saved = service.save_draft("BOOK", 101, request).to_wire()
    assert saved["state"] == "saved" and saved["draft_revision"] == 1
    assert service.get_draft("BOOK", 101).to_wire() == saved
    assert next(item for item in saved["selection_rows"] if item["key"]["symbol"] == "NEW")["basis_status"] == "unfilled"
    assert service.save_draft("BOOK", 101, request).to_wire() == saved
    assert _query(draft_db, "SELECT count(*) FROM trading.qt_drafts") == [(1,)]
    assert _query(draft_db, "SELECT revision FROM trading.qt_draft_heads") == [(1,)]
    with pytest.raises(QtWorkflowError) as stale:
        service.save_draft("BOOK", 101, {**request,
            "idempotency_key": "00000000-0000-4000-8000-000000000055"})
    assert stale.value.code == "draft_stale"
    with pytest.raises(QtWorkflowError) as conflict:
        service.save_draft("BOOK", 101, {**request,
            "selection_rows": [_choice(proposal, "3"), _choice(new, "0.125")]})
    assert conflict.value.code == "idempotency_conflict"
    assert _query(draft_db, "SELECT row_to_json(p)::text FROM trading.positions p ORDER BY symbol, portfolio_type") == before_positions
    assert _query(draft_db, "SELECT count(*) FROM trading.position_overrides") == before_audits


def test_unresolved_instrument_rejects_before_draft_write(draft_db):
    service = create_qt_workflow_service(QtWorkflowRepository(lambda: psycopg2.connect(draft_db)))
    initial = service.get_draft("BOOK", 101).to_wire()
    proposal = initial["selection_rows"][0]["key"]
    request = {
        "expected_source_digest": initial["source_digest"],
        "expected_provenance_digest": initial["provenance_digest"],
        "expected_draft_revision": 0,
        "idempotency_key": "00000000-0000-4000-8000-000000000066",
        "rationale": "Exercise unresolved instrument refusal.",
        "selection_rows": [_choice(proposal, "2"), _choice({**proposal, "symbol": "UNKNOWN"}, "1")],
    }
    with pytest.raises(QtWorkflowError) as unavailable:
        service.save_draft("BOOK", 101, request)
    assert unavailable.value.code == "draft_identity_unresolved"
    assert _query(draft_db, "SELECT count(*) FROM trading.qt_drafts") == [(0,)]


@pytest.mark.parametrize("mutation", ["zero_quantity", "basis", "delete", "add"])
def test_independent_saved_qt_change_stales_draft_get_and_update(draft_db, mutation):
    _query(draft_db, "INSERT INTO metadata.contract_metadata VALUES ('NQ', 'NQ', 'FUTURE')")
    _query(draft_db, """INSERT INTO trading.positions VALUES
        ('BOOK','engine-one','ONE',(clock_timestamp() AT TIME ZONE 'UTC')::date,
         'NQ','qt',4,200,NULL)""")
    service = create_qt_workflow_service(QtWorkflowRepository(lambda: psycopg2.connect(draft_db)))
    initial = service.get_draft("BOOK", 101).to_wire()
    proposal = next(row["key"] for row in initial["selection_rows"] if row["editable"])
    request = {
        "expected_source_digest": initial["source_digest"],
        "expected_provenance_digest": initial["provenance_digest"],
        "expected_draft_revision": 0,
        "idempotency_key": "00000000-0000-4000-8000-000000000077",
        "rationale": "Exercise draft staleness handling.",
        "selection_rows": [_choice(proposal, "2")],
    }
    saved = service.save_draft("BOOK", 101, request).to_wire()
    assert saved["state"] == "saved"
    if mutation == "zero_quantity":
        _query(draft_db, "UPDATE trading.positions SET quantity = 0 WHERE symbol = 'NQ' AND portfolio_type = 'qt'")
    elif mutation == "basis":
        _query(draft_db, "UPDATE trading.positions SET average_price = 201 WHERE symbol = 'NQ' AND portfolio_type = 'qt'")
    elif mutation == "delete":
        _query(draft_db, "DELETE FROM trading.positions WHERE symbol = 'NQ' AND portfolio_type = 'qt'")
    else:
        _query(draft_db, """INSERT INTO trading.positions VALUES
            ('BOOK','engine-one','ONE',(clock_timestamp() AT TIME ZONE 'UTC')::date,
             'NEW','qt',0,10,NULL)""")
    assert service.get_draft("BOOK", 101).to_wire()["state"] == "stale"
    with pytest.raises(QtWorkflowError) as stale:
        service.save_draft("BOOK", 101, {**request,
            "expected_draft_revision": 1,
            "idempotency_key": "00000000-0000-4000-8000-000000000088"})
    assert stale.value.code == "draft_stale"
    assert _query(draft_db, "SELECT count(*) FROM trading.qt_drafts") == [(1,)]


def test_revision_two_can_remove_new_symbol_but_not_model_source(draft_db):
    service = create_qt_workflow_service(QtWorkflowRepository(lambda: psycopg2.connect(draft_db)))
    initial = service.get_draft("BOOK", 101).to_wire()
    proposal = initial["selection_rows"][0]["key"]
    request = {
        "expected_source_digest": initial["source_digest"],
        "expected_provenance_digest": initial["provenance_digest"],
        "expected_draft_revision": 0,
        "idempotency_key": "00000000-0000-4000-8000-000000000077",
        "rationale": "Exercise removal of a draft-only component.",
        "selection_rows": [_choice(proposal, "2"), _choice({**proposal, "symbol": "NEW"}, "0.125")],
    }
    service.save_draft("BOOK", 101, request)
    second = service.save_draft("BOOK", 101, {**request,
        "expected_draft_revision": 1,
        "idempotency_key": "00000000-0000-4000-8000-000000000088",
        "selection_rows": [_choice(proposal, "1")]}).to_wire()
    assert second["draft_revision"] == 2
    assert [row["key"]["symbol"] for row in second["selection_rows"]] == ["SYN"]
    with pytest.raises(QtWorkflowError) as incomplete:
        service.save_draft("BOOK", 101, {**request,
            "expected_draft_revision": 2,
            "idempotency_key": "00000000-0000-4000-8000-000000000099",
            "selection_rows": []})
    assert incomplete.value.code == "invalid_qt_key"
    assert _query(draft_db, "SELECT count(*) FROM trading.qt_drafts") == [(2,)]


def test_retry_replays_after_provenance_break_but_revoked_grant_denies(draft_db):
    service = create_qt_workflow_service(QtWorkflowRepository(lambda: psycopg2.connect(draft_db)))
    initial = service.get_draft("BOOK", 101).to_wire()
    proposal = initial["selection_rows"][0]["key"]
    request = {
        "expected_source_digest": initial["source_digest"],
        "expected_provenance_digest": initial["provenance_digest"],
        "expected_draft_revision": 0,
        "idempotency_key": "00000000-0000-4000-8000-000000000077",
        "rationale": "Exercise exact draft storage.",
        "selection_rows": [_choice(proposal, "2")],
    }
    first = service.save_draft("BOOK", 101, request).to_wire()
    _query(draft_db, "UPDATE trading.positions SET quantity = 5 WHERE symbol = 'SYN' AND portfolio_type = 'qt_proposal'")
    assert service.save_draft("BOOK", 101, request).to_wire() == first
    with pytest.raises(QtWorkflowError) as conflict:
        service.save_draft("BOOK", 101, {**request, "selection_rows": [_choice(proposal, "3")]})
    assert conflict.value.code == "idempotency_conflict"
    _query(draft_db, "UPDATE trading.qt_action_grants SET active = false WHERE user_id = 101 AND capability = 'qt_submit'")
    with pytest.raises(QtWorkflowError) as denied:
        service.save_draft("BOOK", 101, request)
    assert denied.value.code == "authorization_changed"
