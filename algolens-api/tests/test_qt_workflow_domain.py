"""A3 source provenance and current read-set behavior, with synthetic evidence."""

from datetime import date

import pytest

from algolens.domain.portfolio.qt_canonical import qt_digest_v1
from algolens.infrastructure.portfolio.qt_provenance import (
    reconcile_qt_source,
    verify_exact_proposal_audits,
)
from algolens.infrastructure.portfolio.qt_read_set import (
    canonical_internal_snapshot_bytes,
    capture_qt_read_set,
    internal_snapshot_digest,
)
from algolens.infrastructure.portfolio.qt_workflow_repository import QtTransaction


DAY = date(2026, 9, 25)
BOOK = "synthetic-book-A"
PUBLICATION_ID = "10000000-0000-4000-8000-000000000001"
SECOND_PUBLICATION_ID = "10000000-0000-4000-8000-000000000002"
REVISION_ID = "30000000-0000-4000-8000-000000000001"
SEED_DIGEST = "a6c33d6973d6cca994a5a08a2e98a69638abb68c2d6d835803e32b25bcea6ef8"


def key(stream="system", *, symbol="SYN", strategy_name="synthetic-alpha", day="2026-09-25"):
    return {
        "portfolio_id": BOOK,
        "strategy_id": "component-1",
        "strategy_name": strategy_name,
        "date": day,
        "symbol": symbol,
        "portfolio_type": stream,
    }


def row(stream="system", *, quantity="4", basis="100", revision=None, **key_changes):
    value = {
        "key": key(stream, **key_changes),
        "quantity_exact": quantity,
        "average_price_exact": basis,
    }
    if stream == "qt_proposal":
        value["position_revision"] = revision
    return value


def publication():
    return {
        "publication_id": PUBLICATION_ID,
        "attempt_id": None,
        "portfolio_id": BOOK,
        "strategy_id": "component-1",
        "source_day": DAY,
        "publication_version": 1,
        "system_components": [row()],
        "seed_digest": SEED_DIGEST,
        "producer_version": "synthetic-build-1",
    }


def audit_state(stream="qt_proposal", *, quantity="4", basis="100"):
    return {
        **key(stream),
        "quantity": float(quantity),
        "average_price": float(basis),
        "quantity_exact": quantity,
        "average_price_exact": basis,
    }


def audit_entry(before=None, after=None):
    return {
        "id": 17,
        "user_id": 101,
        "portfolio_id": BOOK,
        "strategy_id": "component-1",
        "symbol": "SYN",
        "source_app": "algolens",
        "before_state": audit_state() if before is None else before,
        "after_state": audit_state(quantity="5") if after is None else after,
    }


def synthetic_lineage():
    # This immutable per-key insertion proof is the frozen E1 correction.
    return [{
        "action": "inserted",
        "key": key("qt_proposal"), "quantity_exact": "4", "average_price_exact": "100",
        "position_revision": REVISION_ID, "origin_publication_id": PUBLICATION_ID,
    }]


def linked_publication():
    value = publication()
    value["proposal_components"] = synthetic_lineage()
    value["proposal_manifest_digest"] = internal_snapshot_digest(
        "qt-proposal-manifest/v1", {"proposal_rows": synthetic_lineage()}
    )
    return value


def test_equal_value_without_publication_is_not_model_seed():
    result = reconcile_qt_source(BOOK, DAY, None, [row("qt_proposal")], [])
    assert result.status == "provenance_unresolved"
    assert result.seed_rows == ()


def test_matching_seed_does_not_prove_proposal_lineage():
    result = reconcile_qt_source(
        BOOK, DAY, [publication()], [row("qt_proposal")], [],
        observed_system_rows=[row()],
    )
    assert result.status == "provenance_unresolved"
    assert result.draft_overlay == ()


def test_explicit_exact_proposal_audit_chain_reconciles_human_edit():
    verified = verify_exact_proposal_audits(
        [row("qt_proposal", revision=REVISION_ID)], [audit_entry()]
    )
    assert verified[0].quantity_exact == "5"
    result = reconcile_qt_source(
        BOOK, DAY, [linked_publication()],
        [row("qt_proposal", quantity="5", revision=REVISION_ID)], [audit_entry()],
        observed_system_rows=[row()],
    )
    # A qt_proposal UPDATE refreshes its physical token. Existing audits have
    # no approved transition tying that new token to the original insertion.
    assert result.status == "provenance_unresolved"


def test_verified_qt_edit_is_overlay_without_becoming_proposal_lineage():
    audit = audit_entry(before=audit_state("qt", quantity="7"),
                        after=audit_state("qt", quantity="5"))
    result = reconcile_qt_source(
        BOOK, DAY, [linked_publication()],
        [row("qt_proposal", revision=REVISION_ID)], [audit],
        observed_saved_rows=[row("qt", quantity="5")],
        observed_system_rows=[row()],
    )
    assert result.status == "ready"
    assert result.draft_overlay[0].key.portfolio_type == "qt_proposal"
    assert result.draft_overlay[0].quantity_exact == "5"
    assert result.legacy_audit_chain_digest is not None


@pytest.mark.parametrize("change", ["wrong_stream", "broken_before", "missing_identity", "float_only", "no_current_row", "scope_mismatch"])
def test_unverified_qt_edit_cannot_be_overlay(change):
    audit = audit_entry(before=audit_state("qt", quantity="7"),
                        after=audit_state("qt", quantity="5"))
    saved = [row("qt", quantity="5")]
    audits = [audit]
    if change == "wrong_stream":
        audit["after_state"]["portfolio_type"] = "qt_proposal"
    elif change == "broken_before":
        second = audit_entry(before=audit_state("qt", quantity="3"),
                             after=audit_state("qt", quantity="5"))
        second["id"] = 18
        audits.append(second)
    elif change == "missing_identity":
        audit["before_state"].pop("strategy_name")
    elif change == "float_only":
        audit["after_state"].pop("quantity_exact")
    elif change == "no_current_row":
        saved.clear()
    elif change == "scope_mismatch":
        audit["strategy_id"] = "another-component"
    result = reconcile_qt_source(
        BOOK, DAY, [linked_publication()],
        [row("qt_proposal", revision=REVISION_ID)], audits,
        observed_saved_rows=saved,
        observed_system_rows=[row()],
    )
    assert result.status == "provenance_unresolved"
    assert result.draft_overlay == ()


@pytest.mark.parametrize(
    "change",
    [
        "wrong_day", "wrong_digest", "duplicate_publication", "added_component",
        "deleted_component", "changed_basis", "wrong_stream_audit",
        "missing_before_identity", "broken_chain", "duplicate_audit_id", "float_only_audit",
    ],
)
def test_unproven_publication_or_audit_branch_is_unresolved(change):
    pubs = [linked_publication()]
    observed = [row("qt_proposal", quantity="5", revision=REVISION_ID)]
    audit = audit_entry()
    audits = [audit]
    if change == "wrong_day":
        pubs[0]["source_day"] = date(2026, 9, 24)
    elif change == "wrong_digest":
        pubs[0]["seed_digest"] = "0" * 64
    elif change == "duplicate_publication":
        pubs.append(publication())
    elif change == "added_component":
        observed.append(row("qt_proposal", quantity="0", symbol="OTHER"))
    elif change == "deleted_component":
        observed.clear()
    elif change == "changed_basis":
        observed[0]["average_price_exact"] = "101"
    elif change == "wrong_stream_audit":
        audit["before_state"] = audit_state("qt")
        audit["after_state"] = audit_state("qt", quantity="5")
    elif change == "missing_before_identity":
        audit["before_state"].pop("strategy_name")
    elif change == "broken_chain":
        audit["before_state"]["quantity_exact"] = "3"
    elif change == "duplicate_audit_id":
        audits.append(audit.copy())
    elif change == "float_only_audit":
        audit["before_state"].pop("quantity_exact")
        audit["after_state"].pop("quantity_exact")
    result = reconcile_qt_source(
        BOOK, DAY, pubs, observed, audits, observed_system_rows=[row()]
    )
    assert result.status == "provenance_unresolved"


def test_internal_source_vector_is_closed_and_literal():
    document = {
        "schema_version": "qt-source/v1", "book_id": "B", "source_day": "2026-09-25",
        "rows": [],
    }
    assert canonical_internal_snapshot_bytes("qt-source/v1", document) == (
        b'{"book_id":"B","rows":[],"schema_version":"qt-source/v1",'
        b'"source_day":"2026-09-25"}'
    )
    with pytest.raises(ValueError):
        canonical_internal_snapshot_bytes("qt-source/v1", {**document, "unknown": "x"})
    with pytest.raises(ValueError):
        canonical_internal_snapshot_bytes("qt-source/v1", {
            **document, "rows": [row("qt_proposal", quantity="1.00000000")]
        })
    with pytest.raises(ValueError):
        canonical_internal_snapshot_bytes("qt-source/v1", {
            **document, "rows": [row("qt_proposal"), row("qt_proposal")]
        })


def test_literal_inserted_proposal_manifest_vector():
    envelope = {"proposal_rows": synthetic_lineage()}
    assert canonical_internal_snapshot_bytes("qt-proposal-manifest/v1", envelope) == (
        b'{"proposal_rows":[{"action":"inserted","average_price_exact":"100",'
        b'"key":{"date":"2026-09-25","portfolio_id":"synthetic-book-A",'
        b'"portfolio_type":"qt_proposal","strategy_id":"component-1",'
        b'"strategy_name":"synthetic-alpha","symbol":"SYN"},'
        b'"origin_publication_id":"10000000-0000-4000-8000-000000000001",'
        b'"position_revision":"30000000-0000-4000-8000-000000000001",'
        b'"quantity_exact":"4"}]}'
    )


def test_engine_shared_inserted_manifest_digest_vector():
    entry = {
        "action": "inserted", "average_price_exact": "101",
        "key": {"date": "2026-09-22", "portfolio_id": "BOOK",
                "portfolio_type": "qt_proposal", "strategy_id": "LIVE_TREND",
                "strategy_name": "TREND", "symbol": "ES"},
        "origin_publication_id": "00000000-0000-4000-8000-000000000001",
        "position_revision": "00000000-0000-4000-8000-000000000011",
        "quantity_exact": "12",
    }
    expected = (
        b'{"proposal_rows":[{"action":"inserted","average_price_exact":"101",'
        b'"key":{"date":"2026-09-22","portfolio_id":"BOOK",'
        b'"portfolio_type":"qt_proposal","strategy_id":"LIVE_TREND",'
        b'"strategy_name":"TREND","symbol":"ES"},'
        b'"origin_publication_id":"00000000-0000-4000-8000-000000000001",'
        b'"position_revision":"00000000-0000-4000-8000-000000000011",'
        b'"quantity_exact":"12"}]}'
    )
    assert canonical_internal_snapshot_bytes("qt-proposal-manifest/v1", {"proposal_rows": [entry]}) == expected
    assert internal_snapshot_digest("qt-proposal-manifest/v1", {"proposal_rows": [entry]}) == (
        "eb4b978ea28c61429a9ba35f7c53f3b5ff6d27c7125ddda4415fb9c33df82cff"
    )
    preserved = {**entry, "action": "preserved", "average_price_exact": "202",
                 "key": {**entry["key"], "symbol": "NQ"},
                 "origin_publication_id": "00000000-0000-4000-8000-000000000002",
                 "position_revision": "00000000-0000-4000-8000-000000000022",
                 "quantity_exact": "0"}
    unresolved = {**entry, "action": "preserved", "average_price_exact": "303",
                  "key": {**entry["key"], "symbol": "YM"},
                  "origin_publication_id": None, "position_revision": None,
                  "quantity_exact": "5.25"}
    suffix_preserved = (
        b',{"action":"preserved","average_price_exact":"202",'
        b'"key":{"date":"2026-09-22","portfolio_id":"BOOK",'
        b'"portfolio_type":"qt_proposal","strategy_id":"LIVE_TREND",'
        b'"strategy_name":"TREND","symbol":"NQ"},'
        b'"origin_publication_id":"00000000-0000-4000-8000-000000000002",'
        b'"position_revision":"00000000-0000-4000-8000-000000000022",'
        b'"quantity_exact":"0"}'
    )
    suffix_unresolved = (
        b',{"action":"preserved","average_price_exact":"303",'
        b'"key":{"date":"2026-09-22","portfolio_id":"BOOK",'
        b'"portfolio_type":"qt_proposal","strategy_id":"LIVE_TREND",'
        b'"strategy_name":"TREND","symbol":"YM"},'
        b'"origin_publication_id":null,"position_revision":null,"quantity_exact":"5.25"}'
    )
    two_rows = expected[:-2] + suffix_preserved + b']}'
    three_rows = expected[:-2] + suffix_preserved + suffix_unresolved + b']}'
    assert canonical_internal_snapshot_bytes("qt-proposal-manifest/v1", {"proposal_rows": [entry, preserved]}) == two_rows
    assert internal_snapshot_digest("qt-proposal-manifest/v1", {"proposal_rows": [entry, preserved]}) == (
        "fc2ebfda08f041b86d997035490cc1d79d39a410c7a93ace6ee2046676787385"
    )
    assert canonical_internal_snapshot_bytes("qt-proposal-manifest/v1", {
        "proposal_rows": [entry, preserved, unresolved]
    }) == three_rows
    assert internal_snapshot_digest("qt-proposal-manifest/v1", {
        "proposal_rows": [entry, preserved, unresolved]
    }) == "c47cf3bc152bc1dba890e4f76c053eee1f657ff94305132da210f861284d596a"


def test_first_inserted_and_unchanged_repeat_have_token_lineage():
    first = linked_publication()
    observed = [row("qt_proposal", revision=REVISION_ID)]
    initial = reconcile_qt_source(
        BOOK, DAY, [first], observed, [], observed_system_rows=[row()]
    )
    assert initial.status == "ready"
    repeated = publication()
    repeated.update(publication_id=SECOND_PUBLICATION_ID, publication_version=2)
    prior = synthetic_lineage()[0]
    repeated["proposal_components"] = [{**prior, "action": "preserved"}]
    repeated["proposal_manifest_digest"] = internal_snapshot_digest(
        "qt-proposal-manifest/v1", {"proposal_rows": repeated["proposal_components"]}
    )
    after = reconcile_qt_source(
        BOOK, DAY, [first, repeated], observed, [], observed_system_rows=[row()]
    )
    assert after.status == "ready"
    assert after.model_publication_id == SECOND_PUBLICATION_ID
    observed[0]["position_revision"] = "30000000-0000-4000-8000-000000000002"
    assert reconcile_qt_source(
        BOOK, DAY, [first, repeated], observed, [], observed_system_rows=[row()]
    ).status == "provenance_unresolved"


def test_new_model_baseline_does_not_relabel_preserved_old_proposal():
    first = linked_publication()
    latest = publication()
    latest.update(publication_id=SECOND_PUBLICATION_ID, publication_version=2,
                  system_components=[row(quantity="6")])
    latest["seed_digest"] = qt_digest_v1({"seed_rows": [row(quantity="6")]})
    latest["proposal_components"] = [{**synthetic_lineage()[0], "action": "preserved"}]
    latest["proposal_manifest_digest"] = internal_snapshot_digest(
        "qt-proposal-manifest/v1", {"proposal_rows": latest["proposal_components"]}
    )
    result = reconcile_qt_source(
        BOOK, DAY, [first, latest], [row("qt_proposal", revision=REVISION_ID)], [],
        observed_system_rows=[row(quantity="6")],
    )
    assert result.status == "provenance_unresolved"
    assert result.reason == "changed_model_baseline"
    assert result.model_publication_id == SECOND_PUBLICATION_ID
    assert result.draft_overlay == ()


def test_origin_insert_must_match_its_own_hashed_model_seed():
    origin = linked_publication()
    origin["system_components"] = [row(quantity="6")]
    origin["seed_digest"] = qt_digest_v1({"seed_rows": origin["system_components"]})
    latest = linked_publication()
    latest["publication_id"] = SECOND_PUBLICATION_ID
    latest["publication_version"] = 2
    latest["proposal_components"] = [{**synthetic_lineage()[0], "action": "preserved"}]
    latest["proposal_manifest_digest"] = internal_snapshot_digest(
        "qt-proposal-manifest/v1", {"proposal_rows": latest["proposal_components"]}
    )
    result = reconcile_qt_source(
        BOOK, DAY, [origin, latest], [row("qt_proposal", revision=REVISION_ID)], [],
        observed_system_rows=[row()],
    )
    assert result.status == "provenance_unresolved"


def test_extra_current_system_component_blocks_complete_model_proof():
    result = reconcile_qt_source(
        BOOK, DAY, [linked_publication()],
        [row("qt_proposal", revision=REVISION_ID)], [],
        observed_system_rows=[row(), row(quantity="0", symbol="EXTRA")],
    )
    assert result.status == "provenance_unresolved"


def test_missing_current_system_snapshot_cannot_be_ready():
    result = reconcile_qt_source(
        BOOK, DAY, [linked_publication()],
        [row("qt_proposal", revision=REVISION_ID)], [],
    )
    assert result.status == "provenance_unresolved"
    assert result.reason == "current_system_rows_missing"


def test_intermediate_preserved_manifest_must_keep_origin_token():
    first = linked_publication()
    middle = linked_publication()
    middle.update(publication_id=SECOND_PUBLICATION_ID, publication_version=2)
    middle["proposal_components"] = [{**synthetic_lineage()[0], "action": "preserved",
                                      "position_revision": "30000000-0000-4000-8000-000000000002"}]
    middle["proposal_manifest_digest"] = internal_snapshot_digest(
        "qt-proposal-manifest/v1", {"proposal_rows": middle["proposal_components"]}
    )
    latest = linked_publication()
    latest.update(publication_id="10000000-0000-4000-8000-000000000003",
                  publication_version=3)
    latest["proposal_components"] = [{**synthetic_lineage()[0], "action": "preserved"}]
    latest["proposal_manifest_digest"] = internal_snapshot_digest(
        "qt-proposal-manifest/v1", {"proposal_rows": latest["proposal_components"]}
    )
    result = reconcile_qt_source(
        BOOK, DAY, [first, middle, latest],
        [row("qt_proposal", revision=REVISION_ID)], [],
        observed_system_rows=[row()],
    )
    assert result.status == "provenance_unresolved"


def _read_set_facts():
    absent = lambda name: {
        "name": name, "status": "unavailable", "source_id": None,
        "version": None, "as_of": None, "valid_until": None,
        "digest": None, "reason": "no_authoritative_versioned_source",
    }
    return {
        "schema_version": "qt-read-set/v1", "book_id": BOOK,
        "source_day": "2026-09-25", "captured_at": "2026-09-25T12:00:00Z",
        "source_rows": [row("qt_proposal")], "saved_rows": [row("qt", quantity="0")],
        "saved_accounting": [{**row("qt", quantity="0"), "daily_unrealized_pnl_exact": "1.25",
                              "daily_realized_pnl_exact": "-0.5", "last_update": "2026-09-25T11:59:00Z"}],
        "system_rows": [row()],
        "publication_refs": [{
            "publication_id": PUBLICATION_ID, "strategy_id": "component-1",
            "publication_version": 1, "seed_digest": SEED_DIGEST,
            "proposal_manifest_digest": "3" * 64,
            "producer_version": "synthetic-build-1",
        }],
        "audit_refs": [],
        "draft": {"status": "absent", "draft_id": None, "revision": 0, "digest": None},
        "registry": [{"id": "ui-component-1", "strategy_type": "component-1",
                      "portfolio_id": BOOK, "is_active": True, "lifecycle": "live",
                      "updated_at": "2026-09-25T11:00:00Z"}],
        "memberships": [{"strategy_id": "component-1", "portfolio_id": BOOK}],
        "capability": {"status": "present", "enabled": True, "version": 1},
        "grants": [{"user_id": "101", "capability": "qt_submit", "active": True,
                    "version": 1}],
        "risk_limits": {"status": "absent", "id": None, "published_at": None,
                        "content_digest": None},
        "risk_inventory": [],
        "portfolio_inputs": {"status": "absent", "source_id": None,
                             "source_day": None, "capital_exact": None,
                             "content_digest": None},
        "external_sources": [absent(name) for name in (
            "mark", "history", "cost", "multiplier", "universe", "instrument_type",
            "quantity_rule", "evaluator_policy",
        )],
        "evaluator": {"status": "unavailable", "build": None, "policy_version": None},
        "provenance": {"status": "provenance_unresolved", "source_digest": None,
                       "chain_digest": None, "seed_digest": SEED_DIGEST},
    }


@pytest.mark.parametrize("mutation", [
    "day", "zero", "add", "delete", "basis", "membership", "registry",
    "capability", "grant", "risk", "market", "cost", "version", "manifest",
])
def test_full_current_fact_change_changes_read_set_digest(mutation):
    before = _read_set_facts()
    changed = _read_set_facts()
    if mutation == "day":
        changed["source_day"] = "2026-09-26"
        for field in ("source_rows", "saved_rows", "system_rows", "saved_accounting"):
            for component in changed[field]:
                component["key"]["date"] = "2026-09-26"
    elif mutation == "zero":
        changed["saved_rows"][0]["quantity_exact"] = "1"
    elif mutation == "add":
        changed["source_rows"].append(row("qt_proposal", quantity="0", symbol="ADD"))
    elif mutation == "delete":
        changed["source_rows"].clear()
    elif mutation == "basis":
        changed["source_rows"][0]["average_price_exact"] = "101"
    elif mutation == "membership":
        changed["memberships"].clear()
    elif mutation == "registry":
        changed["registry"][0]["is_active"] = False
    elif mutation == "capability":
        changed["capability"]["version"] = 2
    elif mutation == "grant":
        changed["grants"][0]["version"] = 2
    elif mutation == "risk":
        changed["risk_inventory"] = [{"id": 7, "strategy_id": "component-1",
                                      "published_at": "2026-09-25T11:00:00Z",
                                      "content_digest": "1" * 64}]
    elif mutation == "manifest":
        changed["publication_refs"][0]["proposal_manifest_digest"] = "4" * 64
    elif mutation in {"market", "cost", "version"}:
        name = "mark" if mutation != "cost" else "cost"
        source = next(x for x in changed["external_sources"] if x["name"] == name)
        source.update(status="available", source_id="synthetic-snapshot",
                      version="v2" if mutation == "version" else "v1",
                      as_of="2026-09-25T11:59:00Z", valid_until="2026-09-25T12:01:00Z",
                      digest="2" * 64, reason=None)
    assert capture_qt_read_set(before).digest != capture_qt_read_set(changed).digest


def test_read_set_is_immutable_and_unavailable_is_distinct_from_empty():
    facts = _read_set_facts()
    read_set = capture_qt_read_set(facts)
    assert read_set.available is False
    facts["saved_rows"].clear()
    assert read_set.payload["saved_rows"][0]["quantity_exact"] == "0"
    with pytest.raises((TypeError, AttributeError)):
        read_set.payload["source_day"] = "2026-09-26"
    empty_changed = _read_set_facts()
    empty_changed["external_sources"] = []
    with pytest.raises(ValueError):
        capture_qt_read_set(empty_changed)


@pytest.mark.parametrize("field,value", [
    ("daily_unrealized_pnl_exact", "2.5"), ("daily_realized_pnl_exact", "1"),
    ("last_update", "2026-09-25T12:00:00Z"),
])
def test_actual_saved_accounting_changes_read_set_identity(field, value):
    original = _read_set_facts()
    changed = _read_set_facts()
    changed["saved_accounting"][0][field] = value
    assert capture_qt_read_set(original).digest != capture_qt_read_set(changed).digest


def test_audit_actor_identity_changes_read_set_digest():
    first = _read_set_facts()
    first["audit_refs"] = [{"id": 17, "user_id": "101", "source_app": "algolens",
                            "strategy_id": "component-1", "symbol": "SYN",
                            "before_digest": "1" * 64, "after_digest": "2" * 64}]
    changed = _read_set_facts()
    changed["audit_refs"] = [{**first["audit_refs"][0], "user_id": "202"}]
    assert capture_qt_read_set(first).digest != capture_qt_read_set(changed).digest


def test_stale_or_unversioned_available_external_source_rejected():
    facts = _read_set_facts()
    mark = facts["external_sources"][0]
    mark.update(status="available", source_id="synthetic-snapshot", version="v1",
                as_of="2026-09-25T11:00:00Z", valid_until="2026-09-25T11:30:00Z",
                digest="2" * 64, reason=None)
    with pytest.raises(ValueError):
        capture_qt_read_set(facts)
    mark["valid_until"] = "2026-09-25T12:01:00Z"
    mark["version"] = None
    with pytest.raises(ValueError):
        capture_qt_read_set(facts)


def test_clock_progress_within_fresh_window_does_not_change_read_set_digest():
    first = _read_set_facts()
    later = _read_set_facts()
    later["captured_at"] = "2026-09-25T12:00:30Z"
    assert capture_qt_read_set(first).digest == capture_qt_read_set(later).digest


def test_transaction_source_evidence_reads_full_rows_after_ordered_locks():
    class Cursor:
        def __init__(self):
            self.calls = []
            self.results = [
                [{"captured_at": "2026-09-25T12:00:00Z", "source_day": DAY}],
                [{**key("qt_proposal"), "quantity_exact": "4.00000000",
                  "average_price_exact": "100.00000000", "position_revision": REVISION_ID}],
                [{**key("qt"), "quantity_exact": "0.00000000",
                  "average_price_exact": "100.00000000"}],
                [{**key(), "quantity_exact": "4.00000000",
                  "average_price_exact": "100.00000000"}],
                [linked_publication()],
                [{"owner_v2_table_present": False}],
                [audit_entry()],
                [{**key("qt"), "quantity_exact": "0", "average_price_exact": "100",
                  "daily_unrealized_pnl_exact": "1.25", "daily_realized_pnl_exact": "-0.5",
                  "last_update": "2026-09-25T11:59:00Z"}],
                [],
            ]

        def execute(self, sql, params=()):
            self.calls.append((sql, params))

        def fetchall(self):
            return self.results.pop(0)

        def fetchone(self):
            return None

    cursor = Cursor()
    tx = QtTransaction(cursor, BOOK, 101)
    with pytest.raises(RuntimeError):
        tx.read_source_evidence()
    tx._stage = 4  # Lock methods are independently exercised by A2 tests.
    evidence = tx.read_source_evidence()
    assert evidence["source_day"] == DAY
    assert evidence["source_rows"][0]["position_revision"] == REVISION_ID
    assert evidence["saved_rows"][0]["quantity_exact"] == "0"
    assert evidence["publications"][0]["proposal_manifest_digest"]
    assert evidence["audits"][0]["before_state"]["quantity_exact"] == "4"
    assert evidence["saved_accounting"][0]["daily_unrealized_pnl_exact"] == "1.25"
    assert evidence["processed_publications"] == []
    assert len(cursor.calls) == 9
    assert "to_regclass('trading.qt_empty_model_owner_publications')" in cursor.calls[5][0]
    assert "qt_storage_capabilities" not in " ".join(q for q, _ in cursor.calls)
    for (sql, params), stream in zip(cursor.calls[1:4], ("qt_proposal", "qt", "system")):
        assert "trading.positions" in sql and "portfolio_id = %s" in sql
        assert params == (BOOK, DAY, stream)


def test_transaction_read_set_selects_current_registry_grant_and_risk_inventory():
    class Cursor:
        def __init__(self):
            self.calls = []
            self.rows = []

        def execute(self, sql, params=()):
            self.calls.append((sql, params))
            if "strategy_registry" in sql:
                self.rows = [{"id": "ui-component-1", "strategy_type": "component-1",
                              "portfolio_id": BOOK, "is_active": True, "lifecycle": "live",
                              "updated_at": "2026-09-25T11:00:00Z"}]
            elif "strategy_book_memberships" in sql:
                self.rows = [{"strategy_id": "component-1", "portfolio_id": BOOK}]
            elif "qt_workflow_capabilities" in sql:
                self.rows = [{"enabled": True, "version": 1}]
            elif "qt_action_grants" in sql:
                self.rows = [{"user_id": 101, "capability": "qt_submit",
                              "active": True, "version": 1}]
            elif "qt_draft_heads" in sql:
                self.rows = []
            elif "risk_limits" in sql:
                self.rows = [{"id": 7, "strategy_id": "component-1",
                              "published_at": "2026-09-25T11:00:00Z",
                              "limits": {"max_net_leverage": "2"}}]
            elif "to_jsonb(p)" in sql:
                self.rows = [{**key("qt"), "quantity_exact": "0", "average_price_exact": "100",
                              "daily_unrealized_pnl_exact": "1.25", "daily_realized_pnl_exact": "-0.5",
                              "last_update": "2026-09-25T11:59:00Z"}]
            else:
                raise AssertionError(sql)

        def fetchall(self):
            return self.rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

    cursor = Cursor()
    tx = QtTransaction(cursor, BOOK, 101)
    tx._stage = 4
    tx.read_source_evidence = lambda: {
        "captured_at": "2026-09-25T12:00:00Z", "source_day": DAY,
        "source_rows": [row("qt_proposal", revision=REVISION_ID)],
        "saved_rows": [row("qt", quantity="0")], "system_rows": [row()],
        "publications": [linked_publication()], "audits": [],
        "saved_accounting": [{**row("qt", quantity="0"), "daily_unrealized_pnl_exact": "1.25",
            "daily_realized_pnl_exact": "-0.5", "last_update": "2026-09-25T11:59:00Z"}],
        "processed_publications": [],
    }
    facts = tx.read_current_facts()
    assert facts["registry"][0]["strategy_type"] == "component-1"
    assert facts["memberships"] == [{"strategy_id": "component-1", "portfolio_id": BOOK}]
    assert facts["grants"][0]["user_id"] == "101"
    assert facts["risk_inventory"][0]["id"] == 7
    assert facts["risk_limits"]["status"] == "absent"
    assert capture_qt_read_set(facts).available is False
    assert len(cursor.calls) == 6
