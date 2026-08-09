from datetime import datetime

import pytest

from algolens.application.portfolio.ports import PortfolioDetailRows
from algolens.application.portfolio.use_cases import (
    GetStrategyDetail,
    ListStrategies,
    StrategyDataNotFound,
    StrategyNotFound,
)


CFG = {
    "id": "trendfollowing",
    "strategy_type": "LIVE_TREND_FOLLOWING",
    "portfolio_id": "CONSERVATIVE_PORTFOLIO",
    "name": "Trend Following",
    "description": "Systematic trend following across multiple futures contracts",
    "initial_equity": 500000.0,
    "managers": ["AlgoLens System"],
}


class FakeRegistry:
    def __init__(self, cfg=CFG):
        self.cfg = cfg

    def list(self, active_only=True):
        return [self.cfg] if self.cfg else []

    def get(self, strategy_id):
        if self.cfg and self.cfg["id"] == strategy_id:
            return self.cfg
        return None


class FakeReader:
    def __init__(self, detail_rows=None, summary_row=None):
        self.detail_rows = detail_rows
        self.summary_row = summary_row

    def fetch_summary_row(self, strategy_type, portfolio_id):
        return self.summary_row

    def fetch_detail_rows(self, strategy_type, portfolio_id):
        return self.detail_rows


def latest_row():
    return {
        "date": datetime(2026, 1, 2),
        "current_portfolio_value": 510000,
        "volatility": 10,
        "total_annualized_return": 20,
        "daily_return": None,
        "gross_leverage": None,
        "net_leverage": None,
        "portfolio_leverage": None,
        "margin_posted": None,
        "equity_to_margin_ratio": None,
        "margin_cushion": None,
        "gross_notional": None,
        "total_unrealized_pnl": None,
        "total_realized_pnl": None,
        "total_transaction_costs": None,
        "cash_available": None,
    }


def detail_rows():
    return PortfolioDetailRows(
        latest=latest_row(),
        equity_curve=[
            {"timestamp": datetime(2026, 1, 1), "equity": 500000},
            {"timestamp": datetime(2026, 1, 2), "equity": 510000},
        ],
        equity_by_stream={
            "qt": [
                {"timestamp": datetime(2026, 1, 1), "equity": 500000},
                {"timestamp": datetime(2026, 1, 2), "equity": 510000},
            ]
        },
        positions=[],
        executions=[],
        yesterday_positions=[],
    )


def test_get_strategy_detail_maps_current_response_shape():
    use_case = GetStrategyDetail(FakeRegistry(), FakeReader(detail_rows=detail_rows()))
    out = use_case.execute("trendfollowing")
    assert out["id"] == "trendfollowing"
    assert out["invested"] == 500000.0
    assert out["currentValue"] == 510000.0
    assert out["returnPercent"] == 2.0
    assert out["metrics"]["sharpeRatio"] == 2.0
    assert out["equityByStream"]["qt"][0]["value"] == 500000.0


def test_get_strategy_detail_unknown_strategy():
    use_case = GetStrategyDetail(FakeRegistry(cfg=None), FakeReader())
    with pytest.raises(StrategyNotFound):
        use_case.execute("missing")


def test_get_strategy_detail_known_strategy_without_data():
    empty_rows = PortfolioDetailRows(None, [], {}, [], [], [])
    use_case = GetStrategyDetail(FakeRegistry(), FakeReader(detail_rows=empty_rows))
    with pytest.raises(StrategyDataNotFound):
        use_case.execute("trendfollowing")


def test_list_strategies_uses_summary_rows():
    use_case = ListStrategies(
        FakeRegistry(),
        FakeReader(
            summary_row={
                "current_portfolio_value": 525000,
                "volatility": 5,
                "total_annualized_return": 10,
            }
        ),
    )
    out = use_case.execute()
    assert out == [
        {
            "id": "trendfollowing",
            "name": "Trend Following",
            "currentValue": 525000.0,
            "returnPercent": 5.0,
            "volatility": 5.0,
            "sharpeRatio": 2.0,
            "annualizedReturn": 10.0,
        }
    ]
