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


def test_notionals_apply_the_contract_size():
    # D-32: 5 ZF at 103.65625 with contract size 1000 is $518,281.25, not $518; a root
    # with no size (an equity) counts with 1.
    from algolens.domain.portfolio.calculations import transform_executions, transform_positions

    sizes = {"ZF": 1000.0, "MBT": 0.1}
    positions = [
        {"symbol": "ZF.v.0", "quantity": -5, "average_price": 103.65625},
        {"symbol": "MBT.v.0", "quantity": 3, "average_price": 111026.67},
        {"symbol": "AAPL", "quantity": 10, "average_price": 200},
    ]
    out = {p["symbol"]: p for p in transform_positions(positions, 1_000_000, sizes)}

    assert out["ZF.v.0"]["notional"] == pytest.approx(518281.25)
    assert out["ZF.v.0"]["percentOfTotal"] == pytest.approx(51.828125)
    assert out["MBT.v.0"]["notional"] == pytest.approx(33308.0)
    assert out["AAPL"]["notional"] == 2000.0

    [trade] = transform_executions(
        [{"symbol": "ZF.v.0", "side": "SELL", "quantity": 1, "price": 103.65625,
          "commissions_fees": 1.5, "execution_time": None}],
        sizes,
    )
    assert trade["notional"] == pytest.approx(103656.25)


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
