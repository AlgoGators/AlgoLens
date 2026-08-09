from datetime import datetime

import pytest

from algolens.application.portfolio.ports import PortfolioDetailRows


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
    def __init__(self, cfg=CFG, fail_list=False):
        self.cfg = cfg
        self.fail_list = fail_list

    def list(self, active_only=True):
        if self.fail_list:
            raise RuntimeError("registry failed")
        return [self.cfg] if self.cfg else []

    def get(self, strategy_id):
        if self.cfg and self.cfg["id"] == strategy_id:
            return self.cfg
        return None


class FakeReader:
    def __init__(self, detail_rows=None, summary_row=None, fail_detail=False):
        self.detail_rows = detail_rows
        self.summary_row = summary_row
        self.fail_detail = fail_detail

    def fetch_summary_row(self, strategy_type, portfolio_id):
        return self.summary_row

    def fetch_detail_rows(self, strategy_type, portfolio_id):
        if self.fail_detail:
            raise RuntimeError("detail failed")
        return self.detail_rows


def _latest_row():
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


_DEFAULT_LATEST = object()


def _detail_rows(latest=_DEFAULT_LATEST):
    return PortfolioDetailRows(
        latest=_latest_row() if latest is _DEFAULT_LATEST else latest,
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


@pytest.fixture
def authenticated_client(client, monkeypatch):
    monkeypatch.setenv("DEV_MODE", "1")
    monkeypatch.setenv("FLASK_ENV", "development")
    client.post("/auth/dev-login")
    return client


def _patch_portfolio_dependencies(monkeypatch, registry, reader):
    import algolens.adapters.http.portfolio as portfolio_mod

    monkeypatch.setattr(
        portfolio_mod,
        "_portfolio_dependencies",
        lambda: (registry, reader),
    )


def test_strategy_list_returns_current_summary_shape(authenticated_client, monkeypatch):
    _patch_portfolio_dependencies(
        monkeypatch,
        FakeRegistry(),
        FakeReader(
            summary_row={
                "current_portfolio_value": 525000,
                "volatility": 5,
                "total_annualized_return": 10,
            }
        ),
    )

    resp = authenticated_client.get("/portfolio/strategies")

    assert resp.status_code == 200
    assert resp.get_json() == {
        "strategies": [
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
    }


def test_strategy_detail_returns_current_payload_shape(authenticated_client, monkeypatch):
    _patch_portfolio_dependencies(
        monkeypatch, FakeRegistry(), FakeReader(detail_rows=_detail_rows())
    )

    resp = authenticated_client.get("/portfolio/strategy/trendfollowing")
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["id"] == "trendfollowing"
    assert body["name"] == "Trend Following"
    assert body["invested"] == 500000.0
    assert body["currentValue"] == 510000.0
    assert body["returnPercent"] == 2.0
    assert body["historicalData"][0] == {
        "date": "2026-01-01T00:00:00",
        "value": 500000.0,
    }
    assert body["equityByStream"]["qt"][1]["value"] == 510000.0
    assert body["metrics"]["sharpeRatio"] == 2.0


def test_strategy_detail_unknown_strategy_maps_to_404(authenticated_client, monkeypatch):
    _patch_portfolio_dependencies(monkeypatch, FakeRegistry(cfg=None), FakeReader())

    resp = authenticated_client.get("/portfolio/strategy/missing")

    assert resp.status_code == 404
    assert resp.get_json() == {"error": "Strategy not found"}


def test_strategy_detail_without_data_maps_to_404(authenticated_client, monkeypatch):
    _patch_portfolio_dependencies(
        monkeypatch,
        FakeRegistry(),
        FakeReader(detail_rows=_detail_rows(latest=None)),
    )

    resp = authenticated_client.get("/portfolio/strategy/trendfollowing")

    assert resp.status_code == 404
    assert resp.get_json() == {"error": "No data found for strategy"}


def test_strategy_detail_unexpected_error_maps_to_500(authenticated_client, monkeypatch):
    _patch_portfolio_dependencies(
        monkeypatch,
        FakeRegistry(),
        FakeReader(fail_detail=True),
    )

    resp = authenticated_client.get("/portfolio/strategy/trendfollowing")

    assert resp.status_code == 500
    assert resp.get_json() == {"error": "Failed to fetch strategy"}


def test_strategy_list_dependency_error_maps_to_500(authenticated_client, monkeypatch):
    import algolens.adapters.http.portfolio as portfolio_mod

    monkeypatch.setattr(
        portfolio_mod,
        "_portfolio_dependencies",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    resp = authenticated_client.get("/portfolio/strategies")

    assert resp.status_code == 500
    assert resp.get_json() == {"error": "Failed to fetch strategies"}


def test_strategy_list_logs_timing(authenticated_client, monkeypatch, caplog):
    caplog.set_level("INFO")
    _patch_portfolio_dependencies(
        monkeypatch,
        FakeRegistry(),
        FakeReader(
            summary_row={
                "current_portfolio_value": 525000,
                "volatility": 5,
                "total_annualized_return": 10,
            }
        ),
    )

    resp = authenticated_client.get("/portfolio/strategies")

    assert resp.status_code == 200
    assert "[PORTFOLIO_TIMING] strategies" in caplog.text


def test_strategy_detail_logs_timing(authenticated_client, monkeypatch, caplog):
    caplog.set_level("INFO")
    _patch_portfolio_dependencies(
        monkeypatch, FakeRegistry(), FakeReader(detail_rows=_detail_rows())
    )

    resp = authenticated_client.get("/portfolio/strategy/trendfollowing")

    assert resp.status_code == 200
    assert "[PORTFOLIO_TIMING] detail" in caplog.text
