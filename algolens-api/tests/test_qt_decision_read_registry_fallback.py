"""Pure tests for F2: the override-approval evidence check must receive the
same per-key registry fallback get_proposal/get_draft already thread
through, or an equity book the catalog does not know can never validate a
pending_override decision -- the frontend's approve button never appears.

Three layers, no database:

1. `test_validate_preview_evidence_*`: exercise
   QtWorkflowService._validate_preview_evidence directly -- the function F2's
   fix threads the fallback into. This proves the function itself behaves
   correctly given a per-key registry mapping (and fails closed without
   one), but calling it directly bypasses the actual bug, which was at the
   CALL SITE in qt_decision_read.py._read_decision -- that call already
   accepted an optional registry_kind argument before the fix; the bug was
   that the call site never supplied it.
2. `test_read_decision_pending_override_threads_the_per_key_registry_fallback`
   (independent review finding 5): a BEHAVIORAL test that drives the real
   `_read_decision` pending_override branch, through the existing
   `tests/test_qt_read_service.py::decision_reader` harness, with a spy on
   `workflow._validate_preview_evidence`. This is discriminating in a way
   the AST test below is not (it would still pass if the call passed a 6th
   argument that was `None`, or the raw `registries` tuple): it asserts the
   spy's actual received value. Fails on the installed code (the spy
   receives `None`, since only 5 args are passed) and passes on the fix
   (the spy receives `{'LIVE_TREND': 'EQUITY'}`).
3. `test_read_decision_call_site_threads_the_registry_fallback`: a source-
   level regression guard on the same call site, kept as a second,
   independent signal (structural, not behavioral).

The PostgreSQL test in
tests/integration/test_qt_decision_read_registry_fallback_postgres.py is
the full end-to-end proof against a real database (written, not run here).
"""
import ast
from collections.abc import Mapping
from copy import deepcopy
from datetime import date
import inspect
from types import SimpleNamespace
import textwrap

import pytest

from algolens.application.portfolio.qt_decision_read import QtDecisionReadService
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from tests.test_qt_a6_confirmation import confirmation_fixture
from tests.test_qt_read_service import decision_reader


def _strict_registry_resolver(keys, registry_asset_class=None):
    """Simulates a book whose only symbol is unknown to the catalog: every
    key needs its OWN per-key registry fallback, or it fails closed exactly
    as the real QtTransaction.resolve_instrument_types does."""
    fallback = registry_asset_class if isinstance(registry_asset_class, Mapping) else {}
    resolved = {}
    for item in keys:
        kind = fallback.get(item.strategy_id)
        if kind is None:
            raise QtWorkflowError("draft_identity_unresolved", "QT instrument type is unavailable")
        resolved[item] = kind
    return resolved


def test_validate_preview_evidence_without_registry_fallback_raises_for_an_equity_only_book(monkeypatch):
    # This is the exact F2 bug reproduced at the unit closest to the call
    # site: qt_decision_read.py's _read_decision called
    # _validate_preview_evidence(tx, preview, book, day, facts) with no
    # fifth argument, so registry_kind defaulted to None and the equity
    # key's own strategy fallback was never consulted.
    service, tx, facts, preview_id, request = confirmation_fixture(monkeypatch)
    tx.resolve_instrument_types = _strict_registry_resolver
    with pytest.raises(QtWorkflowError) as blocked:
        service._validate_preview_evidence(tx, tx.preview, "BOOK", date.fromisoformat("2026-09-25"), facts)
    assert blocked.value.code == "draft_identity_unresolved"


def test_validate_preview_evidence_with_the_per_key_registry_fallback_resolves(monkeypatch):
    # F2's fix: qt_decision_read.py now captures `registries =
    # tx.lock_registries(ids)` and passes registry_asset_class(registries)
    # through. Threading the same per-key mapping this call site now
    # supplies lets an equity book's own strategy resolve past instrument
    # type and reach the rest of preview-evidence validation.
    service, tx, facts, preview_id, request = confirmation_fixture(monkeypatch)
    tx.resolve_instrument_types = _strict_registry_resolver
    payload, provenance, inputs, policy = service._validate_preview_evidence(
        tx, tx.preview, "BOOK", date.fromisoformat("2026-09-25"), facts, {"LIVE_TREND": "EQUITY"})
    assert payload["confirmable"] is True


def test_a_null_registry_asset_class_still_fails_closed_even_when_threaded(monkeypatch):
    # The registry fallback itself must still refuse a NULL asset_class --
    # threading it through must not paper over F1's fail-closed rule.
    service, tx, facts, preview_id, request = confirmation_fixture(monkeypatch)
    tx.resolve_instrument_types = _strict_registry_resolver
    with pytest.raises(QtWorkflowError) as blocked:
        service._validate_preview_evidence(
            tx, tx.preview, "BOOK", date.fromisoformat("2026-09-25"), facts, {"LIVE_TREND": None})
    assert blocked.value.code == "draft_identity_unresolved"


def test_read_decision_pending_override_threads_the_per_key_registry_fallback(monkeypatch):
    """Independent review finding 5: a behavioral (not merely structural)
    proof of the actual call-site fix, using the read-service's own
    `decision_reader` harness with a pending_override context."""
    service, tx, evidence, actors, context = decision_reader(monkeypatch)
    context["decision"]["status"] = "pending_override"
    context["request"] = {"request_id": "00000000-0000-4000-8000-000000000090",
                           "required_approvals": 2, "eligibility_version": 1}
    from algolens.infrastructure.portfolio import qt_decision_read_repository as storage
    monkeypatch.setattr(storage, "_context", lambda *a: deepcopy(context))
    # A pending_override decision has no receipt yet (desk processing has
    # not run); QtDecisionResponse.from_wire requires receipt is None here.
    tx.get_receipt = lambda _: None

    # An active+live owner row for the facts' own registry strategy_type
    # (LIVE_TREND, from DraftTransaction.read_current_facts), so
    # registry_asset_class(registries) resolves to a real per-key mapping
    # if -- and only if -- the call site actually threads `registries`
    # through. If it does not (the installed bug), this row is simply
    # never looked at.
    tx.lock_registries = lambda ids: [{"id": "registry-1", "strategy_type": "LIVE_TREND",
        "portfolio_id": "BOOK", "is_active": True, "lifecycle": "live", "asset_class": "EQUITY"}]

    # A stub person, so self.authorization.resolve(actor_id, tx) succeeds
    # without a real authorization adapter reaching a database.
    person = SimpleNamespace(person_id="eric_shwartz", user_id=202, mapping_version=1, grant_version=1)
    service.authorization = SimpleNamespace(resolve=lambda actor_id, tx: person)

    calls = []

    def spy(tx, preview, book, day, facts, registry_kind=None):
        calls.append(registry_kind)
        # Raise immediately: this test's assertion is on what the spy
        # actually received, not on the (heavier-to-fixture) downstream
        # can_approve computation.
        raise QtWorkflowError("preview_stale")

    monkeypatch.setattr(service.workflow, "_validate_preview_evidence", spy)

    response = service.get_decision("00000000-0000-4000-8000-000000000081", 202).to_wire()
    assert response["can_approve"] is False  # the spy always raises; not the assertion under test
    assert len(calls) == 1, "the pending_override branch must call _validate_preview_evidence exactly once"
    assert calls[0] == {"LIVE_TREND": "EQUITY"}, (
        "the call site must thread registry_asset_class(registries) through as the 6th argument; "
        f"got {calls[0]!r} (installed code passes only 5 args, so this is None there)")


def _validate_preview_evidence_call(source):
    """The single call to self.workflow._validate_preview_evidence inside
    QtDecisionReadService._read_decision's pending_override branch."""
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "_validate_preview_evidence"]
    assert len(calls) == 1, "expected exactly one _validate_preview_evidence call in _read_decision"
    return calls[0]


def test_read_decision_call_site_threads_the_registry_fallback():
    # F2's actual bug: _read_decision's pending_override branch called
    # self.workflow._validate_preview_evidence(tx, preview, book, day,
    # facts) -- 5 arguments, registry_kind defaulting to None -- even
    # though `registries = tx.lock_registries(ids)` was already available
    # a few lines above (assigned, but its result was discarded before the
    # fix: `tx.lock_registries(ids)` with no assignment).
    source = textwrap.dedent(inspect.getsource(QtDecisionReadService._read_decision))
    call = _validate_preview_evidence_call(source)
    assert len(call.args) + len(call.keywords) >= 6, (
        "the pending_override branch must pass a 6th argument (the per-key "
        "registry fallback) to _validate_preview_evidence")
    tree = ast.parse(source)
    assigned_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
                       and isinstance(node.ctx, ast.Store)}
    assert "registries" in assigned_names, (
        "lock_registries(ids)'s result must be captured (not discarded) so "
        "it can be threaded into registry_asset_class(...)")
