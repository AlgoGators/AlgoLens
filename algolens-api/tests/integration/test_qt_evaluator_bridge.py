"""Actual offline artifact transport; later A5 tests add evidence admission."""
from hashlib import sha256
import json
from pathlib import Path

from algolens.infrastructure.portfolio.qt_evaluator_process import QtEvaluatorProcess
from tests.qt_native_artifacts import require_native_artifact_paths


def test_real_compiled_evaluator_through_isolated_bounded_process():
    paths = require_native_artifact_paths()
    binary = paths.artifact("qt_evaluator")
    assert binary.is_file(), "Build the actual reviewed evaluator before this gate"
    fixture = paths.source_dir / "tests/contracts/qt-eval-v1.json"
    request = json.loads(fixture.read_text())["selected_book"]
    process = QtEvaluatorProcess(binary, sha256(binary.read_bytes()).hexdigest(),
                                 request["evaluator_build"])
    response = process.run(request)
    assert response["completeness"] == "complete"
    assert [row["quantity_exact"] for row in response["evaluated_book"]] == ["5", "1"]
    assert response["evaluated_book_digest"] == "170528e9e3a72c56773ceeba05ed1762eb4a35ff1a35d0af8633e35039ee99df"
    assert response["selected_costs"]["total_exact"] == "0.02"
    assert response["selected_risk"]["evaluated_book_digest"] == response["evaluated_book_digest"]
    assert response["selected_costs"]["evaluated_book_digest"] == response["evaluated_book_digest"]
