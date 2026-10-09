"""Postgres-backed check of the book-scoped positions read (AlgoLens#83).

Opt-in: runs only when ALGOLENS_TEST_DATABASE_URL points at a THROWAWAY
Postgres on localhost. It DROPs and recreates a `trading` schema, so it refuses
any non-local host.
CI has no Postgres service, so it is skipped there; run it locally with e.g.

    docker run -d --rm --name al-pg -e POSTGRES_PASSWORD=test -p 55433:5432 postgres:16-alpine
    ALGOLENS_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55433/postgres \
        python -m pytest tests/test_positions_book_integration.py -q

The tables carry only the columns the reader touches, with the production key
(portfolio_id, strategy_id, strategy_name, date, symbol, portfolio_type).
"""

import os
from datetime import date, datetime

import pytest

DB_URL = os.environ.get("ALGOLENS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DB_URL, reason="ALGOLENS_TEST_DATABASE_URL not set (needs a throwaway Postgres)"
)


def _assert_local(url):
    from urllib.parse import urlparse

    host = urlparse(url).hostname
    assert host in {"localhost", "127.0.0.1", "::1"}, (
        f"refusing to drop the trading schema on non-local host {host!r}"
    )

STRATEGY = "LIVE_TREND_FOLLOWING"
PORTFOLIO = "P1"
D1, D2 = date(2026, 10, 6), date(2026, 10, 7)

SCHEMA = """
DROP SCHEMA IF EXISTS trading CASCADE;
CREATE SCHEMA trading;
CREATE TABLE trading.positions (
    portfolio_id TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_name TEXT NOT NULL DEFAULT 'tf',
    date DATE NOT NULL,
    symbol TEXT NOT NULL,
    portfolio_type TEXT NOT NULL DEFAULT 'system',
    quantity NUMERIC NOT NULL,
    average_price NUMERIC NOT NULL,
    daily_unrealized_pnl NUMERIC DEFAULT 0,
    daily_realized_pnl NUMERIC DEFAULT 0,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (portfolio_id, strategy_id, strategy_name, date, symbol, portfolio_type)
);
CREATE TABLE trading.equity_curve (
    strategy_id TEXT,
    portfolio_id TEXT,
    portfolio_type TEXT NOT NULL DEFAULT 'system',
    "timestamp" TIMESTAMP,
    equity NUMERIC
);
CREATE TABLE trading.executions (
    strategy_id TEXT, portfolio_id TEXT, symbol TEXT, side TEXT,
    quantity NUMERIC, price NUMERIC, execution_time TIMESTAMP,
    commissions_fees NUMERIC
);
CREATE TABLE trading.live_results (
    portfolio_id TEXT, config TEXT, date DATE
);
"""


@pytest.fixture
def conn_factory():
    import psycopg2
    from psycopg2.extras import RealDictCursor

    import algolens.infrastructure.portfolio.repositories as repo_module

    _assert_local(DB_URL)
    repo_module._has_portfolio_type_cache = None
    repo_module._has_portfolio_type_expires_at = 0

    setup = psycopg2.connect(DB_URL)
    setup.autocommit = True
    with setup.cursor() as cur:
        cur.execute(SCHEMA)
        cur.execute(
            "INSERT INTO trading.live_results VALUES (%s, %s, %s)",
            (PORTFOLIO, '{"strategy_type": "%s"}' % STRATEGY, D2),
        )

    def factory():
        return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)

    factory.setup = setup
    yield factory

    with setup.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS trading CASCADE")
    setup.close()
    repo_module._has_portfolio_type_cache = None


def _insert_position(factory, book, day, symbol, qty, price=100.0, portfolio=PORTFOLIO):
    with factory.setup.cursor() as cur:
        cur.execute(
            """
            INSERT INTO trading.positions
                (portfolio_id, strategy_id, date, symbol, portfolio_type,
                 quantity, average_price, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (portfolio, STRATEGY, day, symbol, book, qty, price,
             datetime(day.year, day.month, day.day, 18)),
        )


def _insert_equity(factory, book, day, equity):
    with factory.setup.cursor() as cur:
        cur.execute(
            """
            INSERT INTO trading.equity_curve
                (strategy_id, portfolio_id, portfolio_type, "timestamp", equity)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (STRATEGY, PORTFOLIO, book, datetime(day.year, day.month, day.day), equity),
        )


def _read(factory, book="qt", allow_fallback=True):
    from algolens.infrastructure.portfolio.repositories import PostgresPortfolioRepository

    return PostgresPortfolioRepository(connection_factory=factory).fetch_detail_rows(
        STRATEGY, PORTFOLIO, book=book, allow_fallback=allow_fallback
    )


def _symbols(rows):
    return sorted(p["symbol"] for p in rows.positions)


def test_zero_quantity_close_on_latest_date_hides_symbol(conn_factory):
    _insert_position(conn_factory, "qt", D1, "ES", 2)
    _insert_position(conn_factory, "qt", D1, "NQ", 1)
    _insert_position(conn_factory, "qt", D2, "ES", 0)  # flattened today
    _insert_position(conn_factory, "qt", D2, "NQ", 1)

    rows = _read(conn_factory, "qt", allow_fallback=False)

    assert _symbols(rows) == ["NQ"]


def test_symbol_absent_on_latest_date_is_not_carried_forward(conn_factory):
    _insert_position(conn_factory, "qt", D1, "CL", 3)
    _insert_position(conn_factory, "qt", D2, "NQ", 1)

    assert _symbols(_read(conn_factory, "qt", allow_fallback=False)) == ["NQ"]


def test_system_rows_are_not_returned_when_qt_is_requested(conn_factory):
    _insert_position(conn_factory, "system", D2, "ES", 5)
    _insert_position(conn_factory, "system", D2, "ZN", -4)
    _insert_position(conn_factory, "qt", D2, "ES", 3)
    _insert_equity(conn_factory, "system", D2, 999)
    _insert_equity(conn_factory, "qt", D2, 111)

    rows = _read(conn_factory)  # default request

    assert (rows.book, rows.fell_back) == ("qt", False)
    assert [(p["symbol"], float(p["quantity"])) for p in rows.positions] == [("ES", 3.0)]
    assert [float(r["equity"]) for r in rows.equity_curve] == [111.0]


def test_latest_date_is_per_book(conn_factory):
    # system has a later date than qt; qt must still read its own latest date.
    _insert_position(conn_factory, "qt", D1, "ES", 1)
    _insert_position(conn_factory, "system", D2, "NQ", 1)

    assert _symbols(_read(conn_factory, "qt", allow_fallback=False)) == ["ES"]


def test_default_falls_back_to_system_when_qt_has_no_rows(conn_factory):
    _insert_position(conn_factory, "system", D2, "ES", 5)
    _insert_equity(conn_factory, "system", D2, 999)
    # qt rows for ANOTHER portfolio must not count as "qt exists".
    _insert_position(conn_factory, "qt", D2, "ES", 1, portfolio="OTHER")

    rows = _read(conn_factory)

    assert (rows.book, rows.fell_back) == ("system", True)
    assert _symbols(rows) == ["ES"]
    assert [float(r["equity"]) for r in rows.equity_curve] == [999.0]


def test_explicit_qt_does_not_fall_back(conn_factory):
    _insert_position(conn_factory, "system", D2, "ES", 5)

    rows = _read(conn_factory, "qt", allow_fallback=False)

    assert (rows.book, rows.fell_back) == ("qt", False)
    assert rows.positions == []


def test_invalid_book_is_400_over_http(conn_factory, client, monkeypatch):
    import algolens.adapters.http.portfolio as portfolio_http
    from flask_jwt_extended import create_access_token

    from app import app

    called = []
    monkeypatch.setattr(
        portfolio_http,
        "create_portfolio_dependencies",
        lambda: called.append(1) or (None, None),
    )
    with app.app_context():
        token = create_access_token(identity="1", additional_claims={"role": "admin"})
    client.set_cookie("access_token_cookie", token)

    response = client.get("/portfolio/strategy/trendfollowing?book=benchmark")

    assert response.status_code == 400
