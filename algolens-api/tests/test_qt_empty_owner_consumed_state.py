"""Actual workflow/read-service behavior with a verified-receipt port fixture.

This tests service composition, not independent financial or SQL proof. The
fixture preserves the real immutable decision status: confirmed_decision.
Only the separate immutable receipt is processed.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

from algolens.application.portfolio.qt_workflow import QtWorkflowService
from algolens.application.portfolio.qt_decision_read import QtDecisionReadService
from algolens.domain.portfolio.qt_canonical import qt_digest_v1
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.portfolio.qt_provenance import QtProvenance
from algolens.infrastructure.portfolio.qt_receipt_provenance import verified_receipt_chain
from tests.test_qt_a4_draft import DraftTransaction, BOOK, DAY


def consumed_fixture():
    marker = dict(schema_version="qt-empty-owner-choice/v2",
        model_publication_id="00000000-0000-4000-8000-000000000001",
        owner_document_digest="e" * 64, configured_owner_names=["EQUITY_MEAN_REVERSION"])
    selection = {"selection_rows": []}
    digest = qt_digest_v1(selection)
    head = dict(book_id=BOOK, draft_id="00000000-0000-4000-8000-000000000002",
        revision=1, draft_digest=digest, selection_payload=selection,
        model_publication_id=marker["model_publication_id"], model_publication_version=1,
        seed_digest="b" * 64, source_digest="a" * 64, provenance_digest="c" * 64)
    link = dict(decision_id="00000000-0000-4000-8000-000000000003",
        attempt_id="00000000-0000-4000-8000-000000000004",
        preview_id="00000000-0000-4000-8000-000000000005", publication_digest="f" * 64,
        audit_ids=[], source_keys=[], processed_at=DAY + "T12:00:00.000001Z")
    decision = dict(book_id=BOOK, source_day=DAY, decision_id=link["decision_id"],
        preview_id=link["preview_id"], draft_id=head["draft_id"], draft_revision=1,
        draft_digest=digest, selection_digest=digest, source_digest=head["source_digest"],
        provenance_digest=head["provenance_digest"], model_publication_id=head["model_publication_id"],
        status="confirmed_decision", empty_owner_choice=deepcopy(marker))
    provenance = QtProvenance(head["model_publication_id"], 1, head["seed_digest"],
        head["source_digest"], "d" * 64, "ready", (), (),
        receipt_links=(link,), receipt_decisions=(decision,), empty_owner_choice=marker)
    return head, provenance, link


class Transaction(DraftTransaction):
    def __init__(self, head, provenance):
        super().__init__()
        self.book_id = BOOK
        self.head, self.provenance = deepcopy(head), provenance

    def read_current_facts(self):
        facts = super().read_current_facts()
        facts["registry"][0]["strategy_type"] = "LIVE_EQUITY_MEAN_REVERSION"
        facts["provenance"] = dict(source_digest=self.provenance.observed_source_digest,
            chain_digest=self.provenance.legacy_audit_chain_digest)
        return facts

    def approval_authority(self, actor):
        return {"grants": [{"user_id": actor, "capability": "qt_submit", "active": True}]}

    def read_source_evidence(self):
        return dict(source_day=date.fromisoformat(DAY), publications=[], source_rows=[], saved_rows=[],
            system_rows=[], audits=[], saved_accounting=[], processed_publications=[])


def services(head, provenance):
    tx = Transaction(head, provenance)
    class Repository:
        @contextmanager
        def transaction(self, book, actor):
            assert (book, actor) == (BOOK, 101)
            before = deepcopy((tx.head, tx.pending, tx.idempotency))
            try:
                yield tx
            except Exception:
                tx.head, tx.pending, tx.idempotency = before
                raise
    repository = Repository()
    evidence = SimpleNamespace(reconcile_source=lambda *args, **kwargs: provenance)
    workflow = QtWorkflowService(repository, evidence=evidence, input_loader=None,
        evaluator=None, authorization=None)
    reader = QtDecisionReadService(repository, evidence=evidence, input_loader=None,
        authorization=None, queries=None, workflow=workflow)
    return workflow, reader, tx


@pytest.mark.parametrize("service_kind", ["workflow", "reader"])
def test_processed_receipt_exposes_consumed_head_without_rewriting_confirmed_decision(service_kind):
    head, provenance, link = consumed_fixture()
    old = deepcopy(head)
    workflow, reader, tx = services(head, provenance)
    wire = (workflow if service_kind == "workflow" else reader).get_draft(BOOK, 101).to_wire()
    assert wire["state"] == "consumed" and wire["schema_version"] == "qt-workflow/v2"
    assert wire["successor"] == {name: link[name] for name in
        ("decision_id", "attempt_id", "preview_id", "publication_digest")}
    assert wire["draft_id"] == old["draft_id"] and wire["draft_revision"] == old["revision"]
    assert wire["draft_digest"] == old["draft_digest"] and wire["selection_rows"] == []
    assert wire["provenance_digest"] == provenance.legacy_audit_chain_digest
    assert tx.head == old and provenance.receipt_decisions[-1]["status"] == "confirmed_decision"
    assert tx.position_mutations == 0


def test_explicit_save_uses_verified_processed_receipt_and_preserves_consumed_history():
    head, provenance, _ = consumed_fixture()
    old = deepcopy(head)
    workflow, _, tx = services(head, provenance)
    request = dict(expected_source_digest=provenance.observed_source_digest,
        expected_provenance_digest=provenance.legacy_audit_chain_digest,
        expected_draft_revision=1, rationale="Confirm the verified empty book choice.", selection_rows=[],
        idempotency_key="00000000-0000-4000-8000-000000000006")
    wire = workflow.save_draft(BOOK, 101, request).to_wire()
    assert wire["state"] == "saved" and wire["draft_revision"] == 2
    assert wire["draft_id"] != old["draft_id"] and wire["empty_owner"] == dict(provenance.empty_owner_choice)
    assert "successor" not in wire and workflow.save_draft(BOOK, 101, request).to_wire() == wire
    assert head == old and tx.position_mutations == 0
    assert tx.lock_order[:4] == ["auth", "registry", "book", "mutable"]


@pytest.mark.parametrize("damage", ["invented_processed_decision", "failed", "pending_override",
    "missing_receipt", "newer_head", "changed_owner", "changed_source", "changed_model",
    "changed_day", "changed_seed", "changed_model_version", "changed_selection", "changed_preview"])
def test_unproved_or_changed_receipt_never_grants_consumed_successor(damage):
    head, provenance, link = consumed_fixture()
    decision = provenance.receipt_decisions[-1]
    if damage == "invented_processed_decision": decision["status"] = "processed"
    elif damage in {"failed", "pending_override"}: decision["status"] = damage
    elif damage == "missing_receipt": provenance = replace(provenance, receipt_links=())
    elif damage == "newer_head": head["revision"] = 2
    elif damage == "changed_owner": decision["empty_owner_choice"]["configured_owner_names"] = ["OTHER"]
    elif damage == "changed_source": head["source_digest"] = "e" * 64
    elif damage == "changed_model": head["model_publication_id"] = link["decision_id"]
    elif damage == "changed_day": decision["source_day"] = "2026-09-24"
    elif damage == "changed_seed": head["seed_digest"] = "e" * 64
    elif damage == "changed_model_version": head["model_publication_version"] = 2
    elif damage == "changed_selection": decision["selection_digest"] = "e" * 64
    else: decision["preview_id"] = link["decision_id"]
    workflow, reader, tx = services(head, provenance)
    old = deepcopy(tx.head)
    for service in (workflow, reader):
        wire = service.get_draft(BOOK, 101).to_wire()
        assert wire["state"] == "stale" and wire["schema_version"] == "qt-workflow/v1"
        assert "successor" not in wire and "empty_owner" not in wire
    request = dict(expected_source_digest=provenance.observed_source_digest,
        expected_provenance_digest=provenance.legacy_audit_chain_digest,
        expected_draft_revision=head["revision"], rationale="Confirm the verified empty book choice.", selection_rows=[],
        idempotency_key="00000000-0000-4000-8000-000000000006")
    with pytest.raises(QtWorkflowError): workflow.save_draft(BOOK, 101, request)
    assert tx.head == old and tx.pending is None and tx.idempotency == {} and tx.position_mutations == 0


def test_failed_receipt_is_rejected_before_entering_the_verified_successor_port():
    head, provenance, link = consumed_fixture()
    evidence = dict(decision=provenance.receipt_decisions[-1],
        receipt=dict(attempt_id=link["attempt_id"], status="failed"),
        preview=dict(read_set_payload={"audit_refs": []}))
    with pytest.raises((QtWorkflowError, ValueError)):
        verified_receipt_chain(BOOK, date.fromisoformat(DAY), [evidence], [], [])
