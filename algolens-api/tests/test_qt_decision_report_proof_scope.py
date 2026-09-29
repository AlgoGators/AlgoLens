"""Pure tests for independent review finding 1: the processed-report proof's
`report_scope` must come from before UNION after (mirroring the native
processor, qt_desk_processor.cpp report() ~line 321-326), not from `before`
alone.

`_prove_processed` (qt_decision_report_proof.py) calls three collaborators
that independently do real cryptographic/financial proof work
(`validate_qt_publication_chain`, `current_accounting_after`,
`capture_qt_read_set`) before reaching the scope check. This file stubs
exactly those three -- the same technique the independent reviewer used --
so these tests are pure, fast and isolate only the scope-derivation logic.
`report_row_manifest` itself is NOT stubbed: it is exercised for real, using
the same before/after/selection shapes as the shared vectors v2 cases
`open_into_empty_before_book` and `open_from_absent_new_strategy_name`, so
this file also incidentally re-proves the manifest side for these two
vectors end to end through the processed-report path, not just through
`report_row_manifest` in isolation.
"""
from copy import deepcopy
from types import SimpleNamespace

import algolens.infrastructure.portfolio.qt_decision_report_proof as target
from algolens.domain.portfolio.qt_workflow_models import QtKey


BOOK, DAY = "QT_BOOK", "2026-09-25"


def _row(symbol, quantity, strategy_name, strategy_id="RUN"):
    key = QtKey(BOOK, strategy_id, strategy_name, DAY, symbol, "qt")
    return key, {"key": key.to_wire(), "quantity_exact": quantity, "average_price_exact": "10",
                 "daily_unrealized_pnl_exact": "0", "daily_realized_pnl_exact": "0",
                 "last_update": f"{DAY}T20:00:00Z"}


def _selection(symbol, strategy_name, asset_type="FUTURE", strategy_id="RUN"):
    return {"asset_type": asset_type, "key": {"date": DAY, "portfolio_id": BOOK,
            "strategy_id": strategy_id, "strategy_name": strategy_name, "symbol": symbol}}


def _drive(monkeypatch, before_pairs, after_pairs, selection_rows):
    """Build minimal evidence for the given before/after rows, stub the
    three collaborators `_prove_processed` does not itself re-derive scope
    from, and return processed_report_blocked_reasons(evidence)."""
    old = dict(before_pairs)
    new = dict(after_pairs)
    before_accounting = [row for _, row in before_pairs]
    after_accounting = [row for _, row in after_pairs]

    manifest = target.report_row_manifest(before_accounting, after_accounting, selection_rows)
    assert manifest is not None, "test setup: the vector shape itself must be eligible"

    decision = {"decision_id": "00000000-0000-4000-8000-000000000001",
                "book_id": BOOK, "source_day": DAY}
    receipt = {"publication_payload": {"before_accounting": before_accounting,
                   "after_accounting": after_accounting, "report_scope": None},
               "report_eligibility_status": "eligible", "report_reason_codes": [],
               "row_manifest_digest": manifest}
    observation = {"payload": {"schema_version": "qt-execution/v1"},
                    "producer_id": "synthetic-producer", "policy_version": "synthetic-policy-v1"}
    saved_rows = [{"key": row["key"], "quantity_exact": row["quantity_exact"],
                   "average_price_exact": row["average_price_exact"]} for row in after_accounting]
    current_facts = {"saved_accounting": deepcopy(after_accounting), "saved_rows": saved_rows,
                      "audit_refs": []}
    evidence = {"decision": decision, "receipt": receipt, "observation": observation,
                "latest_decision_id": decision["decision_id"],
                "execution_policy": {"enabled": True, "producer_id": observation["producer_id"],
                                      "policy_version": observation["policy_version"]},
                "current_facts": current_facts, "checked_at": f"{DAY}T20:00:01Z"}

    def stub_validate_qt_publication_chain(evidence, **kwargs):
        return {"before": old, "after": new, "audit_additions": {},
                "payload": {"selection_rows": selection_rows},
                "original": {"saved_rows": [], "saved_accounting": [], "provenance": {}, "audit_refs": []}}

    def stub_current_accounting_after(evidence, new, **kwargs):
        d = evidence["decision"]
        return target._accounting(evidence["current_facts"]["saved_accounting"], d["book_id"], str(d["source_day"]))

    def stub_capture_qt_read_set(current):
        return SimpleNamespace(available=True, digest="matched-read-set-digest")

    monkeypatch.setattr(target, "validate_qt_publication_chain", stub_validate_qt_publication_chain)
    monkeypatch.setattr(target, "current_accounting_after", stub_current_accounting_after)
    monkeypatch.setattr(target, "capture_qt_read_set", stub_capture_qt_read_set)
    decision["read_set_digest"] = "matched-read-set-digest"
    # report_scope is what the fix must derive correctly; set it to the
    # NATIVE-shaped expectation (before UNION after) so `pub['report_scope']
    # == scope` in _prove_processed passes only when the API's own
    # derivation matches it.
    ids = {key.strategy_id for key in old} | {key.strategy_id for key in new}
    names = sorted({key.strategy_name for key in old} | {key.strategy_name for key in new})
    receipt["publication_payload"]["report_scope"] = {
        "portfolio_id": BOOK, "strategy_id": next(iter(ids)),
        "strategy_names": names, "portfolio_type": "qt", "date": DAY,
    }
    return target.processed_report_blocked_reasons(evidence)


def test_opening_into_an_empty_before_book_is_ready(monkeypatch):
    # Shared vector: open_into_empty_before_book. before = [] entirely (a
    # book with no QT rows at all opening its first position). Before this
    # fix, `first = next(iter(old))` raised StopIteration here, caught and
    # reported as report_snapshot_stale even though report_row_manifest
    # itself (already fixed) returns a valid digest.
    before_pairs = []
    after_pairs = [_row("NQ", "2", "alpha")]
    selection_rows = [_selection("NQ", "alpha", asset_type="FUTURE")]
    assert _drive(monkeypatch, before_pairs, after_pairs, selection_rows) == ()


def test_opening_from_absent_under_a_new_strategy_name_is_ready_with_both_names(monkeypatch):
    # Shared vector: open_from_absent_new_strategy_name. before has only
    # 'alpha'/SYN; after adds a genuinely new strategy_name 'beta'/ALT under
    # the same strategy_id. Before this fix, strategy_names was recomputed
    # from `old` alone (["alpha"]), so `pub['report_scope'] == scope`
    # failed against the native-shaped publication (["alpha","beta"]).
    before_pairs = [_row("SYN", "5", "alpha")]
    after_pairs = [_row("SYN", "5", "alpha"), _row("ALT", "-3", "beta")]
    selection_rows = [_selection("SYN", "alpha", asset_type="EQUITY"),
                       _selection("ALT", "beta", asset_type="EQUITY")]
    assert _drive(monkeypatch, before_pairs, after_pairs, selection_rows) == ()


def test_a_wrong_report_scope_still_refuses_after_the_fix(monkeypatch):
    # Confirms the fix is a real equality check, not a tautology: if the
    # publication's stored report_scope does not match the union-derived
    # scope (for example, a stale strategy_names list missing the new
    # name), the report is still refused. Reuses the new-strategy-name
    # shape, but corrupts the expected receipt scope after _drive would
    # have set it correctly.
    before_pairs = [_row("SYN", "5", "alpha")]
    after_pairs = [_row("SYN", "5", "alpha"), _row("ALT", "-3", "beta")]
    selection_rows = [_selection("SYN", "alpha", asset_type="EQUITY"),
                       _selection("ALT", "beta", asset_type="EQUITY")]

    def corrupt_scope(monkeypatch, before_pairs, after_pairs, selection_rows):
        old = dict(before_pairs)
        new = dict(after_pairs)
        before_accounting = [row for _, row in before_pairs]
        after_accounting = [row for _, row in after_pairs]
        manifest = target.report_row_manifest(before_accounting, after_accounting, selection_rows)
        decision = {"decision_id": "00000000-0000-4000-8000-000000000002", "book_id": BOOK, "source_day": DAY}
        receipt = {"publication_payload": {"before_accounting": before_accounting,
                       "after_accounting": after_accounting,
                       # Stale: only the before-side name, exactly the old bug's own output.
                       "report_scope": {"portfolio_id": BOOK, "strategy_id": "RUN",
                           "strategy_names": ["alpha"], "portfolio_type": "qt", "date": DAY}},
                   "report_eligibility_status": "eligible", "report_reason_codes": [],
                   "row_manifest_digest": manifest}
        observation = {"payload": {"schema_version": "qt-execution/v1"},
                        "producer_id": "synthetic-producer", "policy_version": "synthetic-policy-v1"}
        saved_rows = [{"key": row["key"], "quantity_exact": row["quantity_exact"],
                       "average_price_exact": row["average_price_exact"]} for row in after_accounting]
        current_facts = {"saved_accounting": deepcopy(after_accounting), "saved_rows": saved_rows, "audit_refs": []}
        evidence = {"decision": decision, "receipt": receipt, "observation": observation,
                    "latest_decision_id": decision["decision_id"],
                    "execution_policy": {"enabled": True, "producer_id": observation["producer_id"],
                                          "policy_version": observation["policy_version"]},
                    "current_facts": current_facts, "checked_at": f"{DAY}T20:00:01Z"}
        decision["read_set_digest"] = "matched-read-set-digest"

        def stub_validate_qt_publication_chain(evidence, **kwargs):
            return {"before": old, "after": new, "audit_additions": {},
                    "payload": {"selection_rows": selection_rows},
                    "original": {"saved_rows": [], "saved_accounting": [], "provenance": {}, "audit_refs": []}}

        def stub_current_accounting_after(evidence, new, **kwargs):
            d = evidence["decision"]
            return target._accounting(evidence["current_facts"]["saved_accounting"], d["book_id"], str(d["source_day"]))

        def stub_capture_qt_read_set(current):
            return SimpleNamespace(available=True, digest="matched-read-set-digest")

        monkeypatch.setattr(target, "validate_qt_publication_chain", stub_validate_qt_publication_chain)
        monkeypatch.setattr(target, "current_accounting_after", stub_current_accounting_after)
        monkeypatch.setattr(target, "capture_qt_read_set", stub_capture_qt_read_set)
        return target.processed_report_blocked_reasons(evidence)

    assert corrupt_scope(monkeypatch, before_pairs, after_pairs, selection_rows) == ("report_snapshot_stale",)
