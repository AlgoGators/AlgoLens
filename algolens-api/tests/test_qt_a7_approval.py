"""Explicit approvals count current canonical people and preserve one decision."""
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
from contextlib import contextmanager

import pytest

from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from tests.test_qt_a6_confirmation import confirmation_fixture
from algolens.domain.portfolio.qt_workflow_models import QtApproveRequest


def person(user_id, person_id):
    return {"person_id": person_id, "user_id": user_id, "mapping_version": 1, "grant_version": 1}


def authority(user_id, person_id, role="general_member"):
    return {"account": {"id": user_id, "role": role},
            "grants": [{"user_id": user_id, "capability": "qt_approve", "active": True, "version": 1}],
            "mappings": [{"user_id": user_id, "person_id": person_id, "active": True, "mapping_version": 1}]}


def test_exec_board_hemdutt_with_explicit_grant_is_a_current_approver():
    from algolens.infrastructure.portfolio.qt_authorization import resolve_approved_person
    current = authority(101, "hemdutt_rao", role="exec_board")
    tx = SimpleNamespace(approval_authority=lambda user: current,
                         capability=lambda: {"enabled": True, "version": 1})
    assert asdict(resolve_approved_person(101, tx)) == person(101, "hemdutt_rao")


def test_retired_approver_identity_cannot_count():
    from algolens.infrastructure.portfolio.qt_authorization import resolve_approved_person
    current = authority(101, "eric_shwartz")
    tx = SimpleNamespace(approval_authority=lambda user: current,
                         capability=lambda: {"enabled": True, "version": 1})
    with pytest.raises(QtWorkflowError) as error:
        resolve_approved_person(101, tx)
    assert error.value.code == "approval_identity_unmapped"


@pytest.mark.parametrize("person_id", ["john_riley", "dominick_dupuoy"])
def test_submitter_and_historical_typo_are_not_approval_identities(person_id):
    from algolens.infrastructure.portfolio.qt_authorization import resolve_approved_person
    current = authority(101, person_id)
    tx = SimpleNamespace(approval_authority=lambda user: current,
                         capability=lambda: {"enabled": True, "version": 1})
    with pytest.raises(QtWorkflowError) as error:
        resolve_approved_person(101, tx)
    assert error.value.code == "approval_identity_unmapped"


def test_corrected_dominick_identity_can_count():
    from algolens.infrastructure.portfolio.qt_authorization import resolve_approved_person
    current = authority(101, "dominick_dupuy")
    tx = SimpleNamespace(approval_authority=lambda user: current,
                         capability=lambda: {"enabled": True, "version": 1})
    assert asdict(resolve_approved_person(101, tx)) == person(101, "dominick_dupuy")


def test_current_mapping_and_explicit_distinct_quorum():
    from algolens.infrastructure.portfolio.qt_authorization import resolve_approved_person, two_person_quorum
    authorities = {101: authority(101, "hemdutt_rao", role="exec_board"), 202: authority(202, "xander_robbins")}
    tx = SimpleNamespace(approval_authority=lambda user: authorities[user],
                         capability=lambda: {"enabled": True, "version": 1})
    first = resolve_approved_person(101, tx)
    second = resolve_approved_person(202, tx)
    assert asdict(first) == person(101, "hemdutt_rao")
    assert not two_person_quorum([]) and not two_person_quorum([first, first])
    assert two_person_quorum([first, second])
    assert not two_person_quorum([first, person(202, "hemdutt_rao")])
    assert not two_person_quorum([first, person(101, "xander_robbins")])


@pytest.mark.parametrize("mutation", ["role", "grant", "mapping", "ambiguous", "unknown", "version", "capability"])
def test_missing_revoked_ambiguous_identity_cannot_count(mutation):
    from algolens.infrastructure.portfolio.qt_authorization import resolve_approved_person
    current = authority(101, "hemdutt_rao", role="exec_board")
    cap = {"enabled": True, "version": 1}
    if mutation == "role": current["account"]["role"] = "guest"
    elif mutation == "grant": current["grants"][0]["active"] = False
    elif mutation == "mapping": current["mappings"][0]["active"] = False
    elif mutation == "ambiguous": current["mappings"].append({**current["mappings"][0], "person_id": "john_riley"})
    elif mutation == "unknown": current["mappings"][0]["person_id"] = "display_name_person"
    elif mutation == "version": current["mappings"][0]["mapping_version"] = 0
    else: cap["enabled"] = False
    tx = SimpleNamespace(approval_authority=lambda user: current, capability=lambda: cap)
    with pytest.raises(QtWorkflowError): resolve_approved_person(101, tx)


def approval_fixture(monkeypatch):
    service, tx, facts, preview_id, confirm = confirmation_fixture(monkeypatch, breach=True)
    decision = service.confirm_preview(preview_id, 101, confirm).to_wire()
    tx.decision = deepcopy(tx.decisions[0])
    tx.override = deepcopy(tx.requests[0])
    tx.approvals = []
    tx.authorities = {101: authority(101, "john_riley"), 202: authority(202, "hemdutt_rao", role="exec_board"),
                      303: authority(303, "xander_robbins")}
    @contextmanager
    def transaction(book_id, actor_id):
        assert book_id == "BOOK"
        tx.actor_id = actor_id
        yield tx
    service.repository.transaction = transaction
    idempotency = {}
    def get_idempotent(operation, scope, key, digest):
        stored = idempotency.get((tx.actor_id, operation, scope, key))
        if stored is not None and stored[0] != digest: raise QtWorkflowError("idempotency_conflict")
        return deepcopy(stored[1]) if stored else None
    tx.get_idempotent = get_idempotent
    tx.insert_idempotent = lambda operation, scope, key, digest, response: idempotency.update({(tx.actor_id, operation, scope, key): (digest, deepcopy(response))})
    def lock_authorities(ids):
        tx.lock_order.append("auth")
        tx.locked_users = sorted(ids)
        return tuple(tx.authorities[user]["account"] for user in tx.locked_users)
    tx.lock_authorities = lock_authorities
    tx.approval_authority = lambda user: deepcopy(tx.authorities[user])
    tx.capability = lambda: deepcopy(facts["capability"])
    tx.get_override_context = lambda request: {"request": deepcopy(tx.override), "decision": deepcopy(tx.decision), "approvals": deepcopy(tx.approvals)}
    def route(request):
        return {"request_id": tx.override["request_id"], "decision_id": tx.decision["decision_id"],
                "preview_id": preview_id, "book_id": "BOOK", "source_day": tx.decision["source_day"],
                "created_by": 101, "approvals": deepcopy(tx.approvals)}
    service.repository.override_routing = route
    tx.read_current_facts = lambda **kwargs: deepcopy(facts)
    def insert_approval(data):
        tx.approvals.append({**data, "approved_at": "2026-09-25T12:01:00Z"})
        return data["approval_id"]
    tx.insert_approval = insert_approval
    def promote_decision(identity):
        assert tx.decision["status"] == "pending_override" and tx.preview["state"] == "pending_override"
        tx.decision["status"] = tx.preview["state"] = "confirmed_decision"
    tx.promote_decision = promote_decision
    approve = {"action": "approve", "idempotency_key": "00000000-0000-4000-8000-000000000071"}
    return service, tx, facts, decision["request_id"], approve


def test_submitter_cannot_count_and_two_distinct_non_submitters_promote(monkeypatch):
    service, tx, facts, request_id, approve = approval_fixture(monkeypatch)
    with pytest.raises(QtWorkflowError) as blocked:
        service.approve_override(request_id, 101, approve)
    assert blocked.value.code == "authorization_changed"
    assert tx.approvals == []
    first = service.approve_override(request_id, 202, approve).to_wire()
    assert first["status"] == "pending_override" and first["approvals_count"] == 1
    second = service.approve_override(
        request_id, 303,
        {**approve, "idempotency_key": "00000000-0000-4000-8000-000000000072"},
    ).to_wire()
    assert second["status"] == "confirmed_decision" and second["approvals_count"] == 2
    assert tx.preview["state"] == "confirmed_decision"
    assert len(tx.decisions) == 1 and len(tx.requests) == 1 and len(tx.approvals) == 2
    assert not second["report_ready"] and second["receipt"] is None and tx.position_mutations == 0
    assert tx.locked_users == [101, 202, 303]


def test_duplicate_click_is_idempotent_and_new_key_never_counts_twice(monkeypatch):
    service, tx, facts, request_id, approve = approval_fixture(monkeypatch)
    first = service.approve_override(request_id, 202, approve).to_wire()
    assert service.approve_override(request_id, 202, approve).to_wire() == first
    with pytest.raises(QtWorkflowError):
        service.approve_override(request_id, 202, {**approve, "idempotency_key": "00000000-0000-4000-8000-000000000072"})
    assert len(tx.approvals) == 1
    tx.authorities[202]["grants"][0]["active"] = False
    with pytest.raises(QtWorkflowError): service.approve_override(request_id, 202, approve)


@pytest.mark.parametrize("mutation", ["mapping", "grant", "role", "source", "draft", "policy"])
def test_second_approval_revalidates_every_counted_person_and_current_evidence(monkeypatch, mutation):
    service, tx, facts, request_id, approve = approval_fixture(monkeypatch)
    service.approve_override(request_id, 202, approve)
    if mutation == "mapping": tx.authorities[202]["mappings"][0]["mapping_version"] = 2
    elif mutation == "grant": tx.authorities[202]["grants"][0]["active"] = False
    elif mutation == "role": tx.authorities[202]["account"]["role"] = "guest"
    elif mutation == "source": facts["source_rows"][0]["quantity_exact"] = "99"
    elif mutation == "draft": tx.head["revision"] = 2
    else: tx.override["eligibility_version"] = 8
    with pytest.raises(QtWorkflowError): service.approve_override(
        request_id, 303,
        {**approve, "idempotency_key": "00000000-0000-4000-8000-000000000072"},
    )
    assert tx.decision["status"] == "pending_override" and len(tx.approvals) == 1


def test_changed_discovered_approval_set_rejects_without_out_of_order_lock(monkeypatch):
    service, tx, facts, request_id, approve = approval_fixture(monkeypatch)
    original = service.repository.override_routing
    def race(identity):
        route = original(identity)
        tx.approvals.append({"approval_id": "00000000-0000-4000-8000-000000000073", "request_id": request_id,
                             **person(303, "xander_robbins"), "approved_at": "2026-09-25T12:00:00Z"})
        return route
    service.repository.override_routing = race
    with pytest.raises(QtWorkflowError): service.approve_override(request_id, 202, approve)
    assert tx.locked_users == [101, 202] and tx.decision["status"] == "pending_override"


def test_explicit_typed_action_and_current_book_access_required(monkeypatch):
    service, tx, facts, request_id, approve = approval_fixture(monkeypatch)
    with pytest.raises(QtWorkflowError) as action:
        service.approve_override(request_id, 202, QtApproveRequest(action="deny", idempotency_key=approve["idempotency_key"]))
    assert action.value.code == "invalid_qt_action"
    facts["memberships"] = []
    with pytest.raises(QtWorkflowError): service.approve_override(request_id, 202, approve)
    assert not tx.approvals


def test_unrelated_inactive_person_does_not_veto_pair_and_replay_survives_source_change(monkeypatch):
    service, tx, facts, request_id, approve = approval_fixture(monkeypatch)
    tx.authorities[101]["mappings"][0]["active"] = False
    first = service.approve_override(request_id, 202, approve).to_wire()
    facts["source_rows"][0]["quantity_exact"] = "99"
    assert service.approve_override(request_id, 202, approve).to_wire() == first
    # Restore the actual pre-mutation fixture quantity, independent of MODEL guesses.
    facts["source_rows"][0]["quantity_exact"] = tx.preview["read_set_payload"]["source_rows"][0]["quantity_exact"]
    assert service.approve_override(
        request_id, 303,
        {**approve, "idempotency_key": "00000000-0000-4000-8000-000000000072"},
    ).to_wire()["approvals_count"] == 2


def test_locked_authority_reader_cannot_invent_unlocked_account():
    from algolens.infrastructure.portfolio.qt_workflow_repository import QtTransaction
    transaction = QtTransaction(None, "BOOK", 101)
    transaction._stage = 4
    with pytest.raises(QtWorkflowError): transaction.approval_authority(202)
