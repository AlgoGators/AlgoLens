"""Confirmation consumes an immutable preview without position publication."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from psycopg2.errors import UndefinedColumn

from algolens.domain.portfolio.qt_canonical import qt_digest_v1
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.domain.portfolio.qt_workflow_models import QtConfirmRequest
from algolens.infrastructure.portfolio.qt_read_set import capture_qt_read_set, canonical_internal_snapshot_bytes
from tests.test_qt_evaluator_client import RISK_METRICS
from tests.test_qt_preview import preview_fixture
from tests.test_qt_a4_draft import _ready_provenance
from algolens.infrastructure.portfolio.qt_workflow_repository import QtTransaction


def confirmation_fixture(monkeypatch, *, breach=False):
    service, repository, _ = preview_fixture(monkeypatch)
    tx = repository.tx
    original_facts = tx.read_current_facts()
    vectors = json.loads((Path(__file__).resolve().parents[2] / "contracts/qt-read-set-v1.json").read_text())
    complete = next(row["payload"] for row in vectors["cases"] if row["name"] == "complete_available")
    overrides = {name: deepcopy(complete[name]) for name in ("risk_limits", "portfolio_inputs", "external_sources", "evaluator")}
    facts = {**original_facts, **overrides}
    tx.role = "general_member"
    def lock_authorities(ids):
        tx.lock_order.append("auth")
        return ({"id": 101, "role": tx.role},)
    tx.lock_authorities = lock_authorities
    tx.lock_mutable = lambda **kwargs: tx.lock_order.append("mutable")
    tx.read_current_facts = lambda: deepcopy(facts)
    inputs = SimpleNamespace(read_set_overrides=overrides, evaluator_build=facts["evaluator"]["build"],
        policy_version=facts["evaluator"]["policy_version"], allowed_override_codes=("gross_leverage",) if breach else (),
        engine_inputs={"risk_config_source_id": "unit-risk-source", "risk_inputs": {"market_snapshot_id": "unit-market"}})
    monkeypatch.setattr("algolens.infrastructure.portfolio.qt_workflow_runtime.load_qt_evaluation_inputs", lambda *a, **k: inputs)
    read_set = capture_qt_read_set(facts)
    rows = tx.head["selection_payload"]["selection_rows"]
    target = service._target_digest(service._stored_rows(tx.head))
    baseline, immutable = service._base_rows(tx, tx.read_source_evidence(), _ready_provenance())
    diagnostic_digest = service._target_digest((*baseline.values(), *immutable))
    evidence = service._unavailable_evidence()
    evidence["optimizer"]["status"] = "disabled"
    evidence["selected_risk"].update(status="evaluated", evaluated_book_digest=target, passed=not breach,
        breaches=[{"code": "gross_leverage", "limit_diagnostic": "4", "actual_diagnostic": "5"}] if breach else [],
        metrics=[{"code": code, "value_diagnostic": "5" if breach and code == "gross_leverage" else "0", "unit": "ratio", "source_id": "unit-market"} for code in RISK_METRICS],
        config_source_id="unit-risk-source", market_snapshot_id="unit-market")
    evidence["selected_costs"].update(status="evaluated", evaluated_book_digest=target, total_exact="0.02",
        by_component=[{"key": rows[0]["key"], "prior_quantity_exact": "0", "selected_quantity_exact": "2", "cash_cost_exact": "0.02", "source_id": "unit-cost"}])
    preview_id = "00000000-0000-4000-8000-000000000061"
    payload = {"schema_version": "qt-workflow/v1", "book_id": "BOOK", "source_day": "2026-09-25",
        "preview_id": preview_id, "optimizer_book_digest": diagnostic_digest, "selected_book_digest": target,
        "draft_id": tx.head["draft_id"], "draft_revision": 1, "source_digest": "a" * 64,
        "provenance_digest": "b" * 64, "read_set_digest": read_set.digest, "availability": "ready",
        "confirmable": True, "requires_override": breach, "selection_rows": rows,
        "unavailable_reasons": [], "evaluation": evidence}
    payload["payload_digest"] = qt_digest_v1(payload)
    tx.preview = {**payload, "payload": payload, "read_set_payload": json.loads(canonical_internal_snapshot_bytes("qt-read-set/v1", read_set.payload)),
        "draft_digest": tx.head["draft_digest"], "evaluator_build": inputs.evaluator_build,
        "policy_version": inputs.policy_version, "created_by": 101, "state": "pending"}
    tx.get_preview = lambda identity: deepcopy(tx.preview)
    repository.preview_routing = lambda identity: {"book_id": "BOOK", "source_day": date(2026, 9, 25), "preview_id": identity}
    tx.read_evaluation_policy = lambda: {"version": 7, "policy_version": inputs.policy_version,
        "enabled": True, "allowed_override_codes": list(inputs.allowed_override_codes)}
    tx.decisions, tx.requests = [], []
    tx.insert_decision = lambda data: tx.decisions.append(data) or data["decision_id"]
    tx.insert_override_request = lambda data: tx.requests.append(data) or data["request_id"]
    def consume_preview(identity, expected_state, new_state):
        assert tx.preview["state"] == expected_state
        tx.preview["state"] = new_state
    tx.consume_preview = consume_preview
    request = {"action": "confirm_selected_book", "expected_digest": payload["payload_digest"],
        "idempotency_key": "00000000-0000-4000-8000-000000000062", "acknowledge_warnings": breach}
    return service, tx, facts, preview_id, request


@pytest.mark.parametrize("breach", [False, True])
def test_confirm_atomic_decision_and_optional_single_request(monkeypatch, breach):
    service, tx, facts, preview_id, request = confirmation_fixture(monkeypatch, breach=breach)
    response = service.confirm_preview(preview_id, 101, request).to_wire()
    assert response["status"] == ("pending_override" if breach else "confirmed_decision")
    assert len(tx.decisions) == 1 and len(tx.requests) == int(breach)
    assert not response["report_ready"] and response["receipt"] is None
    assert tx.decisions[0]["payload"]["schema_version"] == "qt-desk-decision/v1"
    assert tx.decisions[0]["workflow_capability_version"] == 1
    if breach: assert tx.requests[0]["eligibility_version"] == 7
    assert tx.position_mutations == 0


def test_response_loss_replays_before_source_freshness_but_after_current_role(monkeypatch):
    service, tx, facts, preview_id, request = confirmation_fixture(monkeypatch)
    first = service.confirm_preview(preview_id, 101, request).to_wire()
    facts["source_rows"][0]["quantity_exact"] = "99"
    assert service.confirm_preview(preview_id, 101, request).to_wire() == first
    assert len(tx.decisions) == 1
    tx.role = "guest"
    with pytest.raises(QtWorkflowError) as error: service.confirm_preview(preview_id, 101, request)
    assert error.value.code == "authorization_changed"


def test_same_key_collision_and_new_key_consumed_do_not_create_more_decisions(monkeypatch):
    service, tx, facts, preview_id, request = confirmation_fixture(monkeypatch)
    service.confirm_preview(preview_id, 101, request)
    with pytest.raises(QtWorkflowError) as collision:
        service.confirm_preview(preview_id, 101, {**request, "expected_digest": "0" * 64})
    assert collision.value.code == "idempotency_conflict"
    with pytest.raises(QtWorkflowError) as consumed:
        service.confirm_preview(preview_id, 101, {**request, "idempotency_key": "00000000-0000-4000-8000-000000000063"})
    assert consumed.value.code == "preview_consumed"
    assert len(tx.decisions) == 1


@pytest.mark.parametrize("mutation", ["source", "draft", "grant", "digest", "unavailable", "warning"])
def test_stale_unavailable_unacknowledged_preview_never_creates_decision(monkeypatch, mutation):
    service, tx, facts, preview_id, request = confirmation_fixture(monkeypatch, breach=mutation == "warning")
    if mutation == "source": facts["source_rows"][0]["quantity_exact"] = "99"
    elif mutation == "draft": tx.head["revision"] = 2
    elif mutation == "grant": facts["grants"][0]["active"] = False
    elif mutation == "digest": request["expected_digest"] = "0" * 64
    elif mutation == "unavailable": tx.preview["availability"] = "unavailable"
    else: request["acknowledge_warnings"] = False
    with pytest.raises(QtWorkflowError): service.confirm_preview(preview_id, 101, request)
    assert not tx.decisions and not tx.requests and tx.position_mutations == 0


def test_typed_wrong_action_cannot_bypass_confirm_decoder(monkeypatch):
    service, tx, facts, preview_id, request = confirmation_fixture(monkeypatch)
    with pytest.raises(QtWorkflowError) as error:
        service.confirm_preview(preview_id, 101, QtConfirmRequest(**{**request, "action": "approve"}))
    assert error.value.code == "invalid_qt_action" and not tx.decisions


def test_incomplete_claimed_ready_metrics_cannot_create_override_request(monkeypatch):
    service, tx, facts, preview_id, request = confirmation_fixture(monkeypatch, breach=True)
    tx.preview["payload"]["evaluation"]["selected_risk"]["metrics"].pop()
    payload = tx.preview["payload"]
    payload["payload_digest"] = qt_digest_v1({key: value for key, value in payload.items() if key != "payload_digest"})
    tx.preview["payload_digest"] = request["expected_digest"] = payload["payload_digest"]
    with pytest.raises(QtWorkflowError): service.confirm_preview(preview_id, 101, request)
    assert not tx.decisions and not tx.requests


def test_missing_authoritative_account_role_is_typed_unavailable():
    class Cursor:
        def execute(self, statement, values):
            raise UndefinedColumn("synthetic missing role")
    with pytest.raises(QtWorkflowError) as error:
        QtTransaction(Cursor(), "BOOK", 101).lock_authorities([101])
    assert error.value.code == "workflow_unavailable"


@pytest.mark.parametrize("mutation", ["membership", "registry"])
def test_replay_requires_current_editable_book_ownership(monkeypatch, mutation):
    service, tx, facts, preview_id, request = confirmation_fixture(monkeypatch)
    service.confirm_preview(preview_id, 101, request)
    if mutation == "membership": facts["memberships"] = []
    else: facts["registry"][0]["is_active"] = False
    with pytest.raises(QtWorkflowError) as error: service.confirm_preview(preview_id, 101, request)
    assert error.value.code == "authorization_changed"
