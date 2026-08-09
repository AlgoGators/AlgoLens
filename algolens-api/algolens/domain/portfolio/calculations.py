"""Pure portfolio calculations and response-shape transforms."""

from collections.abc import Mapping, Sequence
from typing import Any


def _get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def resolve_initial_equity(equity_curve: Sequence[Any], base_equity: float) -> float:
    """Use the true first equity point, falling back to configured base equity."""
    if equity_curve:
        return float(_get(equity_curve[0], "equity"))
    return base_equity


def build_historical_data(equity_curve: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        {"date": _get(point, "timestamp").isoformat(), "value": float(_get(point, "equity"))}
        for point in equity_curve
    ]


def transform_positions(positions: Sequence[Any], current_value: float) -> list[dict[str, Any]]:
    transformed = []
    for pos in positions:
        quantity = float(_get(pos, "quantity"))
        average_price = float(_get(pos, "average_price"))
        notional = abs(quantity * average_price)
        transformed.append(
            {
                "symbol": _get(pos, "symbol"),
                "name": _get(pos, "symbol").replace(".v.0", ""),
                "shares": quantity,
                "quantity": quantity,
                "costBasis": average_price,
                "currentValue": notional,
                "marketPrice": average_price,
                "notional": notional,
                "percentOfTotal": (notional / current_value * 100) if current_value > 0 else 0,
            }
        )
    return transformed


def compute_return_stats(historical_data: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Best/worst day, drawdown, win rate, and win/loss aggregates."""
    daily_returns = []
    daily_pnl = []
    for i in range(1, len(historical_data)):
        prev_val = historical_data[i - 1]["value"]
        curr_val = historical_data[i]["value"]
        if prev_val > 0:
            daily_returns.append(((curr_val - prev_val) / prev_val) * 100)
            daily_pnl.append(curr_val - prev_val)

    best_day = max(daily_returns) if daily_returns else 0
    worst_day = min(daily_returns) if daily_returns else 0

    max_drawdown = 0
    peak = historical_data[0]["value"] if historical_data else 0
    for point in historical_data:
        if point["value"] > peak:
            peak = point["value"]
        drawdown = ((peak - point["value"]) / peak) * 100 if peak > 0 else 0
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    winning_days = [pnl for pnl in daily_pnl if pnl > 0]
    losing_days = [pnl for pnl in daily_pnl if pnl < 0]
    total_days = len(daily_pnl)
    win_rate = (len(winning_days) / total_days * 100) if total_days > 0 else 0

    avg_win = sum(winning_days) / len(winning_days) if winning_days else 0
    avg_loss = abs(sum(losing_days) / len(losing_days)) if losing_days else 0

    gross_profit = sum(winning_days) if winning_days else 0
    gross_loss = abs(sum(losing_days)) if losing_days else 0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0

    return {
        "best_day": best_day,
        "worst_day": worst_day,
        "max_drawdown": max_drawdown,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
    }


def transform_executions(executions: Sequence[Any]) -> list[dict[str, Any]]:
    transformed = []
    for execution in executions:
        exec_time = _get(execution, "execution_time")
        quantity = float(_get(execution, "quantity"))
        price = float(_get(execution, "price"))
        transformed.append(
            {
                "symbol": _get(execution, "symbol"),
                "side": _get(execution, "side"),
                "quantity": quantity,
                "price": price,
                "notional": quantity * price,
                "commission": float(_get(execution, "commissions_fees")),
                "date": exec_time.isoformat() if exec_time else None,
            }
        )
    return transformed


def transform_finalized(yesterday_positions: Sequence[Any], positions: Sequence[Any]) -> list[dict[str, Any]]:
    """Compare yesterday's positions to today's to surface closed/changed lots."""
    transformed = []
    for yesterday in yesterday_positions:
        symbol = _get(yesterday, "symbol")
        yesterday_qty = float(_get(yesterday, "quantity"))
        yesterday_price = float(_get(yesterday, "average_price"))

        today_pos = next((p for p in positions if _get(p, "symbol") == symbol), None)
        today_qty = float(_get(today_pos, "quantity")) if today_pos else 0
        today_price = float(_get(today_pos, "average_price")) if today_pos else yesterday_price

        if today_qty - yesterday_qty != 0:
            realized_pnl = float(_get(yesterday, "daily_realized_pnl") or 0)
            transformed.append(
                {
                    "symbol": symbol.replace(".v.0", ""),
                    "quantity": yesterday_qty,
                    "entryPrice": yesterday_price,
                    "exitPrice": today_price,
                    "realizedPnL": realized_pnl,
                }
            )
    return transformed


def float_or_default(value: Any, default: float = 0) -> float:
    return float(value) if value is not None else default


def compute_sharpe(annualized_return: float, volatility: float) -> float:
    return annualized_return / volatility if volatility > 0 else 0
