"""Actual native iteration evidence is admitted without substituting a limit."""
from copy import deepcopy
import json

import pytest

from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.portfolio.qt_evaluator_client import QtEvaluatorClient
from test_qt_evaluator_client import FIXTURE, Process, request, response


def optimizer_case(iterations=7):
    req = request()
    template = json.loads(FIXTURE.read_text())["draft_diagnostic"]
    req["operation"] = "draft_diagnostic"
    for field in ("optimizer_policy", "optimizer_inputs", "optimizer_config"):
        req[field] = deepcopy(template[field])
    for field in ("portfolio_id", "date", "portfolio_type", "revision"):
        req["optimizer_inputs"]["expected_" + field] = req["context"][field]
    if type(iterations) is int and iterations > req["optimizer_config"]["max_iterations"]:
        req["optimizer_config"]["max_iterations"] = iterations
    value = response(req)
    instrument = req["context"]["slots"][0]["instrument"]
    value["optimizer"] = dict(status="evaluated", evaluated_book_digest=value["evaluated_book_digest"],
        aggregate_bindings=[dict(instrument_type=instrument["instrument_type"], symbol=instrument["symbol"],
            component_keys=[slot["key"] for slot in req["context"]["slots"]],
            previous_net_quantity_exact="6", proposed_net_quantity_exact="6")],
        current_weights=[dict(**instrument, weight_diagnostic="0.0006")],
        target_weights=[dict(**instrument, weight_diagnostic="0.0006")],
        solved_weights=[dict(**instrument, weight_diagnostic="0.00059")],
        trace=dict(buffer_branch="applied", solver_positions=["0.00059"],
            continuous_buffered_positions=["0.0006"], rounded_buffered_positions=["0.0006"]),
        actual_iterations=iterations, cost_penalty_diagnostic="0.01", tracking_error_diagnostic="0.0001",
        config_source_id=req["optimizer_policy"]["config_source_id"], diagnostics=[])
    return req, value


@pytest.mark.parametrize("iterations", [0, 7, 100, 101, 2147483647])
def test_exact_actual_iterations_survive_unchanged_public_trace(iterations):
    req, value = optimizer_case(iterations)
    admitted = QtEvaluatorClient(Process(value)).evaluate(req)
    assert admitted.available
    optimizer = admitted.evidence["optimizer"]
    assert "actual_iterations" not in optimizer
    assert optimizer["trace"][2] == "actual_iterations=" + str(iterations)
    assert json.loads(optimizer["trace"][0])["buffer_branch"] == "applied"
    assert optimizer["trace"][1] == "tracking_error=0.0001"


@pytest.mark.parametrize("iterations", [-1, True, False, 1.5, "7", None, 2147483648])
def test_evaluated_iteration_evidence_must_be_an_actual_bounded_integer(iterations):
    req, value = optimizer_case(iterations)
    with pytest.raises(QtWorkflowError, match="Evaluator evidence is incomplete"):
        QtEvaluatorClient(Process(value)).evaluate(req)


def test_missing_evaluated_iteration_evidence_is_not_replaced_with_maximum():
    req, value = optimizer_case()
    value["optimizer"].pop("actual_iterations")
    with pytest.raises(QtWorkflowError, match="Evaluator evidence is incomplete"):
        QtEvaluatorClient(Process(value)).evaluate(req)


def test_actual_iterations_cannot_exceed_the_admitted_native_loop_limit():
    req, value = optimizer_case(2)
    req["optimizer_config"]["max_iterations"] = 1
    with pytest.raises(QtWorkflowError, match="Evaluator evidence is incomplete"):
        QtEvaluatorClient(Process(value)).evaluate(req)


@pytest.mark.parametrize("status", ["disabled", "unavailable", "rejected"])
def test_inactive_optimizer_does_not_invent_an_iteration_count(status):
    req, value = optimizer_case()
    value["optimizer"] = response(req)["optimizer"]
    value["optimizer"].update(status=status, actual_iterations=None)
    if status == "disabled":
        req = request()
        value = response(req)
        value["optimizer"]["actual_iterations"] = None
    else:
        value["completeness"] = "partial"
    admitted = QtEvaluatorClient(Process(value)).evaluate(req)
    assert admitted.evidence["optimizer"]["trace"] == []


@pytest.mark.parametrize("status", ["disabled", "unavailable", "rejected"])
def test_inactive_optimizer_cannot_claim_a_numeric_iteration_count(status):
    req, value = optimizer_case()
    value["optimizer"] = response(req)["optimizer"]
    value["optimizer"].update(status=status, actual_iterations=0)
    if status == "disabled":
        req = request()
        value = response(req)
        value["optimizer"]["actual_iterations"] = 0
    else:
        value["completeness"] = "partial"
    with pytest.raises(QtWorkflowError):
        QtEvaluatorClient(Process(value)).evaluate(req)
