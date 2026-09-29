"""Shared manifest vectors v2 (F3, F9): the native lane's final handoff.

qt-report-manifest-vectors-v2.json was copied byte-for-byte from the native
lane's report-recompute-staging/native-plan14/tree/tests/contracts/ into
this repo's tests/contracts/ (sha256
963fd137e73fccfa679a87562ab96f6ed99bb183f9ba315d87e1cc399128f88f, matching
the coordinator's handoff). It supersedes v1 for the "after keys must cover
before keys" rule: the first 9 cases are v1's 9 cases, byte-identical; 12
new cases cover open-from-absent (futures, equity, short), a new strategy
name opening from absent, absent-to-zero staying hidden, opening into a book
with no rows at all, a closed future, refused fractional-future-from-absent,
two-strategy-id refusals (including one where the second id appears only on
an after-only key), a before key missing from after, and the fully empty
case. v1 (tests/test_qt_report_manifest_vectors.py,
tests/contracts/qt-report-manifest-vectors-v1.json) is unchanged and still
passes: its selection_rows semantics do not conflict with v2 -- v1's cases
already had selection keys equal to the after keys (before == after in
every v1 case), so "selection_rows are now the AFTER keys" was already true
there; v2 only makes it true for cases where before and after differ.
"""
import json
from pathlib import Path

from algolens.infrastructure.portfolio.qt_publication_proof import report_row_manifest

VECTORS = json.loads((Path(__file__).resolve().parent / "contracts" / "qt-report-manifest-vectors-v2.json").read_text())


def test_vectors_v2_schema_and_case_count():
    assert VECTORS["schema_version"] == "qt-report-manifest-vectors/v2"
    assert VECTORS["case_count"] == 21
    assert len(VECTORS["cases"]) == 21


def test_every_v2_vector_matches_expected_digest():
    for case in VECTORS["cases"]:
        got = report_row_manifest(case["before"], case["after"], case["selection_rows"])
        assert got == case["expected_manifest_digest"], case["name"]


def test_every_v2_vector_selection_rows_are_exactly_the_after_keys():
    # Documents the v2 handoff's stated invariant so a future vectors file
    # that violates it fails loudly here, not just downstream in
    # report_row_manifest's own key-set refusal.
    from algolens.domain.portfolio.qt_workflow_models import QtKey

    for case in VECTORS["cases"]:
        after_keys = {QtKey.from_wire(row["key"]) for row in case["after"]}
        selection_keys = {QtKey.from_wire({**row["key"], "portfolio_type": "qt"}) for row in case["selection_rows"]}
        assert selection_keys == after_keys, case["name"]


def test_refused_cases_have_a_null_digest_and_no_shown_keys():
    refused = [case for case in VECTORS["cases"] if case["expected_manifest_digest"] is None]
    eligible = [case for case in VECTORS["cases"] if case["expected_manifest_digest"] is not None]
    assert len(refused) == 7 and len(eligible) == 14
    for case in refused:
        assert case["expected_shown_keys"] is None
        assert report_row_manifest(case["before"], case["after"], case["selection_rows"]) is None
