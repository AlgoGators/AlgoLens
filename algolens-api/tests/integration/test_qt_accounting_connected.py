"""Actual HTTP/native preview -> new accounting producer -> report -> release.

Reuse the existing whole-futures HTTP/report acceptance flow, replacing only
its explicitly synthetic execution-observation adapter with the real producer.
All market inputs and finalized prior-day source records remain synthetic.
"""
from copy import deepcopy
from datetime import date, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4
import psycopg2
from psycopg2.extras import Json
import pytest
from algolens.application.portfolio.qt_investor_publication import QtInvestorPublicationService
from algolens.infrastructure.portfolio.qt_investor_publication import QtInvestorPublicationRepository
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from tests.integration.test_qt_connected_workflow import connected_db, preview_db, a3_db, DESK, query
from tests.integration.test_qt_connected_multiowner import future_connected_db
from tests.integration.test_qt_investor_publication import grant, release, public
from tests.integration.test_qt_preview_evaluator import FIXTURE

INPUT = '90000000-0000-4000-8000-000000000061'


def digest(payload):
    return sha256(canonical_qt_input_bytes(payload)).hexdigest()


def accounting_schema(dsn):
    api = Path(__file__).resolve().parents[2]
    engine = api.parent.parent / 'trade-ngin-qt'
    # DDL contains PostgreSQL format-percent tokens, not DBAPI placeholders.
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute((api / 'migrations/006_qt_investor_publication.sql').read_text())
            cursor.execute((engine / 'migrations/017_desk_accounting_inputs.sql').read_text())
    query(dsn, """CREATE TABLE trading.executions (
        portfolio_id text, strategy_id text, strategy_name text, date date, symbol text,
        portfolio_type text, exec_id text, order_id text, side text, quantity numeric,
        price numeric, execution_time timestamptz, commissions_fees numeric,
        implicit_price_impact numeric, slippage_market_impact numeric,
        total_transaction_costs numeric, is_partial boolean,
        PRIMARY KEY(portfolio_id,strategy_id,exec_id,portfolio_type));
        CREATE TABLE trading.live_results (
        portfolio_id text,strategy_id text,date date,portfolio_type text,
        daily_pnl numeric,daily_realized_pnl numeric,daily_unrealized_pnl numeric,
        daily_transaction_costs numeric,total_pnl numeric,current_portfolio_value numeric,
        PRIMARY KEY(portfolio_id,strategy_id,date,portfolio_type));
        CREATE TABLE trading.equity_curve (
        portfolio_id text,strategy_id text,timestamp timestamptz,portfolio_type text,equity numeric,
        PRIMARY KEY(portfolio_id,strategy_id,timestamp,portfolio_type));""")


def accounting_input(dsn, preview, decision, previous_quantity):
    now = query(dsn, 'SELECT clock_timestamp()')[0][0]
    previous_day = (date.fromisoformat(preview['source_day']) - timedelta(days=1)).isoformat()
    key = {**preview['selection_rows'][0]['key'], 'portfolio_type': 'qt'}
    prior_key = {**key, 'date': previous_day}
    query(dsn, """INSERT INTO trading.positions
        (portfolio_id,strategy_id,strategy_name,date,symbol,portfolio_type,quantity,average_price,
         daily_unrealized_pnl,daily_realized_pnl,last_update)
        VALUES('BOOK','engine-one','ONE',%s,'FUT','qt',%s,100,0,0,%s);
        INSERT INTO trading.live_results(portfolio_id,strategy_id,date,portfolio_type,total_pnl,current_portfolio_value)
        VALUES('BOOK','engine-one',%s,'qt',20,1000);""", (previous_day, previous_quantity, now, previous_day))
    totals = [{'strategy_id': 'engine-one', 'equity_exact': '1000', 'total_pnl_exact': '20'}]
    final = {'schema_version': 'qt-finalized-accounting/v1', 'book_id': 'BOOK',
             'source_day': previous_day, 'previous_totals': totals}
    query(dsn, """INSERT INTO trading.qt_source_policies
        (book_id,purpose,enabled,version,producer_id,policy_version,allowed_override_codes)
        VALUES('BOOK','execution',true,1,'synthetic-real-accounting','accounting-v1','[]');
        INSERT INTO trading.qt_desk_finalization_sources
        (source_id,book_id,source_day,producer_id,policy_version,source_version,content_digest,payload)
        VALUES('synthetic-final','BOOK',%s,'synthetic-real-accounting','accounting-v1','final-v1',%s,%s);""",
        (previous_day, digest(final), Json(final)))
    payload = {'schema_version': 'qt-futures-accounting-input/v1',
        'decision_id': decision['decision_id'], 'book_id': 'BOOK', 'source_day': preview['source_day'],
        'previous_day': previous_day, 'accounting_source_id': 'synthetic-accounting',
        'prior_finalization_source_id': 'synthetic-final', 'timestamp': preview['source_day'] + 'T00:00:00Z',
        'currency': 'USD', 'previous_positions': [{'key': prior_key, 'quantity_exact': previous_quantity,
                                                  'average_price_exact': '100'}],
        'previous_totals': totals,
        'cost_config': {'explicit_fee_per_contract': '1.5', 'min_adv': '100',
                        'min_participation': '0', 'max_participation': '0.1'},
        'instruments': [{'symbol': 'FUT', 'price_exact': '101', 'adv_exact': '100000',
            'volatility_multiplier_exact': '1', 'source_id': 'synthetic-prior-close',
            'baseline_spread_ticks': '1', 'min_spread_ticks': '1', 'max_spread_ticks': '10',
            'spread_cost_multiplier': '0.5', 'max_impact_bps': '100', 'tick_size': '0.01',
            'point_value': '50', 'max_total_implicit_bps': '200'}]}
    query(dsn, """INSERT INTO trading.qt_desk_accounting_inputs
        (input_id,decision_id,producer_id,policy_version,source_version,as_of,valid_until,content_digest,payload)
        VALUES(%s,%s,'synthetic-real-accounting','accounting-v1','accounting-v1',%s,%s,%s,%s)""",
        (INPUT, decision['decision_id'], now - timedelta(seconds=1), now + timedelta(minutes=5),
         digest(payload), Json(payload)))


@pytest.mark.parametrize(('previous_quantity', 'optimizer_enabled'), [('5', False), ('7', False), ('5', True)])
def test_http_accounting_report_and_separate_release(future_connected_db, tmp_path, monkeypatch,
                                                    previous_quantity, optimizer_enabled):
    import tests.integration.test_qt_connected_multiowner as flow
    import tests.integration.test_qt_connected_workflow as adapters
    import algolens.adapters.http.qt_workflow as routes
    dsn = psycopg2.extensions.make_dsn(future_connected_db,
        options='-c timezone=' + ('America/New_York' if previous_quantity == '7' else 'UTC'))
    accounting_schema(dsn)
    captured = {}
    original_harness = flow.http_harness
    original_saved_components = flow.saved_components
    original_authority = flow.explicit_future_authority
    current_day = query(dsn, "SELECT max(date)::text FROM trading.positions WHERE portfolio_type='system'")[0][0]

    def prior_evidence(db):
        result = {}
        for table in ('positions', 'executions', 'live_results', 'equity_curve'):
            column = 'timestamp' if table == 'equity_curve' else 'date'
            bound = current_day + 'T00:00:00Z' if table == 'equity_curve' else current_day
            result[table] = query(db, 'SELECT to_jsonb(t)::text FROM trading.' + table +
                                 ' t WHERE ' + column + '<%s ORDER BY to_jsonb(t)::text', (bound,))
        for table in ('qt_desk_accounting_inputs', 'qt_desk_finalization_sources'):
            result[table] = query(db, 'SELECT to_jsonb(t)::text FROM trading.' + table +
                                 ' t ORDER BY to_jsonb(t)::text')
        return result

    def current_components(db):
        # The reused report acceptance compares only the selected day's book.
        # This producer also needs a prior-day book, checked separately below.
        return {key: value for key, value in original_saved_components(db).items() if key[3] == current_day}

    def authority(db, selection):
        # Governed evaluator wire times are canonical UTC. The application
        # connections retain New York time in the quiet-carry regression.
        original_authority(psycopg2.extensions.make_dsn(db, options='-c timezone=UTC'), selection)
        if optimizer_enabled:
            payload = deepcopy(query(db, 'SELECT payload FROM trading.qt_evaluation_snapshots ORDER BY snapshot_id DESC LIMIT 1')[0][0])
            template = json.loads(FIXTURE.read_text())['draft_diagnostic']
            inputs = payload['engine_inputs']
            risk = inputs['risk_inputs']
            optimizer = {key: deepcopy(value) for key, value in template['optimizer_inputs'].items()
                         if not key.startswith('expected_')}
            optimizer.update(valuation_time=risk['valuation_time'],
                             expected_observation_times=risk['expected_observation_times'],
                             closes=deepcopy(risk['closes']))
            optimizer['instruments'] = [{**optimizer['instruments'][0], **deepcopy(risk['valuations'][0])}]
            inputs.update(optimizer_policy=deepcopy(template['optimizer_policy']),
                          optimizer_config=deepcopy(template['optimizer_config']), optimizer_inputs=optimizer)
            query(db, """INSERT INTO trading.qt_evaluation_snapshots
                (book_id,source_day,model_publication_id,producer_id,policy_version,source_version,
                 as_of,valid_until,content_digest,payload)
                SELECT book_id,source_day,model_publication_id,producer_id,policy_version,
                    'synthetic-future-optimizer-v3',as_of,valid_until,%s,%s
                FROM trading.qt_evaluation_snapshots ORDER BY snapshot_id DESC LIMIT 1""",
                (digest(payload), Json(payload)))

    def harness(*args, **kwargs):
        result = original_harness(*args, **kwargs)
        browser, headers = result[1](101)
        captured['http'] = {'browser': browser, 'headers': headers}
        return result

    def seed_inputs(db, preview, decision, quantity):
        assert quantity == '7'
        captured.update(preview=deepcopy(preview), decision=deepcopy(decision))
        accounting_input(db, preview, decision, previous_quantity)
        captured['prior_evidence'] = prior_evidence(db)
        assert query(db, 'SELECT count(*) FROM trading.qt_execution_observations') == [(0,)]

    def process(decision):
        return subprocess.run([str(DESK), '--accounting', decision['decision_id'], str(uuid4()), INPUT],
                              capture_output=True, text=True, timeout=30, env=os.environ.copy())

    monkeypatch.setattr(flow, 'http_harness', harness)
    monkeypatch.setattr(flow, 'saved_components', current_components)
    monkeypatch.setattr(flow, 'explicit_future_authority', authority)
    monkeypatch.setattr(adapters, 'observe', seed_inputs)
    monkeypatch.setattr(flow, 'desk', process)
    monkeypatch.setattr(routes, '_publication_service', lambda: QtInvestorPublicationService(
        routes._read_service(), QtInvestorPublicationRepository(lambda: psycopg2.connect(dsn))))
    # Executes real HTTP fraction refusal, MODEL lineage, exact seven draft,
    # bundled evaluator, confirmation, native processing and byte-for-byte
    # report comparison with only current quantity cells changed.
    flow.test_actual_future_fraction_refuses_without_writes_then_whole_seven_publishes_and_renders(
        dsn, tmp_path, monkeypatch)
    assert prior_evidence(dsn) == captured['prior_evidence']
    assert query(dsn, 'SELECT count(*) FROM trading.desk_run_results') == [(1,)]
    diagnostics = query(dsn, 'SELECT payload FROM trading.desk_run_results')[0][0]['desk_diagnostics']
    model_distance = diagnostics['model_to_choice'][0]
    assert model_distance['model_quantity_exact'] == '4'
    assert model_distance['selected_quantity_exact'] == '7'
    assert model_distance['quantity_delta_exact'] == '3'
    assert model_distance['notional_delta_exact'] == '15150'
    assert model_distance['price_exact'] == '101' and model_distance['valuation_multiplier_exact'] == '50'
    assert diagnostics['execution_distance'][0]['execution_delta_exact'] == ('2' if previous_quantity == '5' else '0')
    assert diagnostics['controls_applied'] == []
    if optimizer_enabled:
        iterations = diagnostics['optimizer']['actual_iterations']
        assert type(iterations) is int and 0 <= iterations <= 100
        assert 'actual_iterations=' + str(iterations) in captured['preview']['evaluation']['optimizer']['trace']
        assert diagnostics['optimizer']['aggregate_recommendation']
    else:
        assert diagnostics['optimizer']['actual_iterations'] is None
    assert query(dsn, "SELECT count(*) FROM trading.executions WHERE portfolio_type='qt'") == [(1 if previous_quantity == '5' else 0,)]
    assert query(dsn, "SELECT count(*) FROM trading.live_results WHERE date=%s AND portfolio_type='qt'",
                 (captured['preview']['source_day'],)) == [(1,)]
    grant(dsn, public=True)
    assert public(captured['http'], captured['preview']).status_code == 404
    released = release(captured['http'], captured['decision'])
    assert released.status_code == 200, released.json
    assert [row['quantity_exact'] for row in released.json['snapshot']['positions']] == ['7']
    assert public(captured['http'], captured['preview']).json == released.json
    # Current readiness must keep proving the producer's actual financial rows.
    # The separately published immutable snapshot remains its original release.
    query(dsn, "UPDATE trading.equity_curve SET equity=equity+1 WHERE portfolio_type='qt' AND timestamp=%s",
          (captured['preview']['source_day'] + 'T00:00:00Z',))
    current = captured['http']['browser'].get('/portfolio/qt-decisions/' + captured['decision']['decision_id'])
    assert current.status_code == 200, current.json
    assert current.json['report_ready'] is False
    assert public(captured['http'], captured['preview']).json == released.json
