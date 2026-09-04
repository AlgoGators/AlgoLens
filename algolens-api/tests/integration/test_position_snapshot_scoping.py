"""A position that closed must leave the current-positions view.

``trading.positions`` holds one row per open position per day. The engine
rewrites the day's rows on every run and writes nothing at all for a position
that closed -- not even a zero-quantity row (trade-ngin
``PostgresDatabase::store_positions``).

The current-positions query took the latest row per symbol with no date
predicate, so every symbol the strategy had ever held stayed in the view,
frozen at the last day it was open, under a heading that says "Today's
Positions". The ``quantity != 0`` guard did nothing: a closed position has no
row to be zero.

These tests run against real PostgreSQL because the bug was in SQL. A double
would have agreed with whatever the code asked for.
"""

import datetime

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

from tests.integration.conftest import claim_schema, require_test_dsn

from algolens.infrastructure.portfolio.repositories import (
    PostgresPortfolioRepository,
)

SCHEMA = """
CREATE TABLE trading.positions (
    id                   BIGSERIAL PRIMARY KEY,
    strategy_id          TEXT NOT NULL,
    strategy_name        TEXT,
    portfolio_id         TEXT NOT NULL,
    portfolio_type       TEXT,
    symbol               TEXT NOT NULL,
    quantity             NUMERIC NOT NULL,
    average_price        NUMERIC,
    daily_unrealized_pnl NUMERIC NOT NULL,
    daily_realized_pnl   NUMERIC NOT NULL,
    date                 DATE NOT NULL,
    last_update          TIMESTAMPTZ NOT NULL,
    updated_at           TIMESTAMPTZ
);
"""

STRATEGY = "LIVE_TREND_FOLLOWING"
BOOK = "CONSERVATIVE_PORTFOLIO"


def _insert(cur, symbol, quantity, price, day):
    cur.execute(
        """
        INSERT INTO trading.positions
          (strategy_id, strategy_name, portfolio_id, portfolio_type, symbol,
           quantity, average_price, daily_unrealized_pnl, daily_realized_pnl,
           date, last_update, updated_at)
        VALUES (%s, 'Trend Following', %s, 'qt', %s, %s, %s, 0, 0, %s, %s, %s)
        """,
        (STRATEGY, BOOK, symbol, quantity, price, day, day, day),
    )


@pytest.fixture
def cursor():
    dsn = require_test_dsn()
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    with conn.cursor() as cur:
        claim_schema(cur)
        cur.execute(SCHEMA)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        yield cur
    conn.close()


def test_a_position_closed_yesterday_is_not_a_position_today(cursor):
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)

    # Held on both days.
    _insert(cursor, "ES.v.0", 12, 5280.25, yesterday)
    _insert(cursor, "ES.v.0", 12, 5280.25, today)
    # Held yesterday only: closed, so the engine wrote no row for today.
    _insert(cursor, "ZB.v.0", 8, 119.50, yesterday)

    reader = PostgresPortfolioRepository()
    rows = reader._fetch_current_positions(cursor, STRATEGY, BOOK)

    symbols = [r["symbol"] for r in rows]
    assert symbols == ["ES.v.0"], (
        "ZB closed yesterday and has no row today; it must not appear in "
        "current positions, where it would also inflate total notional and "
        "every position weight"
    )


def test_current_positions_come_from_one_snapshot_not_many(cursor):
    """Mixing symbols across dates produces a book that never existed."""
    today = datetime.date.today()
    _insert(cursor, "ES.v.0", 12, 5280.25, today - datetime.timedelta(days=30))
    _insert(cursor, "NQ.v.0", 5, 18420.50, today - datetime.timedelta(days=10))
    _insert(cursor, "GC.v.0", 7, 2418.90, today)

    reader = PostgresPortfolioRepository()
    rows = reader._fetch_current_positions(cursor, STRATEGY, BOOK)

    assert [r["symbol"] for r in rows] == ["GC.v.0"]


def test_the_previous_snapshot_is_the_one_before_the_latest(cursor):
    """Not literally CURRENT_DATE - 1.

    Asking for yesterday's date meant the comparison had nothing to compare
    against every Monday and after every holiday: markets shut, no rows
    written, and the finalized-positions panel went blank with no explanation.
    """
    today = datetime.date.today()
    friday = today - datetime.timedelta(days=3)

    _insert(cursor, "ES.v.0", 12, 5280.25, friday)
    _insert(cursor, "ZB.v.0", 8, 119.50, friday)
    _insert(cursor, "ES.v.0", 12, 5280.25, today)

    reader = PostgresPortfolioRepository()
    previous = reader._fetch_yesterday_positions(cursor, STRATEGY, BOOK)

    assert sorted(r["symbol"] for r in previous) == ["ES.v.0", "ZB.v.0"]


def test_a_strategy_with_one_snapshot_has_no_previous_one(cursor):
    _insert(cursor, "ES.v.0", 12, 5280.25, datetime.date.today())

    reader = PostgresPortfolioRepository()
    assert reader._fetch_yesterday_positions(cursor, STRATEGY, BOOK) == []
