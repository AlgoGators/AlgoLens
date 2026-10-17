"""Tests for the data-driven strategy registry and the extracted portfolio service.

The registry test forces the DB-unavailable path (so it runs without a database)
and asserts it is an error (D-23: there is no built-in fallback). The service tests exercise the pure transform /
computation helpers with hand-built rows -- no DB needed.
"""

import pytest

from services import strategy_registry as reg
from services import portfolio_service as svc


# --- registry ----------------------------------------------------------------


def test_registry_read_failure_is_an_error(monkeypatch):
    # D-23: no built-in default stands in for the registry (it hid the QT books).
    def boom():
        raise ValueError("no db configured")

    monkeypatch.setattr(reg, "get_db_connection", boom)

    with pytest.raises(reg.RegistryUnavailable):
        reg.get_registry()
    with pytest.raises(reg.RegistryUnavailable):
        reg.get_strategy_config("trendfollowing")


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
