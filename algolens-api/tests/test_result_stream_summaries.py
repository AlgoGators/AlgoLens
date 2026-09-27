"""QT summary availability and incomplete book totals."""
from datetime import date

import pytest

from algolens.adapters.serializers.portfolio import serialize_portfolio_list
from algolens.application.portfolio.use_cases import (
    ListPortfolios, ListStrategies, build_strategy_summary,
)


def _cfg(strategy_id):
    return {
        "id": strategy_id, "name": strategy_id, "strategy_type": strategy_id,
        "portfolio_id": "BOOK", "initial_equity": 100,
    }


def test_strategy_summary_names_qt_result_source_and_date_without_inventing_missing_values():
    cfg = _cfg("known")
    absent = build_strategy_summary(cfg, None)
    assert absent["dataAvailable"] is False
    assert absent["resultSource"] == "qt"
    assert absent["resultDate"] is None
    assert absent["currentValue"] is None

    present = build_strategy_summary(cfg, {
        "date": date(2026, 9, 18), "current_portfolio_value": 120,
        "volatility": 2, "total_annualized_return": 5,
    })
    assert present["dataAvailable"] is True
    assert present["resultSource"] == "qt"
    assert present["resultDate"] == "2026-09-18"
    assert present["currentValue"] == 120


def test_partial_qt_result_keeps_unknown_measurements_null():
    summary = build_strategy_summary(_cfg("known"), {
        "date": date(2026, 9, 18), "current_portfolio_value": None,
        "volatility": None, "total_annualized_return": None,
    })
    assert summary["dataAvailable"] is True
    assert summary["currentValue"] is None
    assert summary["returnPercent"] is None
    assert summary["volatility"] is None
    assert summary["sharpeRatio"] is None


class Registry:
    def list(self, active_only=True):
        return [_cfg("known"), _cfg("unknown")]

    def list_memberships(self):
        return []


class Reader:
    def fetch_summary_row(self, strategy_type, portfolio_id):
        return {"current_portfolio_value": 120, "volatility": 2,
                "total_annualized_return": 5} if strategy_type == "known" else None


def test_lists_retain_unknown_strategy_and_disclose_partial_book_total():
    listed = ListStrategies(Registry(), Reader()).execute()
    assert [s["id"] for s in listed] == ["known", "unknown"]
    assert listed[1]["dataAvailable"] is False

    books = serialize_portfolio_list(ListPortfolios(Registry(), Reader()).execute())
    book = books["portfolios"][0]
    assert book["total_value"] == 120
    assert book["strategies_awaiting_data"] == 1
    assert book["strategies"][1]["current_value"] is None


def test_unrelated_summary_read_failure_propagates():
    class FailingReader:
        def fetch_summary_row(self, strategy_type, portfolio_id):
            raise RuntimeError("synthetic database failure")

    with pytest.raises(RuntimeError, match="synthetic database failure"):
        ListStrategies(Registry(), FailingReader()).execute()
    with pytest.raises(RuntimeError, match="synthetic database failure"):
        ListPortfolios(Registry(), FailingReader()).execute()
