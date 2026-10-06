"""Synthetic full-envelope tests for the parsed publication v2 boundary."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from algolens.domain.portfolio.configuration_inspection import PublicationError, parse_publication


TESTS = Path(__file__).parent
V1_FIXTURE = TESTS / "fixtures" / "configuration_inspection_v1.json"
CASES = json.loads((TESTS.parents[1] / "contracts" / "consumption-v2-cases.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)
SCOPE = {"registry_id": "trend", "registry_revision": 1, "engine_strategy_id": "LIVE_TREND",
         "portfolio_id": "BOOK", "run_date": "2026-09-22"}


def publication(child_name="ordinary"):
    envelope = json.loads(V1_FIXTURE.read_text(encoding="utf-8"))
    envelope["publication_schema_version"] = 2
    envelope["consumption"] = deepcopy(CASES["accepted"][child_name])
    return envelope


def parse(value, scope=SCOPE):
    return parse_publication(json.dumps(value, ensure_ascii=False, allow_nan=True), scope, NOW)


def test_valid_synthetic_v2_full_envelope_is_returned_unchanged():
    value = publication()
    expected = deepcopy(value)
    assert parse(value) == expected
    assert value == expected


def _locate(value, path):
    parts = path.split(".")
    for part in parts[:-1]:
        value = value[int(part)] if type(value) is list else value[part]
    return value, int(parts[-1]) if type(value) is list else parts[-1]


def _invalid(value):
    with pytest.raises(PublicationError) as exc:
        parse(value)
    assert exc.value.reason == str(exc.value) == "invalid_publication"
    assert exc.value.__cause__ is None


@pytest.mark.parametrize("name", CASES["accepted"])
def test_every_accepted_shared_child_survives_synthetic_full_envelope(name):
    value = publication(name)
    original = deepcopy(value)
    assert parse(value) == original
    assert value == original


@pytest.mark.parametrize("control_mode", ["controlled", "uncontrolled"])
@pytest.mark.parametrize("reason", ["projection_invalid", "selected_stage_unavailable", "capture_failed"])
def test_valid_consumption_survives_unavailable_early_capture(control_mode, reason):
    value = publication("nested_partial")
    value.update(status="unavailable", reason=reason, supplied=None, selected_trend=None)
    if control_mode == "uncontrolled":
        value["identity"].update(control_mode="uncontrolled", runtime_attempt_id=None)
    assert parse(value) == value


@pytest.mark.parametrize("case", CASES["rejected"], ids=lambda case: case["name"])
@pytest.mark.parametrize("early_unavailable", [False, True])
def test_every_rejected_shared_child_rejects_the_whole_envelope(case, early_unavailable, caplog):
    value = publication(case["base"])
    if "path" in case:
        target, key = _locate(value["consumption"], case["path"])
        target[key] = case["value"]
    else:
        target, key = _locate(value["consumption"], case["append_to"])
        target[key].append(deepcopy(case["item"]))
    if early_unavailable:
        value.update(status="unavailable", reason="capture_failed", supplied=None,
                     selected_trend=None)
    _invalid(value)
    assert "SECRET-SENTINEL" not in caplog.text


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(consumption={"status": "not_collected"}),
    lambda p: p["consumption"].update(extra="SECRET-SENTINEL"),
    lambda p: p["consumption"].pop("coverage"),
    lambda p: p.update(consumption=None),
    lambda p: p.update(extra="SECRET-SENTINEL"),
    lambda p: p.pop("consumption"),
    lambda p: p.update(consumption={**p["consumption"], "nodes": None}),
])
def test_v2_rejects_legacy_or_missing_extra_null_children_and_root_keys(mutate):
    value = publication()
    mutate(value)
    _invalid(value)


def test_v1_keeps_only_the_legacy_child():
    value = publication()
    value["publication_schema_version"] = 1
    _invalid(value)
    value["consumption"] = {"status": "not_collected"}
    assert parse(value) == value


@pytest.mark.parametrize("version", [3, True, 2.0, "2", None])
def test_unsupported_v2_version_has_distinct_fixed_reason(version):
    value = publication()
    value["publication_schema_version"] = version
    with pytest.raises(PublicationError) as exc:
        parse(value)
    assert exc.value.reason == str(exc.value) == "unsupported_publication"


def test_unknown_profile_is_unsupported():
    value = publication()
    value["profile"] = "SECRET-SENTINEL"
    with pytest.raises(PublicationError) as exc:
        parse(value)
    assert exc.value.reason == str(exc.value) == "unsupported_publication"


def test_duplicate_child_key_rejects_before_materialization():
    raw = json.dumps(publication(), ensure_ascii=False)
    changed = raw.replace('"consumption": {"version": 2,',
                          '"consumption": {"version": 2, "version": 2,', 1)
    assert changed != raw
    with pytest.raises(PublicationError) as exc:
        parse_publication(changed, SCOPE, NOW)
    assert exc.value.reason == str(exc.value) == "invalid_publication"


def test_duplicate_nested_read_key_rejects_before_materialization():
    raw = json.dumps(publication("rich"), ensure_ascii=False)
    changed = raw.replace('"field":', '"field": "SECRET-SENTINEL", "field":', 1)
    assert changed != raw
    with pytest.raises(PublicationError) as exc:
        parse_publication(changed, SCOPE, NOW)
    assert exc.value.reason == str(exc.value) == "invalid_publication"
    assert "SECRET-SENTINEL" not in str(exc.value)


def test_malformed_child_has_only_fixed_public_diagnostics(capsys, caplog):
    value = publication()
    value["consumption"]["reason"] = "SECRET-SENTINEL"
    _invalid(value)
    captured = capsys.readouterr()
    assert "SECRET-SENTINEL" not in captured.out + captured.err + caplog.text


def test_v2_raw_cap_counts_whitespace_and_bad_unicode_is_private():
    raw = _compact(publication())
    padded = raw + " " * (2_097_153 - len(raw.encode("utf-8")))
    assert len(padded.encode("utf-8")) == 2_097_153
    for rejected in (padded, "\ud800", raw[:-1]):
        with pytest.raises(PublicationError) as exc:
            parse_publication(rejected, SCOPE, NOW)
        assert exc.value.reason == str(exc.value) == "invalid_publication"


@pytest.mark.parametrize("mutate", [
    lambda p: p["identity"].update(runtime_attempt_id=None),
    lambda p: p["identity"].update(run_date="2026-09-24"),
    lambda p: p.update(captured_at="2026-09-24T00:00:00Z"),
    lambda p: p["supplied"]["fields"].pop(0),
    lambda p: p["selected_trend"]["strategies"][0].update(selected_allocation=True),
])
def test_v2_child_cannot_hide_invalid_identity_date_supplied_or_selected(mutate):
    value = publication()
    mutate(value)
    _invalid(value)


def test_v2_scope_mismatch_remains_distinct():
    with pytest.raises(PublicationError) as exc:
        parse(publication(), {**SCOPE, "registry_revision": 2})
    assert exc.value.reason == "scope_changed"


@pytest.mark.parametrize("capacity", [0, 2**64 - 1])
def test_v2_keeps_selected_history_capacity_unsigned64(capacity):
    value = publication()
    for stage in ("factory_resolved", "constructor_normalized"):
        value["selected_trend"]["strategies"][0][stage]["max_history_size"] = capacity
    assert parse(value) == value


def test_partial_and_whole_unavailable_children_return_honestly():
    for name in ("nested_partial", "unavailable_capacity_exceeded"):
        value = publication(name)
        assert parse(value) == value


def _compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False)


def _boundary_publication(target_bytes):
    """Fill an existing legal v1 pair value to a chosen compact-envelope size."""
    value = publication()
    row = next(row for row in value["supplied"]["fields"]
               if row["path"] == "/strategy_defaults/fdm")
    row["value"] = []
    # One ordinary float token gains one byte during Python's compact
    # serialization: raw 1e20 becomes 1e+20. This isolates the compact cap
    # while the independently bounded raw transport still fits.
    row["value"].append([1, 1e20])
    base = len(_compact(value).encode("utf-8"))
    delta = target_bytes - base
    full, remainder = divmod(delta, 306)
    assert full > 0
    row["value"].extend([[1, 10**300] for _ in range(full)])
    if 0 < remainder < 10:
        row["value"][-1][0] = 10**remainder
    elif remainder >= 10:
        row["value"].append([1, 10**(remainder - 6)])
    assert len(_compact(value).encode("utf-8")) == target_bytes
    return value


def _raw_short_exponent(value):
    raw = _compact(value)
    changed = raw.replace("1e+20", "1e20", 1)
    assert changed != raw
    return changed


def test_combined_v2_compact_envelope_accepts_exact_two_mib():
    value = _boundary_publication(2_097_152)
    raw = _raw_short_exponent(value)
    assert len(raw.encode("utf-8")) == 2_097_151
    assert parse_publication(raw, SCOPE, NOW) == value


def test_combined_v2_compact_envelope_rejects_one_byte_over():
    value = _boundary_publication(2_097_153)
    raw = _raw_short_exponent(value)
    assert len(raw.encode("utf-8")) == 2_097_152
    assert len(_compact(value["consumption"]).encode("utf-8")) < 2_097_152
    assert len(_compact(value["supplied"]).encode("utf-8")) < 2_097_152
    with pytest.raises(PublicationError) as exc:
        parse_publication(raw, SCOPE, NOW)
    assert exc.value.reason == str(exc.value) == "invalid_publication"
