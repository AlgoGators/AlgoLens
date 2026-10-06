"""Synthetic native first-day processing consumed by the real API proof readers."""
from copy import deepcopy
from contextlib import closing
from decimal import Decimal
import sys

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor
from tests.qt_native_artifacts import require_native_artifact_paths

ENGINE_SOURCE = require_native_artifact_paths(allow_module_level=True).source_dir
import tests
tests.__path__ = [*tests.__path__, str(ENGINE_SOURCE / 'tests')]
sys.path.insert(0, str(ENGINE_SOURCE / 'tests/integration'))
from test_qt_first_day_accounting import (
    connection as native_connection, first_day, desk, process, DECISION, INPUT,
    test_real_first_day_finalizes_on_day_two_without_invented_predecessor as native_day_two,
)
from algolens.infrastructure.portfolio.qt_accounting_proof import (
    load_accounting_evidence, producer_prior_carries, _verify_current_financial_rows,
)
from algolens.infrastructure.portfolio.qt_finalization_proof import verified_finalization_successor
from algolens.infrastructure.portfolio.qt_original_processing_proof import verify_original_processing

pytestmark = pytest.mark.parametrize('connection', ['UTC', 'America/New_York'], indirect=True)


@pytest.fixture()
def connection(request):
    from tests.integration.conftest import OWNERSHIP_MARK, refuse_to_clobber_a_real_schema, require_test_dsn
    dsn = require_test_dsn()
    assert 'algolens_test_' in dsn and 'host=/tmp/algolens-repair-pg-' in dsn
    with closing(psycopg2.connect(dsn)) as control:
        control.autocommit = True
        with control.cursor() as cur:
            refuse_to_clobber_a_real_schema(cur)
    fixture = native_connection.__wrapped__(request)
    conn = next(fixture)
    try:
        with conn.cursor() as cur:
            cur.execute('COMMENT ON SCHEMA trading IS %s', (OWNERSHIP_MARK,))
        yield conn
    finally:
        fixture.close()
        conn.close()


def loaded_evidence(conn, decision_id=DECISION, input_id=INPUT):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT * FROM trading.qt_decisions WHERE decision_id=%s', (decision_id,))
        decision = dict(cur.fetchone())
        accounting = load_accounting_evidence(cur, decision, input_id, current=True)
        assert accounting is not None, 'first-day input must not disappear in predecessor INNER JOIN'
        cur.execute('SELECT * FROM trading.qt_previews WHERE preview_id=%s', (decision['preview_id'],))
        preview = dict(cur.fetchone())
        cur.execute('SELECT * FROM trading.qt_desk_receipts WHERE decision_id=%s', (decision_id,))
        receipt = dict(cur.fetchone())
        cur.execute('SELECT * FROM trading.qt_execution_observations WHERE observation_id=%s', (input_id,))
        observation = dict(cur.fetchone())
    return dict(accounting=accounting, decision=decision, preview=preview,
                receipt=receipt, observation=observation)


def current_publication_evidence(conn, evidence):
    from algolens.infrastructure.portfolio.qt_workflow_repository import QtTransaction
    from algolens.infrastructure.portfolio.qt_evaluation_inputs import load_qt_evaluation_inputs
    from algolens.infrastructure.portfolio.qt_decision_read_repository import _publication_evidence
    decision = evidence['decision']
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
            return _publication_evidence(tx, {'decision': decision}, evidence['preview'], evidence['receipt'], facts)
    finally:
        conn.rollback()
        conn.autocommit = True


@pytest.mark.parametrize('desk', ['futures', 'futures_quiet'], indirect=True)
def test_real_first_day_is_proven_with_inherited_financials(first_day):
    conn, _ = first_day
    result = process()
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = loaded_evidence(conn)
    carries = producer_prior_carries(evidence)
    assert len(carries) == (2 if not evidence['accounting']['payload']['executions'] else 0)
    verify_original_processing(evidence['accounting'])
    from algolens.infrastructure.portfolio.qt_decision_report_proof import processed_report_blocked_reasons
    from algolens.infrastructure.portfolio.qt_receipt_provenance import verified_receipt_chain
    current = current_publication_evidence(conn, evidence)
    assert processed_report_blocked_reasons(current) == ()
    decision = evidence['decision']
    chain = verified_receipt_chain(decision['book_id'], decision['source_day'], [current],
                                  current['audits'], current['current_facts']['saved_accounting'])
    assert chain is not None and chain['choices']
    damaged = deepcopy(evidence)
    damaged['accounting']['financial_rows']['live_results'][0]['total_transaction_costs'] += Decimal(1)
    with pytest.raises(ValueError):
        producer_prior_carries(damaged)


@pytest.mark.parametrize('desk', ['futures'], indirect=True)
@pytest.mark.parametrize('continue_day_two', [False, True])
def test_api_first_day_finalizes_on_day_two(first_day, monkeypatch, continue_day_two):
    # The settlement case stops before the separate native continuation test;
    # neither case substitutes a financial/anchor/proof implementation.
    if not continue_day_two:
        monkeypatch.setattr('test_qt_first_day_accounting.confirm_and_process_second_day', lambda *args: None)
    native_day_two(first_day)
    conn, _ = first_day
    evidence = loaded_evidence(conn)
    accounting = evidence['accounting']
    producer_prior_carries(evidence)
    verify_original_processing(accounting)
    actual = verified_finalization_successor(accounting, evidence['decision'])
    assert actual['live_results'][0]['daily_pnl_exact'] == '297'
    assert actual['live_results'][0]['daily_realized_pnl_exact'] == '299'
    assert actual['live_results'][0]['daily_unrealized_pnl_exact'] == '2.5'
    assert actual['live_results'][0]['total_transaction_costs_exact'] == '16'
    from algolens.infrastructure.portfolio.qt_finalization_proof import _digest
    for field, value in (('first_day_anchor_digest', '0'*64), ('first_day_anchor_id', 'other'),
                         ('predecessor_finalization_source_id', 'invented')):
        changed = deepcopy(accounting)
        changed['successor']['transition_row']['payload'][field] = value
        changed['successor']['transition_row']['content_digest'] = _digest(changed['successor']['transition_row']['payload'])
        with pytest.raises(ValueError):
            verified_finalization_successor(changed, evidence['decision'])
    for field, value in (('daily_pnl_exact', '296'), ('daily_realized_pnl_exact', '300'),
                         ('daily_unrealized_pnl_exact', '0'), ('total_transaction_costs_exact', '4')):
        changed = deepcopy(accounting)
        transition = changed['successor']['transition_row']
        transition['payload']['after_financial']['live_results'][0][field] = value
        transition['content_digest'] = _digest(transition['payload'])
        with pytest.raises(ValueError):
            verified_finalization_successor(changed, evidence['decision'])
    if not continue_day_two:
        return
    with conn.cursor() as cur:
        cur.execute('SELECT decision_id,input_id FROM trading.desk_run_results WHERE decision_id<>%s', (DECISION,))
        next_id, next_input = cur.fetchone()
    continuation = loaded_evidence(conn, next_id, next_input)
    assert continuation['accounting']['input_row']['payload']['schema_version'] == 'qt-futures-accounting-input/v2'
    assert continuation['accounting']['prior_accounting']['first_day_context']['anchor']['decision_id'] == DECISION
    assert len(producer_prior_carries(continuation)) == 2
    from algolens.infrastructure.portfolio.qt_decision_report_proof import processed_report_blocked_reasons
    assert processed_report_blocked_reasons(current_publication_evidence(conn, continuation)) == ()


@pytest.mark.parametrize('desk', ['futures'], indirect=True)
def test_first_day_proofs_reject_rehashed_authority_and_financial_tampering(first_day):
    from algolens.infrastructure.portfolio.qt_first_day_proof import verify_first_day_input
    from algolens.infrastructure.portfolio.qt_finalization_proof import _digest
    conn, _ = first_day
    result = process()
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = loaded_evidence(conn)
    row = evidence['accounting']
    mutations = [
        lambda r: r['first_day_context']['anchor']['payload']['bindings'].update(model_seed_digest='0'*64),
        lambda r: r['first_day_context']['anchor']['payload']['bindings'].update(config_digest='0'*64),
        lambda r: r['first_day_context']['anchor']['payload']['bindings'].update(schema_digest='0'*64),
        lambda r: r['first_day_context']['anchor']['payload']['bindings'].update(evaluator_sha256='0'*64),
        lambda r: r['first_day_context']['anchor']['payload']['bindings'].update(evaluation_snapshot_digest='0'*64),
        lambda r: r['first_day_context']['anchor']['payload']['bindings'].update(execution_policy_revision=2),
        lambda r: r['first_day_context']['anchor']['payload'].update(decision_id='00000000-0000-4000-8000-000000000009'),
        lambda r: r['input_row']['payload'].update(previous_day='2020-01-01'),
        lambda r: r['input_row']['payload'].update(currency='EUR'),
        lambda r: r['input_row']['payload']['instruments'][0].update(price_model_number='101'),
        lambda r: r['input_row']['payload']['previous_positions'][0]['key'].update(portfolio_type='system'),
        lambda r: r['input_row']['payload']['previous_totals'][0].update(equity_exact='1001'),
        lambda r: r['payload']['observation']['fills'][0].update(daily_realized_pnl_exact='0'),
        lambda r: r['payload']['live_results'][0].update(daily_pnl_exact='-4'),
        lambda r: r['payload']['live_results'][0].update(daily_transaction_costs_exact='4'),
        lambda r: r['payload']['live_results'][0].update(total_transaction_costs_exact='4'),
    ]
    for mutation in mutations:
        damaged = deepcopy(row)
        mutation(damaged)
        anchor = damaged['first_day_context']['anchor']
        anchor['content_digest'] = _digest(anchor['payload'])
        damaged['input_row']['payload']['first_day_anchor_digest'] = anchor['content_digest']
        damaged['input_row']['content_digest'] = _digest(damaged['input_row']['payload'])
        damaged['payload']['input_digest'] = damaged['input_row']['content_digest']
        damaged['content_digest'] = _digest(damaged['payload'])
        with pytest.raises(ValueError):
            verify_first_day_input(damaged, evidence['decision'])
