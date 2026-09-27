"""Admit exact evaluator evidence after the pinned process transport."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import re

from algolens.domain.portfolio.position_decimal import canonical_position_decimal8
from algolens.domain.portfolio.qt_canonical import canonical_qt_bytes, qt_book_digest_v1
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.domain.portfolio.qt_workflow_models import QtKey
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from algolens.infrastructure.portfolio.qt_evaluator_process import QtEvaluatorUnavailable


_METRICS = frozenset({"portfolio_var", "jump_risk", "correlation_risk", "gross_leverage", "net_leverage",
    "max_portfolio_risk", "max_jump_risk", "max_leverage_risk", "portfolio_multiplier",
    "jump_multiplier", "correlation_multiplier", "leverage_multiplier", "portfolio_var_gate", "recommended_scale"})
_IDENTITY = ("schema", "operation", "evaluator_build", "context_fingerprint")


def _shape(value, fields):
    if type(value) is not dict or set(value) != set(fields.split()):
        raise ValueError("shape")
    return value


def _text(value):
    if type(value) is not str or not value or len(value) > 4096:
        raise ValueError("text")
    return value


def _texts(value):
    if type(value) is not list or len(value) > 4096 or any(type(item) is not str or len(item) > 4096 for item in value):
        raise ValueError("text_array")
    return value


def _exact(value):
    if type(value) is not str or canonical_position_decimal8(value) != value:
        raise ValueError("exact")
    return value


def _diagnostic(value):
    if type(value) is not str or len(value) > 128 or not Decimal(value).is_finite():
        raise ValueError("diagnostic")
    return value


def _timestamp(value):
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value):
        raise ValueError("timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _positive(value, *, exact=False, zero=False):
    number = Decimal(_exact(value) if exact else _diagnostic(value))
    if number < 0 or (number == 0 and not zero):
        raise ValueError("positive")
    return number


def _key(value):
    return QtKey.from_wire(value)


def _instrument(value):
    _shape(value, "instrument_type symbol")
    if value["instrument_type"] not in {"EQUITY", "FUTURE"}:
        raise ValueError("instrument")
    return value["instrument_type"], _text(value["symbol"])


def _unique(rows, identity):
    if type(rows) is not list or len(rows) > 4096:
        raise ValueError("array")
    result = {}
    for row in rows:
        key = identity(row)
        if key in result:
            raise ValueError("duplicate")
        result[key] = row
    return result


@dataclass(frozen=True)
class QtEvaluation:
    book_digest: str
    available: bool
    requires_override: bool
    unavailable_reasons: tuple[str, ...]
    _evidence_bytes: bytes

    @property
    def evidence(self):
        return json.loads(self._evidence_bytes)


class QtEvaluatorClient:
    def __init__(self, process, *, allowed_override_codes=()):
        self.process = process
        self.allowed_override_codes = frozenset(allowed_override_codes)
        if any(type(code) is not str or not code for code in self.allowed_override_codes):
            raise ValueError("invalid_override_codes")

    def validate_request(self, request) -> None:
        try:
            self._request(request)
        except (ValueError, TypeError, KeyError, InvalidOperation, OverflowError, QtWorkflowError):
            raise QtWorkflowError("preview_unavailable", "Governed evaluator inputs do not cover the frozen book") from None

    def _request(self, value):
        req = json.loads(canonical_qt_input_bytes(value))
        operation = req["operation"]
        fields = "schema operation evaluator_build context_fingerprint risk_config_source_id context proposal risk_inputs risk_config quantity_rules component_cost_inputs"
        if operation == "draft_diagnostic":
            fields += " optimizer_policy"
            policy = _shape(req["optimizer_policy"], "enabled config_source_id")
            if type(policy["enabled"]) is not bool:
                raise ValueError("policy")
            _text(policy["config_source_id"])
            if policy["enabled"]:
                fields += " optimizer_inputs optimizer_config"
        elif operation != "selected_book":
            raise ValueError("operation")
        _shape(req, fields)
        empty_owner = req["schema"] == "qt-eval-empty-owner/v2"
        if req["schema"] not in {"qt-eval/v1", "qt-eval-empty-owner/v2"} or req["evaluator_build"] != self.process.expected_build:
            raise ValueError("identity")
        digest = req["context_fingerprint"]
        if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("fingerprint")
        context = _shape(req["context"], "portfolio_id date portfolio_type revision slots")
        if context["portfolio_type"] != "qt_proposal":
            raise ValueError("stream")
        _text(context["revision"])
        slots = _unique(context["slots"], lambda row: _key(row["key"]))
        if empty_owner and (slots or (operation == "draft_diagnostic" and policy["enabled"])):
            raise ValueError("empty_owner_scope")
        for key, slot in slots.items():
            _shape(slot, "key instrument editable previous")
            if (key.portfolio_id != context["portfolio_id"] or key.date != context["date"]
                    or key.portfolio_type != context["portfolio_type"] or type(slot["editable"]) is not bool
                    or _instrument(slot["instrument"])[1] != key.symbol):
                raise ValueError("slot")
            prior = slot["previous"]
            if prior is None:
                if not slot["editable"]:
                    raise ValueError("immutable_prior")
            else:
                _shape(prior, "symbol quantity_exact average_price_exact unrealized_pnl_exact realized_pnl_exact last_update")
                if prior["symbol"] != key.symbol:
                    raise ValueError("prior")
                for name in ("quantity_exact", "average_price_exact", "unrealized_pnl_exact", "realized_pnl_exact"):
                    _exact(prior[name])
                _timestamp(prior["last_update"])
        expected = {"expected_portfolio_id": context["portfolio_id"], "expected_date": context["date"],
                    "expected_portfolio_type": context["portfolio_type"], "expected_revision": context["revision"]}
        proposal = _shape(req["proposal"], "expected_portfolio_id expected_date expected_portfolio_type expected_revision quantities")
        if any(proposal[name] != item for name, item in expected.items()):
            raise ValueError("proposal_context")
        quantities = _unique(proposal["quantities"], lambda row: _key(row["key"]))
        if set(quantities) != {key for key, slot in slots.items() if slot["editable"]}:
            raise ValueError("selection_scope")
        for row in quantities.values():
            _shape(row, "key quantity_exact")
            _exact(row["quantity_exact"])
        costs = _unique(req["component_cost_inputs"], lambda row: _key(row["key"]))
        if set(costs) != set(quantities):
            raise ValueError("cost_scope")
        for key, row in costs.items():
            _shape(row, "key instrument calculation_increment_exact cash_cost_per_increment_exact approved_model_id source_id currency")
            if _instrument(row["instrument"]) != _instrument(slots[key]["instrument"]):
                raise ValueError("cost_instrument")
            for name in ("calculation_increment_exact", "cash_cost_per_increment_exact"):
                _positive(row[name], exact=True, zero=name == "cash_cost_per_increment_exact")
            for name in ("approved_model_id", "source_id", "currency"):
                _text(row[name])
            if row["approved_model_id"] != "linear-cash-per-increment-v1":
                raise ValueError("cost_model")
        instruments = {_instrument(slot["instrument"]) for slot in slots.values()}
        rules = _unique(req["quantity_rules"], lambda row: _instrument(row["instrument"]))
        if set(rules) != instruments:
            raise ValueError("quantity_scope")
        for rule in rules.values():
            _shape(rule, "instrument increment_exact mode minimum_exact maximum_exact")
            increment = _positive(rule["increment_exact"], exact=True)
            if rule["mode"] != "reject_off_increment": raise ValueError("quantity_mode")
            for name in ("minimum_exact", "maximum_exact"):
                if rule[name] is not None: _exact(rule[name])
            if rule["minimum_exact"] is not None and rule["maximum_exact"] is not None and Decimal(rule["minimum_exact"]) > Decimal(rule["maximum_exact"]):
                raise ValueError("quantity_bounds")
        risk = self._market(req["risk_inputs"], expected, instruments, optimizer=False, empty_owner=empty_owner)
        config = _shape(req["risk_config"], "var_limit jump_risk_limit max_correlation corr_shock_threshold jump_shock_threshold max_gross_leverage max_net_leverage confidence_level lookback_period capital_exact version")
        for name in ("var_limit", "jump_risk_limit", "max_correlation", "corr_shock_threshold", "jump_shock_threshold", "max_gross_leverage", "max_net_leverage", "confidence_level"):
            _positive(config[name], zero=True)
        if not 0 < Decimal(config["confidence_level"]) < 1 or type(config["lookback_period"]) is not int or config["lookback_period"] < 2:
            raise ValueError("risk_config")
        _positive(config["capital_exact"], exact=True)
        _text(config["version"])
        _text(req["risk_config_source_id"])
        _text(risk["market_snapshot_id"])
        _text(risk["capital_currency"])
        if any(row["currency"] != risk["capital_currency"] for row in costs.values()): raise ValueError("cost_currency")
        if operation == "draft_diagnostic" and policy["enabled"]:
            self._market(req["optimizer_inputs"], expected,
                {_instrument(slot["instrument"]) for slot in slots.values() if slot["editable"]}, optimizer=True)
            config = _shape(req["optimizer_config"], "tau capital cost_penalty_scalar asymmetric_risk_buffer max_iterations convergence_threshold use_buffering buffer_size_factor version")
            for name in ("tau", "capital", "convergence_threshold"):
                _positive(config[name])
            for name in ("cost_penalty_scalar", "asymmetric_risk_buffer", "buffer_size_factor"):
                _positive(config[name], zero=True)
            if type(config["max_iterations"]) is not int or config["max_iterations"] < 1 or type(config["use_buffering"]) is not bool:
                raise ValueError("optimizer_config")
            _text(config["version"])
        expected_rows = []
        for key, slot in slots.items():
            quantity = quantities[key]["quantity_exact"] if slot["editable"] else slot["previous"]["quantity_exact"]
            expected_rows.append({"key": key.to_wire(), "quantity_exact": quantity})
        return req, slots, quantities, costs, qt_book_digest_v1(expected_rows, source_portfolio_type="qt_proposal")

    @staticmethod
    def _market(value, expected, instruments, *, optimizer, empty_owner=False):
        collection = "instruments" if optimizer else "valuations"
        market = _shape(value, "expected_portfolio_id expected_date expected_portfolio_type expected_revision market_snapshot_id valuation_time capital_currency expected_observation_times closes " + collection)
        if any(market[name] != item for name, item in expected.items()): raise ValueError("market_context")
        valuation_time = _timestamp(market["valuation_time"])
        _text(market["market_snapshot_id"]); _text(market["capital_currency"])
        valuations = _unique(market[collection], lambda row: _instrument(row["instrument"]))
        if set(valuations) != instruments: raise ValueError("valuation_scope")
        for row in valuations.values():
            fields = "instrument mark_as_of mark price_multiplier quote_currency"
            if optimizer: fields += " calculation_increment_exact cash_cost_per_increment cost_currency increment_source_id cost_source_id"
            _shape(row, fields)
            if _timestamp(row["mark_as_of"]) != valuation_time or row["quote_currency"] != market["capital_currency"]:
                raise ValueError("valuation_source")
            _positive(row["mark"]); _positive(row["price_multiplier"])
            if optimizer:
                _positive(row["calculation_increment_exact"], exact=True)
                _positive(row["cash_cost_per_increment"], zero=True)
                if row["cost_currency"] != market["capital_currency"]: raise ValueError("optimizer_currency")
                _text(row["increment_source_id"]); _text(row["cost_source_id"])
        times = market["expected_observation_times"]
        if type(times) is not list or (not empty_owner and not times) or len(times) > 4096: raise ValueError("history_scope")
        if empty_owner and (instruments or times or market["closes"]): raise ValueError("empty_owner_scope")
        stamps = [_timestamp(stamp) for stamp in times]
        if stamps != sorted(set(stamps)) or (stamps and stamps[-1] > valuation_time): raise ValueError("history_scope")
        closes = _unique(market["closes"], lambda row: (_instrument(row["instrument"]), row["timestamp"]))
        if set(closes) != {(instrument, stamp) for instrument in instruments for stamp in times}: raise ValueError("history_scope")
        for row in closes.values():
            _shape(row, "instrument timestamp close")
            _positive(row["close"])
        return market

    def _optimizer(self, req, stage, digest, slots, quantities):
        _shape(stage, "status evaluated_book_digest aggregate_bindings current_weights target_weights solved_weights trace actual_iterations cost_penalty_diagnostic tracking_error_diagnostic config_source_id diagnostics")
        _texts(stage["diagnostics"])
        public = {name: stage[name] for name in ("status", "evaluated_book_digest", "aggregate_bindings", "current_weights", "target_weights", "solved_weights", "config_source_id", "diagnostics")}
        public.update(trace=[], cost_penalty=None)
        enabled = req["operation"] == "draft_diagnostic" and req["optimizer_policy"]["enabled"]
        if stage["status"] == "evaluated":
            if not enabled or stage["evaluated_book_digest"] != digest or stage["config_source_id"] != req["optimizer_policy"]["config_source_id"]:
                raise ValueError("optimizer_identity")
            iterations = stage["actual_iterations"]
            if (type(iterations) is not int or not 0 <= iterations <= 2147483647
                    or iterations > req["optimizer_config"]["max_iterations"]):
                raise ValueError("optimizer_iterations")
            grouped = {}
            for key, slot in slots.items():
                if not slot["editable"]: continue
                grouped.setdefault(_instrument(slot["instrument"]), []).append(key)
            bindings = _unique(stage["aggregate_bindings"], lambda row: (row["instrument_type"], row["symbol"]))
            if set(bindings) != set(grouped): raise ValueError("optimizer_scope")
            for instrument, members in grouped.items():
                binding = _shape(bindings[instrument], "instrument_type symbol component_keys previous_net_quantity_exact proposed_net_quantity_exact")
                if {_key(item) for item in binding["component_keys"]} != set(members): raise ValueError("optimizer_members")
                prior = sum((Decimal(slots[key]["previous"]["quantity_exact"]) if slots[key]["previous"] else Decimal(0) for key in members), Decimal(0))
                selected = sum((Decimal(quantities[key]["quantity_exact"]) for key in members), Decimal(0))
                if Decimal(_exact(binding["previous_net_quantity_exact"])) != prior or Decimal(_exact(binding["proposed_net_quantity_exact"])) != selected:
                    raise ValueError("optimizer_aggregate")
            for name in ("current_weights", "target_weights", "solved_weights"):
                weights = _unique(stage[name], lambda row: (row["instrument_type"], row["symbol"]))
                if set(weights) != set(grouped): raise ValueError("optimizer_weights")
                for row in weights.values():
                    _shape(row, "instrument_type symbol weight_diagnostic")
                    _diagnostic(row["weight_diagnostic"])
            trace = _shape(stage["trace"], "buffer_branch solver_positions continuous_buffered_positions rounded_buffered_positions")
            if trace["buffer_branch"] not in {"not_reached", "disabled", "returned_prior", "applied", "failed"}: raise ValueError("optimizer_trace")
            for name in ("solver_positions", "continuous_buffered_positions", "rounded_buffered_positions"):
                vector = trace[name]
                if vector is not None:
                    if type(vector) is not list or len(vector) != len(grouped): raise ValueError("optimizer_trace")
                    for item in vector: _diagnostic(item)
            public["cost_penalty"] = _diagnostic(stage["cost_penalty_diagnostic"])
            tracking = _diagnostic(stage["tracking_error_diagnostic"])
            public["trace"] = [canonical_qt_input_bytes(trace).decode("utf-8"), "tracking_error=" + tracking,
                               "actual_iterations=" + str(iterations)]
        else:
            if stage["status"] not in {"disabled", "unavailable", "rejected"} or (stage["status"] == "disabled") == enabled:
                raise ValueError("optimizer_status")
            if any(stage[name] is not None for name in ("evaluated_book_digest", "trace", "actual_iterations", "cost_penalty_diagnostic", "tracking_error_diagnostic", "config_source_id")) or any(stage[name] for name in ("aggregate_bindings", "current_weights", "target_weights", "solved_weights")):
                raise ValueError("optimizer_absence")
        return public

    def evaluate(self, request) -> QtEvaluation:
        try:
            req, slots, quantities, inputs, digest = self._request(request)
            result = self.process.run(req)
            _shape(result, "schema operation evaluator_build context_fingerprint completeness evaluated_book_digest evaluated_book optimizer selected_risk selected_costs diagnostics")
            canonical_qt_input_bytes(result)
            if any(result[name] != req[name] for name in _IDENTITY) or result["evaluated_book_digest"] != digest:
                raise ValueError("response_identity")
            _texts(result["diagnostics"])
            book = _unique(result["evaluated_book"], lambda row: _key(row["key"]))
            if set(book) != set(slots): raise ValueError("book_scope")
            for key, slot in slots.items():
                row = _shape(book[key], "key instrument editable unfilled quantity_exact previous_quantity_exact average_price_exact")
                prior = slot["previous"]
                chosen = quantities[key]["quantity_exact"] if slot["editable"] else prior["quantity_exact"]
                if (row["instrument"] != slot["instrument"] or row["editable"] is not slot["editable"]
                        or row["unfilled"] is not (prior is None) or row["quantity_exact"] != chosen
                        or row["previous_quantity_exact"] != (prior["quantity_exact"] if prior else None)
                        or row["average_price_exact"] != (prior["average_price_exact"] if prior else None)):
                    raise ValueError("book_value")
            risk = result["selected_risk"]
            _shape(risk, "status evaluated_book_digest passed breaches metrics config_source_id market_snapshot_id diagnostics")
            _texts(risk["diagnostics"])
            if risk["status"] == "evaluated":
                if (risk["evaluated_book_digest"] != digest or type(risk["passed"]) is not bool
                        or risk["config_source_id"] != req["risk_config_source_id"]
                        or risk["market_snapshot_id"] != req["risk_inputs"]["market_snapshot_id"]): raise ValueError("risk_identity")
                metrics = _unique(risk["metrics"], lambda row: row["code"])
                if set(metrics) != _METRICS: raise ValueError("risk_metrics")
                for row in metrics.values():
                    _shape(row, "code value_diagnostic unit source_id")
                    if row["unit"] != "ratio" or row["source_id"] != risk["market_snapshot_id"]: raise ValueError("metric_source")
                    _diagnostic(row["value_diagnostic"])
                breaches = _unique(risk["breaches"], lambda row: row["code"])
                for row in breaches.values():
                    _shape(row, "code limit_diagnostic actual_diagnostic")
                    _text(row["code"])
                    _diagnostic(row["limit_diagnostic"]); _diagnostic(row["actual_diagnostic"])
                if risk["passed"] == bool(breaches): raise ValueError("risk_verdict")
            else:
                if risk["status"] not in {"unavailable", "rejected"} or any(risk[name] is not None for name in ("evaluated_book_digest", "passed", "config_source_id", "market_snapshot_id")) or risk["metrics"] or risk["breaches"]:
                    raise ValueError("risk_absence")
                breaches = {}
            costs = result["selected_costs"]
            _shape(costs, "status evaluated_book_digest by_component total_exact currency diagnostics")
            _texts(costs["diagnostics"])
            if costs["status"] == "evaluated":
                if costs["evaluated_book_digest"] != digest or costs["currency"] != req["risk_inputs"]["capital_currency"]: raise ValueError("cost_identity")
                lines = _unique(costs["by_component"], lambda row: _key(row["key"]))
                if set(lines) != set(quantities): raise ValueError("cost_scope")
                total = Decimal(0)
                for key, row in lines.items():
                    _shape(row, "key prior_quantity_exact selected_quantity_exact cash_cost_exact source_id")
                    prior = slots[key]["previous"]
                    if (row["prior_quantity_exact"] != (prior["quantity_exact"] if prior else "0")
                            or row["selected_quantity_exact"] != quantities[key]["quantity_exact"]
                            or row["source_id"] != inputs[key]["source_id"]): raise ValueError("cost_value")
                    amount = Decimal(_exact(row["cash_cost_exact"]))
                    increments = abs(Decimal(quantities[key]["quantity_exact"]) - Decimal(prior["quantity_exact"] if prior else "0")) / Decimal(inputs[key]["calculation_increment_exact"])
                    if increments != increments.to_integral_value() or amount != increments * Decimal(inputs[key]["cash_cost_per_increment_exact"]):
                        raise ValueError("cost_calculation")
                    total += amount
                if total != Decimal(_exact(costs["total_exact"])): raise ValueError("cost_total")
            elif costs["status"] not in {"unavailable", "rejected"} or costs["evaluated_book_digest"] is not None or costs["total_exact"] is not None or costs["currency"] is not None or costs["by_component"]:
                raise ValueError("cost_absence")
            optimizer = self._optimizer(req, result["optimizer"], digest, slots, quantities)
            complete = risk["status"] == costs["status"] == "evaluated" and optimizer["status"] in {"evaluated", "disabled"}
            expected_completeness = "complete" if complete else ("partial" if "evaluated" in {risk["status"], costs["status"]} else "unavailable")
            if result["completeness"] != expected_completeness: raise ValueError("completeness")
            reasons = []
            if risk["status"] != "evaluated": reasons.append("selected_risk_unavailable")
            if costs["status"] != "evaluated": reasons.append("selected_costs_unavailable")
            if optimizer["status"] not in {"evaluated", "disabled"}: reasons.append("optimizer_unavailable")
            if set(breaches) - self.allowed_override_codes: reasons.append("unpermitted_risk_breach")
            evidence = {"optimizer": optimizer, "selected_risk": risk,
                        "selected_costs": {key: value for key, value in costs.items() if key != "currency"}}
            wire = canonical_qt_bytes({"evaluation": evidence})
            evidence_wire = canonical_qt_input_bytes(json.loads(wire)["evaluation"])
            return QtEvaluation(digest, not reasons, bool(breaches) and not reasons, tuple(reasons), evidence_wire)
        except QtEvaluatorUnavailable as error:
            raise QtWorkflowError("preview_unavailable", str(error)) from None
        except (ValueError, TypeError, KeyError, InvalidOperation, OverflowError, QtWorkflowError):
            raise QtWorkflowError("preview_unavailable", "Evaluator evidence is incomplete or does not match the frozen request") from None
