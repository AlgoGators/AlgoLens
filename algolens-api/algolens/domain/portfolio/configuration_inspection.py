"""Strict, bounded inspection wire contract. No transport or storage dependency."""

from datetime import date, datetime
import json
import math
import re
from uuid import UUID

from .consumption_inspection import ConsumptionProtocolError, validate_consumption_v2


MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}\Z", re.ASCII)
BUILD_TOKEN = re.compile(r"[A-Za-z0-9._-]{1,128}\Z", re.ASCII)
UTC_TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z\Z", re.ASCII)
TYPES = frozenset({"TrendFollowingStrategy", "TrendFollowingFastStrategy", "TrendFollowingSlowStrategy"})
CAPTURE_REASONS = frozenset({"projection_invalid", "selected_stage_unavailable", "capture_failed"})
ROOT_KEYS = frozenset({"publication_schema_version", "profile", "authority", "stream", "identity",
                       "captured_at", "publication_recorded_at", "status", "reason", "supplied",
                       "selected_trend", "consumption"})
IDENTITY_KEYS = frozenset({"registry_id", "registry_revision", "engine_strategy_id", "portfolio_id",
                           "run_date", "capture_id", "publication_id", "runtime_attempt_id",
                           "producer_version", "control_mode"})
FIELD_KEYS = frozenset({"path", "scope", "classification", "reason", "condition", "value_type",
                        "unit", "value_origin", "value_state"})
TREND_KEYS = frozenset({"weight", "risk_target", "fx_rate", "idm", "max_symbol_concentration",
                        "use_position_buffering", "carver_buffer_floor", "carver_buffer_position_factor",
                        "ema_windows", "vol_lookback_short", "vol_lookback_long", "max_history_size", "fdm"})

# path | classification | reason | condition | type | unit | origin | state.
# This is the fixed 40-leaf v1 inventory, transcribed from the normative catalog.
FIXED_CATALOG_TEXT = """
/portfolio_id|read_only_metadata|identity_metadata|metadata_only|string|identity|not_projected|omitted
/initial_capital|source_supported_config_input|source_reader|source_path|number|account_currency|app_config_member|included
/reserve_capital_pct|unsupported_in_profile|stored_metadata_only|no_active_profile_reader|number|fraction|app_config_member|included
/benchmark_mode|source_supported_config_input|source_reader|benchmark_stage|enum_string|mode|app_config_member|included
/execution/commission_rate|unsupported_in_profile|not_wired_to_futures_cost_model|no_active_profile_reader|number|unverified_rate|app_config_member|included
/execution/slippage_bps|unsupported_in_profile|not_wired_to_futures_cost_model|no_active_profile_reader|number|basis_points|app_config_member|included
/execution/position_limit_backtest|unsupported_in_profile|backtest_only|no_active_profile_reader|number|contracts|app_config_member|included
/execution/position_limit_live|source_supported_config_input|source_reader|base_position_validation|number|contracts|app_config_member|included
/optimization/tau|source_supported_config_input|source_reader|optimizer_succeeded_and_buffering_enabled|number|risk_scale|app_config_member|included
/optimization/capital|read_only_metadata|derived_alias|metadata_only|number|account_currency|app_config_member|included
/optimization/cost_penalty_scalar|source_supported_config_input|source_reader|optimizer_enabled|number|multiplier|app_config_member|included
/optimization/asymmetric_risk_buffer|unsupported_in_profile|no_active_reader|no_active_profile_reader|number|unverified_buffer_fraction|app_config_member|included
/optimization/max_iterations|source_supported_config_input|source_reader|optimizer_enabled|integer|iterations|app_config_member|included
/optimization/convergence_threshold|source_supported_config_input|source_reader|optimizer_enabled|number|objective_difference|app_config_member|included
/optimization/use_buffering|source_supported_config_input|source_reader|optimizer_enabled|boolean|flag|app_config_member|included
/optimization/buffer_size_factor|source_supported_config_input|source_reader|optimizer_succeeded_and_buffering_enabled|number|multiplier|app_config_member|included
/optimization/version|read_only_metadata|version_metadata|metadata_only|string|config_version|not_projected|omitted
/risk/var_limit|source_supported_config_input|source_reader|risk_enabled|number|annualized_volatility_fraction|app_config_member|included
/risk/jump_risk_limit|source_supported_config_input|source_reader|risk_enabled|number|fraction|app_config_member|included
/risk/corr_shock_threshold|unsupported_in_profile|inactive_alternative|no_active_profile_reader|number|annualized_volatility_fraction|app_config_member|included
/risk/jump_shock_threshold|unsupported_in_profile|inactive_alternative|no_active_profile_reader|number|annualized_volatility_fraction|app_config_member|included
/risk/max_gross_leverage|source_supported_config_input|source_reader|risk_enabled|number|leverage_multiple|app_config_member|included
/risk/max_net_leverage|source_supported_config_input|source_reader|risk_enabled|number|leverage_multiple|app_config_member|included
/risk/capital|read_only_metadata|derived_alias|metadata_only|number|account_currency|app_config_member|included
/risk/version|read_only_metadata|version_metadata|metadata_only|string|config_version|not_projected|omitted
/risk/max_drawdown|source_supported_config_input|source_reader|base_strategy_risk_check|number|fraction|app_config_member|included
/risk/max_leverage|source_supported_config_input|diagnostic_reader|base_strategy_risk_check|number|leverage_multiple|app_config_member|included
/risk_defaults/confidence_level|source_supported_config_input|source_reader|risk_enabled|number|probability|app_config_member|included
/risk_defaults/lookback_period|source_supported_config_input|source_reader|risk_enabled|integer|bar_records|app_config_member|included
/risk_defaults/max_correlation|source_supported_config_input|source_reader|risk_enabled|number|absolute_correlation|app_config_member|included
/backtest/lookback_years|unsupported_in_profile|backtest_only|no_active_profile_reader|integer|years|app_config_member|included
/backtest/store_trade_details|unsupported_in_profile|backtest_only|no_active_profile_reader|boolean|flag|app_config_member|included
/live/historical_days|source_supported_config_input|source_reader|source_path|integer|calendar_days|app_config_member|included
/strategy_defaults/fdm|unsupported_in_profile|blocked_default_fallback|no_active_profile_reader|integer_number_pairs|rule_count_multiplier_pairs|app_config_member|included
/strategy_defaults/max_strategy_allocation|source_supported_config_input|source_reader|allocation_validation|number|fraction|app_config_member|included
/strategy_defaults/min_strategy_allocation|source_supported_config_input|source_reader|allocation_validation|number|fraction|app_config_member|included
/strategy_defaults/use_optimization|source_supported_config_input|source_reader|source_path|boolean|flag|app_config_member|included
/strategy_defaults/use_risk_management|source_supported_config_input|source_reader|source_path|boolean|flag|app_config_member|included
/strategy_defaults/carver_buffer_floor|source_supported_config_input|source_reader|strategy_config_present_leaf_absent_and_buffering_enabled|number|contracts|app_config_member|included
/strategy_defaults/carver_buffer_position_factor|source_supported_config_input|source_reader|strategy_config_present_leaf_absent_and_buffering_enabled|number|fraction|app_config_member|included
"""
FIXED_CATALOG = {parts[0]: parts[1:] for parts in
                 (line.split("|") for line in FIXED_CATALOG_TEXT.strip().splitlines())}

# suffix | classification | reason | condition | type | unit | origin.
STRATEGY_CATALOG_TEXT = """
enabled_live|source_supported_config_input|source_reader|strategy_selection|boolean|flag|configured_strategy_leaf
default_allocation|source_supported_config_input|source_reader|strategy_selection|number|fraction|configured_strategy_leaf
enabled_backtest|unsupported_in_profile|backtest_only|no_active_profile_reader|boolean|flag|configured_strategy_leaf
type|source_supported_config_input|source_reader|strategy_dispatch|enum_string|strategy_type|configured_strategy_leaf
config/weight|source_supported_config_input|source_reader|selected_known_strategy_buffering_enabled|number|multiplier|configured_strategy_leaf
config/risk_target|source_supported_config_input|source_reader|selected_known_strategy|number|annualized_volatility_fraction|configured_strategy_leaf
config/idm|source_supported_config_input|source_reader|selected_known_strategy|number|multiplier|configured_strategy_leaf
config/max_symbol_concentration|source_supported_config_input|source_reader|selected_known_strategy|number|fraction|configured_strategy_leaf
config/use_position_buffering|source_supported_config_input|source_reader|selected_known_strategy|boolean|flag|configured_strategy_leaf
config/carver_buffer_floor|source_supported_config_input|source_reader|selected_known_strategy_buffering_enabled|number|contracts|configured_strategy_leaf
config/carver_buffer_position_factor|source_supported_config_input|source_reader|selected_known_strategy_buffering_enabled|number|fraction|configured_strategy_leaf
config/ema_windows|source_supported_config_input|source_reader|selected_known_strategy|integer_pairs|short_long_bar_pairs|configured_strategy_leaf
config/vol_lookback_short|source_supported_config_input|source_reader|selected_known_strategy|integer|bar_windows|configured_strategy_leaf
config/vol_lookback_long|source_supported_config_input|source_reader|selected_known_strategy|integer|bar_windows|configured_strategy_leaf
config/fx_rate|unsupported_in_profile|typed_member_not_input_wired|no_active_profile_reader|number|currency_ratio|not_projected
config/max_history_size|unsupported_in_profile|typed_member_not_input_wired|no_active_profile_reader|integer|bar_records|not_projected
config/fdm|unsupported_in_profile|typed_member_not_input_wired|no_active_profile_reader|integer_number_pairs|rule_count_multiplier_pairs|not_projected
"""
STRATEGY_CATALOG = {parts[0]: parts[1:] for parts in
                    (line.split("|") for line in STRATEGY_CATALOG_TEXT.strip().splitlines())}


class PublicationError(ValueError):
    def __init__(self, reason="invalid_publication"):
        self.reason = reason
        super().__init__(reason)


def _require(condition, reason="invalid_publication"):
    if not condition:
        raise PublicationError(reason)


def _pairs(items):
    result = {}
    for key, value in items:
        _require(key not in result)
        result[key] = value
    return result


def _reject_constant(_value):
    raise PublicationError()


def _keys(value, expected):
    _require(type(value) is dict and value.keys() == expected)


def _integer(value):
    return type(value) is int and -(2**31) <= value <= 2**31 - 1


def _value(value, kind, path):
    if kind == "number":
        _require(type(value) in (int, float))
        try:
            _require(math.isfinite(float(value)))
        except OverflowError:
            raise PublicationError() from None
    elif kind == "integer":
        _require(_integer(value))
    elif kind == "unsigned64":
        _require(type(value) is int and 0 <= value <= 2**64 - 1)
    elif kind == "boolean":
        _require(type(value) is bool)
    elif kind in ("enum_string", "string"):
        _require(type(value) is str)
        if path == "/benchmark_mode":
            _require(value in ("live", "deferred"))
        elif path.endswith("/type"):
            _require(value in TYPES)
        else:
            _require(False)
    elif kind in ("integer_pairs", "integer_number_pairs"):
        _require(type(value) is list)
        for pair in value:
            _require(type(pair) is list and len(pair) == 2 and _integer(pair[0]))
            _value(pair[1], "integer" if kind == "integer_pairs" else "number", path)
    else:
        _require(False)


def _field(row, path, spec, state=None):
    classification, reason, condition, kind, unit, origin = spec[:6]
    expected_state = state or (spec[6] if len(spec) == 7 else None)
    _require(type(row) is dict)
    _require(row.keys() == (FIELD_KEYS | ({"value"} if row.get("value_state") == "included" else set())))
    _require(row["path"] == path and row["scope"] == "exact")
    _require((row["classification"], row["reason"], row["condition"], row["value_type"],
              row["unit"], row["value_origin"]) == (classification, reason, condition, kind, unit, origin))
    _require(row["value_state"] == expected_state if expected_state else row["value_state"] in
             ("included", "absent_in_input"))
    if row["value_state"] == "included":
        _value(row["value"], kind, path)


def _supplied(value):
    _keys(value, {"projection_version", "profile", "coverage", "authority", "consumption_evidence", "fields"})
    _require(type(value["projection_version"]) is int and value["projection_version"] == 1)
    _require(value["profile"] == "live_portfolio_runner_futures"
             and value["coverage"] == "current_typed_fields_and_known_strategy_leaves"
             and value["authority"] == "inspection_only"
             and value["consumption_evidence"] == "not_collected")
    fields = value["fields"]
    _require(type(fields) is list)
    paths = [row.get("path") if type(row) is dict else None for row in fields]
    _require(all(type(path) is str for path in paths) and paths == sorted(set(paths)))
    by_path = dict(zip(paths, fields))
    for path, spec in FIXED_CATALOG.items():
        _require(path in by_path)
        _field(by_path[path], path, spec)
    definitions = {}
    for path in paths:
        if path in FIXED_CATALOG:
            continue
        match = re.fullmatch(r"/strategies/([A-Za-z0-9_-]{1,128})/(.+)", path, re.ASCII)
        _require(match is not None)
        definitions.setdefault(match[1], set()).add(match[2])
    _require(len(definitions) <= 1024)
    for strategy_id, suffixes in definitions.items():
        root = "/strategies/" + strategy_id + "/"
        type_row = by_path.get(root + "type")
        _require(type_row is not None)
        unknown = type_row.get("reason") == "unknown_strategy_type"
        expected = {"enabled_live", "default_allocation", "enabled_backtest", "type"} if unknown else set(STRATEGY_CATALOG)
        _require(suffixes == expected)
        for suffix in expected:
            path = root + suffix
            if unknown and suffix == "type":
                _field(by_path[path], path, ("unsupported_in_profile", "unknown_strategy_type",
                      "no_active_profile_reader", "enum_string", "strategy_type", "not_projected", "omitted"))
            else:
                spec = STRATEGY_CATALOG[suffix]
                _field(by_path[path], path, spec, "omitted" if spec[5] == "not_projected" else None)
    _require(len(fields) == len(FIXED_CATALOG) + sum(len(suffixes) for suffixes in definitions.values()))
    return definitions, by_path


def _utc(value, now):
    _require(type(value) is str and UTC_TIME.fullmatch(value) is not None)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PublicationError() from None
    _require(parsed.tzinfo is not None and parsed <= now)
    return parsed


def _uuid(value):
    _require(type(value) is str)
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        raise PublicationError() from None
    _require(str(parsed) == value)


def _finish_publication(value):
    if value["publication_schema_version"] == 2:
        # The raw input was capped before parsing, and the consumption child
        # has already passed its bounded preflight and semantic validation.
        try:
            compact = json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                                 allow_nan=False)
            _require(len(compact.encode("utf-8")) <= MAX_DOCUMENT_BYTES)
        except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
            raise PublicationError() from None
    return value


def parse_publication(raw, scope, now):
    """Return a fully validated public envelope or a fixed protocol reason."""
    _require(type(raw) is str)
    try:
        _require(len(raw.encode("utf-8")) <= MAX_DOCUMENT_BYTES)
    except UnicodeError:
        raise PublicationError() from None
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise PublicationError() from None
    _keys(value, ROOT_KEYS)
    _require(type(value["publication_schema_version"]) is int
             and value["publication_schema_version"] in (1, 2)
             and value["profile"] == "live_portfolio_runner_futures", "unsupported_publication")
    _require(value["authority"] == "inspection_only" and value["stream"] == "system")
    identity = value["identity"]
    _keys(identity, IDENTITY_KEYS)
    for key in ("registry_id", "engine_strategy_id", "portfolio_id"):
        _require(type(identity[key]) is str and IDENTIFIER.fullmatch(identity[key]) is not None)
    _require(_integer(identity["registry_revision"]) and identity["registry_revision"] >= 0)
    _require(type(identity["run_date"]) is str)
    try:
        run_date = date.fromisoformat(identity["run_date"])
    except ValueError:
        raise PublicationError() from None
    _require(run_date.isoformat() == identity["run_date"] and run_date <= now.date())
    for key in ("capture_id", "publication_id"):
        _uuid(identity[key])
    _require(identity["capture_id"] == identity["publication_id"])
    _require(identity["control_mode"] in ("controlled", "uncontrolled"))
    if identity["control_mode"] == "controlled":
        _uuid(identity["runtime_attempt_id"])
        _require(identity["runtime_attempt_id"] == identity["publication_id"])
    else:
        _require(identity["runtime_attempt_id"] is None)
    _require(type(identity["producer_version"]) is str and
             BUILD_TOKEN.fullmatch(identity["producer_version"]) is not None)
    captured = _utc(value["captured_at"], now)
    recorded = _utc(value["publication_recorded_at"], now)
    _require(captured <= recorded and run_date <= recorded.date())
    if value["publication_schema_version"] == 1:
        _require(value["consumption"] == {"status": "not_collected"})
    else:
        try:
            validate_consumption_v2(value["consumption"])
        except ConsumptionProtocolError:
            raise PublicationError() from None
    _require((identity["registry_id"], identity["registry_revision"],
              identity["engine_strategy_id"], identity["portfolio_id"], identity["run_date"])
             == (scope["registry_id"], scope["registry_revision"], scope["engine_strategy_id"],
                 scope["portfolio_id"], scope["run_date"]), "scope_changed")
    _require(value["status"] in ("available", "unavailable"))
    if value["status"] == "unavailable":
        _require(type(value["reason"]) is str and value["reason"] in CAPTURE_REASONS
                 and value["supplied"] is None
                 and value["selected_trend"] is None)
        _require(identity["producer_version"] != "unversioned" or value["reason"] == "capture_failed")
        return _finish_publication(value)
    _require(value["reason"] == "none" and identity["producer_version"] != "unversioned")
    definitions, fields = _supplied(value["supplied"])
    trend = value["selected_trend"]
    _keys(trend, {"schema_version", "provenance", "slow_concentration_override", "strategies"})
    _require(type(trend["schema_version"]) is int and trend["schema_version"] == 1
             and trend["provenance"] == "shared_resolver_same_inputs")
    override = trend["slow_concentration_override"]
    _require(type(override) is dict and override.keys() in ({"state"}, {"state", "value"}))
    _require(override == {"state": "absent"} or
             (override.get("state") == "present" and override.keys() == {"state", "value"}))
    if override.get("state") == "present":
        _value(override["value"], "number", "")
    strategies = trend["strategies"]
    _require(type(strategies) is list and len(strategies) <= len(definitions))
    selected = set()
    for item in strategies:
        _keys(item, {"strategy_id", "strategy_type", "selected_allocation", "factory_resolved", "constructor_normalized"})
        sid = item["strategy_id"]
        _require(type(sid) is str and IDENTIFIER.fullmatch(sid) is not None
                 and sid in definitions and sid not in selected)
        selected.add(sid)
        type_row = fields["/strategies/" + sid + "/type"]
        if type_row["value_state"] == "included":
            _require(item["strategy_type"] == type_row["value"]
                     and item["strategy_type"] in TYPES)
        else:
            # The factory's documented missing-type route is standard only.
            _require(type_row["value_state"] == "absent_in_input"
                     and item["strategy_type"] == "TrendFollowingStrategy")
        enabled = fields["/strategies/" + sid + "/enabled_live"]
        _require(enabled["value_state"] == "included" and enabled["value"] is True)
        _value(item["selected_allocation"], "number", "")
        for stage in ("factory_resolved", "constructor_normalized"):
            values = item[stage]
            _keys(values, TREND_KEYS)
            for key, kind in (("weight", "number"), ("risk_target", "number"), ("fx_rate", "number"),
                              ("idm", "number"), ("max_symbol_concentration", "number"),
                              ("use_position_buffering", "boolean"), ("carver_buffer_floor", "number"),
                              ("carver_buffer_position_factor", "number"), ("ema_windows", "integer_pairs"),
                              ("vol_lookback_short", "integer"), ("vol_lookback_long", "integer"),
                              ("max_history_size", "unsigned64"), ("fdm", "integer_number_pairs")):
                _value(values[key], kind, "")
    return _finish_publication(value)
