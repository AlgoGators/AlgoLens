"""Authenticated HTTP regressions for the strategy positions stream selector.

Only the storage and market-data boundaries are replaced. Requests still pass
through the registered route, membership lookup, use case, builder and JSON
serializer. The two snapshots intentionally share a symbol but disagree on
component, quantity and date, so an ignored selector cannot satisfy both.
"""

from datetime import date, datetime, timezone

import pytest
from flask_jwt_extended import create_access_token

from app import app
from algolens.application.portfolio.ports import PortfolioDetailRows


BOOK = "BASE_PORTFOLIO"
STRATEGY_TYPE = "LIVE_TREND_FOLLOWING"
QT_DAY = date(2099, 1, 2)
SYSTEM_DAY = date(2099, 1, 1)


def _position(name, quantity, day):
    return {
        "date": day,
        "symbol": "ES",
        "strategy_name": name,
        "quantity": quantity,
        "average_price": 100.0,
        "daily_unrealized_pnl": 0.0,
        "daily_realized_pnl": 0.0,
    }


class _Registry:
    def get(self, strategy_id):
        if strategy_id != "trendfollowing":
            return None
        return {
            "id": strategy_id,
            "strategy_type": STRATEGY_TYPE,
            "portfolio_id": BOOK,
            "name": "Trend Following",
            "description": "",
            "managers": [],
            "initial_equity": 200000,
            "lifecycle": "live",
        }

    def books_for_strategy(self, strategy_id):
        return [BOOK]


class _Reader:
    """The default matches today's reader, making an unwired route return QT."""

    def __init__(self, *, empty_system=False):
        self.calls = []
        self.empty_system = empty_system

    def fetch_detail_rows(self, strategy_type, portfolio_id, position_stream="qt"):
        self.calls.append((strategy_type, portfolio_id, position_stream))
        if position_stream == "system":
            positions = [] if self.empty_system else [
                _position("MODEL_FAST", 2, SYSTEM_DAY),
                _position("MODEL_SLOW", 5, SYSTEM_DAY),
            ]
            position_date = SYSTEM_DAY
            names = ("MODEL_FAST", "MODEL_SLOW")
        elif position_stream == "qt":
            positions = [_position("QT_DESK", 17, QT_DAY)]
            position_date = QT_DAY
            names = ("QT_DESK",)
        else:
            pytest.fail(f"Unvalidated position stream reached storage: {position_stream!r}")

        return PortfolioDetailRows(
            latest={
                "date": QT_DAY,
                "current_portfolio_value": 250000,
                "total_annualized_return": 8.0,
                "total_cumulative_return": 8.0,
                "volatility": 12.0,
                "daily_return": 0.1,
            },
            equity_curve=[],
            equity_by_stream={},
            positions=positions,
            executions=[{
                "execution_time": datetime(2099, 1, 2, 12, tzinfo=timezone.utc),
                "symbol": "ES",
                "side": "BUY",
                "quantity": 1,
                "price": 100.0,
                "commissions_fees": 2.0,
            }],
            # The previous QT holding matches the current QT holding. A
            # comparison against today's model quantities would invent a close.
            yesterday_positions=[_position("QT_DESK", 17, date(2099, 1, 1))],
            position_date=position_date,
            position_strategy_names=names,
            position_stream=position_stream,
            execution_date=QT_DAY,
            executions_available=True,
            qt_positions=[_position("QT_DESK", 17, QT_DAY)],
            activity_stream="qt",
            finalized_positions_available=True,
        )


class _MarketData:
    def latest_prices(self, symbols):
        return {"ES": 125.0}

    def contract_multipliers(self, symbols):
        return {"ES": 50.0}


@pytest.fixture
def route_reader(client, monkeypatch):
    import algolens.adapters.http.portfolio as portfolio_http
    import algolens.application.portfolio.use_cases as use_cases

    reader = _Reader()
    monkeypatch.setattr(portfolio_http, "create_portfolio_dependencies", lambda: (_Registry(), reader))
    monkeypatch.setattr(portfolio_http, "create_market_data", lambda: _MarketData())
    monkeypatch.setattr(use_cases, "current_utc_date", lambda: QT_DAY)
    with app.app_context():
        token = create_access_token(identity="83", additional_claims={"role": "general_member"})
    client.current_users.set("83", role="general_member")
    client.set_cookie("access_token_cookie", token)
    return reader


def _get_detail(client, query_string=None):
    return client.get("/portfolio/strategy/trendfollowing", query_string=query_string)


def test_omitted_stream_returns_model_components_with_qt_performance(client, route_reader):
    response = _get_detail(client)

    assert response.status_code == 200
    detail = response.get_json()
    assert route_reader.calls[0] == (STRATEGY_TYPE, BOOK, "system")
    assert detail["positionStream"] == "system"
    assert [(p["strategyName"], p["quantity"]) for p in detail["positions"]] == [
        ("MODEL_FAST", 2.0), ("MODEL_SLOW", 5.0),
    ]
    assert detail["positionDate"] == SYSTEM_DAY.isoformat()
    assert detail["positionStrategyNames"] == ["MODEL_FAST", "MODEL_SLOW"]
    assert detail["positionsEditable"] is False
    assert "model" in detail["positionEditUnavailableReason"].lower()
    assert [p["percentOfTotal"] for p in detail["positions"]] == [None, None]
    assert detail["resultSource"] == "qt"
    assert detail["currentValue"] == 250000.0
    assert detail["metrics"]["executionsToday"] == 1
    assert detail["executions"][0]["notional"] == 5000.0
    assert detail["finalizedPositions"] == []
    assert detail["activityStream"] == "qt"
    assert detail["finalizedPositionsAvailable"] is True


def test_explicit_qt_returns_qt_snapshot_and_retains_qt_percentage(client, route_reader):
    response = _get_detail(client, {"position_stream": "qt"})

    assert response.status_code == 200
    detail = response.get_json()
    assert route_reader.calls[0] == (STRATEGY_TYPE, BOOK, "qt")
    assert detail["positionStream"] == "qt"
    assert [(p["strategyName"], p["quantity"]) for p in detail["positions"]] == [
        ("QT_DESK", 17.0),
    ]
    assert detail["positionDate"] == QT_DAY.isoformat()
    assert detail["positionStrategyNames"] == ["QT_DESK"]
    assert detail["positionsEditable"] is True
    assert detail["positions"][0]["percentOfTotal"] == 42.5
    assert detail["resultSource"] == "qt"
    assert detail["activityStream"] == "qt"
    assert detail["finalizedPositionsAvailable"] is True


def test_explicit_system_switch_does_not_return_cached_qt_rows(client, route_reader):
    response = _get_detail(client, {"position_stream": "system", "portfolio_id": BOOK})

    assert response.status_code == 200
    detail = response.get_json()
    assert route_reader.calls[0] == (STRATEGY_TYPE, BOOK, "system")
    assert [p["strategyName"] for p in detail["positions"]] == ["MODEL_FAST", "MODEL_SLOW"]
    assert detail["portfolio_id"] == BOOK


def test_empty_model_snapshot_keeps_its_own_date_and_identity(client, route_reader):
    route_reader.empty_system = True

    response = _get_detail(client, {"position_stream": "system"})

    assert response.status_code == 200
    detail = response.get_json()
    assert detail["positionStream"] == "system"
    assert detail["positions"] == []
    assert detail["positionDate"] == SYSTEM_DAY.isoformat()
    assert detail["positionStrategyNames"] == ["MODEL_FAST", "MODEL_SLOW"]
    assert detail["positionsEditable"] is False


@pytest.mark.parametrize(
    "query_string",
    [
        [("position_stream", "")],
        [("position_stream", "SYSTEM")],
        [("position_stream", "benchmark")],
        [("position_stream", "system"), ("position_stream", "qt")],
        [("position_stream", "qt"), ("position_stream", "qt")],
    ],
    ids=["blank", "wrong-case", "unsupported", "conflicting-repeat", "duplicate-repeat"],
)
def test_invalid_stream_is_rejected_before_positions_read(client, route_reader, query_string):
    response = _get_detail(client, query_string)

    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_position_stream"
    assert route_reader.calls == []


def test_stream_selector_does_not_bypass_book_membership(client, route_reader):
    response = _get_detail(client, {"portfolio_id": "OTHER_BOOK", "position_stream": "system"})

    assert response.status_code == 400
    assert response.get_json()["code"] == "not_a_member_of_book"
    assert route_reader.calls == []
