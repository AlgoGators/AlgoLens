"""Actual SQL authority, immutable preview proof and atomic explicit quorum."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg2
import pytest

from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from tests.integration.test_qt_a6_confirmation_postgres import prepared
from tests.integration.test_qt_preview_evaluator import preview_db, query
from tests.integration.test_qt_a3_read_set_postgres import a3_db


def approval_request():
    return {"action": "approve", "idempotency_key": str(uuid4())}


def pending(dsn):
    query(dsn, """INSERT INTO auth.users(id,role) VALUES (202,'exec_board'),(303,'general_member')
        ON CONFLICT(id) DO UPDATE SET role=excluded.role;
        INSERT INTO trading.qt_action_grants(user_id,capability,active,version)
          VALUES(101,'qt_approve',true,1),(202,'qt_approve',true,1),(303,'qt_approve',true,1);
        INSERT INTO trading.qt_approver_allowlist(person_id,display_label,user_id,active,mapping_version)
          VALUES('john_riley','john riley',101,true,1),('hemdutt_rao','hemdutt rao',202,true,1),
                ('xander_robbins','xander robbins',303,false,1);""")
    service, preview, confirm = prepared(dsn, case="allowed_breach")
    decision = service.confirm_preview(preview["preview_id"], 101, confirm).to_wire()
    return service, decision


def assert_pending(dsn, approvals):
    assert query(dsn, "SELECT status FROM trading.qt_decisions") == [("pending_override",)]
    assert query(dsn, "SELECT count(*) FROM trading.qt_override_approvals") == [(approvals,)]


def test_actual_explicit_requester_distinct_second_promotes_same_immutable_decision(preview_db):
    service, decision = pending(preview_db)
    before = query(preview_db, "SELECT payload FROM trading.qt_decisions")
    positions = query(preview_db, "SELECT row_to_json(p)::text FROM trading.positions p ORDER BY symbol,portfolio_type")
    first_request = approval_request()
    first = service.approve_override(decision["request_id"], 101, first_request).to_wire()
    assert first["approvals_count"] == 1 and first["status"] == "pending_override"
    assert service.approve_override(decision["request_id"], 101, first_request).to_wire() == first
    with pytest.raises(QtWorkflowError): service.approve_override(decision["request_id"], 101, approval_request())
    second = service.approve_override(decision["request_id"], 202, approval_request()).to_wire()
    assert second["status"] == "confirmed_decision" and second["approvals_count"] == 2
    assert query(preview_db, "SELECT state FROM trading.qt_previews") == [("confirmed_decision",)]
    assert second["decision_id"] == decision["decision_id"] and not second["report_ready"] and second["receipt"] is None
    assert query(preview_db, "SELECT payload FROM trading.qt_decisions") == before
    assert query(preview_db, "SELECT count(*) FROM trading.qt_decisions") == [(1,)]
    assert query(preview_db, "SELECT count(*) FROM trading.qt_override_requests") == [(1,)]
    assert query(preview_db, "SELECT row_to_json(p)::text FROM trading.positions p ORDER BY symbol,portfolio_type") == positions
    assert query(preview_db, "SELECT count(*) FROM trading.position_overrides") == [(0,)]
    assert query(preview_db, "SELECT count(*) FROM trading.qt_desk_receipts") == [(0,)]


@pytest.mark.parametrize("mutation", ["mapping", "grant", "role", "source", "accounting", "policy", "market", "membership", "capability"])
def test_actual_second_approval_rejects_revocation_or_stale_evidence(preview_db, mutation):
    service, decision = pending(preview_db)
    service.approve_override(decision["request_id"], 101, approval_request())
    sql = {
        "mapping": "UPDATE trading.qt_approver_allowlist SET mapping_version=2 WHERE user_id=101",
        "grant": "UPDATE trading.qt_action_grants SET active=false,version=2 WHERE user_id=101 AND capability='qt_approve'",
        "role": "UPDATE auth.users SET role='guest' WHERE id=101",
        "source": "UPDATE trading.positions SET quantity=9 WHERE portfolio_type='qt_proposal'",
        "accounting": "UPDATE trading.positions SET daily_unrealized_pnl=9 WHERE portfolio_type='qt'",
        "policy": "UPDATE trading.qt_source_policies SET version=2",
        "market": "UPDATE trading.qt_source_policies SET producer_id='changed-approved-producer',version=2",
        "membership": "DELETE FROM trading.strategy_book_memberships",
        "capability": "UPDATE trading.qt_workflow_capabilities SET enabled=false,version=2",
    }[mutation]
    query(preview_db, sql)
    with pytest.raises(QtWorkflowError): service.approve_override(decision["request_id"], 202, approval_request())
    assert_pending(preview_db, 1)


@pytest.mark.parametrize("failure", ["approval", "promotion", "preview_promotion", "idempotency"])
def test_actual_failure_rolls_back_second_approval_and_promotion(preview_db, failure):
    service, decision = pending(preview_db)
    service.approve_override(decision["request_id"], 101, approval_request())
    table, operation = {"approval": ("qt_override_approvals", "INSERT"), "promotion": ("qt_decisions", "UPDATE"),
                        "preview_promotion": ("qt_previews", "UPDATE"),
                        "idempotency": ("qt_idempotency", "INSERT")}[failure]
    query(preview_db, f"""CREATE FUNCTION trading.synthetic_approval_failure() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'synthetic approval rollback'; END $$;
        CREATE TRIGGER synthetic_approval_failure BEFORE {operation} ON trading.{table}
        FOR EACH ROW EXECUTE FUNCTION trading.synthetic_approval_failure();""")
    request = approval_request()
    with pytest.raises(psycopg2.Error): service.approve_override(decision["request_id"], 202, request)
    assert_pending(preview_db, 1)
    assert query(preview_db, "SELECT state FROM trading.qt_previews") == [("pending_override",)]
    query(preview_db, f"DROP TRIGGER synthetic_approval_failure ON trading.{table}; DROP FUNCTION trading.synthetic_approval_failure()")
    assert service.approve_override(decision["request_id"], 202, request).to_wire()["approvals_count"] == 2
    assert query(preview_db, "SELECT state FROM trading.qt_previews") == [("confirmed_decision",)]


def test_actual_replay_survives_source_change_but_rechecks_current_caller(preview_db):
    service, decision = pending(preview_db)
    request = approval_request()
    first = service.approve_override(decision["request_id"], 202, request).to_wire()
    query(preview_db, "UPDATE trading.positions SET quantity=17 WHERE portfolio_type='qt'")
    assert service.approve_override(decision["request_id"], 202, request).to_wire() == first
    query(preview_db, "UPDATE trading.qt_action_grants SET active=false,version=2 WHERE user_id=202 AND capability='qt_approve'")
    with pytest.raises(QtWorkflowError): service.approve_override(decision["request_id"], 202, request)
    assert_pending(preview_db, 1)


def test_actual_concurrent_seconds_have_one_promotion_and_no_extra_approval(preview_db):
    service, decision = pending(preview_db)
    query(preview_db, "UPDATE trading.qt_approver_allowlist SET active=true WHERE user_id=303")
    service.approve_override(decision["request_id"], 101, approval_request())
    def approve(actor):
        try: return service.approve_override(decision["request_id"], actor, approval_request()).to_wire()["status"]
        except QtWorkflowError as error: return error.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(approve, (202, 303)))
    assert results.count("confirmed_decision") == 1
    assert query(preview_db, "SELECT count(*) FROM trading.qt_override_approvals") == [(2,)]
    assert query(preview_db, "SELECT status FROM trading.qt_decisions") == [("confirmed_decision",)]


def test_actual_duplicate_person_or_account_mapping_is_physically_rejected(preview_db):
    service, decision = pending(preview_db)
    with pytest.raises(psycopg2.IntegrityError):
        query(preview_db, "INSERT INTO trading.qt_approver_allowlist VALUES "
              "('hemdutt_rao','hemdutt rao',303,true,1,clock_timestamp())")
    with pytest.raises(psycopg2.IntegrityError):
        query(preview_db, "INSERT INTO trading.qt_approver_allowlist VALUES "
              "('xander_robbins','xander robbins',101,true,1,clock_timestamp())")
    assert_pending(preview_db, 0)
    assert service.approve_override(decision["request_id"], 101, approval_request()).to_wire()["approvals_count"] == 1
