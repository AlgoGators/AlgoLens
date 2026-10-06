"""A receipt permits only an explicit complete CAS successor for its consumed draft."""
from copy import deepcopy
from dataclasses import replace

import pytest

from algolens.infrastructure.config.dependencies import create_qt_workflow_service
from algolens.domain.portfolio.qt_canonical import qt_digest_v1
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.portfolio.qt_provenance import QtExactPosition, QtVerifiedQtEdit
from tests.test_qt_a4_draft import DraftRepository, _ready_provenance, _save_request, key, choice, DAY, BOOK


def successor_fixture(monkeypatch):
    state = [_ready_provenance()]
    monkeypatch.setattr("algolens.infrastructure.portfolio.qt_workflow_runtime.reconcile_qt_source", lambda *a, **k: state[0])
    repository = DraftRepository()
    service = create_qt_workflow_service(repository)
    service.save_draft(BOOK, 101, _save_request([choice(key(), "2")]))
    tx = repository.tx
    head = deepcopy(tx.head)
    source_keys = [replace(key(), portfolio_type="qt"), replace(key("AAPL"), portfolio_type="qt")]
    overlay = (QtExactPosition(key(), "2", "101"), QtExactPosition(key("AAPL"), "3", "102"))
    decision = {"decision_id": "00000000-0000-4000-8000-000000000081", "source_day": DAY,
        "model_publication_id": head["model_publication_id"], "draft_id": head["draft_id"],
        "draft_revision": head["revision"], "draft_digest": head["draft_digest"],
        "selection_digest": qt_digest_v1({"selection_rows": head["selection_payload"]["selection_rows"]}),
        "source_digest": head["source_digest"],
        "provenance_digest": head["provenance_digest"]}
    state[0] = replace(state[0], legacy_audit_chain_digest="d" * 64, draft_overlay=overlay,
        verified_qt_edits=tuple(QtVerifiedQtEdit(source, position.key, (100 + index,), "verified_qt_decision")
                               for index, (source, position) in enumerate(zip(source_keys, overlay))),
        receipt_links=({"decision_id": decision["decision_id"]},), receipt_decisions=(decision,))
    tx.saved_rows = [QtExactPosition(source, position.quantity_exact, position.average_price_exact).to_wire()
                     for source, position in zip(source_keys, overlay)]
    old_facts = tx.read_current_facts
    def facts():
        current = old_facts()
        current["provenance"]["chain_digest"] = state[0].legacy_audit_chain_digest
        return current
    tx.read_current_facts = facts
    request = _save_request([choice(key(), "4"), choice(key("AAPL"), "3.25")], revision=1,
                            idempotency="00000000-0000-4000-8000-000000000083")
    request["expected_provenance_digest"] = "d" * 64
    return service, tx, state, request


def test_processed_consumed_head_exposes_current_base_for_explicit_second_choice(monkeypatch):
    service, tx, state, request = successor_fixture(monkeypatch)
    shown = service.get_draft(BOOK, 101).to_wire()
    assert shown["state"] == "stale" and shown["draft_revision"] == 1
    assert len(shown["selection_rows"]) == 2
    assert all(row["origin"] == "verified_qt_decision" for row in shown["selection_rows"])
    saved = service.save_draft(BOOK, 101, request).to_wire()
    assert saved["draft_revision"] == 2 and saved["state"] == "saved"
    assert next(row for row in saved["selection_rows"] if row["key"]["symbol"] == "ES")["average_price_exact"] == "101"
    assert service.save_draft(BOOK, 101, request).to_wire() == saved
    with pytest.raises(QtWorkflowError):
        service.save_draft(BOOK, 101, {**request, "idempotency_key": "00000000-0000-4000-8000-000000000084"})
    assert tx.position_mutations == 0


@pytest.mark.parametrize("mutation", ["missing", "draft", "digest", "model", "day", "proposal", "incomplete", "revision"])
def test_unproved_or_mismatched_successor_never_rebases_stale_head(monkeypatch, mutation):
    service, tx, state, request = successor_fixture(monkeypatch)
    if mutation == "missing": state[0] = replace(state[0], receipt_links=(), receipt_decisions=())
    elif mutation == "draft": state[0].receipt_decisions[0]["draft_id"] = "00000000-0000-4000-8000-000000000099"
    elif mutation == "digest": state[0].receipt_decisions[0]["selection_digest"] = "e" * 64
    elif mutation == "model": state[0] = replace(state[0], model_publication_id="00000000-0000-4000-8000-000000000099")
    elif mutation == "day": state[0].receipt_decisions[0]["source_day"] = "2026-09-24"
    elif mutation == "proposal": state[0] = replace(state[0], observed_source_digest="e" * 64)
    elif mutation == "incomplete": request["selection_rows"].pop()
    else: request["expected_draft_revision"] = 0
    before = deepcopy(tx.head)
    with pytest.raises(QtWorkflowError): service.save_draft(BOOK, 101, request)
    assert tx.head == before and tx.position_mutations == 0
