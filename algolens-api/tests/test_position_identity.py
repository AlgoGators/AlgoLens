"""Exercise emitted repository SQL with a local relational fixture, no server.

SQLite supports this write's SQL except PostgreSQL placeholders and row locks.
Lock behavior is not claimed here; this pins identity selection and mutations.
"""
import sqlite3
import re
from datetime import date, timedelta

import pytest

from algolens.application.portfolio.ports import StrategyNameUnresolved
from algolens.domain.portfolio.position_edit import validate_position_payload
from algolens.infrastructure.portfolio.repositories import PostgresPortfolioRepository


class Cursor:
    def __init__(self, db):
        self.cursor = db.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cursor.close()

    def execute(self, sql, params):
        # Equivalent DISTINCT ON semantics for the legacy risk-book query.
        distinct = re.search(r'SELECT DISTINCT ON \(symbol\)(.*?)FROM(.*?)ORDER BY symbol, updated_at DESC', sql, re.S)
        if distinct:
            sql = ('SELECT * FROM (SELECT ' + distinct[1] +
                   ', ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY updated_at DESC) AS rn FROM ' +
                   distinct[2] + ') WHERE rn = 1')
        self.cursor.execute(sql.replace('%s', '?').replace('FOR UPDATE', '').replace('now()', 'CURRENT_TIMESTAMP'), params)

    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(row) for row in self.cursor.fetchall()]


class Connection:
    def __init__(self, db):
        self.db = db

    def cursor(self):
        return Cursor(self.db)

    def __enter__(self):
        self.db.__enter__()
        return self

    def __exit__(self, *args):
        return self.db.__exit__(*args)

    def close(self):
        pass  # fixture owns the local connection


@pytest.fixture
def book():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute("ATTACH DATABASE ':memory:' AS trading")
    db.executescript('''
      CREATE TABLE trading.positions (
        portfolio_id TEXT, strategy_id TEXT, strategy_name TEXT, date DATE,
        symbol TEXT, portfolio_type TEXT, quantity NUMERIC, average_price NUMERIC,
        daily_unrealized_pnl NUMERIC DEFAULT 0, daily_realized_pnl NUMERIC DEFAULT 0,
        last_update TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (portfolio_id,strategy_id,strategy_name,date,symbol,portfolio_type));
      CREATE TABLE trading.position_overrides (
        id INTEGER PRIMARY KEY, portfolio_id TEXT, user_id TEXT, source_app TEXT,
        strategy_id TEXT, symbol TEXT, before_state TEXT, after_state TEXT,
        reason TEXT, risk_check_result TEXT, overrode_risk BOOLEAN);
    ''')
    yield db
    db.close()


def seed(book, name, symbol, quantity, *, day=None, stream='qt', portfolio='BOOK'):
    book.execute('''INSERT INTO trading.positions
        (portfolio_id,strategy_id,strategy_name,date,symbol,portfolio_type,quantity,average_price,updated_at)
        VALUES (?, 'COMBINED', ?, ?, ?, ?, ?, 100, ?)''',
        (portfolio, name, day or date.today(), symbol, stream, quantity,
         '2099-01-01' if name == 'OTHER' else '2026-01-01'))
    book.commit()


def edit(book, **extra):
    payload = dict(strategy_id='combined', symbol='ES', quantity=7, reason='hedge')
    payload.update(extra)
    normalized = validate_position_payload(payload)
    return PostgresPortfolioRepository(connection_factory=lambda: Connection(book)).write_qt_position(
        'COMBINED', 'BOOK', normalized, '7', {'passed': True}, False)


def test_edit_binds_the_symbol_not_the_most_recent_unrelated_strategy(book):
    seed(book, 'TARGET', 'ES', 12)
    seed(book, 'OTHER', 'NQ', 99)
    edit(book)
    rows = [tuple(r) for r in book.execute('SELECT strategy_name,symbol,quantity FROM trading.positions ORDER BY strategy_name,symbol')]
    assert rows == [('OTHER', 'NQ', 99), ('TARGET', 'ES', 7)]


def test_same_symbol_in_two_strategies_is_refused_without_writing(book):
    seed(book, 'TARGET', 'ES', 12)
    seed(book, 'OTHER', 'ES', 99)
    with pytest.raises(StrategyNameUnresolved):
        edit(book)
    assert book.execute('SELECT count(*) FROM trading.position_overrides').fetchone()[0] == 0
    assert sorted(r[0] for r in book.execute('SELECT quantity FROM trading.positions')) == [12, 99]


def test_named_edit_keeps_the_other_strategy_and_uses_its_own_before_state(book):
    seed(book, 'TARGET', 'ES', 12)
    seed(book, 'OTHER', 'ES', 99)
    edit(book, strategy_name='TARGET')
    assert [tuple(r) for r in book.execute('SELECT strategy_name,quantity FROM trading.positions ORDER BY strategy_name')] == [('OTHER', 99), ('TARGET', 7)]
    import json
    audit = book.execute('SELECT before_state,after_state FROM trading.position_overrides').fetchone()
    assert json.loads(audit[0])['quantity'] == 12
    assert json.loads(audit[1])['strategy_name'] == 'TARGET'


def test_new_symbol_derives_the_only_current_qt_strategy(book):
    seed(book, 'TARGET', 'ES', 12)
    edit(book, symbol='NEW', average_price=200)
    assert tuple(book.execute("SELECT strategy_name,quantity FROM trading.positions WHERE symbol='NEW'").fetchone()) == ('TARGET', 7)


def test_new_symbol_in_a_multistrategy_book_requires_a_valid_explicit_name(book):
    seed(book, 'TARGET', 'ES', 12)
    seed(book, 'OTHER', 'NQ', 99)
    with pytest.raises(StrategyNameUnresolved):
        edit(book, symbol='NEW', average_price=200)
    with pytest.raises(StrategyNameUnresolved):
        edit(book, symbol='NEW', average_price=200, strategy_name='UNKNOWN')
    edit(book, symbol='NEW', average_price=200, strategy_name='TARGET')
    assert tuple(book.execute("SELECT strategy_name,quantity FROM trading.positions WHERE symbol='NEW'").fetchone()) == ('TARGET', 7)


@pytest.mark.parametrize('name', [[], 7, '', '   '])
def test_strategy_name_must_be_a_nonempty_string(name):
    from algolens.domain.portfolio.position_edit import PositionValidationError
    with pytest.raises(PositionValidationError):
        validate_position_payload(dict(strategy_id='combined', symbol='ES', quantity=7,
                                       reason='hedge', strategy_name=name))


def test_named_risk_projection_replaces_only_the_intended_strategy():
    from algolens.domain.portfolio.position_edit import evaluate_risk, with_known_price
    rows = [dict(symbol='ES', strategy_name='TARGET', quantity=12, average_price=100, notional=1200),
            dict(symbol='ES', strategy_name='OTHER', quantity=99, average_price=200, notional=9900)]
    proposal = dict(symbol='ES', strategy_name='TARGET', quantity=0, average_price=None, notional=0)
    assert with_known_price(list(reversed(rows)), proposal)['average_price'] == 100
    verdict = evaluate_risk({'max_gross_notional': 9000}, rows, proposal)
    assert verdict['breaches'][0]['actual'] == 9900


def test_risk_book_keeps_both_current_strategy_identities_and_excludes_old_rows(book):
    seed(book, 'TARGET', 'ES', 12)
    seed(book, 'OTHER', 'ES', 99)
    seed(book, 'TARGET', 'OLD', 15, day=date.today()-timedelta(days=1))
    seed(book, 'TARGET', 'CLOSED', 0)
    rows = PostgresPortfolioRepository(connection_factory=lambda: Connection(book)).fetch_qt_book('COMBINED', 'BOOK')
    assert sorted((r.get('strategy_name'), r['symbol'], r['quantity']) for r in rows) == [('OTHER', 'ES', 99), ('TARGET', 'CLOSED', 0), ('TARGET', 'ES', 12)]


@pytest.mark.parametrize('foreign', [dict(stream='system'), dict(day=date.today()-timedelta(days=1)), dict(portfolio='OTHER')])
def test_wrong_stream_date_or_book_cannot_supply_identity(book, foreign):
    seed(book, 'TARGET', 'ES', 12, **foreign)
    with pytest.raises(StrategyNameUnresolved):
        edit(book, average_price=100)
    assert book.execute('SELECT count(*) FROM trading.position_overrides').fetchone()[0] == 0
