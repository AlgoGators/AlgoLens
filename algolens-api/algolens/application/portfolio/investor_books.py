"""Application boundary for an investor's automatically published system book."""

from datetime import datetime, timezone
from decimal import Decimal


def _stamp(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def _exact(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


class InvestorBookService:
    """Returns only rows bound to one durable system publication."""

    def __init__(self, repository):
        self.repository = repository

    def read(self, user_id, portfolio_id, source_day=None):
        raw = self.repository.read(user_id, portfolio_id, source_day)
        if raw is None:
            return None
        publication = raw["publication"]
        if publication.get("model_stream") != "system":
            return None

        positions = []
        for row in raw["positions"]:
            positions.append({
                "strategy_name": row["strategy_name"],
                "symbol": row["symbol"],
                "quantity_exact": _exact(row["quantity"]),
                "average_price_exact": _exact(row["average_price"]),
                "daily_realized_pnl_exact": _exact(row["daily_realized_pnl"]),
                "daily_unrealized_pnl_exact": _exact(row["daily_unrealized_pnl"]),
            })

        result_fields = (
            "current_portfolio_value", "total_cumulative_return",
            "total_annualized_return", "daily_return", "volatility",
            "sharpe_ratio", "sortino_ratio", "max_drawdown",
        )
        results = []
        for row in raw["results"]:
            item = {"strategy_id": row["strategy_id"]}
            item.update({name + "_exact": _exact(row.get(name)) for name in result_fields})
            results.append(item)

        equity = [{
            "timestamp": _stamp(row["timestamp"]),
            "equity_exact": _exact(row["equity"]),
        } for row in raw["equity"]]

        return {
            "schema_version": "system-investor-book/v1",
            "portfolio_id": publication["portfolio_id"],
            "source_day": str(publication["source_day"]),
            "model_stream": "system",
            "publication": {
                "publication_id": str(publication["publication_id"]),
                "content_digest": publication["content_digest"],
                "published_at": _stamp(publication["published_at"]),
            },
            "positions": positions,
            "results": results,
            "equity": equity,
        }
