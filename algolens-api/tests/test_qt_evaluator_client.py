"""Semantic admission for compiled evaluator evidence, separate from transport."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.portfolio.qt_evaluator_client import QtEvaluatorClient


FIXTURE = Path(__file__).with_name("fixtures") / "qt-eval-v1.json"
RISK_METRICS = (
    "portfolio_var", "jump_risk", "correlation_risk", "gross_leverage", "net_leverage",
    "max_portfolio_risk", "max_jump_risk", "max_leverage_risk", "portfolio_multiplier",
    "jump_multiplier", "correlation_multiplier", "leverage_multiplier", "portfolio_var_gate", "recommended_scale",
)


def request():
    return json.loads(FIXTURE.read_text())["selected_book"]


def response(req):
    digest = "170528e9e3a72c56773ceeba05ed1762eb4a35ff1a35d0af8633e35039ee99df"
    rows = []
    costs = []
    for slot, quantity, cost in zip(req["context"]["slots"], req["proposal"]["quantities"], req["component_cost_inputs"]):
        rows.append({"key": slot["key"], "instrument": slot["instrument"], "editable": True,
                     "unfilled": False, "quantity_exact": quantity["quantity_exact"],
                     "previous_quantity_exact": slot["previous"]["quantity_exact"],
                     "average_price_exact": slot["previous"]["average_price_exact"]})
        costs.append({"key": slot["key"], "prior_quantity_exact": slot["previous"]["quantity_exact"],
                      "selected_quantity_exact": quantity["quantity_exact"], "cash_cost_exact": "0.01",
                      "source_id": cost["source_id"]})
    return {
        **{name: req[name] for name in ("schema", "operation", "evaluator_build", "context_fingerprint")},
        "completeness": "complete", "evaluated_book_digest": digest, "evaluated_book": rows,
        "optimizer": {"status": "disabled", "evaluated_book_digest": None, "aggregate_bindings": [],
                      "current_weights": [], "target_weights": [], "solved_weights": [], "trace": None,
                      "actual_iterations": None,
                      "cost_penalty_diagnostic": None, "tracking_error_diagnostic": None,
                      "config_source_id": None, "diagnostics": []},
        "selected_risk": {"status": "evaluated", "evaluated_book_digest": digest, "passed": True,
                          "breaches": [], "metrics": [{"code": code, "value_diagnostic": "0",
                          "unit": "ratio", "source_id": req["risk_inputs"]["market_snapshot_id"]}
                          for code in RISK_METRICS], "config_source_id": req["risk_config_source_id"],
                          "market_snapshot_id": req["risk_inputs"]["market_snapshot_id"], "diagnostics": []},
        "selected_costs": {"status": "evaluated", "evaluated_book_digest": digest, "by_component": costs,
                           "total_exact": "0.02", "currency": "USD", "diagnostics": []},
        "diagnostics": [],
    }


class Process:
    expected_build = "local-qt-controlled"

    def __init__(self, value):
        self.value = value

    def run(self, req):
        return deepcopy(self.value)


def test_complete_evidence_is_bound_to_exact_selected_split_and_sources():
    req = request()
    admitted = QtEvaluatorClient(Process(response(req))).evaluate(req)
    assert admitted.available
    assert admitted.book_digest == response(req)["evaluated_book_digest"]
    assert admitted.evidence["selected_costs"]["total_exact"] == "0.02"
    assert "currency" not in admitted.evidence["selected_costs"]


@pytest.mark.parametrize("mutation", ["split", "digest", "cost_missing", "cost_prior", "cost_source", "risk_source", "metric_missing", "extra"])
def test_mismatched_or_incomplete_claimed_complete_evidence_is_rejected(mutation):
    req = request()
    value = response(req)
    if mutation == "split":
        value["evaluated_book"][0]["quantity_exact"] = "4"
        value["evaluated_book"][1]["quantity_exact"] = "2"
    elif mutation == "digest": value["evaluated_book_digest"] = "0" * 64
    elif mutation == "cost_missing": value["selected_costs"]["by_component"].pop()
    elif mutation == "cost_prior": value["selected_costs"]["by_component"][0]["prior_quantity_exact"] = "3"
    elif mutation == "cost_source": value["selected_costs"]["by_component"][0]["source_id"] = "other"
    elif mutation == "risk_source": value["selected_risk"]["market_snapshot_id"] = "other"
    elif mutation == "metric_missing": value["selected_risk"]["metrics"].pop()
    else: value["claimed_pass"] = True
    with pytest.raises(QtWorkflowError):
        QtEvaluatorClient(Process(value)).evaluate(req)


def test_risk_breach_requires_exact_versioned_policy_code():
    req = request()
    value = response(req)
    value["selected_risk"]["passed"] = False
    value["selected_risk"]["breaches"] = [{"code": "gross_leverage", "actual_diagnostic": "5", "limit_diagnostic": "4"}]
    denied = QtEvaluatorClient(Process(value)).evaluate(req)
    assert not denied.available and "unpermitted_risk_breach" in denied.unavailable_reasons
    allowed = QtEvaluatorClient(Process(value), allowed_override_codes=("gross_leverage",)).evaluate(req)
    assert allowed.available and allowed.requires_override


@pytest.mark.parametrize("mutation", ["risk_extra", "valuation_extra", "rule_extra", "bad_increment", "bad_prior_time", "bad_mark_time", "bad_cost", "bad_config", "bad_close"])
def test_governed_request_is_closed_and_has_no_implicit_financial_inputs(mutation):
    req = request()
    if mutation == "risk_extra": req["risk_inputs"]["fallback_mark"] = "100"
    elif mutation == "valuation_extra": req["risk_inputs"]["valuations"][0]["fallback"] = True
    elif mutation == "rule_extra": req["quantity_rules"][0]["unknown"] = True
    elif mutation == "bad_increment": req["quantity_rules"][0]["increment_exact"] = "0"
    elif mutation == "bad_prior_time": req["context"]["slots"][0]["previous"]["last_update"] = "unknown"
    elif mutation == "bad_mark_time": req["risk_inputs"]["valuations"][0]["mark_as_of"] = "2026-09-25T12:00:01Z"
    elif mutation == "bad_cost": req["component_cost_inputs"][0]["cash_cost_per_increment_exact"] = "-1"
    elif mutation == "bad_config": req["risk_config"]["capital_exact"] = "0"
    else: req["risk_inputs"]["closes"][0]["close"] = "0"
    with pytest.raises(QtWorkflowError):
        QtEvaluatorClient(Process({})).validate_request(req)


def test_claimed_cost_must_equal_approved_model_for_actual_component_delta():
    req = request()
    value = response(req)
    value["selected_costs"]["by_component"][0]["cash_cost_exact"] = "99"
    value["selected_costs"]["total_exact"] = "99.01"
    with pytest.raises(QtWorkflowError):
        QtEvaluatorClient(Process(value)).evaluate(req)
