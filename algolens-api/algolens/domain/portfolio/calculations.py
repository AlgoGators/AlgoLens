"""Pure portfolio calculations and response-shape transforms."""

from collections.abc import Mapping, Sequence
from typing import Any

from algolens.domain.portfolio.instruments import base_symbol, notional


def _get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def resolve_initial_equity(
    equity_curve: Sequence[Any], base_equity: float | None
) -> float | None:
    """Use the true first equity point, falling back to configured base equity."""
    if equity_curve:
        return float(_get(equity_curve[0], "equity"))
    return base_equity


def build_historical_data(equity_curve: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        {"date": _get(point, "timestamp").isoformat(), "value": float(_get(point, "equity"))}
        for point in equity_curve
    ]


def transform_positions(
    positions: Sequence[Any],
    current_value: float,
    prices: Mapping[str, float] | None = None,
    multipliers: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    """One row per position, priced at the market.

    ``prices`` is the latest close per symbol from the market data pipeline and
    ``multipliers`` the contract size per root symbol. Both may be missing
    entries, and a missing entry produces an explicit unknown rather than a
    substitute:

    * ``marketPrice`` used to be the average entry price under a column
      labelled "Market Price". It is now the market price, or None.
    * ``notional`` used to be ``quantity x entry price``, omitting the contract
      size, which understated every futures exposure by the size of the
      contract. It is now ``quantity x price x contract size``, or None.

    ``costBasis`` remains the average entry price, which is what it always was.
    """
    prices = prices or {}
    multipliers = multipliers or {}
    transformed = []
    for pos in positions:
        quantity = float(_get(pos, "quantity"))
        raw_price = _get(pos, "average_price")
        average_price = float(raw_price) if raw_price is not None else None

        symbol = _get(pos, "symbol")
        root = base_symbol(symbol)
        market_price = prices.get(symbol)
        if market_price is None:
            market_price = prices.get(root)
        multiplier = multipliers.get(root)

        exposure = notional(quantity, market_price, multiplier)
        transformed.append(
            {
                "symbol": symbol,
                "name": root,
                "shares": quantity,
                "quantity": quantity,
                "costBasis": average_price,
                "priceUnknown": average_price is None,
                # Named for what they are. None means "not known", and every
                # consumer renders that as unknown rather than as zero.
                "marketPrice": market_price,
                "marketPriceUnknown": market_price is None,
                "contractMultiplier": multiplier,
                "multiplierUnknown": multiplier is None,
                "notional": exposure,
                "currentValue": exposure,
                "percentOfTotal": (
                    (exposure / current_value * 100)
                    if exposure is not None and current_value > 0
                    else None
                ),
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

    # None, not 0, when there is nothing to measure. "Best day 0.00%" is a
    # claim about a day; "no days yet" is not.
    best_day = max(daily_returns) if daily_returns else None
    worst_day = min(daily_returns) if daily_returns else None

    max_drawdown = 0.0 if historical_data else None
    peak = historical_data[0]["value"] if historical_data else 0
    for point in historical_data:
        if point["value"] > peak:
            peak = point["value"]
        drawdown = ((peak - point["value"]) / peak) * 100 if peak > 0 else 0
        if max_drawdown is not None and drawdown > max_drawdown:
            max_drawdown = drawdown

    winning_days = [pnl for pnl in daily_pnl if pnl > 0]
    losing_days = [pnl for pnl in daily_pnl if pnl < 0]
    total_days = len(daily_pnl)
    # These are computed over DAYS of the equity curve, not over trades. The
    # UI labels them accordingly.
    win_rate = (len(winning_days) / total_days * 100) if total_days > 0 else None

    avg_win = sum(winning_days) / len(winning_days) if winning_days else None
    avg_loss = abs(sum(losing_days) / len(losing_days)) if losing_days else None

    gross_profit = sum(winning_days) if winning_days else 0.0
    gross_loss = abs(sum(losing_days)) if losing_days else 0.0
    # A book with gains and no losses has an undefined profit factor, not a
    # profit factor of zero -- zero would say it never made money.
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    return {
        "best_day": best_day,
        "worst_day": worst_day,
        "max_drawdown": max_drawdown,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
    }


def transform_executions(
    executions: Sequence[Any], multipliers: Mapping[str, float] | None = None
) -> list[dict[str, Any]]:
    """One row per fill, with the traded value of each.

    ``notional`` was ``quantity x price``, which is the same contract-size
    omission that understated position exposure: four ES at 5,276 read as
    $21,104 where the contracts are worth $1,055,200. Without a contract size
    on file the value is unknown rather than understated.
    """
    multipliers = multipliers or {}
    transformed = []
    for execution in executions:
        exec_time = _get(execution, "execution_time")
        quantity = float(_get(execution, "quantity"))
        price = float(_get(execution, "price"))
        symbol = _get(execution, "symbol")
        multiplier = multipliers.get(base_symbol(symbol))
        transformed.append(
            {
                "symbol": symbol,
                "side": _get(execution, "side"),
                "quantity": quantity,
                "price": price,
                "notional": notional(quantity, price, multiplier),
                "contractMultiplier": multiplier,
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
        yesterday_price = float_or_none(_get(yesterday, "average_price"))

        today_pos = next((p for p in positions if _get(p, "symbol") == symbol), None)
        today_qty = float(_get(today_pos, "quantity")) if today_pos else 0
        # A lot that is gone today exited at a price nobody here knows; carrying
        # yesterday's entry price forward as the "exit" was a guess dressed as
        # a fill. Unknown is reported as unknown.
        today_price = float_or_none(_get(today_pos, "average_price")) if today_pos else None

        if today_qty - yesterday_qty != 0:
            realized_pnl = float_or_none(_get(yesterday, "daily_realized_pnl"))
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


def net_pnl(
    unrealized: float | None, realized: float | None, commissions: float | None
) -> float | None:
    """Unrealised plus realised, less costs. Unknown if any part is unknown.

    Summing what is known and calling the result "net" would report a partial
    figure as a complete one, which is the error this function exists to stop.
    """
    if unrealized is None or realized is None or commissions is None:
        return None
    return unrealized + realized - commissions


def published_or_computed(published: Any, computed: float | None) -> float | None:
    """The engine's own figure when it published one, else AlgoLens's.

    trade-ngin writes sharpe_ratio, sortino_ratio, max_drawdown, win_rate,
    avg_win, avg_loss, profit_factor, best_day and worst_day into
    trading.live_results every run (live_portfolio_runner.cpp:2930). AlgoLens
    computed all nine again, from the equity curve, and showed the results
    under the same names -- so the dashboard could disagree with the engine
    about the engine's own book, and nothing on screen would say which number
    the reader was looking at.

    The published value wins. The local computation stays as the fallback for
    a row written before the engine published that column, which is why it is
    not simply deleted.
    """
    if published is not None:
        return float(published)
    return computed


def float_or_none(value: Any) -> float | None:
    """A NULL from the engine stays unknown.

    `float_or_default` turned a NULL margin_posted, cash_available or leverage
    into 0.0, which the UI then rendered as a measurement: "$0 margin posted",
    "0.00x leverage". The engine had said nothing; the app said zero.
    """
    return float(value) if value is not None else None


def compute_sharpe(annualized_return: float | None, volatility: float | None) -> float | None:
    """Annualised return over volatility, with a ZERO risk-free rate.

    The engine does not publish a Sharpe ratio, so this is computed here from
    the two figures it does publish. No risk-free rate is subtracted because
    none is available from any source; the UI says so on the tile. A zero
    volatility makes the ratio undefined, and undefined is returned as None
    rather than as 0, which would read as "no risk-adjusted return".
    """
    if annualized_return is None or volatility is None or volatility <= 0:
        return None
    return annualized_return / volatility
