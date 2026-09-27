"""Performed optimizer iterations survive the actual pinned native boundary."""
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path

import pytest

from algolens.infrastructure.portfolio.qt_evaluator_client import QtEvaluatorClient
from algolens.infrastructure.portfolio.qt_evaluator_process import QtEvaluatorProcess
from tests.qt_native_evaluator import native_evaluator_configuration

FIXTURE = Path(__file__).resolve().parents[4] / "trade-ngin-qt/tests/contracts/qt-eval-v1.json"


@pytest.mark.parametrize("maximum,threshold", [(50, "1"), (1, "1e-12")])
def test_real_executed_iteration_count_is_neither_limit_nor_terminal_increment(maximum, threshold):
    req = json.loads(FIXTURE.read_text())["draft_diagnostic"]
    stamps = [(date(2026, 9, 5) + timedelta(days=index)).isoformat() + "T12:00:00Z" for index in range(21)]
    closes = [dict(instrument=dict(instrument_type="EQUITY", symbol="SYN"), timestamp=stamp,
                   close="100" if index % 2 == 0 else "110") for index, stamp in enumerate(stamps)]
    for inputs in (req["risk_inputs"], req["optimizer_inputs"]):
        inputs.update(expected_observation_times=stamps, closes=deepcopy(closes))
    req["optimizer_config"].update(max_iterations=maximum, convergence_threshold=threshold,
                                   cost_penalty_scalar="0", use_buffering=False)
    process = QtEvaluatorProcess(**native_evaluator_configuration())
    raw = process.run(req)
    assert raw["optimizer"]["status"] == "evaluated"
    # Threshold 1 prevents improvement in the first pass; maximum 50 is unused.
    # The one-pass cap allows improvement but never counts its terminal check.
    assert raw["optimizer"]["actual_iterations"] == 1
    admitted = QtEvaluatorClient(process).evaluate(req)
    # This alternating synthetic history intentionally breaches the risk limit.
    # Successful decoding retains optimizer evidence without admitting the book.
    assert not admitted.available
    assert admitted.unavailable_reasons == ("unpermitted_risk_breach",)
    assert not admitted.requires_override
    risk = admitted.evidence["selected_risk"]
    assert risk["status"] == "evaluated" and risk["passed"] is False
    assert risk["breaches"] and risk["breaches"] == raw["selected_risk"]["breaches"]
    assert admitted.evidence["optimizer"]["trace"][2] == "actual_iterations=1"


def test_real_disabled_optimizer_keeps_iterations_absent():
    req = json.loads(FIXTURE.read_text())["selected_book"]
    process = QtEvaluatorProcess(**native_evaluator_configuration())
    assert process.run(req)["optimizer"]["actual_iterations"] is None
    assert QtEvaluatorClient(process).evaluate(req).evidence["optimizer"]["trace"] == []
