from datetime import datetime

from algolens.application.portfolio.ports import PortfolioDetailRows
from algolens.infrastructure.config.dependencies import create_portfolio_dependencies
from algolens.infrastructure.portfolio.cache import CachedPortfolioReader
from algolens.infrastructure.portfolio.repositories import PostgresPortfolioRepository


class FakeClock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeReader:
    def __init__(self):
        self.summary_calls = 0
        self.detail_calls = 0

    def fetch_summary_row(self, strategy_type, portfolio_id):
        self.summary_calls += 1
        return {
            "strategy_type": strategy_type,
            "portfolio_id": portfolio_id,
            "value": self.summary_calls,
        }

    def fetch_detail_rows(self, strategy_type, portfolio_id):
        self.detail_calls += 1
        return PortfolioDetailRows(
            latest={"current_portfolio_value": self.detail_calls},
            equity_curve=[
                {
                    "timestamp": datetime(2026, 1, 1),
                    "equity": 500000 + self.detail_calls,
                }
            ],
            equity_by_stream={},
            positions=[],
            executions=[],
            yesterday_positions=[],
        )


def test_summary_rows_are_cached_until_ttl_expires():
    clock = FakeClock()
    reader = FakeReader()
    cached = CachedPortfolioReader(reader, ttl_seconds=30, clock=clock)

    first = cached.fetch_summary_row("LIVE_TREND_FOLLOWING", "CONSERVATIVE")
    second = cached.fetch_summary_row("LIVE_TREND_FOLLOWING", "CONSERVATIVE")

    assert first == second
    assert reader.summary_calls == 1

    clock.advance(31)
    third = cached.fetch_summary_row("LIVE_TREND_FOLLOWING", "CONSERVATIVE")

    assert third["value"] == 2
    assert reader.summary_calls == 2


def test_detail_rows_are_cached_by_strategy_and_portfolio():
    clock = FakeClock()
    reader = FakeReader()
    cached = CachedPortfolioReader(reader, ttl_seconds=30, clock=clock)

    first = cached.fetch_detail_rows("STRATEGY_A", "P1")
    second = cached.fetch_detail_rows("STRATEGY_A", "P1")
    other_portfolio = cached.fetch_detail_rows("STRATEGY_A", "P2")

    assert first == second
    assert first.latest["current_portfolio_value"] == 1
    assert other_portfolio.latest["current_portfolio_value"] == 2
    assert reader.detail_calls == 2


def test_cached_values_are_defensive_copies():
    clock = FakeClock()
    reader = FakeReader()
    cached = CachedPortfolioReader(reader, ttl_seconds=30, clock=clock)

    first = cached.fetch_summary_row("STRATEGY_A", "P1")
    first["value"] = 999
    second = cached.fetch_summary_row("STRATEGY_A", "P1")

    assert second["value"] == 1
    assert reader.summary_calls == 1


def test_cache_can_be_disabled():
    reader = FakeReader()
    cached = CachedPortfolioReader(reader, ttl_seconds=0)

    first = cached.fetch_summary_row("STRATEGY_A", "P1")
    second = cached.fetch_summary_row("STRATEGY_A", "P1")

    assert first["value"] == 1
    assert second["value"] == 2
    assert reader.summary_calls == 2


def test_clear_evicts_cached_rows():
    reader = FakeReader()
    cached = CachedPortfolioReader(reader, ttl_seconds=30)

    cached.fetch_summary_row("STRATEGY_A", "P1")
    cached.clear()
    second = cached.fetch_summary_row("STRATEGY_A", "P1")

    assert second["value"] == 2
    assert reader.summary_calls == 2


def test_portfolio_dependencies_wrap_reader_in_cache_by_default(monkeypatch):
    monkeypatch.delenv("PORTFOLIO_CACHE_TTL_SECONDS", raising=False)

    _registry, reader = create_portfolio_dependencies()

    assert isinstance(reader, CachedPortfolioReader)


def test_portfolio_dependencies_reuse_cached_reader_instance(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_CACHE_TTL_SECONDS", "30")

    _registry, first = create_portfolio_dependencies()
    _registry, second = create_portfolio_dependencies()

    assert first is second


def test_portfolio_dependencies_can_disable_cache(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_CACHE_TTL_SECONDS", "0")

    _registry, reader = create_portfolio_dependencies()

    assert isinstance(reader, PostgresPortfolioRepository)
