"""Tests for the data-driven strategy registry and the extracted portfolio service.

The registry tests force the DB-unavailable path (so they run without a database)
and assert the built-in fallback. The service tests exercise the pure transform /
computation helpers with hand-built rows -- no DB needed.
"""

from services import strategy_registry as reg
from services import portfolio_service as svc


# --- registry ----------------------------------------------------------------


def test_registry_falls_back_to_default_on_db_error(monkeypatch):
    # Simulate the DB being unavailable / migration not applied.
    def boom():
        raise ValueError("no db configured")

    monkeypatch.setattr(reg, "get_db_connection", boom)

    registry = reg.get_registry()
    assert [s["id"] for s in registry] == ["trendfollowing"]
    assert registry[0]["strategy_type"] == "LIVE_TREND_FOLLOWING"
    assert registry[0]["initial_equity"] == 500000.0


def test_every_registry_entry_names_a_portfolio(monkeypatch):
    """A registry entry without a portfolio is a correctness bug, not a default.

    The trading tables are keyed by portfolio as well as strategy, and
    LIVE_TREND_FOLLOWING exists under more than one. An entry that names only the
    strategy would make every downstream query ambiguous, silently blending
    portfolios rather than failing. See AlgoGators/AlgoLens#29.
    """
    monkeypatch.setattr(
        reg, "get_db_connection", lambda: (_ for _ in ()).throw(ValueError())
    )

    for strategy in reg.get_registry():
        assert strategy.get("portfolio_id"), (
            f"registry entry {strategy['id']!r} does not name a portfolio_id"
        )


def test_get_strategy_config_known_and_unknown(monkeypatch):
    monkeypatch.setattr(
        reg, "get_db_connection", lambda: (_ for _ in ()).throw(ValueError())
    )

    assert reg.get_strategy_config("trendfollowing")["name"] == "Trend Following"
    assert reg.get_strategy_config("does-not-exist") is None


# --- pure computation helpers ------------------------------------------------


def test_resolve_initial_equity_snaps_within_tolerance():
    curve = [{"equity": 500123, "timestamp": None}]
    # within 5000 of the configured base -> snap to the round number
    assert svc._resolve_initial_equity(curve, 500000) == 500000


def test_resolve_initial_equity_keeps_value_outside_tolerance():
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
    assert out[0]["notional"] == 200.0
    assert out[0]["percentOfTotal"] == 50.0


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
