"""Protocol tests use a hand-specified full synthetic publication fixture."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from algolens.domain.portfolio.configuration_inspection import PublicationError, parse_publication


FIXTURE = Path(__file__).parent / "fixtures" / "configuration_inspection_v1.json"
NOW = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)
SCOPE = {"registry_id": "trend", "registry_revision": 1, "engine_strategy_id": "LIVE_TREND",
         "portfolio_id": "BOOK", "run_date": "2026-09-22"}


def publication():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def parse(value, scope=SCOPE):
    return parse_publication(json.dumps(value, allow_nan=True), scope, NOW)


def field(value, path):
    return next(row for row in value["supplied"]["fields"] if row["path"] == path)


def test_full_independently_specified_fixture_is_accepted():
    value = publication()
    assert len(value["supplied"]["fields"]) == 57
    assert parse(value) == value
    assert {row["path"] for row in value["supplied"]["fields"]
            if row["path"].startswith("/strategies/ALPHA/")} == {
                "/strategies/ALPHA/" + suffix for suffix in (
                    "enabled_live", "default_allocation", "enabled_backtest", "type",
                    "config/weight", "config/risk_target", "config/idm",
                    "config/max_symbol_concentration", "config/use_position_buffering",
                    "config/carver_buffer_floor", "config/carver_buffer_position_factor",
                    "config/ema_windows", "config/vol_lookback_short",
                    "config/vol_lookback_long", "config/fx_rate",
                    "config/max_history_size", "config/fdm")}


@pytest.mark.parametrize("mutate", [
    lambda p: p["supplied"]["fields"].pop(0),
    lambda p: p["supplied"]["fields"].append(deepcopy(p["supplied"]["fields"][0])),
    lambda p: field(p, "/risk/max_leverage").update(reason="source_reader"),
    lambda p: field(p, "/risk_defaults/lookback_period").update(value=True),
    lambda p: field(p, "/optimization/use_buffering").update(value=1),
    lambda p: field(p, "/initial_capital").update(value=float("inf")),
    lambda p: field(p, "/benchmark_mode").update(value="SECRET-SENTINEL"),
    lambda p: field(p, "/strategies/ALPHA/config/ema_windows").update(value=[[8, 2.5]]),
    lambda p: field(p, "/strategies/ALPHA/config/fx_rate").update(value=9),
    lambda p: p["selected_trend"]["strategies"][0]["factory_resolved"].pop("fdm"),
    lambda p: p["selected_trend"]["strategies"][0]["constructor_normalized"].update(fdm=[[1, True]]),
    lambda p: p["selected_trend"]["strategies"][0].update(strategy_id="OTHER"),
    lambda p: p["selected_trend"]["strategies"][0].update(selected_allocation=float("nan")),
    lambda p: p["selected_trend"].update(slow_concentration_override={"state": "present"}),
    lambda p: p["identity"].update(producer_version="secret/path"),
    lambda p: p["identity"].update(publication_id="not-a-uuid"),
    lambda p: p.update(captured_at="2026-09-24T00:00:00Z"),
    lambda p: p.update(publication_recorded_at="2026-09-22T14:00:00Z"),
    lambda p: p.update(consumption={"status": "collected"}),
])
def test_malformed_or_partial_publication_is_rejected(mutate):
    value = publication()
    mutate(value)
    with pytest.raises(PublicationError) as exc:
        parse(value)
    assert exc.value.reason == "invalid_publication"


def test_scope_change_is_distinct_from_bad_shape():
    with pytest.raises(PublicationError) as exc:
        parse(publication(), {**SCOPE, "registry_revision": 2})
    assert exc.value.reason == "scope_changed"


def test_unsupported_version_is_distinct():
    value = publication()
    value["publication_schema_version"] = 3
    with pytest.raises(PublicationError) as exc:
        parse(value)
    assert exc.value.reason == "unsupported_publication"


def test_duplicate_keys_and_nonfinite_constants_are_rejected_before_materialization():
    raw = FIXTURE.read_text(encoding="utf-8")
    for changed in (raw.replace('"stream": "system",', '"stream": "system", "stream": "system",'),
                    raw.replace('"selected_allocation": 0.4', '"selected_allocation": NaN')):
        with pytest.raises(PublicationError):
            parse_publication(changed, SCOPE, NOW)


def test_oversized_document_and_unavailable_coherence():
    raw = FIXTURE.read_text(encoding="utf-8")
    with pytest.raises(PublicationError):
        parse_publication(raw + (" " * (2 * 1024 * 1024)), SCOPE, NOW)
    value = publication()
    value.update(status="unavailable", reason="capture_failed", supplied=None,
                 selected_trend=None)
    assert parse(value)["reason"] == "capture_failed"
    value["supplied"] = publication()["supplied"]
    with pytest.raises(PublicationError):
        parse(value)


def test_uncontrolled_publication_has_no_attempt_claim():
    value = publication()
    value["identity"].update(control_mode="uncontrolled", runtime_attempt_id=None)
    assert parse(value)["identity"]["runtime_attempt_id"] is None
    value["identity"]["runtime_attempt_id"] = value["identity"]["publication_id"]
    with pytest.raises(PublicationError):
        parse(value)


def test_unknown_definition_has_only_four_common_rows_and_no_selected_stage():
    value = publication()
    fields = value["supplied"]["fields"]
    fields[:] = [row for row in fields if not row["path"].startswith("/strategies/ALPHA/config/")]
    type_row = field(value, "/strategies/ALPHA/type")
    type_row.update(classification="unsupported_in_profile", reason="unknown_strategy_type",
                    condition="no_active_profile_reader", value_origin="not_projected",
                    value_state="omitted")
    del type_row["value"]
    value["selected_trend"]["strategies"] = []
    assert parse(value)["supplied"]["fields"] == fields
    fields.append({"path": "/strategies/ALPHA/config/private", "scope": "exact"})
    with pytest.raises(PublicationError):
        parse(value)


def test_absent_known_leaf_is_distinct_from_omitted_or_fabricated_value():
    value = publication()
    row = field(value, "/strategies/ALPHA/config/vol_lookback_long")
    assert row["value_state"] == "absent_in_input" and "value" not in row
    assert parse(value)["selected_trend"]["strategies"][0]["factory_resolved"]["vol_lookback_long"] == 60
    row.update(value_state="omitted")
    with pytest.raises(PublicationError):
        parse(value)


def test_value_and_identity_boundaries_are_strict():
    value = publication()
    field(value, "/optimization/max_iterations")["value"] = 2**31
    with pytest.raises(PublicationError):
        parse(value)
    value = publication()
    value["identity"]["registry_id"] = "secret/path"
    with pytest.raises(PublicationError):
        parse(value)
    value = publication()
    value["selected_trend"]["strategies"][0]["strategy_type"] = "UnknownClass"
    with pytest.raises(PublicationError):
        parse(value)


def test_large_json_number_and_invalid_unicode_are_protocol_errors():
    value = publication()
    field(value, "/initial_capital")["value"] = 10**1000
    with pytest.raises(PublicationError):
        parse(value)
    with pytest.raises(PublicationError):
        parse_publication("\ud800", SCOPE, NOW)


def test_unavailable_unversioned_is_only_valid_for_capture_failure():
    value = publication()
    value.update(status="unavailable", reason="capture_failed", supplied=None,
                 selected_trend=None)
    value["identity"]["producer_version"] = "unversioned"
    assert parse(value)["status"] == "unavailable"
    value["reason"] = "projection_invalid"
    with pytest.raises(PublicationError):
        parse(value)


def test_missing_supplied_type_routes_only_to_standard_selected_strategy():
    value = publication()
    type_row = field(value, "/strategies/ALPHA/type")
    type_row["value_state"] = "absent_in_input"
    del type_row["value"]
    assert parse(value)["supplied"]["fields"] == value["supplied"]["fields"]
    for wrong_type in ("TrendFollowingFastStrategy", "TrendFollowingSlowStrategy"):
        changed = deepcopy(value)
        changed["selected_trend"]["strategies"][0]["strategy_type"] = wrong_type
        with pytest.raises(PublicationError):
            parse(changed)


@pytest.mark.parametrize("reason", [[], {}])
def test_unavailable_reason_must_be_a_fixed_string(reason):
    value = publication()
    value.update(status="unavailable", reason=reason, supplied=None,
                 selected_trend=None)
    with pytest.raises(PublicationError) as exc:
        parse(value)
    assert exc.value.reason == "invalid_publication"


@pytest.mark.parametrize("stage", ["factory_resolved", "constructor_normalized"])
@pytest.mark.parametrize("capacity", [0, 2**31 - 1, 2**31, 2**64 - 1])
def test_history_capacity_accepts_full_unsigned_64_bit_range(stage, capacity):
    value = publication()
    value["selected_trend"]["strategies"][0][stage]["max_history_size"] = capacity
    assert parse(value)["selected_trend"]["strategies"][0][stage]["max_history_size"] == capacity


@pytest.mark.parametrize("stage", ["factory_resolved", "constructor_normalized"])
@pytest.mark.parametrize("capacity", [-1, True, 0.0, 2**64])
def test_history_capacity_rejects_non_unsigned_64_bit_values(stage, capacity):
    value = publication()
    value["selected_trend"]["strategies"][0][stage]["max_history_size"] = capacity
    with pytest.raises(PublicationError):
        parse(value)
