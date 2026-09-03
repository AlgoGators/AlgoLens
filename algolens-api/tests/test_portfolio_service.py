import pytest
"""Tests for the data-driven strategy registry and the extracted portfolio service.

The registry tests force the DB-unavailable path (so they run without a database)
and assert the built-in fallback. The service tests exercise the pure transform /
computation helpers with hand-built rows -- no DB needed.
"""

from services import strategy_registry as reg
from services import portfolio_service as svc


# --- registry ----------------------------------------------------------------


def test_a_registry_read_failure_is_an_error_not_a_default(monkeypatch):
    """The registry used to answer a failed read with a built-in strategy:
    "Trend Following", $500,000, managed by "AlgoLens System". A connection
    blip produced a fabricated strategy card with nothing in the response to
    say so. It now fails, and the route reports a database error."""
    from algolens.application.portfolio.ports import IncubationStorageError

    def boom():
        raise ValueError("no db configured")

    monkeypatch.setattr(reg, "get_db_connection", boom)
    with pytest.raises(IncubationStorageError):
        reg.get_registry()


class _FakeRegistry:
    """What a registry answers, without a database and without inventing one.

    The old tests reached these functions with no database configured and
    relied on the built-in default strategy that used to fill the gap. That
    default is gone -- it was a fabricated strategy with fabricated capital --
    so the tests now say exactly what the registry holds.
    """

    ROWS = [
        {
            "id": "trendfollowing",
            "strategy_type": "LIVE_TREND_FOLLOWING",
            "portfolio_id": "CONSERVATIVE_PORTFOLIO",
            "name": "Trend Following",
            "description": "",
            "initial_equity": 500000.0,
            "managers": [],
            "is_active": True,
            "lifecycle": "live",
            "sort_order": 0,
            "mock_capital": None,
        }
    ]

    def list(self, active_only=True):
        return list(self.ROWS)

    def get(self, strategy_id):
        return next((r for r in self.ROWS if r["id"] == strategy_id), None)


def test_every_registry_entry_names_a_portfolio(monkeypatch):
    """A registry entry without a portfolio is a correctness bug, not a default.

    The trading tables are keyed by portfolio as well as strategy, and
    LIVE_TREND_FOLLOWING exists under more than one. An entry that names only the
    strategy would make every downstream query ambiguous, silently blending
    portfolios rather than failing. See AlgoGators/AlgoLens#29.
    """
    monkeypatch.setattr(reg, "PostgresStrategyRegistry", _FakeRegistry)
    for strategy in reg.get_registry():
        assert strategy.get("portfolio_id"), (
            f"registry entry {strategy['id']!r} does not name a portfolio_id"
        )


def test_get_strategy_config_known_and_unknown(monkeypatch):
    monkeypatch.setattr(reg, "PostgresStrategyRegistry", _FakeRegistry)
    assert reg.get_strategy_config("trendfollowing")["name"] == "Trend Following"
    assert reg.get_strategy_config("does-not-exist") is None


def test_an_empty_registry_is_an_empty_list_not_a_default(monkeypatch):
    class _Empty(_FakeRegistry):
        ROWS = []

    monkeypatch.setattr(reg, "PostgresStrategyRegistry", _Empty)
    assert reg.get_registry() == []


# --- pure computation helpers ------------------------------------------------


def test_resolve_initial_equity_uses_the_true_first_point():
    # No snapping: the actual first equity-curve value is used as-is, even when it
    # sits close to the configured base.
    curve = [{"equity": 500123, "timestamp": None}]
    assert svc._resolve_initial_equity(curve, 500000) == 500123


def test_resolve_initial_equity_uses_first_point_far_from_base():
    curve = [{"equity": 480000, "timestamp": None}]
    assert svc._resolve_initial_equity(curve, 500000) == 480000


def test_resolve_initial_equity_falls_back_when_empty():
    assert svc._resolve_initial_equity([], 500000) == 500000


def test_compute_return_stats_basic():
    hist = [
        {"value": 100.0},
        {"value": 110.0},  # +10%
        {"value": 99.0},  # -10%
    ]
    stats = svc._compute_return_stats(hist)
    assert round(stats["best_day"], 2) == 10.0
    assert round(stats["worst_day"], 2) == -10.0
    assert round(stats["win_rate"], 2) == 50.0  # 1 up day, 1 down day
    assert round(stats["max_drawdown"], 2) == 10.0  # 110 peak -> 99


def test_transform_positions_percent_of_total():
    positions = [
        {
            "symbol": "ES.v.0",
            "quantity": 2,
            "average_price": 100,
            "daily_unrealized_pnl": 0,
            "daily_realized_pnl": 0,
        }
    ]
    out = svc._transform_positions(positions, current_value=400)
    assert out[0]["name"] == "ES"  # ".v.0" stripped
    # Without a market price and a contract size, exposure is unknown. It used
    # to be quantity x entry price, which omitted the contract size entirely.
    assert out[0]["notional"] is None
    assert out[0]["percentOfTotal"] is None


def test_transform_positions_prices_at_the_market_when_it_can():
    positions = [
        {
            "symbol": "ES.v.0",
            "quantity": 2,
            "average_price": 100,
            "daily_unrealized_pnl": 0,
            "daily_realized_pnl": 0,
        }
    ]
    out = svc._transform_positions(
        positions,
        current_value=400,
        prices={"ES.v.0": 110.0},
        multipliers={"ES": 50.0},
    )
    # 2 x 110 x 50, not 2 x 100. Entry price is cost basis, not exposure.
    assert out[0]["marketPrice"] == 110.0
    assert out[0]["contractMultiplier"] == 50.0
    assert out[0]["notional"] == 11000.0
    assert out[0]["costBasis"] == 100.0


def test_transform_finalized_only_changed_positions():
    yesterday = [
        {
            "symbol": "ES.v.0",
            "quantity": 3,
            "average_price": 100,
            "daily_realized_pnl": 5,
        },
        {
            "symbol": "NQ.v.0",
            "quantity": 1,
            "average_price": 200,
            "daily_realized_pnl": 0,
        },
    ]
    today = [
        {"symbol": "ES.v.0", "quantity": 3, "average_price": 100},  # unchanged -> skip
        {"symbol": "NQ.v.0", "quantity": 0, "average_price": 200},  # closed -> included
    ]
    out = svc._transform_finalized(yesterday, today)
    assert {p["symbol"] for p in out} == {"NQ"}
