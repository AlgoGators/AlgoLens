"""Portfolio-id keyed read endpoints (AlgoLens#102 intent, contract section 7)."""

from datetime import date

import pytest
from flask_jwt_extended import create_access_token

import algolens.adapters.http.portfolio as portfolio_http
from algolens.application.portfolio.ports import PortfolioDetailRows
from app import app

REGISTRY = [
    {
        "id": "trendfollowing",
        "strategy_type": "LIVE_TREND_FOLLOWING",
        "portfolio_id": "CONSERVATIVE_PORTFOLIO",
        "name": "Trend Following",
        "description": "",
        "initial_equity": 500000.0,
        "managers": ["AlgoLens System"],
        "portfolio_group": None,
        "desk_editable": False,
    },
    {
        "id": "qt_conservative",
        "strategy_type": "LIVE_TREND_FOLLOWING",
        "portfolio_id": "QT_CONSERVATIVE_PORTFOLIO",
        "name": "QT Trend Following",
        "description": "",
        "initial_equity": 500000.0,
        "managers": ["QT desk"],
        "portfolio_group": "qt_conservative",
        "desk_editable": True,
    },
    {
        "id": "qt_conservative_model",
        "strategy_type": "LIVE_TREND_FOLLOWING",
        "portfolio_id": "QT_CONSERVATIVE_MODEL_PORTFOLIO",
        "name": "QT Trend Following (model)",
        "description": "",
        "initial_equity": 500000.0,
        "managers": ["AlgoLens System"],
        "portfolio_group": "qt_conservative",
        "desk_editable": False,
    },
]

LATEST = {
    "date": date(2026, 10, 8),
    "current_portfolio_value": 510000,
    "volatility": 10,
    "total_annualized_return": 5,
    "daily_return": 0,
    "gross_leverage": 1,
    "net_leverage": 1,
    "portfolio_leverage": 1,
    "margin_posted": 0,
    "equity_to_margin_ratio": 0,
    "margin_cushion": 0,
    "gross_notional": 0,
    "total_unrealized_pnl": 0,
    "total_realized_pnl": 0,
    "total_transaction_costs": 0,
    "cash_available": 0,
}


class FakeRegistry:
    def list(self, active_only=True):
        return REGISTRY

    def get(self, strategy_id):
        return next((r for r in REGISTRY if r["id"] == strategy_id), None)

    def get_portfolio(self, portfolio_id):
        return next((r for r in REGISTRY if r["portfolio_id"] == portfolio_id), None)


class FakeReader:
    def __init__(self):
        self.calls = []

    def fetch_portfolio_rows(self, portfolio_id, book="qt", allow_fallback=True):
        self.calls.append((portfolio_id, book, allow_fallback))
        served = "system" if allow_fallback else book
        return PortfolioDetailRows(
            latest=LATEST,
            equity_curve=[],
            equity_by_stream={},
            positions=[{"symbol": "ZC.v.0", "quantity": 2, "average_price": 400,
                        "daily_unrealized_pnl": 0, "daily_realized_pnl": 0}],
            executions=[],
            yesterday_positions=[],
            book=served,
            fell_back=allow_fallback,
        )


@pytest.fixture
def reader(monkeypatch):
    fake = FakeReader()
    monkeypatch.setattr(
        portfolio_http, "create_portfolio_dependencies", lambda: (FakeRegistry(), fake)
    )
    return fake


def _login(client, role="admin", email="desk@example.com"):
    with app.app_context():
        token = create_access_token(
            identity="7", additional_claims={"role": role, "email": email}
        )
    client.set_cookie("access_token_cookie", token)


def test_portfolios_are_grouped_for_the_switcher(client, reader, monkeypatch):
    monkeypatch.delenv("QT_DESK_ENABLED", raising=False)
    _login(client)

    response = client.get("/portfolio/portfolios")

    assert response.status_code == 200
    body = response.get_json()
    assert body["deskEnabled"] is False
    assert [g["group"] for g in body["groups"]] == ["CONSERVATIVE_PORTFOLIO", "qt_conservative"]
    qt = body["groups"][1]["portfolios"]
    assert [(p["portfolio_id"], p["desk_editable"]) for p in qt] == [
        ("QT_CONSERVATIVE_PORTFOLIO", True),
        ("QT_CONSERVATIVE_MODEL_PORTFOLIO", False),
    ]


def test_portfolios_report_the_desk_flag(client, reader, monkeypatch):
    monkeypatch.setenv("QT_DESK_ENABLED", "true")
    _login(client)

    assert client.get("/portfolio/portfolios").get_json()["deskEnabled"] is True


def test_portfolio_detail_defaults_to_qt_with_fallback(client, reader):
    _login(client)

    response = client.get("/portfolio/portfolios/QT_CONSERVATIVE_PORTFOLIO")

    assert response.status_code == 200
    body = response.get_json()
    assert reader.calls == [("QT_CONSERVATIVE_PORTFOLIO", "qt", True)]
    assert (body["book"], body["fellBack"]) == ("system", True)
    assert body["portfolioId"] == "QT_CONSERVATIVE_PORTFOLIO"
    assert body["deskEditable"] is True
    assert body["assetClass"] == "futures"
    assert body["portfolioGroup"] == "qt_conservative"


@pytest.mark.parametrize("book", ["system", "qt_proposal", "qt"])
def test_portfolio_detail_serves_a_named_book_exactly(client, reader, book):
    _login(client)

    response = client.get(f"/portfolio/portfolios/QT_CONSERVATIVE_PORTFOLIO?book={book}")

    assert response.status_code == 200
    assert reader.calls == [("QT_CONSERVATIVE_PORTFOLIO", book, False)]
    assert response.get_json()["book"] == book


def test_portfolio_detail_rejects_unknown_book(client, reader):
    _login(client)

    response = client.get("/portfolio/portfolios/QT_CONSERVATIVE_PORTFOLIO?book=benchmark")

    assert response.status_code == 400
    assert reader.calls == []


def test_unknown_portfolio_is_404(client, reader):
    _login(client)

    assert client.get("/portfolio/portfolios/NOPE").status_code == 404


def test_portfolio_reads_require_login(client, reader):
    assert client.get("/portfolio/portfolios").status_code == 401
    assert client.get("/portfolio/portfolios/QT_CONSERVATIVE_PORTFOLIO").status_code == 401


def test_desk_access_helpers():
    assert portfolio_http.can_use_qt_desk({"role": "admin"})
    assert portfolio_http.can_use_qt_desk({"role": "general_member"})
    assert not portfolio_http.can_use_qt_desk({"role": "investor"})
    assert not portfolio_http.can_use_qt_desk(None)


def test_is_approver_reads_qt_approvers(monkeypatch):
    monkeypatch.setenv("QT_APPROVERS", "vp=VP@x.com,president=p@x.com")
    assert portfolio_http.is_approver({"email": "vp@x.com"}, "vp")
    assert not portfolio_http.is_approver({"email": "vp@x.com"}, "president")
    assert portfolio_http.is_approver({"email": "P@X.com"}, "president")
    assert not portfolio_http.is_approver({"email": ""}, "vp")
    monkeypatch.delenv("QT_APPROVERS")
    assert not portfolio_http.is_approver({"email": "vp@x.com"}, "vp")
