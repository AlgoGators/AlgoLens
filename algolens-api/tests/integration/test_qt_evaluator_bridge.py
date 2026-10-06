"""Actual isolated Release bundle transport; A5 tests add evidence admission."""

from algolens.infrastructure.portfolio.qt_evaluator_process import QtEvaluatorProcess
from tests.qt_native_evaluator import native_evaluator_configuration, native_evaluator_requests


def test_real_compiled_evaluator_through_isolated_bounded_process():
    request = native_evaluator_requests()["selected_book"]
    # A Release executable depends on libtrade_ngin.so via $ORIGIN. Sealing
    # only that executable into a memfd loses its runtime closure; the staged
    # bundle seals and pins the loader, engine and dependency bytes as well.
    process = QtEvaluatorProcess(**native_evaluator_configuration())
    response = process.run(request)
    assert response["completeness"] == "complete"
    assert [row["quantity_exact"] for row in response["evaluated_book"]] == ["5", "1"]
    assert response["evaluated_book_digest"] == "170528e9e3a72c56773ceeba05ed1762eb4a35ff1a35d0af8633e35039ee99df"
    assert response["selected_costs"]["total_exact"] == "0.02"
    assert response["selected_risk"]["evaluated_book_digest"] == response["evaluated_book_digest"]
    assert response["selected_costs"]["evaluated_book_digest"] == response["evaluated_book_digest"]
