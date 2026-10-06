"""Portfolio stream names produced by the trading engine."""

from datetime import date, datetime, timezone

PORTFOLIO_STREAMS = ("qt", "system", "benchmark")

# The signed-in dashboard and every headline portfolio value show the engine's
# model/system book. QT remains an explicit review/edit stream and cannot become
# the landing view merely because a QT decision was published.
PRIMARY_STREAM = "system"

# The detail page selects positions independently of system financial reporting.
DEFAULT_POSITION_STREAM = "system"
POSITION_READ_STREAMS = ("system", "qt")

# Public portfolio history begins with the feature launch. Earlier engine
# records remain stored for audit and operational continuity, but they are not
# part of the investor-facing product history.
PORTFOLIO_LAUNCH_DATE = date(2026, 10, 1)


class InvalidPositionStream(ValueError):
    code = "invalid_position_stream"


def validate_position_stream(value):
    if value not in POSITION_READ_STREAMS:
        raise InvalidPositionStream("position_stream must be system or qt")
    return value


def current_utc_date():
    """The engine's calendar day for snapshots, writes, and editability."""
    return datetime.now(timezone.utc).date()
