"""Persisted-draft preview admission without any financial fallback."""

from copy import deepcopy
import pytest

from algolens.infrastructure.config.dependencies import create_qt_workflow_service
from algolens.domain.portfolio.qt_canonical import qt_digest_v1
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.domain.portfolio.qt_workflow_models import QtSelectionRow
from tests.test_qt_a4_draft import BOOK, DAY, DraftRepository, key, _ready_provenance
from tests.test_qt_workflow_domain import _read_set_facts


def preview_fixture(monkeypatch):
    monkeypatch.setattr("algolens.infrastructure.portfolio.qt_workflow_runtime.reconcile_qt_source",
                        lambda *args, **kwargs: _ready_provenance())
    repository = DraftRepository()
    row = QtSelectionRow(key(), "2", "preserved_source", "100", "FUTURE", True, "qt_draft").to_wire()
    payload = {"selection_rows": [row]}
    repository.tx.head = {"draft_id": "00000000-0000-4000-8000-000000000011", "revision": 1,
        "source_digest": "a" * 64, "provenance_digest": "b" * 64,
        "draft_digest": qt_digest_v1(payload), "selection_payload": payload,
        "model_publication_id": "00000000-0000-4000-8000-000000000001",
        "model_publication_version": 1, "seed_digest": "c" * 64}
    facts = _read_set_facts()
    facts.update(book_id=BOOK, source_day=DAY,
        source_rows=[{"key": key().to_wire(), "quantity_exact": "3", "average_price_exact": "100",
                      "position_revision": "00000000-0000-4000-8000-000000000099"}],
        saved_rows=[], saved_accounting=[],
        system_rows=[{"key": key(stream="system").to_wire(), "quantity_exact": "3", "average_price_exact": "100"}],
        registry=[{"id": "registry-1", "strategy_type": "LIVE_TREND", "portfolio_id": BOOK,
                   "is_active": True, "lifecycle": "live", "updated_at": "2026-09-25T11:00:00Z"}],
        memberships=[{"strategy_id": "registry-1", "portfolio_id": BOOK}],
        draft={"status": "present", "draft_id": repository.tx.head["draft_id"], "revision": 1,
               "digest": repository.tx.head["draft_digest"]},
        provenance={"status": "ready", "source_digest": "a" * 64, "chain_digest": "b" * 64, "seed_digest": "c" * 64})
    repository.tx.read_current_facts = lambda: deepcopy(facts)
    repository.tx.previews = []
    repository.tx.insert_preview = lambda data: repository.tx.previews.append(data) or data["preview_id"]
    request = {"book_id": BOOK, "draft_id": repository.tx.head["draft_id"], "draft_revision": 1,
               "draft_digest": repository.tx.head["draft_digest"], "expected_source_digest": "a" * 64,
               "expected_provenance_digest": "b" * 64,
               "idempotency_key": "00000000-0000-4000-8000-000000000044"}
    return create_qt_workflow_service(repository), repository, request


def test_missing_governed_input_persists_only_unavailable_preview(monkeypatch):
    service, repository, request = preview_fixture(monkeypatch)

    def unavailable(*args, **kwargs):
        raise QtWorkflowError("preview_unavailable")

    monkeypatch.setattr("algolens.infrastructure.portfolio.qt_workflow_runtime.load_qt_evaluation_inputs", unavailable, raising=False)
    first = service.create_preview(101, request).to_wire()
    assert first["availability"] == "unavailable"
    assert not first["confirmable"] and not first["requires_override"]
    assert first["unavailable_reasons"] == ["governed_inputs_unavailable"]
    assert service.create_preview(101, request).to_wire() == first
    assert len(repository.tx.previews) == 1
    assert repository.tx.position_mutations == 0


def test_preview_rejects_unsaved_selection_or_stale_draft_identity(monkeypatch):
    service, repository, request = preview_fixture(monkeypatch)
    with pytest.raises(QtWorkflowError) as unsaved:
        service.create_preview(101, {**request, "selection_rows": []})
    assert unsaved.value.code == "invalid_qt_payload"
    with pytest.raises(QtWorkflowError) as stale:
        service.create_preview(101, {**request, "draft_revision": 2})
    assert stale.value.code == "draft_stale"
    assert not repository.tx.previews
