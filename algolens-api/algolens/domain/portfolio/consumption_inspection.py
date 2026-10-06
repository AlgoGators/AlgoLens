"""Pure parsed-object validation of the v2 consumption child.

This checks facts inferable from the child. Native loop coverage, caller-bound
first-selected identity, raw duplicate JSON members/token spellings, and the
combined publication byte budget remain producer/outer-boundary assertions.
"""

import json
import math
import re

from algolens.domain.shared.fixed_decimal8 import parse_fixed_decimal8

from .consumption_catalog import CATALOG


class ConsumptionProtocolError(ValueError):
    def __init__(self):
        self.reason = "invalid_consumption"
        super().__init__(self.reason)


_CONSUMERS = {row["name"]: row for row in CATALOG["consumers"]}
_META = {}
for _row in CATALOG["metadata"]:
    _META.setdefault(_row["consumer"], {})[_row["key"]] = _row
_FIELDS = {}
for _row in CATALOG["fields"]:
    _FIELDS.setdefault(_row["consumer"], {})[_row["field"]] = _row
_STRATEGY = re.compile(CATALOG["identity"]["strategy"], re.ASCII)
_SYMBOL = re.compile(CATALOG["identity"]["symbol"], re.ASCII)
_LIMIT = CATALOG["limits"]
_MAX_FINITE_BINARY64_INTEGER = ((1 << 53) - 1) << 971
_STAGES = CATALOG["stages"]
_PRIORITY = CATALOG["statuses"]["partial"]
_UNAVAILABLE = CATALOG["statuses"]["unavailable"]
_SYMBOL_MAP = {
    "strategy.sizing.symbol_limit.symbol",
    "strategy.buffering.symbol_limit.symbol",
    "strategy.base_risk.trading_multiplier.symbol",
    "strategy.position_limits.symbol",
}
_STRATEGY_SCOPES = {
    "strategy.history", "strategy.volatility", "strategy.forecast", "strategy.regime",
    "strategy.sizing", "strategy.buffering", "strategy.base_risk",
    "strategy.position_limits",
}
_SINGLETON_ROOTS = {
    "setup.selector", "setup.factory", "runner.market_window", "runner.market_fetch",
    "strategy.preparation", "portfolio.primary", "risk.diagnostics",
    "runner.non_trading_day", "runner.benchmark",
}
_UNIQUE_PER_PARENT = {
    "setup.controlled_validation", "setup.ordinary_selection", "strategy.history",
    "strategy.volatility", "strategy.forecast", "strategy.regime", "strategy.sizing",
    "strategy.buffering", "strategy.base_risk", "strategy.position_limits",
    "portfolio.optimization", "portfolio.symbol_collection",
    "portfolio.numeric_aggregation", "portfolio.redistribution",
    "optimizer.primary", "portfolio.risk", "risk.primary", "cost.estimate",
    "cost.history", "cost.execution",
}


def _need(ok):
    if not ok:
        raise ConsumptionProtocolError()


def _keys(value, required, optional=()):
    _need(type(value) is dict)
    keys = value.keys()
    _need(all(type(key) is str and len(key) <= _LIMIT["string_length"] for key in keys))
    _need(set(required) <= keys and keys <= set(required) | set(optional))


def _integer(value, minimum, maximum):
    # Checking integer magnitude before float conversion also handles huge ints.
    if type(value) is int:
        return minimum <= value <= maximum
    return type(value) is float and math.isfinite(value) and value.is_integer() and minimum <= value <= maximum


def _number(value):
    if type(value) is int:
        return -_MAX_FINITE_BINARY64_INTEGER <= value <= _MAX_FINITE_BINARY64_INTEGER
    return type(value) is float and math.isfinite(value)


def _identity(value, pattern):
    _need(type(value) is str and len(value) <= _LIMIT["identity_length"]
          and pattern.fullmatch(value) is not None)


def _preflight(value):
    """Admit only the closed, fixed-depth shape before indexes or serialization.

    The deepest legal path is root/nodes/node/reads/read/pairs/pair/scalar:
    eight JSON levels, below the catalog's ten-level ceiling. Each admitted
    container has a bounded collection and no container-valued scalar leaf;
    aliases in real pair arrays remain legal without recursive expansion.
    """
    _keys(value, ("version", "status", "reason", "coverage", "nodes"))
    _need(type(value["version"]) in (int, float))
    _need(type(value["status"]) is str and len(value["status"]) <= _LIMIT["string_length"])
    _need(type(value["reason"]) is str and len(value["reason"]) <= _LIMIT["string_length"])
    _need(type(value["coverage"]) is dict and value["coverage"].keys() == set(_STAGES))
    for coverage in value["coverage"].values():
        _keys(coverage, ("status", "reason"))
        _need(all(type(item) is str and len(item) <= _LIMIT["string_length"]
                  for item in coverage.values()))
    _need(type(value["nodes"]) is list and len(value["nodes"]) <= _LIMIT["nodes"])
    total_reads = 0
    total_pairs = 0
    for node in value["nodes"]:
        _keys(node, ("id", "parent", "kind", "consumer", "reads", "meta"),
              ("outcome", "strategy", "symbol", "index"))
        for key in ("id", "parent", "index"):
            if key in node:
                _need((key == "parent" and node[key] is None) or
                      type(node[key]) in (int, float))
        for key in ("kind", "consumer", "outcome", "strategy", "symbol"):
            if key in node:
                _need(type(node[key]) is str and len(node[key]) <= _LIMIT["string_length"])
        meta = node["meta"]
        _need(type(meta) is dict and len(meta) <= 5)
        for key, member in meta.items():
            _need(type(key) is str and len(key) <= _LIMIT["string_length"])
            _need(type(member) is bool or
                  (type(member) is str and len(member) <= _LIMIT["string_length"]))
        reads = node["reads"]
        _need(type(reads) is list and len(reads) <= _LIMIT["reads_per_node"])
        total_reads += len(reads)
        _need(total_reads <= _LIMIT["reads_total"])
        for row in reads:
            _keys(row, ("field", "value_type", "value", "origin"), ("symbol",))
            for key in ("field", "value_type", "origin", "symbol"):
                if key in row:
                    _need(type(row[key]) is str and len(row[key]) <= _LIMIT["string_length"])
            kind, observed = row["value_type"], row["value"]
            if kind in ("bool", "number", "int32", "uint53",
                        "fixed_decimal8", "benchmark_mode"):
                expected = (bool,) if kind == "bool" else (
                    (str,) if kind in ("fixed_decimal8", "benchmark_mode") else (int, float))
                _need(type(observed) in expected)
                if type(observed) is str:
                    _need(len(observed) <= _LIMIT["string_length"])
            elif kind in ("int32_pairs", "int32_number_pairs"):
                _need(type(observed) is list and len(observed) <= _LIMIT["pairs_per_read"])
                total_pairs += len(observed)
                _need(total_pairs <= _LIMIT["pairs_total"])
                for pair in observed:
                    _need(type(pair) is list and len(pair) == 2)
                    _need(type(pair[0]) in (int, float) and type(pair[1]) in (int, float))
            else:
                _need(False)


def _typed(value, kind, pairs):
    if kind == "bool":
        _need(type(value) is bool)
    elif kind == "number":
        _need(_number(value))
    elif kind == "int32":
        _need(_integer(value, -(2**31), 2**31 - 1))
    elif kind == "uint53":
        _need(_integer(value, 0, 2**53 - 1))
    elif kind == "fixed_decimal8":
        _need(type(value) is str and parse_fixed_decimal8(value) == value)
    elif kind in ("int32_pairs", "int32_number_pairs"):
        _need(type(value) is list and len(value) <= _LIMIT["pairs_per_read"])
        pairs[0] += len(value)
        _need(pairs[0] <= _LIMIT["pairs_total"])
        for pair in value:
            _need(type(pair) is list and len(pair) == 2)
            _typed(pair[0], "int32", pairs)
            _typed(pair[1], "int32" if kind == "int32_pairs" else "number", pairs)
    elif kind == "benchmark_mode":
        _need(type(value) is str and value in ("live", "deferred"))
    else:
        _need(False)


def _node_meta(node):
    spec = _META.get(node["consumer"], {})
    meta = node["meta"]
    _keys(meta, (key for key, row in spec.items() if row["required"]), spec)
    for key, value in meta.items():
        kind = spec[key]["type"]
        if kind == "bool":
            _need(type(value) is bool)
        else:
            _need(type(value) is str and value in kind[5:].split(","))


def _read_rows(node, pairs, symbols):
    seen = set()
    found = {}
    symbol_maps = {}
    for row in node["reads"]:
        _keys(row, ("field", "value_type", "value", "origin"), ("symbol",))
        field = row["field"]
        _need(type(field) is str and field in _FIELDS.get(node["consumer"], {}))
        spec = _FIELDS[node["consumer"]][field]
        _need(row["value_type"] == spec["type"] and type(row["value_type"]) is str)
        _need(type(row["origin"]) is str and row["origin"] in spec["origins"])
        _typed(row["value"], spec["type"], pairs)
        symbol = row.get("symbol")
        if "symbol" in row:
            _identity(symbol, _SYMBOL)
            symbols.add(symbol)
            _need(len(symbols) <= _LIMIT["symbols"])
            _need(any(field in (prefix + ".present", prefix + ".value") for prefix in _SYMBOL_MAP))
            prefix = field.rsplit(".", 1)[0]
            symbol_maps.setdefault(prefix, {}).setdefault(symbol, {})[field.rsplit(".", 1)[1]] = row["value"]
        else:
            _need(not any(field in (prefix + ".present", prefix + ".value") for prefix in _SYMBOL_MAP))
        key = (field, symbol)
        _need(key not in seen)
        seen.add(key)
        found[field] = row
    for entries in symbol_maps.values():
        _need(len(entries) <= _LIMIT["collection_entries"])
        for entry in entries.values():
            _need("present" in entry and type(entry["present"]) is bool)
            _need(entry["present"] or "value" not in entry)
    return found


def _stage_for(node, nodes):
    spec = _CONSUMERS[node["consumer"]]
    if spec["stage"] != "inherited":
        return spec["stage"]
    return _CONSUMERS[nodes[int(node["parent"])]["consumer"]]["stage"]


def _relations(value, found, children, stage_nodes, causes):
    nodes = value["nodes"]
    by_consumer = {}
    for node in nodes:
        by_consumer.setdefault(node["consumer"], []).append(node)
    only = lambda name: (by_consumer.get(name) or [None])[0]
    selector, factory = only("setup.selector"), only("setup.factory")
    controlled = by_consumer.get("setup.controlled_validation", [])
    _need(factory is None or selector is not None)
    _need(not by_consumer.get("portfolio.registration") or factory is not None)
    if selector:
        _need(not controlled or selector["meta"]["mode"] == "controlled")
    for entry in by_consumer.get("setup.selection_entry", []):
        meta, rows = entry["meta"], found[entry["id"]]
        for field, flag in (("setup.selection.enabled_live", "enabled_live_read"),
                            ("setup.selection.default_allocation", "allocation_read")):
            if field in rows:
                _need(meta[flag])
        _need("enabled_live_defaulted" not in meta or
              "setup.selection.enabled_live" in rows)
        _need("allocation_defaulted" not in meta or
              "setup.selection.default_allocation" in rows)
        if "setup.selection.enabled_live" in rows:
            row = rows["setup.selection.enabled_live"]
            if "enabled_live_defaulted" in meta:
                _need(row["origin"] == ("code_default" if meta["enabled_live_defaulted"] else "configured_strategy_leaf"))
            if "enabled_live_present" in meta and meta["enabled_live_present"]:
                _need(row["origin"] == "configured_strategy_leaf")
            if "enabled_live_present" in meta and not meta["enabled_live_present"]:
                _need(row["origin"] == "code_default")
            if nodes[int(entry["parent"])]["consumer"] == "setup.ordinary_selection":
                _need("enabled_live_defaulted" not in meta)
        if "setup.selection.default_allocation" in rows and "allocation_defaulted" in meta:
            _need(rows["setup.selection.default_allocation"]["origin"] ==
                  ("code_default" if meta["allocation_defaulted"] else "configured_strategy_leaf"))
        for flag, key in (("enabled_live_defaulted", "enabled_live_read"),
                          ("allocation_defaulted", "allocation_read")):
            _need(not meta.get(flag) or meta[key])
    for entry in by_consumer.get("setup.factory_entry", []):
        meta = entry["meta"]
        for prior, later in (("construction", "initialize"), ("initialize", "start")):
            _need(meta[later] == "not_reached" or meta[prior] == "succeeded")
        if "failed" in (meta["construction"], meta["initialize"], meta["start"]):
            causes["setup"].add("nonfatal_error")
        elif "attempted" in (meta["construction"], meta["initialize"], meta["start"]):
            causes["setup"].add("incomplete_call")
        if meta.get("profile") == "unsupported":
            causes["setup"].add("unsupported_consumer")
    registrations = by_consumer.get("portfolio.registration", [])
    factory_started = {n["strategy"] for n in by_consumer.get("setup.factory_entry", [])
                       if n["meta"]["start"] == "succeeded"}
    registered = {n["strategy"] for n in registrations if n["outcome"] == "returned_ok"}
    _need(registered <= factory_started)
    _need({n["strategy"] for n in by_consumer.get("strategy.primary", [])} <= registered)
    _need({n["strategy"] for n in by_consumer.get("portfolio.optimization_strategy", [])} <= registered)
    _need({n["strategy"] for n in by_consumer.get("execution.batch", [])} <= registered)
    _need({n["strategy"] for n in by_consumer.get("cost.strategy_execution", [])} <= registered)
    _need({n["strategy"] for n in by_consumer.get("strategy.preparation", [])} <= registered)
    disabled = {n["strategy"] for n in by_consumer.get("setup.selection_entry", [])
                if (row := found[n["id"]].get("setup.selection.enabled_live")) is not None
                and row["value"] is False}
    _need(not (disabled & ({n["strategy"] for n in by_consumer.get("setup.factory_entry", [])}
                          | {n["strategy"] for n in registrations})))
    for node in registrations:
        rows, meta = found[node["id"]], node["meta"]
        prefix = "portfolio.registration."
        def observed(name):
            row = rows.get(prefix + name)
            return None if row is None else row["value"]
        initial, stored = observed("initial_allocation"), observed("stored_allocation")
        _need(stored is None or (initial is not None and initial == stored))
        minimum, maximum = observed("min_allocation"), observed("max_allocation")
        _need(maximum is None or minimum is not None)
        _need(minimum is None or initial is None or initial >= minimum or maximum is None)
        total = observed("total_allocation")
        if total is not None and "total_within_limit" in meta:
            _need(meta["total_within_limit"] == (not (total > 1.0)))
        for gate in ("optimization", "risk"):
            requested, rhs, stored_gate = (observed("requested_" + gate),
                                            observed("portfolio_" + gate),
                                            observed("stored_" + gate))
            _need(requested is not False or rhs is None)
            _need(rhs is None or requested is True)
            _need(stored_gate is None or requested is not None)
            _need(stored_gate is None or requested is not True or rhs is not None)
            _need(stored_gate is None or stored_gate == bool(requested and rhs))
    for node in by_consumer.get("execution.history_update", []):
        meta = node["meta"]
        kids = children[node["id"]]
        if not meta["cost_model_reached"]:
            _need(not kids and "previous_close_source" not in meta)
        for kid in kids:
            _need(kid["reads"])
    for node in by_consumer.get("strategy.preparation", []) + by_consumer.get("strategy.primary", []):
        scopes = [kid["consumer"] for kid in children[node["id"]]]
        profile = node["meta"]["profile"]
        _need(profile != "unsupported" or not scopes)
        _need(profile != "base" or set(scopes) <= {"strategy.base_risk", "strategy.position_limits"})
        if profile == "unsupported":
            causes[_stage_for(node, nodes)].add("unsupported_consumer")
        for kid in children[node["id"]]:
            if kid["consumer"] in ("strategy.base_risk", "strategy.position_limits"):
                _need(kid["meta"]["supported"] or not kid["reads"])
            else:
                _need(kid["reads"])
    for node in by_consumer.get("portfolio.primary", []):
        if node["meta"].get("skip_execution_generation"):
            _need(not any(kid["consumer"] in ("cost.strategy_execution", "cost.compatibility_execution")
                          for kid in children[node["id"]]))
    for node in by_consumer.get("portfolio.pass", []):
        rows = found[node["id"]]
        for gate, consumer in (("portfolio.pass.use_optimization", "portfolio.optimization"),
                               ("portfolio.pass.use_risk_management", "portfolio.risk")):
            kids = [kid for kid in children[node["id"]] if kid["consumer"] == consumer]
            _need(not kids or (gate in rows and rows[gate]["value"] is True))
            _need(gate not in rows or rows[gate]["value"] is not False or not kids)
    for node in by_consumer.get("portfolio.optimization", []):
        skip = node["meta"]["skip"]
        kids = children[node["id"]]
        if skip != "none":
            _need(not any(kid["consumer"] == "optimizer.primary" for kid in kids))
        for kid in kids:
            if kid["consumer"] in ("portfolio.symbol_collection", "portfolio.numeric_aggregation",
                                   "portfolio.redistribution"):
                for part in children[kid["id"]]:
                    rows = found[part["id"]]
                    enabled = rows.get("portfolio.optimization.strategy.enabled")
                    _need(enabled is None or enabled["value"] is True or
                          "portfolio.optimization.strategy.allocation" not in rows)
    for node in by_consumer.get("portfolio.risk", []):
        meta = node["meta"]
        kids = children[node["id"]]
        _need(meta["skip"] == "none" or not kids)
        _need(meta.get("manager_source") != "absent" or not kids)
        if kids:
            _need(meta.get("manager_source") in ("internal", "external"))
            if meta["manager_source"] == "external":
                for row in kids[0]["reads"]:
                    _need(row["origin"] == "runtime_effective")
    for node in by_consumer.get("optimizer.primary", []):
        if node["meta"]["buffer_branch"] == "failed":
            causes["primary"].add("nonfatal_error")
    for node in by_consumer.get("execution.batch", []):
        state, outcome = node["meta"]["state"], node["outcome"]
        _need((state == "returned" and outcome == "returned_ok") or
              (state in ("rejected_stream", "invalid_argument") and outcome == "returned_error") or
              (state == "entered" and outcome in ("incomplete", "threw")))
        attempts = [kid for kid in children[node["id"]] if kid["consumer"] == "execution.attempt"]
        _need(all(kid["index"] == index for index, kid in enumerate(attempts)))
        seen_removed = False
        for attempt in attempts:
            if attempt["meta"]["branch"] == "removed_position":
                seen_removed = True
            else:
                _need(not seen_removed)
        _need(all(kid["outcome"] == "returned_ok" for kid in attempts[:-1]))
        _need(state != "returned" or all(kid["outcome"] == "returned_ok" for kid in attempts))
        _need(state == "returned" or not attempts or outcome in ("threw", "incomplete"))
    for node in by_consumer.get("execution.attempt", []):
        meta, outcome = node["meta"], node["outcome"]
        _need(meta["branch"] != "current_position" or meta["price_source"] != "previous_average_price")
        _need(meta["branch"] != "removed_position" or meta["price_source"] != "current_average_price")
        _need(not meta["returned"] or (meta["state"] == "returned" and outcome == "returned_ok"))
        _need(meta["state"] != "returned" or meta["returned"] or outcome == "incomplete")
        _need(meta["state"] not in ("entered", "cost_call_reached") or
              outcome in ("incomplete", "threw"))
        _need(meta["state"] not in ("rejected_stream", "rejected_id") or
              (outcome == "threw" and not children[node["id"]]))
        _need(meta["state"] in ("cost_call_reached", "returned") or not children[node["id"]])
        for kid in children[node["id"]]:
            _need(bool(kid["reads"] or kid["meta"]))
    for node in by_consumer.get("runner.pnl_finalization", []):
        row = found[node["id"]].get("runner.pnl_finalization.strategy_allocation")
        if row:
            _need(node["meta"].get("allocation_lookup") in ("hit", "fallback"))
            _need(row["origin"] == ("selected_allocation" if node["meta"]["allocation_lookup"] == "hit" else "code_default"))
    benchmark = only("runner.benchmark")
    if benchmark:
        mode = found[benchmark["id"]].get("runner.benchmark.mode")
        branch = benchmark["meta"]["branch"]
        _need(mode is None or mode["value"] != "deferred" or branch == "not_reached")
        _need(mode is None or mode["value"] != "live" or branch != "not_reached")
        if branch == "failed":
            causes["control_flow"].add("nonfatal_error")
        elif branch == "attempted":
            causes["control_flow"].add("incomplete_call")
    decision = only("runner.non_trading_day")
    skipped = bool(decision and decision["meta"]["skip_strategy_processing"])
    for stage in ("preparation", "primary"):
        coverage = value["coverage"][stage]
        _need((coverage["status"] == "skipped") == skipped)
        if skipped:
            _need(not stage_nodes[stage])
    for stage in _STAGES:
        coverage = value["coverage"][stage]
        if coverage["status"] == "unavailable":
            _need(not stage_nodes[stage])
        if coverage["status"] == "complete":
            _need(not causes[stage])
    if value["coverage"]["setup"]["status"] == "complete":
        _need(selector is not None and factory is not None and
              selector["outcome"] == factory["outcome"] == "returned_ok")
        successful_factory = {n["strategy"] for n in by_consumer.get("setup.factory_entry", [])
                              if n["meta"]["start"] == "succeeded"}
        successful_registration = {n["strategy"] for n in registrations if n["outcome"] == "returned_ok"}
        _need(successful_factory == successful_registration)
    if value["coverage"]["market_input"]["status"] == "complete":
        window, fetch = only("runner.market_window"), only("runner.market_fetch")
        _need(window is not None and "runner.market_input.historical_days" in found[window["id"]]
              and fetch is not None and fetch["outcome"] == "returned_ok")
    if value["coverage"]["preparation"]["status"] == "complete":
        prep = only("strategy.preparation")
        _need(prep is not None and prep["outcome"] == "returned_ok")
    if value["coverage"]["primary"]["status"] == "complete":
        primary = only("portfolio.primary")
        _need(primary is not None and primary["outcome"] == "returned_ok")
        successful_registration = {n["strategy"] for n in registrations if n["outcome"] == "returned_ok"}
        calls = by_consumer.get("strategy.primary", [])
        _need(all(n["outcome"] == "returned_ok" for n in calls))
        _need({n["strategy"] for n in calls} == successful_registration)
    if value["coverage"]["execution"]["status"] == "complete":
        registered = {n["strategy"] for n in registrations if n["outcome"] == "returned_ok"}
        batches = by_consumer.get("execution.batch", [])
        _need({n["strategy"] for n in batches} == registered)
        _need(all(n["outcome"] == "returned_ok" for n in batches))
    if value["coverage"]["diagnostics"]["status"] == "complete":
        risk = only("risk.diagnostics")
        _need(risk is not None and risk["outcome"] == "returned_ok")
    if value["coverage"]["control_flow"]["status"] == "complete":
        _need(decision is not None and benchmark is not None and
              "runner.benchmark.mode" in found[benchmark["id"]])


def _validate(value):
    _preflight(value)
    _need(_integer(value["version"], 2, 2))
    status, reason = value["status"], value["reason"]
    _need(type(status) is str and status in CATALOG["global_statuses"])
    _need(type(reason) is str and reason in CATALOG["global_statuses"][status])
    coverage = value["coverage"]
    for stage in _STAGES:
        row = coverage[stage]
        _keys(row, ("status", "reason"))
        _need(type(row["status"]) is str and row["status"] in CATALOG["statuses"])
        _need(type(row["reason"]) is str and row["reason"] in CATALOG["statuses"][row["status"]])
        _need(row["status"] != "skipped" or stage in ("preparation", "primary"))
    nodes = value["nodes"]
    if status == "unavailable":
        _need(not nodes and all(row == {"status": "unavailable", "reason": reason}
                                for row in coverage.values()))
        return value
    _need(all(not (row["status"] == "unavailable" and row["reason"] not in
                   ("instrumentation_missing", "unsupported_consumer"))
              for row in coverage.values()))
    children = {index: [] for index in range(len(nodes))}
    stage_nodes = {stage: [] for stage in _STAGES}
    causes = {stage: set() for stage in _STAGES}
    found = {}
    strategies, symbols, seen_nodes, singleton_seen = set(), set(), set(), set()
    collection_counts = {}
    pairs = [0]
    for index, node in enumerate(nodes):
        _keys(node, ("id", "parent", "kind", "consumer", "reads", "meta"),
              ("outcome", "strategy", "symbol", "index"))
        consumer = node["consumer"]
        _need(type(consumer) is str and consumer in _CONSUMERS)
        spec = _CONSUMERS[consumer]
        _need(_integer(node["id"], index, index) and node["kind"] == spec["kind"]
              and type(node["kind"]) is str)
        parent = node["parent"]
        if parent is None:
            _need("ROOT" in spec["parents"])
            chain_depth = 1
        else:
            _need(_integer(parent, 0, index - 1)
                  and nodes[int(parent)]["consumer"] in spec["parents"])
            parent = int(parent)
            children[parent].append(node)
            chain_depth = 1
            cursor = parent
            while cursor is not None:
                chain_depth += 1
                following = nodes[int(cursor)]["parent"]
                cursor = int(following) if following is not None else None
        _need(chain_depth <= _LIMIT["chain_depth"])
        if spec["kind"] == "call":
            _need("outcome" in node and type(node["outcome"]) is str
                  and node["outcome"] in ("returned_ok", "returned_error", "threw", "incomplete"))
        else:
            _need("outcome" not in node)
        for dimension in ("strategy", "symbol", "index"):
            _need((dimension in node) == (dimension in spec["dimensions"]))
            if dimension == "strategy":
                if dimension in node:
                    _identity(node[dimension], _STRATEGY)
                    strategies.add(node[dimension])
                    _need(len(strategies) <= _LIMIT["strategies"])
            elif dimension == "symbol":
                if dimension in node:
                    _identity(node[dimension], _SYMBOL)
                    symbols.add(node[dimension])
                    _need(len(symbols) <= _LIMIT["symbols"])
            elif dimension in node:
                _need(_integer(node[dimension], 0, 4095))
        if parent is not None:
            ancestor = nodes[parent]
            while ancestor is not None:
                for dimension in ("strategy", "symbol"):
                    _need(dimension not in node or dimension not in ancestor)
                if "index" in node and "index" in ancestor:
                    _need((consumer == "portfolio.estimate" and ancestor["consumer"] == "portfolio.pass")
                          or (consumer == "execution.attempt" and ancestor["consumer"] == "portfolio.pass"))
                ancestor = nodes[int(ancestor["parent"])] if ancestor["parent"] is not None else None
        stage = _stage_for(node, nodes)
        stage_nodes[stage].append(node)
        if consumer in _SINGLETON_ROOTS:
            _need(consumer not in singleton_seen)
            singleton_seen.add(consumer)
        key = (consumer, parent, node.get("strategy"), node.get("symbol"), node.get("index"))
        if consumer in _UNIQUE_PER_PARENT or consumer in (
                "setup.selection_entry", "setup.factory_entry", "portfolio.registration",
                "strategy.primary", "portfolio.pass", "portfolio.optimization_strategy",
                "portfolio.estimate", "execution.batch", "runner.pnl_finalization"):
            if consumer != "portfolio.registration" or node["outcome"] == "returned_ok":
                _need(key not in seen_nodes)
                seen_nodes.add(key)
        collection = (consumer, parent)
        collection_counts[collection] = collection_counts.get(collection, 0) + 1
        _need(collection_counts[collection] <= _LIMIT["collection_entries"])
        if consumer == "portfolio.pass":
            _need(node["index"] < _LIMIT["passes"])
        _node_meta(node)
        found[index] = _read_rows(node, pairs, symbols)
        if spec["kind"] == "call":
            cause = {"returned_error": "nonfatal_error", "threw": "nonfatal_error",
                     "incomplete": "incomplete_call"}.get(node["outcome"])
            if cause:
                causes[stage].add(cause)
    passes = [n["index"] for n in nodes if n["consumer"] == "portfolio.pass"]
    _need(passes == list(range(len(passes))))
    for node in nodes:
        if node["consumer"] == "portfolio.optimization":
            estimates = [kid["index"] for kid in children[node["id"]]
                         if kid["consumer"] == "portfolio.estimate"]
            _need(estimates == list(range(len(estimates))))
    _relations(value, found, children, stage_nodes, causes)
    for stage in _STAGES:
        row = coverage[stage]
        if row["status"] == "partial":
            observed = min(causes[stage], key=_PRIORITY.index) if causes[stage] else None
            _need(observed is None or _PRIORITY.index(row["reason"]) <= _PRIORITY.index(observed))
        elif row["status"] == "complete":
            _need(not causes[stage])
        elif row["status"] == "skipped":
            _need(not stage_nodes[stage])
    if status == "complete":
        _need(all(row["status"] in ("complete", "skipped") for row in coverage.values()))
    else:
        _need(any(n["kind"] == "call" for n in nodes))
        _need(any(row["status"] in ("partial", "unavailable") for row in coverage.values()))
        reported = [row["reason"] for row in coverage.values()
                    if row["status"] in ("partial", "unavailable")]
        _need(reason == min(reported, key=_PRIORITY.index))
    # This child can never fit inside a 2 MiB combined envelope if it alone
    # exceeds that size. A smaller child is not proof the combined one fits.
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    _need(len(encoded.encode("utf-8")) <= _LIMIT["bytes"])
    return value


def validate_consumption_v2(value: object) -> dict:
    """Return the unchanged validated consumption child."""
    try:
        return _validate(value)
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        raise ConsumptionProtocolError() from None
