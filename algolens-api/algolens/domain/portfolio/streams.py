"""Portfolio stream names produced by the trading engine."""

from datetime import datetime, timezone

PORTFOLIO_STREAMS = ("qt", "system", "benchmark")

# Headline dashboard values represent the real book.
PRIMARY_STREAM = "qt"


def current_utc_date():
    """The engine's calendar day for snapshots, writes, and editability."""
    return datetime.now(timezone.utc).date()
