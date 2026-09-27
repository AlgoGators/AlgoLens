"""Real SQL regressions for composite identity and daily QT execution scope."""
from datetime import date, timedelta

import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from tests.integration.conftest import claim_schema, require_test_dsn
from tests.integration.test_position_snapshot_scoping import SCHEMA, STRATEGY, BOOK, _insert
from algolens.infrastructure.portfolio.repositories import PostgresPortfolioRepository
from algolens.infrastructure.portfolio import repositories


@pytest.fixture
def cursor():
    conn = psycopg2.connect(require_test_dsn())
    conn.autocommit = True
    with conn.cursor() as cur:
        claim_schema(cur)
        repositories._has_portfolio_type_cache.clear()
        repositories._has_portfolio_type_expires_at = 0
        cur.execute(SCHEMA)
        cur.execute('''CREATE TABLE trading.executions (
            strategy_id TEXT, portfolio_id TEXT, portfolio_type TEXT, symbol TEXT,
            side TEXT, quantity NUMERIC, price NUMERIC, execution_time TIMESTAMPTZ,
            commissions_fees NUMERIC)''')
        cur.execute('''CREATE TABLE trading.live_results (
            portfolio_id TEXT, config JSONB, portfolio_type TEXT, date DATE,
            current_portfolio_value NUMERIC, total_annualized_return NUMERIC,
            volatility NUMERIC, total_cumulative_return NUMERIC)''')
        cur.execute('''CREATE TABLE trading.equity_curve (
            strategy_id TEXT, portfolio_id TEXT, portfolio_type TEXT,
            timestamp TIMESTAMPTZ, equity NUMERIC)''')
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
    _result(cursor, 'qt', date.today(), 200)
    _insert(cursor, 'ES', 0, 100, date.today())
    rows = _reader(cursor).fetch_detail_rows(STRATEGY, BOOK, "qt")
    assert rows.positions == []
    assert rows.position_date == date.today()
    assert rows.position_strategy_names == ('Trend Following',)
    assert rows.position_stream == 'qt'
    assert rows.execution_date == date.today()
    assert rows.executions_available is True


def _reader(cursor):
    class BorrowedConnection:
        def cursor(self):
            return cursor.connection.cursor(cursor_factory=RealDictCursor)

        def close(self):
            pass

    return PostgresPortfolioRepository(connection_factory=BorrowedConnection)


def _result(cursor, stream, day, value, strategy=STRATEGY, book=BOOK):
    cursor.execute('''INSERT INTO trading.live_results
        (portfolio_id, config, portfolio_type, date, current_portfolio_value,
         total_annualized_return, volatility, total_cumulative_return)
        VALUES (%s, %s, %s, %s, %s, 5, 2, 10)''',
        (book, '{"strategy_type":"' + strategy + '"}', stream, day, value))


def test_result_helpers_choose_qt_with_same_day_system_and_other_scope(cursor):
    day = date(2026, 9, 18)
    _result(cursor, 'system', day, 900)
    _result(cursor, 'qt', day, 200)
    _result(cursor, 'qt', day + timedelta(days=1), 800, book='OTHER')
    _result(cursor, 'qt', day + timedelta(days=1), 700, strategy='OTHER')
    reader = _reader(cursor)
    assert reader._fetch_latest_live_results(cursor, STRATEGY, BOOK)['current_portfolio_value'] == 200
    assert reader.fetch_summary_row(STRATEGY, BOOK)['current_portfolio_value'] == 200


def test_result_helpers_do_not_choose_newer_system_day(cursor):
    qt_day = date(2026, 9, 18)
    _result(cursor, 'qt', qt_day, 200)
    _result(cursor, 'system', qt_day + timedelta(days=1), 900)
    reader = _reader(cursor)
    assert reader._fetch_latest_live_results(cursor, STRATEGY, BOOK)['date'] == qt_day
    assert reader.fetch_summary_row(STRATEGY, BOOK)['current_portfolio_value'] == 200


def test_qt_result_absent_and_legacy_result_unattributed(cursor):
    _result(cursor, 'system', date(2026, 9, 18), 900)
    reader = _reader(cursor)
    assert reader.fetch_summary_row(STRATEGY, BOOK) is None
    assert reader.fetch_detail_rows(STRATEGY, BOOK).latest is None

    cursor.execute('ALTER TABLE trading.live_results DROP COLUMN portfolio_type')
    repositories._has_portfolio_type_cache.clear()
    repositories._has_portfolio_type_expires_at = 0
    assert reader.fetch_summary_row(STRATEGY, BOOK) is None
    assert reader.fetch_detail_rows(STRATEGY, BOOK).latest is None


def test_qt_snapshot_survives_missing_result_without_borrowing_system_execution_day(cursor):
    today = date.today()
    _result(cursor, 'system', today, 900)
    _insert(cursor, 'ES', 2, 100, today - timedelta(days=1))
    _insert(cursor, 'NQ', 3, 100, today)
    cursor.execute('''INSERT INTO trading.equity_curve VALUES (%s,%s,'qt',%s,123)''',
                   (STRATEGY, BOOK, today))
    cursor.execute('''INSERT INTO trading.executions VALUES (%s,%s,'qt','NQ','BUY',1,100,%s,0)''',
                   (STRATEGY, BOOK, today))
    rows = _reader(cursor).fetch_detail_rows(STRATEGY, BOOK, "qt")
    assert rows.latest is None
    assert [row['symbol'] for row in rows.positions] == ['NQ']
    assert rows.position_date == today
    assert rows.position_strategy_names == ('Trend Following',)
    assert rows.position_stream == 'qt'
    assert rows.equity_curve[0]['equity'] == 123
    assert [row['symbol'] for row in rows.yesterday_positions] == ['ES']
    assert rows.execution_date is None
    assert rows.executions == []
    assert rows.executions_available is False


def test_detail_execution_day_uses_qt_result_even_with_newer_system_result(cursor):
    qt_day = date(2026, 9, 18)
    system_day = qt_day + timedelta(days=1)
    _result(cursor, 'qt', qt_day, 200)
    _result(cursor, 'system', system_day, 900)
    _insert(cursor, 'NQ', 3, 100, system_day)
    for day, symbol in ((qt_day, 'QT_DAY'), (system_day, 'SYSTEM_DAY')):
        cursor.execute('''INSERT INTO trading.executions VALUES
            (%s,%s,'qt',%s,'BUY',1,100,%s,0)''',
            (STRATEGY, BOOK, symbol, day))

    rows = _reader(cursor).fetch_detail_rows(STRATEGY, BOOK, "qt")
    assert rows.latest['current_portfolio_value'] == 200
    assert rows.execution_date == qt_day
    assert [row['symbol'] for row in rows.executions] == ['QT_DAY']
    assert rows.position_date == system_day


def test_zero_quantity_qt_snapshot_without_result_retains_engine_identity(cursor):
    _insert(cursor, 'ES', 0, 100, date.today())
    rows = _reader(cursor).fetch_detail_rows(STRATEGY, BOOK, "qt")
    assert rows.latest is None
    assert rows.positions == []
    assert rows.position_date == date.today()
    assert rows.position_strategy_names == ('Trend Following',)
    assert rows.position_stream == 'qt'
    assert rows.execution_date is None


def _stream_position(cursor, stream, day, name, symbol, quantity):
    cursor.execute('''INSERT INTO trading.positions
        (strategy_id, strategy_name, portfolio_id, portfolio_type, symbol,
         quantity, average_price, daily_unrealized_pnl, daily_realized_pnl,
         date, last_update, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,100,0,0,%s,%s,%s)''',
        (STRATEGY, name, BOOK, stream, symbol, quantity, day, day, day))


def test_mixed_qt_component_identity_stays_uneditable(cursor):
    from algolens.application.portfolio.use_cases import build_strategy_detail

    today = date.today()
    _result(cursor, 'qt', today, 250000)
    _stream_position(cursor, 'qt', today, 'QT_DESK', 'ES', 2)
    _stream_position(cursor, 'qt', today, None, 'NQ', 1)
    rows = _reader(cursor).fetch_detail_rows(STRATEGY, BOOK, 'qt')
    detail = build_strategy_detail(dict(id='trendfollowing', name='Trend Following',
                                        description='', managers=[],
                                        initial_equity=200000), rows)

    assert set(rows.position_strategy_names) == {'QT_DESK', None}
    assert detail['positionsEditable'] is False
    assert 'identity' in detail['positionEditUnavailableReason'].lower()


def test_selected_stream_http_bytes_and_qt_activity_are_separate(
    cursor, client, monkeypatch, tmp_path,
):
    from flask_jwt_extended import create_access_token
    from app import app
    import algolens.adapters.http.portfolio as http
    from algolens.domain.portfolio.streams import current_utc_date

    qt_previous = date(2026, 9, 18)
    qt_day = date(2026, 9, 19)
    model_day = date(2026, 9, 20)
    _result(cursor, 'qt', qt_day, 250000)
    _result(cursor, 'system', model_day, 900000)
    for name, symbol, quantity in (
        ('MODEL_FAST', 'ES', 2), ('MODEL_SLOW', 'ES', 5),
        ('MODEL_ZERO', 'NQ', 0),
    ):
        _stream_position(cursor, 'system', model_day, name, symbol, quantity)
    _stream_position(cursor, 'qt', qt_previous, 'QT_DESK', 'ES', 17)
    _stream_position(cursor, 'qt', qt_previous, 'QT_OLD', 'ZN', 4)
    _stream_position(cursor, 'qt', qt_day, 'QT_DESK', 'ES', 17)
    _stream_position(cursor, 'qt', qt_day, 'QT_ZERO', 'GC', 0)
    cursor.execute('''INSERT INTO trading.executions VALUES
        (%s,%s,'qt','ES','BUY',1,100,%s,2)''', (STRATEGY, BOOK, qt_day))
    cursor.execute('''INSERT INTO trading.executions VALUES
        (%s,%s,'system','NQ','BUY',1,100,%s,2)''', (STRATEGY, BOOK, qt_day))

    reader = _reader(cursor)
    class Registry:
        def get(self, strategy_id):
            if strategy_id != 'trendfollowing':
                return None
            return dict(id=strategy_id, strategy_type=STRATEGY,
                        portfolio_id=BOOK, name='Trend Following',
                        description='', managers=[], initial_equity=200000)

        def books_for_strategy(self, strategy_id):
            return [BOOK]

    class Market:
        def latest_prices(self, symbols):
            return {'ES': 100, 'NQ': 100, 'ZN': 100, 'GC': 100}

        def contract_multipliers(self, symbols):
            return {'ES': 50, 'NQ': 50, 'ZN': 50, 'GC': 50}

    monkeypatch.setattr(http, 'create_portfolio_dependencies', lambda: (Registry(), reader))
    monkeypatch.setattr(http, 'create_market_data', lambda: Market())
    with app.app_context():
        token = create_access_token(identity='83', additional_claims={'role': 'general_member'})
    client.current_users.set('83', role='general_member')
    client.set_cookie('access_token_cookie', token)

    for stream, expected_names, expected_day, expected_quantities in (
        ('system', ['MODEL_FAST', 'MODEL_SLOW', 'MODEL_ZERO'], model_day, [2.0, 5.0]),
        ('qt', ['QT_DESK', 'QT_ZERO'], qt_day, [17.0]),
    ):
        query = None if stream == 'system' else {'position_stream': 'qt'}
        response = client.get('/portfolio/strategy/trendfollowing', query_string=query)
        assert response.status_code == 200
        detail = response.get_json()
        assert detail['positionStream'] == stream
        assert detail['positionDate'] == expected_day.isoformat()
        assert detail['positionStrategyNames'] == expected_names
        assert sorted(p['quantity'] for p in detail['positions']) == sorted(expected_quantities)
        assert detail['currentValue'] == 250000.0
        assert detail['activityStream'] == 'qt'
        assert detail['finalizedPositionsAvailable'] is True
        assert [(p['strategyName'], p['quantity']) for p in detail['finalizedPositions']] == [('QT_OLD', 4.0)]
        assert [e['symbol'] for e in detail['executions']] == ['ES']
        assert [p['percentOfTotal'] for p in detail['positions']] == (
            [None, None] if stream == 'system' else [34.0]
        )
        capture = tmp_path / f'issue83-backend-{stream}-http.json'
        capture.write_bytes(response.data)
        print(f'ISSUE83_HTTP_CAPTURE={capture}')

    # A later, synthetic current-day QT snapshot proves the positive edit
    # contract without altering either historical response captured above.
    qt_current_day = current_utc_date()
    assert qt_current_day > model_day
    _stream_position(cursor, 'qt', qt_current_day, 'QT_DESK', 'ES', 17)
    _stream_position(cursor, 'qt', qt_current_day, 'QT_ZERO', 'GC', 0)
    current_response = client.get('/portfolio/strategy/trendfollowing',
                                  query_string={'position_stream': 'qt'})
    assert current_response.status_code == 200
    current_detail = current_response.get_json()
    assert current_detail['positionStream'] == 'qt'
    assert current_detail['positionDate'] == qt_current_day.isoformat()
    assert current_detail['positionsEditable'] is True
    assert current_detail['activityStream'] == 'qt'
    current_capture = tmp_path / 'issue83-backend-qt-current-http.json'
    current_capture.write_bytes(current_response.data)
    print(f'ISSUE83_HTTP_CAPTURE={current_capture}')

    _stream_position(cursor, 'system', model_day + timedelta(days=1),
                     'MODEL_EMPTY', 'NQ', 0)
    empty = reader.fetch_detail_rows(STRATEGY, BOOK, 'system')
    assert empty.positions == []
    assert empty.position_date == model_day + timedelta(days=1)
    assert empty.position_strategy_names == ('MODEL_EMPTY',)
    assert empty.finalized_positions_available is True
    assert reader.fetch_detail_rows(STRATEGY, BOOK, 'qt').position_date == qt_current_day

    cursor.execute("DELETE FROM trading.positions WHERE portfolio_type = 'qt'")
    absent = reader.fetch_detail_rows(STRATEGY, BOOK, 'system')
    assert absent.positions == []
    assert absent.position_date == model_day + timedelta(days=1)
    assert absent.finalized_positions_available is False
    assert absent.executions and absent.latest['current_portfolio_value'] == 250000


def test_missing_results_table_is_an_error_not_a_legacy_unstreamed_result(cursor):
    cursor.execute('DROP TABLE trading.live_results')
    repositories._has_portfolio_type_cache.clear()
    repositories._has_portfolio_type_expires_at = 0
    with pytest.raises(psycopg2.errors.UndefinedTable):
        _reader(cursor).fetch_summary_row(STRATEGY, BOOK)
