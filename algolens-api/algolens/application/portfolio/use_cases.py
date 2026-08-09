"""Portfolio use cases."""

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from algolens.application.portfolio.ports import (
    IncubationError,
    IncubationPerformanceRows,
    PortfolioDetailRows,
    PortfolioReaderPort,
    StrategyRegistryPort,
)
from algolens.application.shared.errors import NotFoundError
from algolens.domain.portfolio.calculations import (
    build_historical_data,
    compute_return_stats,
    compute_sharpe,
    float_or_default,
    resolve_initial_equity,
    transform_executions,
    transform_finalized,
    transform_positions,
)
from algolens.domain.portfolio.incubation import compute_incubation_window

logger = logging.getLogger(__name__)


class StrategyDataNotFound(NotFoundError):
    """A known strategy has no live portfolio data yet."""


class StrategyNotFound(NotFoundError):
    """No active strategy exists for the requested public id."""


def build_strategy_detail(
    cfg: Mapping[str, Any], rows: PortfolioDetailRows
) -> dict[str, Any] | None:
    if not rows.latest:
        return None

    latest = rows.latest
    initial_equity = resolve_initial_equity(rows.equity_curve, cfg["initial_equity"])
    current_value = float(latest["current_portfolio_value"])
    total_return = current_value - initial_equity
    return_percent = (total_return / initial_equity * 100) if initial_equity > 0 else 0

    historical_data = build_historical_data(rows.equity_curve)
    equity_by_stream = {
        stream: build_historical_data(stream_rows)
        for stream, stream_rows in rows.equity_by_stream.items()
    }
    transformed_positions = transform_positions(rows.positions, current_value)
    stats = compute_return_stats(historical_data)
    transformed_executions = transform_executions(rows.executions)
    transformed_finalized = transform_finalized(rows.yesterday_positions, rows.positions)

    volatility = float(latest["volatility"])
    annualized_return = float(latest["total_annualized_return"])
    sharpe = compute_sharpe(annualized_return, volatility)

    return {
        "id": cfg["id"],
        "name": cfg["name"],
        "description": cfg["description"],
        "invested": initial_equity,
        "currentValue": current_value,
        "return": total_return,
        "returnPercent": return_percent,
        "positions": transformed_positions,
        "historicalData": historical_data,
        "equityByStream": equity_by_stream,
        "bestDay": stats["best_day"],
        "worstDay": stats["worst_day"],
        "executions": transformed_executions,
        "finalizedPositions": transformed_finalized,
        "managers": cfg["managers"],
        "lastUpdate": latest["date"].isoformat(),
        "metrics": {
            "volatility": volatility,
            "sharpeRatio": sharpe,
            "maxDrawdown": stats["max_drawdown"],
            "winRate": stats["win_rate"],
            "totalTrades": len(transformed_executions),
            "avgWin": stats["avg_win"],
            "avgLoss": stats["avg_loss"],
            "profitFactor": stats["profit_factor"],
            "dailyReturn": float_or_default(latest["daily_return"]),
            "cumulativeReturn": return_percent,
            "annualizedReturn": annualized_return,
            "grossLeverage": float_or_default(latest["gross_leverage"]),
            "netLeverage": float_or_default(latest["net_leverage"]),
            "portfolioLeverage": float_or_default(latest["portfolio_leverage"]),
            "marginPosted": float_or_default(latest["margin_posted"]),
            "equityToMarginRatio": float_or_default(latest["equity_to_margin_ratio"]),
            "marginCushion": float_or_default(latest["margin_cushion"]),
            "totalNotional": float_or_default(latest["gross_notional"]),
            "unrealizedPnL": float_or_default(latest["total_unrealized_pnl"]),
            "realizedPnL": float_or_default(latest["total_realized_pnl"]),
            "totalCommissions": float_or_default(latest["total_transaction_costs"]),
            "netPnL": total_return,
            "cashAvailable": float_or_default(latest["cash_available"]),
            "currentPortfolioValue": current_value,
        },
    }


def build_strategy_summary(
    cfg: Mapping[str, Any], latest: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    if not latest:
        return None

    base_equity = cfg["initial_equity"]
    current_value = float(latest["current_portfolio_value"])
    return_percent = ((current_value - base_equity) / base_equity * 100) if base_equity > 0 else 0
    volatility = float(latest["volatility"])
    annualized_return = float(latest["total_annualized_return"])
    sharpe = compute_sharpe(annualized_return, volatility)

    return {
        "id": cfg["id"],
        "name": cfg["name"],
        "currentValue": current_value,
        "returnPercent": return_percent,
        "volatility": volatility,
        "sharpeRatio": sharpe,
        "annualizedReturn": annualized_return,
    }


def build_incubating_strategy(row: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    window = compute_incubation_window(row.get("incubation_started_at"), now)
    return {
        "id": row["id"],
        "strategy_type": row["strategy_type"],
        "portfolio_id": row["portfolio_id"],
        "name": row["name"],
        "description": row.get("description") or "",
        "mock_capital": float(row["mock_capital"])
        if row.get("mock_capital") is not None
        else None,
        "incubation_started_at": row.get("incubation_started_at"),
        "days_elapsed": window.days_elapsed,
        "window_days": window.window_days,
        "progress": window.progress,
    }


def build_incubation_performance(
    rows: IncubationPerformanceRows,
) -> dict[str, list[Mapping[str, Any]]]:
    return {
        "positions": list(rows.positions),
        "equity_curve": list(rows.equity_curve),
    }


def _require_reason(reason: str) -> str:
    if not reason or not reason.strip():
        raise IncubationError("reason must be non-empty")
    return reason.strip()


def _require_mock_capital(mock_capital: float) -> float:
    if mock_capital <= 0:
        raise IncubationError("mock_capital must be positive")
    return mock_capital


class GetStrategyDetail:
    def __init__(self, registry: StrategyRegistryPort, reader: PortfolioReaderPort):
        self.registry = registry
        self.reader = reader

    def execute(self, strategy_id: str) -> dict[str, Any]:
        cfg = self.registry.get(strategy_id)
        if cfg is None:
            raise StrategyNotFound(strategy_id)

        rows = self.reader.fetch_detail_rows(cfg["strategy_type"], cfg["portfolio_id"])
        detail = build_strategy_detail(cfg, rows)
        if detail is None:
            raise StrategyDataNotFound(strategy_id)
        return detail


class ListStrategies:
    def __init__(self, registry: StrategyRegistryPort, reader: PortfolioReaderPort):
        self.registry = registry
        self.reader = reader

    def execute(self) -> list[dict[str, Any]]:
        strategies = []
        for cfg in self.registry.list(active_only=True):
            try:
                latest = self.reader.fetch_summary_row(
                    cfg["strategy_type"], cfg["portfolio_id"]
                )
                summary = build_strategy_summary(cfg, latest)
            except Exception as exc:
                logger.error(
                    "[STRATEGIES] Failed to summarize %s: %s",
                    cfg["id"],
                    str(exc),
                    exc_info=True,
                )
                continue
            if summary:
                strategies.append(summary)
        return strategies


class ListIncubatingStrategies:
    def __init__(self, reader: PortfolioReaderPort):
        self.reader = reader

    def execute(self, now: datetime) -> list[dict[str, Any]]:
        return [
            build_incubating_strategy(row, now)
            for row in self.reader.list_incubating_strategies()
        ]


class GetIncubationPerformance:
    def __init__(self, reader: PortfolioReaderPort):
        self.reader = reader

    def execute(self, strategy_id: str) -> dict[str, list[Mapping[str, Any]]]:
        rows = self.reader.fetch_incubation_performance(strategy_id)
        return build_incubation_performance(rows)


class StartIncubation:
    def __init__(self, reader: PortfolioReaderPort):
        self.reader = reader

    def execute(
        self,
        strategy_id: str,
        mock_capital: float,
        reason: str,
        user_id: str,
    ) -> None:
        self.reader.start_incubation(
            strategy_id=strategy_id,
            mock_capital=_require_mock_capital(mock_capital),
            reason=_require_reason(reason),
            user_id=user_id,
        )


class PromoteToLive:
    def __init__(self, reader: PortfolioReaderPort):
        self.reader = reader

    def execute(self, strategy_id: str, reason: str, user_id: str) -> None:
        self.reader.promote_to_live(
            strategy_id=strategy_id,
            reason=_require_reason(reason),
            user_id=user_id,
        )


class RetireStrategy:
    def __init__(self, reader: PortfolioReaderPort):
        self.reader = reader

    def execute(self, strategy_id: str, reason: str, user_id: str) -> None:
        self.reader.retire_strategy(
            strategy_id=strategy_id,
            reason=_require_reason(reason),
            user_id=user_id,
        )
