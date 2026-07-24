"""Portfolio data service.

Extracted from routes/portfolio.py, which previously mixed HTTP handling, raw SQL,
and ~150 lines of metric math in one 260-line function hardcoded to the trend-
following strategy. This module holds the data-access and computation logic as
small, testable, strategy-agnostic functions; the route layer stays thin.

Every function takes a strategy `cfg` (from services.strategy_registry) so nothing
here is tied to a specific strategy. All SQL is parameterized -- the internal
`strategy_type` is passed as a bind parameter, never string-formatted.
"""

import logging

from database import get_db_connection

logger = logging.getLogger(__name__)

# How close to the configured starting equity the first equity-curve point must be
# before we snap it to the round number (preserves the original behaviour).
_EQUITY_SNAP_TOLERANCE = 5000


# --- data access -------------------------------------------------------------


def _fetch_latest_live_results(cursor, strategy_type):
    cursor.execute(
        """
        SELECT * FROM trading.live_results
        WHERE config::jsonb->>'strategy_type' = %s
        ORDER BY date DESC
        LIMIT 1
        """,
        (strategy_type,),
    )
    return cursor.fetchone()


def _fetch_summary_row(cursor, strategy_type):
    cursor.execute(
        """
        SELECT current_portfolio_value, total_annualized_return,
               volatility, total_cumulative_return
        FROM trading.live_results
        WHERE config::jsonb->>'strategy_type' = %s
        ORDER BY date DESC
        LIMIT 1
        """,
        (strategy_type,),
    )
    return cursor.fetchone()


def _fetch_equity_curve(cursor, strategy_type):
    cursor.execute(
        """
        SELECT timestamp, equity
        FROM trading.equity_curve
        WHERE strategy_id = %s
        ORDER BY timestamp ASC
        """,
        (strategy_type,),
    )
    return cursor.fetchall()


def _fetch_current_positions(cursor, strategy_type):
    cursor.execute(
        """
        SELECT * FROM (
            SELECT DISTINCT ON (symbol)
                   symbol, quantity, average_price,
                   daily_unrealized_pnl, daily_realized_pnl
            FROM trading.positions
            WHERE strategy_id = %s
            AND quantity != 0
            ORDER BY symbol, updated_at DESC
        ) AS latest_positions
        ORDER BY ABS(quantity * average_price) DESC
        """,
        (strategy_type,),
    )
    return cursor.fetchall()


def _fetch_recent_executions(cursor):
    # NOTE: the executions table is not filtered by strategy here -- this preserves
    # the original behaviour, which assumed all executions belong to the single
    # live strategy. When a second live strategy is added this MUST be scoped by
    # strategy (executions needs a strategy_id column / join) or it will mix trades.
    cursor.execute(
        """
        SELECT symbol, side, quantity, price,
               execution_time, commissions_fees
        FROM trading.executions
        ORDER BY execution_time DESC
        LIMIT 100
        """
    )
    return cursor.fetchall()


def _fetch_yesterday_positions(cursor, strategy_type):
    cursor.execute(
        """
        SELECT DISTINCT ON (symbol)
               symbol, quantity, average_price,
               daily_unrealized_pnl, daily_realized_pnl, updated_at
        FROM trading.positions
        WHERE strategy_id = %s
        AND updated_at::date = (CURRENT_DATE - INTERVAL '1 day')::date
        ORDER BY symbol, updated_at DESC
        """,
        (strategy_type,),
    )
    return cursor.fetchall()


# --- pure transforms / computations ------------------------------------------


def _resolve_initial_equity(equity_curve, base_equity):
    """First equity-curve value, snapped to the configured starting equity when
    within tolerance; falls back to the configured value when there is no curve."""
    initial_equity = float(equity_curve[0]["equity"]) if equity_curve else base_equity
    if abs(initial_equity - base_equity) < _EQUITY_SNAP_TOLERANCE:
        initial_equity = base_equity
    return initial_equity


def _build_historical_data(equity_curve):
    return [
        {"date": point["timestamp"].isoformat(), "value": float(point["equity"])}
        for point in equity_curve
    ]


def _transform_positions(positions, current_value):
    transformed = []
    for pos in positions:
        notional = abs(float(pos["quantity"]) * float(pos["average_price"]))
        transformed.append(
            {
                "symbol": pos["symbol"],
                "name": pos["symbol"].replace(".v.0", ""),
                "shares": float(pos["quantity"]),
                "quantity": float(pos["quantity"]),
                "costBasis": float(pos["average_price"]),
                "currentValue": notional,
                "marketPrice": float(pos["average_price"]),
                "notional": notional,
                "percentOfTotal": (notional / current_value * 100)
                if current_value > 0
                else 0,
            }
        )
    return transformed


def _compute_return_stats(historical_data):
    """Best/worst day, drawdown, win rate and win/loss aggregates from the equity
    curve. Returns a dict; mirrors the original inline calculations exactly."""
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


def _transform_executions(executions):
    transformed = []
    for ex in executions:
        exec_time = ex["execution_time"]
        transformed.append(
            {
                "symbol": ex["symbol"],
                "side": ex["side"],
                "quantity": float(ex["quantity"]),
                "price": float(ex["price"]),
                "notional": float(ex["quantity"]) * float(ex["price"]),
                "commission": float(ex["commissions_fees"]),
                "date": exec_time.isoformat() if exec_time else None,
            }
        )
    return transformed


def _transform_finalized(yesterday_positions, positions):
    """Compare yesterday's positions to today's to surface closed/changed lots."""
    transformed = []
    for ypos in yesterday_positions:
        symbol = ypos["symbol"]
        yesterday_qty = float(ypos["quantity"])
        yesterday_price = float(ypos["average_price"])

        today_pos = next((p for p in positions if p["symbol"] == symbol), None)
        today_qty = float(today_pos["quantity"]) if today_pos else 0
        today_price = (
            float(today_pos["average_price"]) if today_pos else yesterday_price
        )

        if today_qty - yesterday_qty != 0:  # position changed
            realized_pnl = (
                float(ypos["daily_realized_pnl"]) if ypos["daily_realized_pnl"] else 0
            )
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


def _f(value, default=0):
    """float() a possibly-None DB numeric, defaulting when NULL."""
    return float(value) if value is not None else default


# --- public API --------------------------------------------------------------


def get_strategy_detail(cfg):
    """Build the full strategy detail payload for a registry config, or None if the
    strategy has no live_results yet."""
    strategy_type = cfg["strategy_type"]
    base_equity = cfg["initial_equity"]

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            latest = _fetch_latest_live_results(cursor, strategy_type)
            if not latest:
                logger.warning("[PORTFOLIO] No live_results for %s", strategy_type)
                return None

            equity_curve = _fetch_equity_curve(cursor, strategy_type)
            positions = _fetch_current_positions(cursor, strategy_type)
            executions = _fetch_recent_executions(cursor)
            yesterday_positions = _fetch_yesterday_positions(cursor, strategy_type)

        initial_equity = _resolve_initial_equity(equity_curve, base_equity)
        current_value = float(latest["current_portfolio_value"])
        total_return = current_value - initial_equity
        return_percent = (
            (total_return / initial_equity * 100) if initial_equity > 0 else 0
        )

        historical_data = _build_historical_data(equity_curve)
        transformed_positions = _transform_positions(positions, current_value)
        stats = _compute_return_stats(historical_data)
        transformed_executions = _transform_executions(executions)
        transformed_finalized = _transform_finalized(yesterday_positions, positions)

        volatility = float(latest["volatility"])
        ann_return = float(latest["total_annualized_return"])
        sharpe = (ann_return / volatility) if volatility > 0 else 0

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
                "dailyReturn": _f(latest["daily_return"]),
                "cumulativeReturn": return_percent,
                "annualizedReturn": ann_return,
                "grossLeverage": _f(latest["gross_leverage"]),
                "netLeverage": _f(latest["net_leverage"]),
                "portfolioLeverage": _f(latest["portfolio_leverage"]),
                "marginPosted": _f(latest["margin_posted"]),
                "equityToMarginRatio": _f(latest["equity_to_margin_ratio"]),
                "marginCushion": _f(latest["margin_cushion"]),
                "totalNotional": _f(latest["gross_notional"]),
                "unrealizedPnL": _f(latest["total_unrealized_pnl"]),
                "realizedPnL": _f(latest["total_realized_pnl"]),
                "totalCommissions": _f(latest["total_transaction_costs"]),
                "netPnL": total_return,
                "cashAvailable": _f(latest["cash_available"]),
                "currentPortfolioValue": current_value,
            },
        }
    finally:
        conn.close()


def get_strategy_summary(cfg):
    """Build the lightweight summary payload for the /strategies list, or None when
    the strategy has no live_results yet."""
    strategy_type = cfg["strategy_type"]
    base_equity = cfg["initial_equity"]

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            latest = _fetch_summary_row(cursor, strategy_type)
    finally:
        conn.close()

    if not latest:
        logger.warning("[PORTFOLIO] No summary live_results for %s", strategy_type)
        return None

    current_value = float(latest["current_portfolio_value"])
    return_percent = (
        ((current_value - base_equity) / base_equity * 100) if base_equity > 0 else 0
    )
    volatility = float(latest["volatility"])
    sharpe = (
        (float(latest["total_annualized_return"]) / volatility) if volatility > 0 else 0
    )

    return {
        "id": cfg["id"],
        "name": cfg["name"],
        "currentValue": current_value,
        "returnPercent": return_percent,
        "volatility": volatility,
        "sharpeRatio": sharpe,
        "annualizedReturn": float(latest["total_annualized_return"]),
    }
