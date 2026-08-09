"""Incubation application and repository tests.

These are no-DB tests: use cases are exercised with small fakes, and the
Postgres repository read path is driven by a fake cursor.
"""

from datetime import datetime, timedelta, timezone

import pytest

from algolens.application.portfolio.ports import IncubationError
from algolens.application.portfolio.use_cases import (
    GetIncubationPerformance,
    PromoteToLive,
    StartIncubation,
)
from algolens.domain.portfolio.incubation import compute_incubation_window
from algolens.infrastructure.portfolio.repositories import PostgresPortfolioRepository


def test_days_elapsed_is_never_negative_from_clock_skew():
    started = datetime.now(timezone.utc)
    host_now = started - timedelta(milliseconds=634)

    raw = (host_now - started).days
    assert raw == -1, "precondition: this is the floor() behavior being guarded"

    window = compute_incubation_window(started, host_now)
    assert window.days_elapsed == 0
    assert window.window_days == 120
    assert window.progress == 0


class RecordingReader:
    def __init__(self):
        self.started = None
        self.promoted = None

    def start_incubation(self, **kwargs):
        self.started = kwargs

    def promote_to_live(self, **kwargs):
        self.promoted = kwargs


def test_start_incubation_requires_positive_mock_capital():
    reader = RecordingReader()

    with pytest.raises(IncubationError, match="mock_capital"):
        StartIncubation(reader).execute(
            strategy_id="trendfollowing",
            mock_capital=0,
            reason="Testing incubation",
            user_id="1",
        )

    assert reader.started is None


def test_promote_to_live_requires_non_empty_reason():
    reader = RecordingReader()

    with pytest.raises(IncubationError, match="reason"):
        PromoteToLive(reader).execute(
            strategy_id="trendfollowing",
            reason="   ",
            user_id="1",
        )

    assert reader.promoted is None


class FakeCursor:
    def __init__(self, incubation_start, positions, equity_curve):
        self.incubation_start = incubation_start
        self.positions = positions
        self.equity_curve = equity_curve
        self.calls = []
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "FROM trading.strategy_registry" in sql:
            self.result = {
                "strategy_type": "LIVE_TREND_FOLLOWING",
                "portfolio_id": "MOCK_PORTFOLIO",
                "incubation_started_at": self.incubation_start,
            }
        elif "FROM trading.positions" in sql:
            started_at = params[2]
            self.result = [
                row for row in self.positions if row["date"] >= started_at
            ]
        elif "FROM trading.equity_curve" in sql:
            started_at = params[2]
            self.result = [
                row for row in self.equity_curve if row["date"] >= started_at
            ]
        else:
            raise AssertionError(f"Unexpected SQL: {sql}")

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


def test_incubation_performance_excludes_pre_incubation_history():
    incubation_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    before = datetime(2026, 6, 30, tzinfo=timezone.utc)
    after = datetime(2026, 7, 2, tzinfo=timezone.utc)
    cursor = FakeCursor(
        incubation_start=incubation_start,
        positions=[
            {"date": before, "symbol": "ES", "quantity": 1, "entry_price": 100},
            {"date": after, "symbol": "NQ", "quantity": 2, "entry_price": 200},
        ],
        equity_curve=[
            {"date": before, "equity": 249000},
            {"date": after, "equity": 251000},
        ],
    )
    repo = PostgresPortfolioRepository(
        connection_factory=lambda: FakeConnection(cursor)
    )

    performance = GetIncubationPerformance(repo).execute("trendfollowing")

    assert [position["date"] for position in performance["positions"]] == [after]
    assert [point["date"] for point in performance["equity_curve"]] == [after]
    position_call = next(call for call in cursor.calls if "trading.positions" in call[0])
    equity_call = next(call for call in cursor.calls if "trading.equity_curve" in call[0])
    assert position_call[1] == (
        "LIVE_TREND_FOLLOWING",
        "MOCK_PORTFOLIO",
        incubation_start,
    )
    assert equity_call[1] == (
        "LIVE_TREND_FOLLOWING",
        "MOCK_PORTFOLIO",
        incubation_start,
    )
