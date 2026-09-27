"""Real native upstream transitions consumed by actual API SQL/proof code.

The reusable historical starting records are explicitly synthetic. Native
market admission/finalization and current-day confirmed processing are real.
"""
from decimal import Decimal
from pathlib import Path
import json
import sys

import pytest
from psycopg2.extras import RealDictCursor

ENGINE_TESTS = Path(__file__).resolve().parents[4] / 'trade-ngin-qt/tests/integration'
sys.path.insert(0, str(ENGINE_TESTS))
from test_qt_desk_upstream import upstream, invoke, OLD, OLD_INPUT, FINAL, MARKET, DECISION, ATTEMPT
from test_qt_desk_accounting import accounting
from test_qt_desk_storage import desk
from tests.integration.qt_native_schema import connection
from algolens.infrastructure.portfolio.qt_accounting_proof import (
    load_accounting_evidence, _verify_current_financial_rows, producer_prior_carries,
)
from algolens.infrastructure.portfolio.qt_finalization_proof import verified_finalization_successor

pytestmark = [pytest.mark.parametrize('desk', ['futures'], indirect=True),
              pytest.mark.parametrize('accounting', ['no_input'], indirect=True)]


def finalize(upstream):
    conn, market, _ = upstream
    result = invoke('--market', payload=market)
    assert result.returncode == 0, result.stdout + result.stderr
    result = invoke('--finalize', OLD, FINAL, MARKET)
    assert result.returncode == 0, result.stdout + result.stderr
    return conn, json.loads(result.stdout)


def evidence(conn, decision_id, input_id):
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute('SELECT * FROM trading.qt_decisions WHERE decision_id=%s', (decision_id,))
        decision = dict(cursor.fetchone())
        loaded = load_accounting_evidence(cursor, decision, input_id, current=True)
    return decision, loaded


def require(value):
    if not value: raise ValueError('unproven_accounting')


def current_read_evidence(conn, decision, preview, receipt):
    from algolens.infrastructure.portfolio.qt_workflow_repository import QtTransaction
    from algolens.infrastructure.portfolio.qt_evaluation_inputs import load_qt_evaluation_inputs
    from algolens.infrastructure.portfolio.qt_decision_read_repository import _publication_evidence
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            tx = QtTransaction(cursor, decision['book_id'], decision['created_by'])
            tx.lock_authorities([])
            tx.lock_registries(tx.registry_ids_for_book())
            tx.lock_books([])
            tx.lock_mutable(source_day=decision['source_day'])
            facts = tx.read_current_facts()
            inputs = load_qt_evaluation_inputs(tx, source_day=decision['source_day'],
                model_publication_id=decision['model_publication_id'], checked_at=facts['captured_at'])
            facts.update(inputs.read_set_overrides)
            return _publication_evidence(tx, {'decision': decision}, preview, receipt, facts)
    finally:
        conn.rollback()
        conn.autocommit = True


@pytest.mark.parametrize('timezone', ['UTC', 'America/New_York'])
@pytest.mark.parametrize('damage', ['equity', 'daily_timestamp'])
def test_native_finalization_sql_context_and_physical_rows(upstream, timezone, damage):
    conn, transition = finalize(upstream)
    with conn.cursor() as cursor: cursor.execute('SET TIME ZONE %s', (timezone,))
    decision, loaded = evidence(conn, OLD, OLD_INPUT)
    assert verified_finalization_successor(loaded, decision) == transition['after_financial']
    _verify_current_financial_rows(loaded, require, Decimal)
    original = json.dumps(loaded['payload'], sort_keys=True)
    with conn.cursor() as cursor:
        if damage == 'equity':
            cursor.execute("UPDATE trading.equity_curve SET equity=equity+1 WHERE portfolio_type='qt' AND timestamp=%s",
                           (str(decision['source_day']) + 'T00:00:00Z',))
        else:
            cursor.execute("UPDATE trading.live_results SET date=date+interval '1 second' WHERE portfolio_type='qt' AND date=%s",
                           (str(decision['source_day']) + 'T00:00:00Z',))
    _, changed = evidence(conn, OLD, OLD_INPUT)
    with pytest.raises(ValueError): _verify_current_financial_rows(changed, require, Decimal)
    assert json.dumps(changed['payload'], sort_keys=True) == original


def test_native_sourced_input_is_readable_by_actual_api_proof(upstream):
    conn, _ = finalize(upstream)
    input_id = 'd0000000-0000-4000-8000-000000000001'
    result = invoke('--sourced', DECISION, ATTEMPT, input_id, MARKET, 'qt-finalization/' + FINAL)
    assert result.returncode == 0, result.stdout + result.stderr
    decision, loaded = evidence(conn, DECISION, input_id)
    original = loaded['prior_accounting']['processing_context']
    assert str(original['decision']['decision_id']) == OLD
    assert str(original['observation']['observation_id']) == OLD_INPUT
    assert original['receipt']['status'] == 'processed'
    assert str(original['model_publication']['publication_id']) == str(original['decision']['model_publication_id'])
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute('SELECT * FROM trading.qt_execution_observations WHERE observation_id=%s', (input_id,))
        observation = dict(cursor.fetchone())
        cursor.execute('SELECT * FROM trading.qt_desk_receipts WHERE decision_id=%s', (DECISION,))
        receipt = dict(cursor.fetchone())
        cursor.execute('SELECT * FROM trading.qt_previews WHERE preview_id=%s', (decision['preview_id'],))
        preview = dict(cursor.fetchone())
    carries = producer_prior_carries({'accounting': loaded, 'decision': decision, 'observation': observation,
                                     'receipt': receipt, 'preview': preview})
    assert carries and all(row['actual_cash_cost_exact'] == '0' for row in carries.values())
    from algolens.infrastructure.portfolio.qt_decision_report_proof import processed_report_blocked_reasons
    from algolens.infrastructure.portfolio.qt_receipt_provenance import verified_receipt_chain
    current = current_read_evidence(conn, decision, preview, receipt)
    assert processed_report_blocked_reasons(current) == ()
    origin = verified_receipt_chain(decision['book_id'], decision['source_day'], [current],
                                   current['audits'], current['current_facts']['saved_accounting'])
    assert origin is not None and origin['choices']
