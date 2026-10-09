"""Postgres-backed tests of the QT desk reads and writes.

Opt-in: see tests/qt_fixture.py (ALGOLENS_TEST_DATABASE_URL, localhost only).
The schema is new_algo_data's after migrations 021 (emulated), 022 and 023.
"""

from datetime import date, datetime, timezone

import pytest

from qt_fixture import qt_db, requires_db  # noqa: F401  (fixture)

pytestmark = requires_db

QT = "QT_CONSERVATIVE_PORTFOLIO"
MODEL = "QT_CONSERVATIVE_MODEL_PORTFOLIO"
STRATEGY = "LIVE_TREND_FOLLOWING"
SLEEVE = "TREND_FOLLOWING"
D1, D2 = date(2026, 10, 7), date(2026, 10, 8)


def _exec(factory, sql, params=()):
    with factory.setup.cursor() as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception:
            return None


def add_position(factory, book, day, symbol, qty, price=100.0, portfolio=QT, sleeve=SLEEVE,
                 moved_by=None):
    _exec(
        factory,
        """
        INSERT INTO trading.positions
            (symbol, quantity, average_price, daily_unrealized_pnl, daily_realized_pnl,
             last_update, updated_at, strategy_id, strategy_name, date, portfolio_id,
             portfolio_type, moved_by)
        VALUES (%s, %s, %s, 5, 1, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (symbol, qty, price, datetime(day.year, day.month, day.day, 18, tzinfo=timezone.utc),
         datetime(day.year, day.month, day.day, 18, tzinfo=timezone.utc), STRATEGY, sleeve,
         day, portfolio, book, moved_by),
    )


def add_results(factory, book, day, value, portfolio=QT):
    _exec(
        factory,
        """
        INSERT INTO trading.live_results
            (strategy_id, portfolio_id, date, config, current_portfolio_value,
             total_annualized_return, volatility, portfolio_type)
        VALUES (%s, %s, %s, %s, %s, 1, 10, %s)
        """,
        (STRATEGY, portfolio, day, '{"strategy_type": "%s"}' % STRATEGY, value, book),
    )


def add_execution(factory, book, day, exec_id, symbol, portfolio=QT):
    _exec(
        factory,
        """
        INSERT INTO trading.executions
            (portfolio_id, strategy_id, strategy_name, date, exec_id, symbol, side,
             quantity, price, execution_time, commissions_fees, portfolio_type)
        VALUES (%s, %s, %s, %s, %s, %s, 'BUY', 1, 100, %s, 1, %s)
        """,
        (portfolio, STRATEGY, SLEEVE, day, exec_id, symbol,
         datetime(day.year, day.month, day.day, 18, tzinfo=timezone.utc), book),
    )


def repo(factory):
    from algolens.infrastructure.portfolio.repositories import PostgresPortfolioRepository

    return PostgresPortfolioRepository(connection_factory=factory)


def registry(factory):
    from algolens.infrastructure.portfolio.strategy_registry import PostgresStrategyRegistry

    return PostgresStrategyRegistry(connection_factory=factory)


# --- A2: registry and portfolio-id reads -------------------------------------


def test_registry_carries_the_two_qt_portfolios_from_migration_023(qt_db):
    from algolens.domain.portfolio.registry import group_portfolios

    groups = group_portfolios(registry(qt_db).list(active_only=True))

    qt_group = next(g for g in groups if g["group"] == "qt_conservative")
    assert [(p["portfolio_id"], p["desk_editable"]) for p in qt_group["portfolios"]] == [
        (QT, True),
        (MODEL, False),
    ]
    equity = next(g for g in groups if g["group"] == "EQUITY_MR_PORTFOLIO")
    assert equity["portfolios"][0]["asset_class"] == "equity"
    assert equity["portfolios"][0]["desk_editable"] is False


def test_portfolio_read_serves_each_book_on_its_latest_date(qt_db):
    add_results(qt_db, "system", D2, 501000)
    add_results(qt_db, "qt", D2, 502000)
    add_position(qt_db, "system", D2, "ZC.v.0", 3)
    add_position(qt_db, "qt_proposal", D2, "ZC.v.0", 2)
    add_position(qt_db, "qt", D1, "ZC.v.0", 9)
    add_position(qt_db, "qt", D2, "ZC.v.0", 1, moved_by="cap")

    by_book = {
        book: repo(qt_db).fetch_portfolio_rows(QT, book=book, allow_fallback=False)
        for book in ("system", "qt_proposal", "qt")
    }

    assert {b: [float(p["quantity"]) for p in r.positions] for b, r in by_book.items()} == {
        "system": [3.0],
        "qt_proposal": [2.0],
        "qt": [1.0],
    }
    assert float(by_book["qt"].latest["current_portfolio_value"]) == 502000
    # qt_proposal has no results row of its own: the system row's numbers.
    assert float(by_book["qt_proposal"].latest["current_portfolio_value"]) == 501000


def test_portfolio_read_nets_sleeves_and_hides_flattened_symbols(qt_db):
    add_results(qt_db, "qt", D2, 500000)
    add_position(qt_db, "qt", D2, "ZC.v.0", 2, price=400, sleeve="A")
    add_position(qt_db, "qt", D2, "ZC.v.0", 1, price=430, sleeve="B")
    add_position(qt_db, "qt", D2, "ZS.v.0", 0)

    rows = repo(qt_db).fetch_portfolio_rows(QT, book="qt", allow_fallback=False)

    assert [(p["symbol"], float(p["quantity"]), float(p["average_price"])) for p in rows.positions] == [
        ("ZC.v.0", 3.0, 410.0)
    ]


def test_portfolio_read_falls_back_to_system_only_when_unnamed(qt_db):
    add_results(qt_db, "system", D2, 500000, portfolio=MODEL)
    add_position(qt_db, "system", D2, "ZC.v.0", 3, portfolio=MODEL)
    add_position(qt_db, "qt", D2, "ZC.v.0", 1, portfolio=QT)  # another portfolio's qt

    fallback = repo(qt_db).fetch_portfolio_rows(MODEL)
    exact = repo(qt_db).fetch_portfolio_rows(MODEL, book="qt", allow_fallback=False)

    assert (fallback.book, fallback.fell_back) == ("system", True)
    assert [p["symbol"] for p in fallback.positions] == ["ZC.v.0"]
    assert (exact.book, exact.fell_back, exact.positions) == ("qt", False, [])


def test_portfolio_read_scopes_executions_to_the_book(qt_db):
    add_results(qt_db, "qt", D2, 500000)
    add_position(qt_db, "qt", D2, "ZC.v.0", 1)
    add_execution(qt_db, "system", D2, "e1", "ZC.v.0")
    add_execution(qt_db, "qt", D2, "e1", "ZS.v.0")

    rows = repo(qt_db).fetch_portfolio_rows(QT, book="qt", allow_fallback=False)

    assert [e["symbol"] for e in rows.executions] == ["ZS.v.0"]


def test_portfolio_read_ignores_strategy_id(qt_db):
    # A book is found by its portfolio id; the strategy id is a description.
    add_results(qt_db, "qt", D2, 500000)
    _exec(
        qt_db,
        "UPDATE trading.live_results SET strategy_id = 'RENAMED', config = '{}'",
    )
    add_position(qt_db, "qt", D2, "ZC.v.0", 1)

    rows = repo(qt_db).fetch_portfolio_rows(QT, book="qt", allow_fallback=False)

    assert rows.latest is not None
    assert [p["symbol"] for p in rows.positions] == ["ZC.v.0"]
