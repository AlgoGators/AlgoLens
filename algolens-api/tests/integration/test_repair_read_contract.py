"""Real SQL regressions for composite identity and daily QT execution scope."""
from datetime import date, timedelta

import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from tests.integration.conftest import claim_schema, require_test_dsn
from tests.integration.test_position_snapshot_scoping import SCHEMA, STRATEGY, BOOK, _insert
from algolens.infrastructure.portfolio.repositories import PostgresPortfolioRepository


@pytest.fixture
def cursor():
    conn = psycopg2.connect(require_test_dsn())
    conn.autocommit = True
    with conn.cursor() as cur:
        claim_schema(cur)
        cur.execute(SCHEMA)
        cur.execute('''CREATE TABLE trading.executions (
            strategy_id TEXT, portfolio_id TEXT, portfolio_type TEXT, symbol TEXT,
            side TEXT, quantity NUMERIC, price NUMERIC, execution_time TIMESTAMPTZ,
            commissions_fees NUMERIC)''')
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        yield cur
    conn.close()


def test_current_and_previous_snapshots_keep_two_engine_names_for_same_symbol(cursor):
    for day in (date.today(), date.today() - timedelta(days=3)):
        _insert(cursor, 'ES', 2, 100, day)
        _insert(cursor, 'ES', 7, 100, day)
        cursor.execute("UPDATE trading.positions SET strategy_name = 'Slow' WHERE quantity = 7")
    reader = PostgresPortfolioRepository()
    current = reader._fetch_current_positions(cursor, STRATEGY, BOOK, has_portfolio_type=True)
    previous = reader._fetch_yesterday_positions(cursor, STRATEGY, BOOK, has_portfolio_type=True)
    assert {(r.get('strategy_name'), r['quantity']) for r in current} == {('Slow', 7), ('Trend Following', 2)}
    assert {r.get('date') for r in current} == {date.today()}
    assert {(r.get('strategy_name'), r['quantity']) for r in previous} == {('Slow', 7), ('Trend Following', 2)}


def test_executions_are_only_the_selected_utc_day_and_qt_stream(cursor):
    day = date(2026, 9, 18)
    for when, stream, symbol, book in [
        ('2026-09-18 00:00:00+00', 'qt', 'ES', BOOK),
        ('2026-09-18 23:59:59+00', 'qt', 'NQ', BOOK),
        ('2026-09-17 23:59:59+00', 'qt', 'OLD', BOOK),
        ('2026-09-19 00:00:00+00', 'qt', 'NEW', BOOK),
        ('2026-09-18 12:00:00+00', 'system', 'SYSTEM', BOOK),
        ('2026-09-18 12:00:00+00', 'qt', 'OTHER', 'OTHER')]:
        cursor.execute('''INSERT INTO trading.executions VALUES (%s,%s,%s,%s,'BUY',1,100,%s,0)''',
                       (STRATEGY, book, stream, symbol, when))
    reader = PostgresPortfolioRepository()
    rows = reader._fetch_recent_executions(cursor, STRATEGY, BOOK, day, has_portfolio_type=True)
    assert {r['symbol'] for r in rows} == {'ES', 'NQ'}


def test_legacy_execution_rows_are_not_guessed_to_be_qt(cursor):
    cursor.execute('ALTER TABLE trading.executions DROP COLUMN portfolio_type')
    cursor.execute('''INSERT INTO trading.executions VALUES (%s,%s,'UNKNOWN','BUY',1,100,now(),0)''', (STRATEGY, BOOK))
    rows = PostgresPortfolioRepository()._fetch_recent_executions(
        cursor, STRATEGY, BOOK, date.today(), has_portfolio_type=False)
    assert rows == []


def test_detail_reader_retains_date_and_identity_after_all_positions_close(cursor):
    from algolens.infrastructure.portfolio import repositories
    repositories._has_portfolio_type_cache.clear()
    cursor.execute('''CREATE TABLE trading.live_results (portfolio_id TEXT, config JSONB, date DATE);
                      CREATE TABLE trading.equity_curve (strategy_id TEXT, portfolio_id TEXT,
                          portfolio_type TEXT, timestamp TIMESTAMPTZ, equity NUMERIC)''')
    cursor.execute('INSERT INTO trading.live_results VALUES (%s,%s,%s)',
                   (BOOK, '{"strategy_type":"' + STRATEGY + '"}', date.today()))
    _insert(cursor, 'ES', 0, 100, date.today())

    class BorrowedConnection:
        def cursor(self):
            return cursor.connection.cursor(cursor_factory=RealDictCursor)

        def close(self):
            pass

    rows = PostgresPortfolioRepository(connection_factory=BorrowedConnection).fetch_detail_rows(STRATEGY, BOOK)
    assert rows.positions == []
    assert rows.position_date == date.today()
    assert rows.position_strategy_names == ('Trend Following',)
    assert rows.position_stream == 'qt'
    assert rows.execution_date == date.today()
    assert rows.executions_available is True
