"""Actual immutable preview confirmation, retry, concurrency and rollback."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import psycopg2
import pytest

from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.portfolio.qt_workflow_repository import QtTransaction
from tests.integration.test_qt_preview_evaluator import preview_db, saved_draft, authority, query
from tests.integration.test_qt_a3_read_set_postgres import a3_db


def prepared(dsn, *, case="clean"):
    service, preview_request = saved_draft(dsn)
    authority(dsn, case=case)
    preview = service.create_preview(101, preview_request).to_wire()
    request = {"action": "confirm_selected_book", "expected_digest": preview["payload_digest"],
        "idempotency_key": "00000000-0000-4000-8000-000000000071", "acknowledge_warnings": case == "allowed_breach"}
    return service, preview, request


def counts(dsn):
    return [query(dsn, f"SELECT count(*) FROM trading.{table}")[0][0]
        for table in ("qt_decisions", "qt_override_requests", "qt_idempotency")]


@pytest.mark.parametrize("case", ["clean", "allowed_breach"])
def test_actual_confirmation_creates_one_decision_and_optional_request_without_publication(preview_db, case):
    service, preview, request = prepared(preview_db, case=case)
    before = query(preview_db, "SELECT row_to_json(p)::text FROM trading.positions p ORDER BY symbol,portfolio_type")
    response = service.confirm_preview(preview["preview_id"], 101, request).to_wire()
    assert response["status"] == ("confirmed_decision" if case == "clean" else "pending_override")
    assert not response["report_ready"] and response["receipt"] is None and response["approvals_count"] == 0
    assert counts(preview_db)[:2] == [1, int(case == "allowed_breach")]
    if case == "allowed_breach": assert query(preview_db, "SELECT eligibility_version FROM trading.qt_override_requests") == [(1,)]
    reference = query(preview_db, "SELECT payload FROM trading.qt_decisions")[0][0]
    assert set(reference) == {"schema_version", "decision_id", "preview_id", "book_id", "source_day",
        "preview_payload_digest", "selected_book_digest", "read_set_digest"}
    assert reference["schema_version"] == "qt-desk-decision/v1" and reference["preview_payload_digest"] == preview["payload_digest"]
    assert query(preview_db, "SELECT row_to_json(p)::text FROM trading.positions p ORDER BY symbol,portfolio_type") == before
    assert query(preview_db, "SELECT count(*) FROM trading.position_overrides") == [(0,)]
    assert query(preview_db, "SELECT count(*) FROM trading.qt_desk_receipts") == [(0,)]


def test_actual_lost_response_replay_after_book_change_and_current_role_revocation(preview_db):
    service, preview, request = prepared(preview_db)
    first = service.confirm_preview(preview["preview_id"], 101, request).to_wire()
    query(preview_db, "UPDATE trading.positions SET quantity=7,last_update=clock_timestamp() WHERE portfolio_type='qt'")
    assert service.confirm_preview(preview["preview_id"], 101, request).to_wire() == first
    with pytest.raises(QtWorkflowError) as collision:
        service.confirm_preview(preview["preview_id"], 101, {**request, "expected_digest": "0" * 64})
    assert collision.value.code == "idempotency_conflict"
    with pytest.raises(QtWorkflowError) as consumed:
        service.confirm_preview(preview["preview_id"], 101, {**request, "idempotency_key": "00000000-0000-4000-8000-000000000072"})
    assert consumed.value.code == "preview_consumed"
    query(preview_db, "UPDATE auth.users SET role='guest' WHERE id=101")
    with pytest.raises(QtWorkflowError) as revoked: service.confirm_preview(preview["preview_id"], 101, request)
    assert revoked.value.code == "authorization_changed"
    assert counts(preview_db)[:2] == [1, 0]


@pytest.mark.parametrize("mutation", ["source", "saved_accounting", "draft", "grant", "capability", "policy", "day", "digest", "warnings", "unavailable"])
def test_actual_stale_or_unavailable_confirmation_has_zero_decision_writes(preview_db, monkeypatch, mutation):
    case = "allowed_breach" if mutation == "warnings" else ("missing_mark" if mutation == "unavailable" else "clean")
    service, preview, request = prepared(preview_db, case=case)
    if mutation == "source": query(preview_db, "UPDATE trading.positions SET quantity=8 WHERE portfolio_type='qt_proposal'")
    elif mutation == "saved_accounting": query(preview_db, "UPDATE trading.positions SET daily_unrealized_pnl=2.5 WHERE portfolio_type='qt'")
    elif mutation == "draft":
        current = service.get_draft("BOOK", 101).to_wire()
        service.save_draft("BOOK", 101, {"expected_source_digest": current["source_digest"],
            "expected_provenance_digest": current["provenance_digest"], "expected_draft_revision": current["draft_revision"],
            "idempotency_key": "00000000-0000-4000-8000-000000000073",
            "selection_rows": [{"key": row["key"], "quantity_exact": row["quantity_exact"]}
                               for row in current["selection_rows"] if row["editable"]]})
    elif mutation == "grant": query(preview_db, "UPDATE trading.qt_action_grants SET active=false,version=2 WHERE user_id=101")
    elif mutation == "capability": query(preview_db, "UPDATE trading.qt_workflow_capabilities SET enabled=false,version=2")
    elif mutation == "policy": query(preview_db, "UPDATE trading.qt_source_policies SET version=2 WHERE book_id='BOOK'")
    elif mutation == "day":
        original = QtTransaction.utc_source_day
        monkeypatch.setattr(QtTransaction, "utc_source_day", lambda tx: original(tx) + timedelta(days=1))
    elif mutation == "digest": request["expected_digest"] = "0" * 64
    elif mutation == "warnings": request["acknowledge_warnings"] = False
    with pytest.raises(QtWorkflowError): service.confirm_preview(preview["preview_id"], 101, request)
    assert counts(preview_db)[:2] == [0, 0]
    assert query(preview_db, "SELECT state FROM trading.qt_previews") == [("pending",)]
    assert query(preview_db, "SELECT count(*) FROM trading.position_overrides") == [(0,)]


def test_actual_concurrent_new_keys_consume_preview_once(preview_db):
    service, preview, request = prepared(preview_db)
    def confirm(key):
        try:
            return service.confirm_preview(preview["preview_id"], 101, {**request, "idempotency_key": key}).to_wire()["status"]
        except QtWorkflowError as error: return error.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(confirm, (request["idempotency_key"], "00000000-0000-4000-8000-000000000074")))
    assert sorted(results) == ["confirmed_decision", "preview_consumed"]
    assert counts(preview_db)[:2] == [1, 0]


@pytest.mark.parametrize("failure_table", ["qt_decisions", "qt_override_requests"])
def test_actual_insert_failure_rolls_back_preview_consumption_and_decision(preview_db, failure_table):
    service, preview, request = prepared(preview_db, case="allowed_breach" if failure_table == "qt_override_requests" else "clean")
    query(preview_db, f"""CREATE FUNCTION trading.synthetic_confirm_failure() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'synthetic confirmation rollback'; END $$;
        CREATE TRIGGER synthetic_confirm_failure BEFORE INSERT ON trading.{failure_table}
        FOR EACH ROW EXECUTE FUNCTION trading.synthetic_confirm_failure();""")
    before_counts = counts(preview_db)
    with pytest.raises(psycopg2.Error): service.confirm_preview(preview["preview_id"], 101, request)
    assert counts(preview_db) == before_counts
    assert query(preview_db, "SELECT state FROM trading.qt_previews") == [("pending",)]
    query(preview_db, f"DROP TRIGGER synthetic_confirm_failure ON trading.{failure_table}; DROP FUNCTION trading.synthetic_confirm_failure()")
    assert service.confirm_preview(preview["preview_id"], 101, request).to_wire()["decision_id"]
