"""Synthetic contract data for the parsed consumption child; no producer claim."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

from algolens.domain.portfolio.consumption_inspection import (
    ConsumptionProtocolError,
    validate_consumption_v2,
)
from algolens.domain.portfolio.consumption_catalog import CATALOG


STAGES = ("setup", "market_input", "cost_history", "preparation", "primary",
          "execution", "diagnostics", "control_flow")
CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
CASES = json.loads((CONTRACTS / "consumption-v2-cases.json").read_text(encoding="utf-8"))


def _locate(value, path):
    parts = path.split(".")
    for part in parts[:-1]:
        value = value[int(part)] if type(value) is list else value[part]
    return value, int(parts[-1]) if type(value) is list else parts[-1]


def _reject(value):
    with pytest.raises(ConsumptionProtocolError) as exc:
        validate_consumption_v2(value)
    assert str(exc.value) == exc.value.reason == "invalid_consumption"


def test_static_runtime_catalog_matches_language_neutral_json():
    assert CATALOG == json.loads((CONTRACTS / "consumption-v2-catalog.json").read_text(encoding="utf-8"))


def test_native_typed_equity_cost_artifact_is_retained_exactly():
    # Real native typed charge observations, in an explicitly synthetic run
    # projection context. This is not evidence of a MODEL or QT SQL handoff.
    raw = (CONTRACTS / "consumption-v2-equity-native.json").read_bytes()
    assert sha256(raw).hexdigest() == "2ac342468114aecbdbebac97a82892d57617760d70ce75b66b1bf06f232d2e9d"
    child = json.loads(raw)
    before = deepcopy(child)
    assert validate_consumption_v2(child) is child
    expected = {
        "cost.spread.tick_constrained": ("bool", True),
        "cost.charge.commission_per_unit": ("number", 0.0035),
        "cost.charge.max_commission_pct": ("number", -1.0),
        "cost.charge.max_commission_per_order": ("number", 98765.0),
        "cost.charge.min_commission_per_order": ("number", 0.35),
        "cost.charge.apply_regulatory_fees": ("bool", True),
        "cost.charge.sec_fee_per_million": ("number", 20.6),
        "cost.charge.finra_taf_per_share": ("number", 0.000195),
        "cost.charge.finra_taf_cap_per_trade": ("number", 9.79),
        "cost.charge.max_total_implicit_bps": ("number", 123.0),
    }
    for consumer in ("cost.estimate", "cost.strategy_execution", "cost.compatibility_execution", "cost.execution"):
        node = next(node for node in child["nodes"] if node["consumer"] == consumer)
        reads = {row["field"]: row for row in node["reads"]}
        for field, (kind, value) in expected.items():
            assert reads[field] == {"field": field, "value_type": kind, "value": value, "origin": "runtime_effective"}
            assert (type(reads[field]["value"]) is bool) == (kind == "bool")
        assert "cost.charge.explicit_fee_per_contract" not in reads
        assert not any(field.startswith("cost.volatility.") for field in reads)
    assert validate_consumption_v2(child) is child and child == before


@pytest.mark.parametrize("consumer", ["cost.estimate", "cost.strategy_execution",
    "cost.compatibility_execution", "cost.execution"])
@pytest.mark.parametrize("field,value_type,value", [
    ("cost.spread.tick_constrained", "bool", False),
    ("cost.charge.commission_per_unit", "number", 0.0035),
    ("cost.charge.max_commission_pct", "number", -1),
    ("cost.charge.max_commission_per_order", "number", 1.25),
    ("cost.charge.min_commission_per_order", "number", 0.35),
    ("cost.charge.apply_regulatory_fees", "bool", False),
    ("cost.charge.sec_fee_per_million", "number", 27.8),
    ("cost.charge.finra_taf_per_share", "number", 0.000166),
    ("cost.charge.finra_taf_cap_per_trade", "number", 8.3),
    ("cost.charge.max_total_implicit_bps", "number", -1),
])
def test_reader_retains_equity_cost_fields_without_coercion(consumer, field, value_type, value):
    # Synthetic protocol admission only; actual producer handoff is tested separately.
    child = deepcopy(CASES["accepted"]["rich"])
    node = next(node for node in child["nodes"] if node["consumer"] == consumer)
    read = {"field": field, "value_type": value_type, "value": value,
            "origin": "runtime_effective"}
    node["reads"].append(read)
    before = deepcopy(child)
    assert validate_consumption_v2(child) is child
    assert child == before and node["reads"][-1] == read


@pytest.mark.parametrize("spec", CATALOG["fields"],
                         ids=lambda spec: spec["consumer"] + ":" + spec["field"])
def test_every_catalogued_field_has_an_accepted_real_consumer_context(spec):
    child = deepcopy(CASES["accepted"]["controlled" if spec["consumer"] ==
                     "setup.controlled_validation" else "rich"])
    node = next(node for node in child["nodes"] if node["consumer"] == spec["consumer"])
    if any(row["field"] == spec["field"] for row in node["reads"]):
        assert validate_consumption_v2(child) is child
        return
    field = spec["field"]
    if spec["type"] == "bool":
        value = True
    elif spec["type"] == "number":
        value = 1
    elif spec["type"] in ("int32", "uint53"):
        value = 1
    elif spec["type"] == "fixed_decimal8":
        value = "1.25"
    elif spec["type"] in ("int32_pairs", "int32_number_pairs"):
        value = []
    else:
        value = "deferred"
    origin = "runtime_effective" if spec["consumer"] == "risk.primary" else spec["origins"][0]
    if field == "portfolio.registration.min_allocation":
        value = 0.1
    if field == "portfolio.registration.max_allocation":
        node["reads"].append({"field": "portfolio.registration.min_allocation",
                              "value_type": "number", "value": 0.1,
                              "origin": "app_config_effective"})
    if field.startswith("portfolio.registration.portfolio_") or field.startswith(
            "portfolio.registration.stored_") and field != "portfolio.registration.stored_allocation":
        gate = "optimization" if field.endswith("optimization") else "risk"
        node["reads"].append({"field": "portfolio.registration.requested_" + gate,
                              "value_type": "bool", "value": True,
                              "origin": "app_config_effective"})
        if field.startswith("portfolio.registration.stored_"):
            node["reads"].append({"field": "portfolio.registration.portfolio_" + gate,
                                  "value_type": "bool", "value": True,
                                  "origin": "app_config_effective"})
    row = {"field": field, "value_type": spec["type"], "value": value, "origin": origin}
    if ".symbol." in field or field.startswith("strategy.position_limits.symbol."):
        row["symbol"] = "YM"
        if field.endswith(".value"):
            node["reads"].append({"field": field[:-5] + "present",
                                  "value_type": "bool", "value": True,
                                  "origin": "runtime_effective", "symbol": "YM"})
    node["reads"].append(row)
    assert validate_consumption_v2(child) is child


@pytest.mark.parametrize("name", CASES["accepted"])
def test_hand_specified_synthetic_child_is_accepted_without_copy_or_mutation(name):
    child = deepcopy(CASES["accepted"][name])
    original = deepcopy(child)
    assert validate_consumption_v2(child) is child
    assert child == original
    assert validate_consumption_v2(child) is child


@pytest.mark.parametrize("case", CASES["rejected"], ids=lambda case: case["name"])
def test_independently_specified_rejected_case(case):
    child = deepcopy(CASES["accepted"][case["base"]])
    if "path" in case:
        target, key = _locate(child, case["path"])
        target[key] = case["value"]
    else:
        target, key = _locate(child, case["append_to"])
        target[key].append(deepcopy(case["item"]))
    _reject(child)


@pytest.mark.parametrize("path,value", [
    ("nodes.0.outcome", "incomplete"),
    ("nodes.0.meta.mode", "secret/path"),
    ("nodes.2.meta.enabled_live_read", False),
    ("nodes.2.reads.0.origin", "code_default"),
    ("nodes.4.meta.initialize", "attempted"),
    ("nodes.5.reads.1.value", 0.6),
    ("nodes.8.meta.cost_model_reached", False),
    ("nodes.10.meta.profile", "unsupported"),
    ("nodes.13.index", 1),
    ("nodes.14.meta.state", "rejected_stream"),
    ("nodes.17.meta.branch", "succeeded"),
    ("coverage.primary.reason", "incomplete_call"),
])
def test_context_relations_reject_contradictory_observations(path, value):
    child = deepcopy(CASES["accepted"]["ordinary"])
    target, key = _locate(child, path)
    target[key] = value
    _reject(child)


def test_selection_default_flags_require_a_returned_value():
    child = deepcopy(CASES["accepted"]["ordinary"])
    child["nodes"][2]["reads"].pop(1)
    _reject(child)
    child = deepcopy(CASES["accepted"]["ordinary"])
    child["nodes"][2]["meta"]["enabled_live_defaulted"] = False
    _reject(child)  # ordinary selection has no native defaulted flag


def test_successful_cross_stage_references_cannot_invent_strategies():
    for path in ("nodes.5.strategy", "nodes.10.strategy", "nodes.12.strategy",
                 "nodes.14.strategy"):
        child = deepcopy(CASES["accepted"]["ordinary"])
        target, key = _locate(child, path)
        target[key] = "OTHER"
        _reject(child)


def test_nested_error_cannot_be_upgraded_by_successful_parent():
    child = deepcopy(CASES["accepted"]["rich"])
    child["nodes"][34]["outcome"] = "returned_error"  # nested estimate charge
    _reject(child)
    child["coverage"]["primary"] = {"status": "partial", "reason": "incomplete_call"}
    _reject(child)  # nonfatal outranks incomplete
    child["coverage"]["primary"]["reason"] = "nonfatal_error"
    child["status"], child["reason"] = "partial", "nonfatal_error"
    assert validate_consumption_v2(child) is child


def test_unsupported_profile_requires_partial_status_and_forbids_read_scopes():
    child = deepcopy(CASES["accepted"]["ordinary"])
    child["nodes"][10]["meta"]["profile"] = "unsupported"
    _reject(child)
    child["coverage"]["preparation"] = {"status": "partial", "reason": "unsupported_consumer"}
    child["status"], child["reason"] = "partial", "unsupported_consumer"
    assert validate_consumption_v2(child) is child
    child["nodes"].append({"id": 18, "parent": 10, "kind": "scope",
                           "consumer": "strategy.history", "reads": [], "meta": {}})
    _reject(child)


def test_partial_with_only_scopes_is_rejected():
    child = deepcopy(CASES["accepted"]["ordinary"])
    child["nodes"] = [{"id": 0, "parent": None, "kind": "scope",
                       "consumer": "runner.non_trading_day", "reads": [],
                       "meta": {"skip_strategy_processing": False}}]
    child["coverage"] = {stage: {"status": "unavailable",
                                 "reason": "instrumentation_missing"} for stage in STAGES}
    child["coverage"]["control_flow"] = {"status": "partial",
                                           "reason": "instrumentation_missing"}
    child["status"], child["reason"] = "partial", "instrumentation_missing"
    _reject(child)


def test_strategy_identity_budget_accepts_32_and_rejects_33_definitions():
    child = deepcopy(CASES["accepted"]["ordinary"])
    child["coverage"]["setup"] = {"status": "partial",
                                    "reason": "instrumentation_missing"}
    child["status"], child["reason"] = "partial", "instrumentation_missing"
    for index in range(1, 32):
        child["nodes"].append({"id": len(child["nodes"]), "parent": 3,
                               "kind": "scope", "consumer": "setup.factory_entry",
                               "reads": [], "meta": {"construction": "not_reached",
                                                    "initialize": "not_reached",
                                                    "start": "not_reached"},
                               "strategy": f"S{index}"})
    assert validate_consumption_v2(child) is child
    child["nodes"].append({"id": len(child["nodes"]), "parent": 3,
                           "kind": "scope", "consumer": "setup.factory_entry",
                           "reads": [], "meta": {"construction": "not_reached",
                                                "initialize": "not_reached",
                                                "start": "not_reached"},
                           "strategy": "S32"})
    _reject(child)


def test_symbol_budget_accepts_1024_and_rejects_1025_distinct_map_keys():
    child = deepcopy(CASES["accepted"]["rich"])
    for index in range(1022):
        child["nodes"][22]["reads"].append({
            "field": "strategy.sizing.symbol_limit.symbol.present",
            "value_type": "bool", "value": False,
            "origin": "runtime_effective", "symbol": f"SYM{index}",
        })
    assert validate_consumption_v2(child) is child
    child["nodes"][22]["reads"].append({
        "field": "strategy.sizing.symbol_limit.symbol.present",
        "value_type": "bool", "value": False,
        "origin": "runtime_effective", "symbol": "ONE_MORE",
    })
    _reject(child)


def test_native_charge_collection_accepts_2048_and_rejects_2049_records():
    child = deepcopy(CASES["accepted"]["rich"])
    for _ in range(2047):
        child["nodes"].append({"id": len(child["nodes"]), "parent": 11,
                               "kind": "call", "consumer": "cost.strategy_execution",
                               "reads": [], "meta": {}, "outcome": "returned_ok",
                               "strategy": "ALPHA", "symbol": "ES"})
    assert validate_consumption_v2(child) is child
    child["nodes"].append({"id": len(child["nodes"]), "parent": 11,
                           "kind": "call", "consumer": "cost.strategy_execution",
                           "reads": [], "meta": {}, "outcome": "returned_ok",
                           "strategy": "ALPHA", "symbol": "ES"})
    _reject(child)


def test_combined_parameter_pair_budget_accepts_8192_and_rejects_8193():
    child = deepcopy(CASES["accepted"]["ordinary"])
    primary_calls = [12]
    for index in range(1, 32):
        strategy = f"S{index}"
        child["nodes"].append({
            "id": len(child["nodes"]), "parent": 1, "kind": "scope",
            "consumer": "setup.selection_entry", "reads": [
                {"field": "setup.selection.enabled_live", "value_type": "bool",
                 "value": True, "origin": "configured_strategy_leaf"},
            ], "meta": {"enabled_live_read": True, "allocation_read": False,
                        "enabled_live_present": True}, "strategy": strategy,
        })
        child["nodes"].append({
            "id": len(child["nodes"]), "parent": 3, "kind": "scope",
            "consumer": "setup.factory_entry", "reads": [],
            "meta": {"construction": "succeeded", "initialize": "succeeded",
                     "start": "succeeded"}, "strategy": strategy,
        })
        child["nodes"].append({
            "id": len(child["nodes"]), "parent": None, "kind": "call",
            "consumer": "portfolio.registration", "reads": [], "meta": {},
            "outcome": "returned_ok", "strategy": strategy,
        })
        primary_calls.append(len(child["nodes"]))
        child["nodes"].append({
            "id": len(child["nodes"]), "parent": 11, "kind": "call",
            "consumer": "strategy.primary", "reads": [],
            "meta": {"profile": "standard"}, "outcome": "returned_ok",
            "strategy": strategy,
        })
        child["nodes"].append({
            "id": len(child["nodes"]), "parent": None, "kind": "call",
            "consumer": "execution.batch", "reads": [],
            "meta": {"state": "returned"}, "outcome": "returned_ok",
            "strategy": strategy,
        })
    for parent in primary_calls:
        for consumer, field in (
            ("strategy.history", "strategy.history.ema_windows"),
            ("strategy.forecast", "strategy.forecast.ema_windows"),
        ):
            child["nodes"].append({
                "id": len(child["nodes"]), "parent": parent, "kind": "scope",
                "consumer": consumer, "reads": [
                    {"field": field, "value_type": "int32_pairs",
                     "value": [[8, 32]] * 128, "origin": "constructor_effective"},
                ], "meta": {},
            })
    assert validate_consumption_v2(child) is child
    child["nodes"][-1]["reads"].append({
        "field": "strategy.forecast.fdm", "value_type": "int32_number_pairs",
        "value": [[1, 0.5]], "origin": "constructor_effective",
    })
    _reject(child)


def test_private_error_does_not_log_or_copy_bad_input(caplog):
    child = deepcopy(CASES["accepted"]["ordinary"])
    child["nodes"][0]["meta"]["mode"] = "SECRET-CONFIG-NAME"
    snapshot = deepcopy(child)
    _reject(child)
    assert child == snapshot
    assert not caplog.records


def test_registration_short_circuit_rejects_rhs_without_requested_read():
    child = deepcopy(CASES["accepted"]["ordinary"])
    child["nodes"][5]["reads"].append({
        "field": "portfolio.registration.portfolio_optimization",
        "value_type": "bool", "value": True, "origin": "app_config_effective",
    })
    _reject(child)


def test_registration_short_circuit_rejects_max_without_min_read():
    child = deepcopy(CASES["accepted"]["ordinary"])
    child["nodes"][5]["reads"].append({
        "field": "portfolio.registration.max_allocation",
        "value_type": "number", "value": 0.8, "origin": "app_config_effective",
    })
    _reject(child)


def test_successful_empty_cost_history_loop_and_empty_execution_batch_are_valid():
    child = deepcopy(CASES["accepted"]["ordinary"])
    child["nodes"] = [node for node in child["nodes"] if node["id"] not in (8, 9)]
    for node in child["nodes"]:
        if node["id"] > 9:
            node["id"] -= 2
        if node["parent"] is not None and node["parent"] > 9:
            node["parent"] -= 2
    assert child["nodes"][12]["consumer"] == "execution.batch"
    assert validate_consumption_v2(child) is child


def test_failed_benchmark_branch_sticks_in_control_flow_coverage():
    child = deepcopy(CASES["accepted"]["ordinary"])
    child["nodes"][17]["reads"][0]["value"] = "live"
    child["nodes"][17]["meta"]["branch"] = "failed"
    _reject(child)
    child["coverage"]["control_flow"] = {"status": "partial", "reason": "nonfatal_error"}
    child["status"], child["reason"] = "partial", "nonfatal_error"
    assert validate_consumption_v2(child) is child


def test_unavailable_fallback_rejects_retained_complete_prefix():
    child = deepcopy(CASES["accepted"]["unavailable_capacity_exceeded"])
    child["nodes"] = [deepcopy(CASES["accepted"]["ordinary"]["nodes"][0])]
    _reject(child)


def test_duplicate_symbol_map_row_and_missing_presence_reject():
    child = deepcopy(CASES["accepted"]["rich"])
    child["nodes"][22]["reads"].append(deepcopy(child["nodes"][22]["reads"][1]))
    _reject(child)
    child = deepcopy(CASES["accepted"]["rich"])
    child["nodes"][22]["reads"].pop(1)
    _reject(child)


def test_preparation_is_one_runner_invocation_even_with_two_registered_strategies():
    child = deepcopy(CASES["accepted"]["ordinary"])
    child["nodes"].extend([
        {"id": 18, "parent": 3, "kind": "scope", "consumer": "setup.factory_entry",
         "reads": [], "meta": {"construction": "succeeded", "initialize": "succeeded",
                              "start": "succeeded"}, "strategy": "BETA"},
        {"id": 19, "parent": None, "kind": "call", "consumer": "portfolio.registration",
         "reads": [], "meta": {}, "outcome": "returned_ok", "strategy": "BETA"},
        {"id": 20, "parent": 11, "kind": "call", "consumer": "strategy.primary",
         "reads": [], "meta": {"profile": "standard"}, "outcome": "returned_ok",
         "strategy": "BETA"},
        {"id": 21, "parent": None, "kind": "call", "consumer": "execution.batch",
         "reads": [], "meta": {"state": "returned"}, "outcome": "returned_ok",
         "strategy": "BETA"},
        {"id": 22, "parent": None, "kind": "call", "consumer": "strategy.preparation",
         "reads": [], "meta": {"profile": "standard"}, "outcome": "returned_ok",
         "strategy": "BETA"},
    ])
    _reject(child)


@pytest.mark.parametrize("path,value", [
    ("nodes.18.parent", 11),                   # strategy history cannot attach to PM
    ("nodes.18.strategy", "ALPHA"),             # inherited strategy cannot be restated
    ("nodes.34.symbol", "ES"),                  # cost child inherits its symbol
    ("nodes.26.index", 0),                     # helper cannot restate PM pass index
    ("nodes.38.reads.0.origin", "app_config_effective"),  # cost origin is runtime only
    ("nodes.37.reads.0.origin", "derived"),     # external risk capital is runtime only
])
def test_parent_dimensions_and_instance_origin_restrictions(path, value):
    child = deepcopy(CASES["accepted"]["rich"])
    target, key = _locate(child, path)
    target[key] = value
    _reject(child)


def test_base_profile_excludes_non_base_strategy_read_scopes():
    child = deepcopy(CASES["accepted"]["rich"])
    child["nodes"][10]["meta"]["profile"] = "base"
    _reject(child)


def test_optional_metadata_null_and_unknown_keys_reject():
    child = deepcopy(CASES["accepted"]["rich"])
    child["nodes"][4]["meta"]["type_defaulted"] = None
    _reject(child)
    child = deepcopy(CASES["accepted"]["rich"])
    child["nodes"][4]["meta"]["path"] = "secret"
    _reject(child)


@pytest.mark.parametrize("path,value", [
    ("nodes.18.reads.1.value", [[1, 2.5]]),  # int32_pairs
    ("nodes.24.reads.1.value", False),       # symbol presence would hide value
    ("nodes.33.index", 1),                   # estimate vector starts at zero
    ("nodes.40.meta.state", "rejected_id"),  # cost scope cannot follow rejection
])
def test_rich_context_rejects_nested_or_collection_contradiction(path, value):
    child = deepcopy(CASES["accepted"]["rich"])
    target, key = _locate(child, path)
    target[key] = value
    _reject(child)


@pytest.mark.parametrize("value", [True, "1", None, float("nan"), float("inf"),
                                    1.5, -(2**31)-1, 2**31])
def test_int32_rejects_wrong_primitive_or_bound(value):
    child = deepcopy(CASES["accepted"]["ordinary"])
    child["nodes"][6]["reads"][0]["value"] = value
    _reject(child)


@pytest.mark.parametrize("value", [True, "1", None, float("nan"), float("inf"),
                                    -1, 2**53, 1.5])
def test_uint53_rejects_wrong_primitive_or_bound(value):
    child = deepcopy(CASES["accepted"]["ordinary"])
    child["nodes"][9]["reads"][0]["value"] = value
    _reject(child)


@pytest.mark.parametrize("value", [True, "1", None, float("nan"), float("inf"), 10**500])
def test_number_rejects_wrong_primitive_or_unrepresentable_value(value):
    child = deepcopy(CASES["accepted"]["ordinary"])
    child["nodes"][4]["reads"][1]["value"] = value
    _reject(child)


def test_integral_float_negative_finite_number_and_empty_parameter_array_survive():
    child = deepcopy(CASES["accepted"]["rich"])
    child["nodes"][6]["reads"][0]["value"] = 1.0
    child["nodes"][9]["reads"][0]["value"] = 1.0
    child["nodes"][19]["reads"][0]["value"] = -8
    child["nodes"][18]["reads"][1]["value"] = []
    assert validate_consumption_v2(child) is child


@pytest.mark.parametrize("decimal", [
    "-0", "0.0", "01", "1.20", "1e2", "92233720368.54775808",
    "-92233720368.54775809", 1.25, None, True,
])
def test_exact_decimal_uses_shared_helper_and_rejects_malformed_value(decimal):
    child = deepcopy(CASES["accepted"]["rich"])
    child["nodes"][24]["reads"][0]["value"] = decimal
    _reject(child)


def test_bounded_pair_array_accepts_endpoint_and_rejects_one_over():
    child = deepcopy(CASES["accepted"]["rich"])
    child["nodes"][18]["reads"][1]["value"] = [[8, 32]] * 128
    assert validate_consumption_v2(child) is child
    child["nodes"][18]["reads"][1]["value"].append([8, 32])
    _reject(child)


def test_container_cycle_and_excess_nesting_raise_only_private_domain_error():
    child = deepcopy(CASES["accepted"]["ordinary"])
    child["nodes"][6]["reads"][0]["value"] = child
    _reject(child)
    child = deepcopy(CASES["accepted"]["ordinary"])
    nested = 1
    for _ in range(11):
        nested = [nested]
    child["nodes"][6]["reads"][0]["value"] = nested
    _reject(child)


def test_compact_child_byte_limit_rejects_bounded_counts():
    child = deepcopy(CASES["accepted"]["rich"])
    fields = (
        "cost.spread.baseline_spread_ticks", "cost.spread.min_spread_ticks",
        "cost.spread.max_spread_ticks", "cost.spread.spread_cost_multiplier",
        "cost.spread.tick_size", "cost.volatility.lambda",
        "cost.volatility.min_multiplier", "cost.volatility.max_multiplier",
        "cost.impact.min_adv", "cost.impact.min_participation",
        "cost.impact.max_participation", "cost.impact.max_impact_bps",
        "cost.charge.explicit_fee_per_contract", "cost.charge.point_value",
    )
    reads = [{"field": field, "value_type": "number", "value": 1.2345678901234567e300,
              "origin": "runtime_effective"} for field in fields]
    for _ in range(1000):
        child["nodes"].append({"id": len(child["nodes"]), "parent": 11,
                               "kind": "call", "consumer": "cost.strategy_execution",
                               "reads": deepcopy(reads), "meta": {},
                               "outcome": "returned_ok", "strategy": "ALPHA", "symbol": "ES"})
    for index in range(1022):
        symbol = "S" + str(index).zfill(63)
        child["nodes"][22]["reads"].extend([
            {"field": "strategy.sizing.symbol_limit.symbol.present", "value_type": "bool",
             "value": True, "origin": "runtime_effective", "symbol": symbol},
            {"field": "strategy.sizing.symbol_limit.symbol.value", "value_type": "number",
             "value": 1, "origin": "runtime_effective", "symbol": symbol},
        ])
    assert len(child["nodes"]) < 4096
    assert sum(len(node["reads"]) for node in child["nodes"]) < 16384
    assert len(json.dumps(child, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 2097152
    _reject(child)


def test_whole_unavailable_child_is_returned_unchanged():
    child = {"version": 2, "status": "unavailable", "reason": "capacity_exceeded",
             "coverage": {stage: {"status": "unavailable", "reason": "capacity_exceeded"}
                          for stage in STAGES}, "nodes": []}
    assert validate_consumption_v2(child) is child


def test_fixed_private_protocol_error():
    with pytest.raises(ConsumptionProtocolError) as exc:
        validate_consumption_v2({"secret": "DO-NOT-ECHO"})
    assert str(exc.value) == exc.value.reason == "invalid_consumption"


@pytest.mark.parametrize("participant", [28, 30, 32])
def test_optimization_participant_must_be_registered_in_each_phase(participant):
    child = deepcopy(CASES["accepted"]["rich"])
    child["nodes"][participant]["strategy"] = "OTHER"
    _reject(child)


def _attempt(child, branch, symbol):
    batch = next(node for node in child["nodes"] if node["consumer"] == "execution.batch")
    attempts = [node for node in child["nodes"] if node["consumer"] == "execution.attempt"]
    child["nodes"].append({
        "id": len(child["nodes"]), "parent": batch["id"], "kind": "call",
        "consumer": "execution.attempt", "reads": [],
        "meta": {"state": "returned", "branch": branch,
                 "price_source": "market_prices", "returned": True},
        "outcome": "returned_ok", "symbol": symbol, "index": len(attempts),
    })


def test_execution_attempts_preserve_current_then_removed_branch_order():
    for branches in (("current_position",), ("removed_position",),
                     ("current_position", "removed_position")):
        child = deepcopy(CASES["accepted"]["ordinary"])
        for branch in branches:
            _attempt(child, branch, "ES")  # repeated symbols remain distinct calls
        assert validate_consumption_v2(child) is child
    child = deepcopy(CASES["accepted"]["ordinary"])
    _attempt(child, "removed_position", "NQ")
    _attempt(child, "current_position", "ES")
    _reject(child)


@pytest.mark.parametrize("sign", [1, -1])
@pytest.mark.parametrize("location", ["scalar", "number_pair"])
def test_number_finite_binary64_integer_magnitude_endpoint_and_one_over(sign, location):
    largest = int(float.fromhex("0x1.fffffffffffffp+1023"))
    child = deepcopy(CASES["accepted"]["rich"])
    def set_number(value):
        if location == "scalar":
            child["nodes"][4]["reads"][1]["value"] = value
        else:
            child["nodes"][20]["reads"][0]["value"] = [[1, value]]
    set_number(sign * largest)
    assert validate_consumption_v2(child) is child
    set_number(sign * (largest + 1))
    _reject(child)


def test_scalar_container_is_rejected_before_aliased_traversal_amplifies_work():
    child = deepcopy(CASES["accepted"]["ordinary"])
    payload = 1
    for _ in range(4):
        payload = [payload] * 8  # 32 stored references, 4096 leaf visits if fully walked
    child["nodes"][4]["reads"][1]["value"] = payload  # declared number, never an array

    class TraversalGuardTrip(RuntimeError):
        pass

    count = 0
    def guard(frame, event, arg):
        nonlocal count
        if event == "line" and frame.f_code.co_name == "_preflight":
            count += 1
            if count > 5000:
                raise TraversalGuardTrip("preflight exceeded 5000 line events")
        return guard

    old_trace = sys.gettrace()
    try:
        sys.settrace(guard)
        _reject(child)
    finally:
        sys.settrace(old_trace)
    assert count <= 5000


def test_skip_fixture_mutates_the_actual_non_trading_decision():
    case = next(row for row in CASES["rejected"] if row["name"] == "skip_without_decision")
    child = deepcopy(CASES["accepted"][case["base"]])
    target, key = _locate(child, case["path"])
    assert child["nodes"][11]["consumer"] == "runner.non_trading_day"
    assert target is child["nodes"][11]["meta"] and key == "skip_strategy_processing"
    assert target[key] is True
    target[key] = case["value"]
    _reject(child)


# This fixture is a synthetic capacity scenario built from literal test settings,
# not from the catalog or validator, and is not evidence of a native producer.
_TYPICAL_STRATEGIES = ("ALPHA", "BETA", "GAMMA")
_TYPICAL_SYMBOLS = tuple(f"SYM{i:02d}" for i in range(40))
_COST_FIELDS = (
    "cost.spread.baseline_spread_ticks", "cost.spread.min_spread_ticks",
    "cost.spread.max_spread_ticks", "cost.spread.spread_cost_multiplier",
    "cost.spread.tick_size", "cost.volatility.lambda",
    "cost.volatility.min_multiplier", "cost.volatility.max_multiplier",
    "cost.impact.min_adv", "cost.impact.min_participation",
    "cost.impact.max_participation", "cost.impact.max_impact_bps",
    "cost.charge.explicit_fee_per_contract", "cost.charge.point_value",
)


def _compact_bytes(child):
    return len(json.dumps(child, ensure_ascii=False, separators=(",", ":"),
                          allow_nan=False).encode("utf-8"))


def _typical_child():
    child = {"version": 2, "status": "complete", "reason": "none",
             "coverage": {stage: {"status": "complete", "reason": "none"}
                          for stage in STAGES}, "nodes": []}
    nodes = child["nodes"]

    def add(consumer, kind, parent=None, *, meta=None, reads=None, **extra):
        node = {"id": len(nodes), "parent": parent, "kind": kind,
                "consumer": consumer, "reads": reads or [], "meta": meta or {}}
        if kind == "call":
            node["outcome"] = "returned_ok"
        node.update(extra)
        nodes.append(node)
        return node["id"]

    def read(field, value_type, value, origin, *, symbol=None):
        row = {"field": field, "value_type": value_type, "value": value,
               "origin": origin}
        if symbol is not None:
            row["symbol"] = symbol
        return row

    def charge(consumer, kind, parent, *, meta=None, **extra):
        return add(consumer, kind, parent, meta=meta,
                   reads=[read(field, "number", 1, "runtime_effective")
                          for field in _COST_FIELDS], **extra)

    selector = add("setup.selector", "call", meta={"mode": "ordinary"})
    selection = add("setup.ordinary_selection", "scope", selector)
    for strategy in _TYPICAL_STRATEGIES:
        add("setup.selection_entry", "scope", selection, strategy=strategy,
            meta={"enabled_live_read": True, "allocation_read": True,
                  "enabled_live_present": True, "allocation_defaulted": False},
            reads=[read("setup.selection.enabled_live", "bool", True,
                        "configured_strategy_leaf"),
                   read("setup.selection.default_allocation", "number", 0.3,
                        "configured_strategy_leaf")])
    factory = add("setup.factory", "call")
    for strategy in _TYPICAL_STRATEGIES:
        add("setup.factory_entry", "scope", factory, strategy=strategy,
            meta={"profile": "standard", "construction": "succeeded",
                  "initialize": "succeeded", "start": "succeeded"})
        add("portfolio.registration", "call", strategy=strategy,
            reads=[read("portfolio.registration.initial_allocation", "number", 0.3,
                        "selected_allocation"),
                   read("portfolio.registration.stored_allocation", "number", 0.3,
                        "selected_allocation")])
    add("runner.market_window", "scope",
        reads=[read("runner.market_input.historical_days", "int32", 250,
                    "app_config_effective")])
    add("runner.market_fetch", "call")
    for symbol in _TYPICAL_SYMBOLS:
        history = add("execution.history_update", "call", symbol=symbol,
                      meta={"cost_model_reached": True,
                            "previous_close_source": "initial_current_close"})
        add("cost.history", "scope", history,
            reads=[read("cost.impact_history.adv_lookback_days", "uint53", 20,
                        "runtime_effective"),
                   read("cost.spread_history.lookback_days", "uint53", 20,
                        "runtime_effective")])

    def strategy_scopes(call):
        simple = (
            ("strategy.history", "strategy.history.max_history_size", "uint53", 500),
            ("strategy.volatility", "strategy.volatility.vol_lookback_short", "int32", 20),
            ("strategy.forecast", "strategy.forecast.vol_lookback_short", "int32", 20),
            ("strategy.regime", "strategy.regime.vol_lookback_long", "int32", 50),
        )
        for consumer, field, value_type, value in simple:
            rows = [read(field, value_type, value, "constructor_effective")]
            if consumer == "strategy.history":
                rows.append(read("strategy.history.ema_windows", "int32_pairs",
                                 [[8, 32], [16, 64], [32, 128], [64, 256],
                                  [128, 512], [256, 1024]], "constructor_effective"))
            elif consumer == "strategy.forecast":
                rows.extend((
                    read("strategy.forecast.ema_windows", "int32_pairs",
                         [[8, 32], [16, 64], [32, 128], [64, 256],
                          [128, 512], [256, 1024]], "constructor_effective"),
                    read("strategy.forecast.fdm", "int32_number_pairs",
                         [[1, 0.5], [2, 0.75], [3, 1], [4, 1.25],
                          [5, 1.5], [6, 1.75], [7, 2], [8, 2.25]],
                         "constructor_effective"),
                ))
            add(consumer, "scope", call, reads=rows)
        for consumer, prefix, value_origin, meta in (
            ("strategy.sizing", "strategy.sizing.symbol_limit.symbol", "derived", {}),
            ("strategy.buffering", "strategy.buffering.symbol_limit.symbol", "derived", {}),
            ("strategy.base_risk", "strategy.base_risk.trading_multiplier.symbol",
             "runtime_effective", {"supported": True}),
            ("strategy.position_limits", "strategy.position_limits.symbol",
             "derived", {"supported": True}),
        ):
            rows = []
            for symbol in _TYPICAL_SYMBOLS:
                rows.append(read(prefix + ".present", "bool", True,
                                 "runtime_effective", symbol=symbol))
                rows.append(read(prefix + ".value", "number", 1,
                                 value_origin, symbol=symbol))
            add(consumer, "scope", call, meta=meta, reads=rows)

    preparation = add("strategy.preparation", "call", strategy="ALPHA",
                      meta={"profile": "standard"})
    strategy_scopes(preparation)
    primary = add("portfolio.primary", "call",
                  meta={"skip_execution_generation": False})
    for strategy in _TYPICAL_STRATEGIES:
        call = add("strategy.primary", "call", primary, strategy=strategy,
                   meta={"profile": "standard"})
        strategy_scopes(call)
    for pass_index in range(5):
        portfolio_pass = add("portfolio.pass", "scope", primary, index=pass_index,
                             reads=[read("portfolio.pass.use_optimization", "bool", True,
                                         "app_config_effective"),
                                    read("portfolio.pass.use_risk_management", "bool", True,
                                         "app_config_effective")])
        optimization = add("portfolio.optimization", "call", portfolio_pass,
                           meta={"skip": "none"},
                           reads=[read("portfolio.optimization.total_capital",
                                       "fixed_decimal8", "1000000", "derived")])
        for phase in ("portfolio.symbol_collection", "portfolio.numeric_aggregation",
                      "portfolio.redistribution"):
            scope = add(phase, "scope", optimization)
            for strategy in _TYPICAL_STRATEGIES:
                add("portfolio.optimization_strategy", "scope", scope,
                    strategy=strategy,
                    reads=[read("portfolio.optimization.strategy.enabled", "bool",
                                True, "derived"),
                           read("portfolio.optimization.strategy.allocation", "number",
                                0.3, "selected_allocation")])
        for estimate_index, symbol in enumerate(_TYPICAL_SYMBOLS):
            estimate = add("portfolio.estimate", "scope", optimization,
                           symbol=symbol, index=estimate_index)
            charge("cost.estimate", "call", estimate,
                   meta={"asset_lookup": "exact_symbol",
                         "input_source": "explicit_values"})
        add("optimizer.primary", "call", optimization,
            meta={"buffer_branch": "disabled"},
            reads=[read("optimizer.use_buffering", "bool", False,
                        "app_config_effective")])
        risk = add("portfolio.risk", "call", portfolio_pass,
                   meta={"skip": "none", "manager_source": "internal"})
        add("risk.primary", "call", risk,
            reads=[read("risk.var_limit", "number", 0.2,
                        "app_config_effective")])
    for strategy in _TYPICAL_STRATEGIES:
        for symbol in _TYPICAL_SYMBOLS:
            charge("cost.strategy_execution", "call", primary,
                   strategy=strategy, symbol=symbol,
                   meta={"input_source": "internally_tracked"})
    for symbol in _TYPICAL_SYMBOLS:
        charge("cost.compatibility_execution", "call", primary, symbol=symbol)
    for strategy in _TYPICAL_STRATEGIES:
        batch = add("execution.batch", "call", strategy=strategy,
                    meta={"state": "returned"})
        for index, symbol in enumerate(_TYPICAL_SYMBOLS):
            attempt = add("execution.attempt", "call", batch, symbol=symbol,
                          index=index,
                          meta={"state": "returned", "branch": "current_position",
                                "price_source": "market_prices", "returned": True})
            charge("cost.execution", "scope", attempt,
                   meta={"input_source": "internally_tracked"})
    add("risk.diagnostics", "call")
    add("runner.non_trading_day", "scope",
        meta={"skip_strategy_processing": False})
    add("runner.benchmark", "scope", meta={"branch": "not_reached"},
        reads=[read("runner.benchmark.mode", "benchmark_mode", "deferred",
                    "app_config_effective")])
    return child


def test_typical_three_strategy_forty_symbol_five_pass_fixture_fits_with_reservation():
    child = _typical_child()
    by_consumer = {}
    for node in child["nodes"]:
        by_consumer.setdefault(node["consumer"], []).append(node)
    assert len(_TYPICAL_STRATEGIES) == 3 and len(_TYPICAL_SYMBOLS) == 40
    assert [node["index"] for node in by_consumer["portfolio.pass"]] == list(range(5))
    assert len(by_consumer["strategy.preparation"] + by_consumer["strategy.primary"]) == 4
    parameter_pairs = 0
    for call in by_consumer["strategy.preparation"] + by_consumer["strategy.primary"]:
        scopes = [node for node in child["nodes"] if node["parent"] == call["id"]]
        assert len(scopes) == 8
        history = next(node for node in scopes if node["consumer"] == "strategy.history")
        forecast = next(node for node in scopes if node["consumer"] == "strategy.forecast")
        expected = (
            (history, "strategy.history.ema_windows", "int32_pairs",
             [[8, 32], [16, 64], [32, 128], [64, 256], [128, 512], [256, 1024]]),
            (forecast, "strategy.forecast.ema_windows", "int32_pairs",
             [[8, 32], [16, 64], [32, 128], [64, 256], [128, 512], [256, 1024]]),
            (forecast, "strategy.forecast.fdm", "int32_number_pairs",
             [[1, 0.5], [2, 0.75], [3, 1], [4, 1.25],
              [5, 1.5], [6, 1.75], [7, 2], [8, 2.25]]),
        )
        for scope, field, kind, pairs in expected:
            matches = [row for row in scope["reads"] if row["field"] == field]
            assert matches == [{"field": field, "value_type": kind,
                                "value": pairs, "origin": "constructor_effective"}]
            parameter_pairs += len(matches[0]["value"])
    assert parameter_pairs == 4 * (6 + 6 + 8) == 80
    assert len(by_consumer["execution.history_update"]) == len(by_consumer["cost.history"]) == 40
    assert len(by_consumer["portfolio.optimization_strategy"]) == 45
    assert len(by_consumer["portfolio.estimate"]) == 200
    assert len(by_consumer["execution.attempt"]) == 120
    assert [len(by_consumer[name]) for name in (
        "cost.estimate", "cost.strategy_execution",
        "cost.compatibility_execution", "cost.execution")] == [200, 120, 40, 120]
    charges = [node for node in child["nodes"] if node["consumer"] in (
        "cost.estimate", "cost.strategy_execution",
        "cost.compatibility_execution", "cost.execution")]
    assert sum(len(node["reads"]) for node in charges) == 480 * 14 == 6720
    assert sum(len(node["reads"]) for node in child["nodes"]
               if node["consumer"] in ("strategy.sizing", "strategy.buffering",
                                       "strategy.base_risk", "strategy.position_limits")) == 1280
    assert len(child["nodes"]) <= 1200
    assert sum(len(node["reads"]) for node in child["nodes"]) <= 8511
    size = _compact_bytes(child)
    print(f"typical_compact_bytes={size} nodes={len(child['nodes'])} "
          f"reads={sum(len(node['reads']) for node in child['nodes'])} "
          f"parameter_pairs={parameter_pairs}")
    assert size + 131072 <= 2097152  # separate 128 KiB outer reservation
    assert validate_consumption_v2(child) is child


def test_structural_typical_companion_accepts_exact_cap_and_rejects_one_more_byte():
    child = _typical_child()
    primary = next(node["id"] for node in child["nodes"]
                   if node["consumer"] == "portfolio.primary")
    current = _compact_bytes(child)
    filler = []
    while True:
        node = {"id": len(child["nodes"]), "parent": primary, "kind": "call",
                "consumer": "cost.strategy_execution", "reads": [
                    {"field": field, "value_type": "number", "value": 1.2345678901234567e100,
                     "origin": "runtime_effective"} for field in _COST_FIELDS],
                "meta": {"input_source": "internally_tracked"},
                "outcome": "returned_ok", "strategy": "ALPHA", "symbol": "SYM00"}
        increment = 1 + len(json.dumps(node, ensure_ascii=False,
                                       separators=(",", ":")).encode("utf-8"))
        if current + increment > 2097152:
            break
        child["nodes"].append(node)
        filler.append(node)
        current += increment
    deficit = 2097152 - current
    adjustable = [row for node in child["nodes"] if node["consumer"] in (
        "cost.estimate", "cost.strategy_execution",
        "cost.compatibility_execution", "cost.execution")
        for row in node["reads"] if row["value"] == 1]
    assert len(adjustable) > deficit  # each 1 -> 10 adds exactly one UTF-8 byte
    for row in adjustable[:deficit]:
        row["value"] = 10
    assert _compact_bytes(child) == 2097152
    assert len(child["nodes"]) <= 4096
    assert sum(len(node["reads"]) for node in child["nodes"]) <= 16384
    assert validate_consumption_v2(child) is child
    adjustable[deficit]["value"] = 10
    assert _compact_bytes(child) == 2097153
    _reject(child)
