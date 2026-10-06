"""A4 draft admission and storage boundaries."""

import pytest
from contextlib import contextmanager
from dataclasses import replace
from datetime import date

from algolens.infrastructure.config.dependencies import create_qt_workflow_service
from algolens.infrastructure.portfolio.qt_provenance import QtExactPosition, QtProvenance

from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.domain.portfolio.qt_workflow_models import QtKey, QtSelectionRow, parse_qt_selection


BOOK = "BOOK"
DAY = "2026-09-25"


def key(symbol="ES", stream="qt_proposal"):
    return QtKey(BOOK, "LIVE_TREND", "TREND", DAY, symbol, stream)


def choice(component, quantity):
    return {"key": component.to_wire(), "quantity_exact": quantity}


def test_selection_preserves_existing_basis_and_appends_immutable():
    editable = key()
    immutable = key("NQ", "qt")
    source = QtSelectionRow(editable, "3", "preserved_source", "100", "FUTURE", True, "verified_model_seed")
    fixed = QtSelectionRow(immutable, "4", "preserved_source", "200", "FUTURE", False, "immutable")
    selected = parse_qt_selection(
        [choice(editable, "2")], frozenset({editable}), {editable: "FUTURE"},
        source_rows={editable: source}, immutable_rows=(fixed,),
    )
    assert selected == (
        QtSelectionRow(editable, "2", "preserved_source", "100", "FUTURE", True, "qt_draft"),
        fixed,
    )


def test_new_component_unfilled_and_fractional_future_rejected():
    new = key("AAPL")
    selected = parse_qt_selection([choice(new, "0.125")], frozenset({new}), {new: "EQUITY"})
    assert selected[0].basis_status == "unfilled"
    assert selected[0].average_price_exact is None
    with pytest.raises(QtWorkflowError, match="whole contracts"):
        parse_qt_selection([choice(new, "0.125")], frozenset({new}), {new: "FUTURE"})
    with pytest.raises(QtWorkflowError):
        parse_qt_selection([choice(new, "1"), choice(new, "1")], frozenset({new}), {new: "EQUITY"})


class DraftTransaction:
    def __init__(self):
        self.head = None
        self.pending = None
        self.idempotency = {}
        self.position_mutations = 0
        self.lock_order = []
        self.saved_rows = []
        self.grant_active = True

    def lock_authorities(self, ids):
        self.lock_order.append("auth")
        return ({"id": 101, "role": "general_member"},)

    def registry_ids_for_book(self):
        return ("registry-1",)

    def lock_registries(self, ids):
        self.lock_order.append("registry")

    def lock_books(self, ids):
        self.lock_order.append("book")

    def utc_source_day(self):
        return date.fromisoformat(DAY)

    def lock_mutable(self, *, source_day):
        self.lock_order.append("mutable")

    def read_current_facts(self):
        return {
            "source_day": DAY,
            "capability": {"status": "present", "enabled": True},
            "grants": [{"user_id": "101", "capability": "qt_submit", "active": self.grant_active}],
            "registry": [{"id": "registry-1", "portfolio_id": BOOK,
                          "strategy_type": "LIVE_TREND", "is_active": True, "lifecycle": "live"}],
            "memberships": [{"strategy_id": "registry-1", "portfolio_id": BOOK}],
            "provenance": {"source_digest": "a" * 64, "chain_digest": "b" * 64},
        }

    def read_source_evidence(self):
        return {"source_day": date.fromisoformat(DAY), "publications": [], "audits": [],
                "source_rows": [], "saved_rows": list(self.saved_rows), "system_rows": []}

    def resolve_instrument_types(self, keys, registry_asset_class=None):
        return {item: "FUTURE" if item.symbol == "ES" else "EQUITY" for item in keys}

    def get_draft_head(self, day):
        return self.head

    def insert_draft_revision(self, data):
        self.pending = data
        return data["draft_id"]

    def advance_draft_head(self, day, expected, draft_id, revision):
        if (self.head["revision"] if self.head else 0) != expected:
            raise QtWorkflowError("draft_stale")
        self.head = self.pending.copy()

    def get_idempotent(self, operation, scope, key, digest):
        value = self.idempotency.get((operation, scope, key))
        if value and value[0] != digest:
            raise QtWorkflowError("idempotency_conflict")
        return value[1] if value else None

    def insert_idempotent(self, operation, scope, key, digest, response):
        self.idempotency[(operation, scope, key)] = (digest, response)


class DraftRepository:
    def __init__(self):
        self.tx = DraftTransaction()

    @contextmanager
    def transaction(self, book_id, actor_id):
        assert (book_id, actor_id) == (BOOK, 101)
        yield self.tx


def _ready_provenance():
    return QtProvenance(
        "00000000-0000-4000-8000-000000000001", 1, "c" * 64,
        "a" * 64, "b" * 64, "ready",
        (QtExactPosition(key(stream="system"), "3", "100"),), (),
    )


def _save_request(rows, *, revision=0, idempotency="00000000-0000-4000-8000-000000000044",
                  rationale="Rebalance the selected book to the reviewed target."):
    return {
        "expected_source_digest": "a" * 64,
        "expected_provenance_digest": "b" * 64,
        "expected_draft_revision": revision,
        "idempotency_key": idempotency,
        "rationale": rationale,
        "selection_rows": rows,
    }


def test_draft_save_complete_selection_cas_and_idempotent_replay(monkeypatch):
    monkeypatch.setattr("algolens.infrastructure.portfolio.qt_workflow_runtime.reconcile_qt_source",
                        lambda *args, **kwargs: _ready_provenance())
    repository = DraftRepository()
    service = create_qt_workflow_service(repository)
    initial = service.get_draft(BOOK, 101)
    assert initial.to_wire()["state"] == "absent"
    assert initial.to_wire()["selection_rows"][0]["quantity_exact"] == "3"
    new = key("AAPL")
    request = _save_request([choice(key(), "2"), choice(new, "0.125")])
    saved = service.save_draft(BOOK, 101, request).to_wire()
    assert saved["draft_revision"] == 1
    assert saved["selection_rows"][0]["basis_status"] == "unfilled"
    assert next(row for row in saved["selection_rows"] if row["key"]["symbol"] == "ES")["average_price_exact"] == "100"
    assert repository.tx.head["selection_payload"]["rationale"] == request["rationale"]
    first_digest = repository.tx.head["draft_digest"]
    assert service.save_draft(BOOK, 101, request).to_wire() == saved
    assert repository.tx.position_mutations == 0
    assert repository.tx.lock_order[:4] == ["auth", "registry", "book", "mutable"]
    with pytest.raises(QtWorkflowError) as conflict:
        service.save_draft(BOOK, 101, {**request, "selection_rows": [choice(key(), "4"), choice(new, "0.125")]})
    assert conflict.value.code == "idempotency_conflict"
    with pytest.raises(QtWorkflowError) as changed_reason:
        service.save_draft(BOOK, 101, {**request, "rationale": "A different decision rationale."})
    assert changed_reason.value.code == "idempotency_conflict"
    assert repository.tx.head["draft_digest"] == first_digest
    with pytest.raises(QtWorkflowError) as stale:
        service.save_draft(BOOK, 101, _save_request([choice(key(), "2"), choice(new, "0.125")],
                                                  idempotency="00000000-0000-4000-8000-000000000055"))
    assert stale.value.code == "draft_stale"


def test_draft_rejects_incomplete_or_unowned_new_component(monkeypatch):
    monkeypatch.setattr("algolens.infrastructure.portfolio.qt_workflow_runtime.reconcile_qt_source",
                        lambda *args, **kwargs: _ready_provenance())
    service = create_qt_workflow_service(DraftRepository())
    with pytest.raises(QtWorkflowError) as incomplete:
        service.save_draft(BOOK, 101, _save_request([choice(key("AAPL"), "1")]))
    assert incomplete.value.code == "invalid_qt_key"
    foreign = QtKey(BOOK, "OTHER", "OTHER", DAY, "AAPL", "qt_proposal")
    with pytest.raises(QtWorkflowError) as unowned:
        service.save_draft(BOOK, 101, _save_request([choice(key(), "2"), choice(foreign, "1")]))
    assert unowned.value.code == "draft_identity_unresolved"


def test_second_revision_keeps_new_component_and_rejects_source_rebase(monkeypatch):
    monkeypatch.setattr("algolens.infrastructure.portfolio.qt_workflow_runtime.reconcile_qt_source",
                        lambda *args, **kwargs: _ready_provenance())
    repository = DraftRepository()
    service = create_qt_workflow_service(repository)
    new = key("AAPL")
    first = service.save_draft(BOOK, 101, _save_request(
        [choice(key(), "2"), choice(new, "0.125")])).to_wire()
    second = service.save_draft(BOOK, 101, _save_request(
        [choice(key(), "1"), choice(new, "0.25")], revision=1,
        idempotency="00000000-0000-4000-8000-000000000055")).to_wire()
    assert second["draft_revision"] == 2 and second["draft_id"] != first["draft_id"]
    assert len(second["selection_rows"]) == 2
    assert next(row for row in second["selection_rows"] if row["key"]["symbol"] == "AAPL")["basis_status"] == "unfilled"
    repository.tx.head["source_digest"] = "f" * 64
    with pytest.raises(QtWorkflowError) as stale:
        service.save_draft(BOOK, 101, _save_request(
            [choice(key(), "1"), choice(new, "0.25")], revision=2,
            idempotency="00000000-0000-4000-8000-000000000066"))
    assert stale.value.code == "draft_stale"


def test_immutable_saved_qt_row_is_preserved_outside_editable_selection(monkeypatch):
    monkeypatch.setattr("algolens.infrastructure.portfolio.qt_workflow_runtime.reconcile_qt_source",
                        lambda *args, **kwargs: _ready_provenance())
    repository = DraftRepository()
    saved = key("NQ", "qt")
    original_reader = repository.tx.read_source_evidence

    def with_immutable():
        source = original_reader()
        source["saved_rows"] = [{"key": saved.to_wire(), "quantity_exact": "4",
                                 "average_price_exact": "200"}]
        return source

    repository.tx.read_source_evidence = with_immutable
    result = create_qt_workflow_service(repository).save_draft(
        BOOK, 101, _save_request([choice(key(), "2")])).to_wire()
    immutable = next(row for row in result["selection_rows"] if row["key"]["symbol"] == "NQ")
    assert immutable["editable"] is False
    assert immutable["quantity_exact"] == "4" and immutable["average_price_exact"] == "200"


def test_stored_draft_digest_is_checked_before_read_or_update(monkeypatch):
    monkeypatch.setattr("algolens.infrastructure.portfolio.qt_workflow_runtime.reconcile_qt_source",
                        lambda *args, **kwargs: _ready_provenance())
    repository = DraftRepository()
    service = create_qt_workflow_service(repository)
    service.save_draft(BOOK, 101, _save_request([choice(key(), "2")]))
    repository.tx.head["draft_digest"] = "f" * 64
    with pytest.raises(QtWorkflowError) as corrupt:
        service.get_draft(BOOK, 101)
    assert corrupt.value.code == "draft_identity_unresolved"
    with pytest.raises(QtWorkflowError) as corrupt:
        service.save_draft(BOOK, 101, _save_request(
            [choice(key(), "1")], revision=1,
            idempotency="00000000-0000-4000-8000-000000000055"))
    assert corrupt.value.code == "draft_identity_unresolved"


def test_changed_independent_qt_row_stales_read_and_update(monkeypatch):
    monkeypatch.setattr("algolens.infrastructure.portfolio.qt_workflow_runtime.reconcile_qt_source",
                        lambda *args, **kwargs: _ready_provenance())
    repository = DraftRepository()
    independent = key("NQ", "qt")
    repository.tx.saved_rows = [{"key": independent.to_wire(), "quantity_exact": "4",
                                 "average_price_exact": "200"}]
    service = create_qt_workflow_service(repository)
    first = service.save_draft(BOOK, 101, _save_request([choice(key(), "2")])).to_wire()
    assert first["state"] == "saved"
    repository.tx.saved_rows[0]["quantity_exact"] = "5"
    assert service.get_draft(BOOK, 101).to_wire()["state"] == "stale"
    with pytest.raises(QtWorkflowError) as stale:
        service.save_draft(BOOK, 101, _save_request(
            [choice(key(), "1")], revision=1,
            idempotency="00000000-0000-4000-8000-000000000055"))
    assert stale.value.code == "draft_stale"


def test_revision_can_remove_prior_draft_only_component(monkeypatch):
    monkeypatch.setattr("algolens.infrastructure.portfolio.qt_workflow_runtime.reconcile_qt_source",
                        lambda *args, **kwargs: _ready_provenance())
    repository = DraftRepository()
    service = create_qt_workflow_service(repository)
    first = service.save_draft(BOOK, 101, _save_request(
        [choice(key(), "2"), choice(key("AAPL"), "0.125")])).to_wire()
    second = service.save_draft(BOOK, 101, _save_request(
        [choice(key(), "1")], revision=1,
        idempotency="00000000-0000-4000-8000-000000000055")).to_wire()
    assert second["draft_revision"] == 2
    assert [row["key"]["symbol"] for row in second["selection_rows"]] == ["ES"]
    with pytest.raises(QtWorkflowError) as incomplete:
        service.save_draft(BOOK, 101, _save_request(
            [], revision=2, idempotency="00000000-0000-4000-8000-000000000066"))
    assert incomplete.value.code == "invalid_qt_key"


def test_committed_retry_replays_after_unresolved_source_but_requires_current_grant(monkeypatch):
    unresolved = {"value": False}
    monkeypatch.setattr("algolens.infrastructure.portfolio.qt_workflow_runtime.reconcile_qt_source",
                        lambda *args, **kwargs: replace(_ready_provenance(), status="provenance_unresolved")
                        if unresolved["value"] else _ready_provenance())
    repository = DraftRepository()
    service = create_qt_workflow_service(repository)
    request = _save_request([choice(key(), "2")])
    first = service.save_draft(BOOK, 101, request).to_wire()
    unresolved["value"] = True
    assert service.save_draft(BOOK, 101, request).to_wire() == first
    with pytest.raises(QtWorkflowError) as conflict:
        service.save_draft(BOOK, 101, {**request, "selection_rows": [choice(key(), "1")]})
    assert conflict.value.code == "idempotency_conflict"
    repository.tx.grant_active = False
    with pytest.raises(QtWorkflowError) as denied:
        service.save_draft(BOOK, 101, request)
    assert denied.value.code == "authorization_changed"
