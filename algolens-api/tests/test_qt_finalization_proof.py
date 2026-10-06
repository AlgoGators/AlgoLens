"""Synthetic immutable records exercise real finalization-proof arithmetic."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from datetime import datetime
from decimal import Decimal

import pytest

from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from algolens.infrastructure.portfolio.qt_finalization_proof import verified_finalization_successor
from algolens.domain.portfolio.qt_canonical import qt_digest_v1


def digest(value):
    return sha256(canonical_qt_input_bytes(value)).hexdigest()


def finalized_fixture():
    contract = json.loads((Path(__file__).parent / 'fixtures/qt_finalization_synthetic_v1.json').read_text())
    transition, market = deepcopy(contract['transition_payload']), deepcopy(contract['market_payload'])
    before = transition['before_financial']
    position = before['positions'][0]
    key = position['key']
    decision = {'decision_id': transition['decision_id'], 'book_id': 'BOOK', 'source_day': '2026-09-25'}
    previous_totals = [{'strategy_id': 'ENGINE', 'equity_exact': '1000', 'total_pnl_exact': '20'}]
    anchor = {'schema_version': 'qt-finalized-accounting/v1', 'book_id': 'BOOK',
              'source_day': '2026-09-24', 'previous_totals': previous_totals}
    original_input = {
        'schema_version': 'qt-futures-accounting-input/v1', **decision,
        'previous_day': '2026-09-24', 'prior_finalization_source_id': transition['predecessor_finalization_source_id'],
        'currency': 'USD', 'timestamp': '2026-09-25T00:00:00Z', 'previous_totals': previous_totals,
        'instruments': [{'symbol': 'SYN', 'price_exact': '100', 'point_value': '50',
                         'source_id': 'synthetic-close-2026-09-24'}],
    }
    execution = {'key': key, 'exec_id': 'QT_synthetic', 'order_id': 'QT_synthetic',
                 'side': 'BUY', 'quantity_exact': '1', 'price_exact': '100',
                 'execution_time': '2026-09-25T00:00:00Z', 'commissions_fees_exact': '2',
                 'implicit_price_impact_exact': '0', 'slippage_market_impact_exact': '0',
                 'total_transaction_costs_exact': '2'}
    fill = {name: value for name, value in position.items() if name != 'quantity_exact'}
    fill.update(selected_quantity_exact='5', observation_kind='executed', execution_id='QT_synthetic',
                actual_cash_cost_exact='2', currency='USD', accounting_source_id='synthetic-original')
    observation = {'schema_version': 'qt-execution/v2', **decision,
                   'accounting_input_id': transition['original_accounting_input_id'], 'fills': [fill],
                   'results': {'position_count': 1, 'currency_totals': [
                       {'currency': 'USD', 'actual_cash_cost_exact': '2',
                        'daily_realized_pnl_exact': '0', 'daily_unrealized_pnl_exact': '0'}]}}
    live = {name: value for name, value in before['live_results'][0].items()
            if name not in {'daily_realized_pnl_exact', 'daily_unrealized_pnl_exact'}}
    original_output = {'schema_version': 'qt-futures-accounting/v1',
                       'input_digest': digest(original_input), 'observation': observation,
                       'executions': [execution], 'live_results': [live]}
    identity = {'producer_id': 'synthetic-execution', 'policy_version': 'execution-policy-v1'}
    input_row = {'input_id': transition['original_accounting_input_id'], **identity,
                 'decision_id': decision['decision_id'], 'payload': original_input,
                 'content_digest': digest(original_input)}
    final_row = {'source_id': transition['predecessor_finalization_source_id'], **identity,
                 'book_id': 'BOOK', 'source_day': '2026-09-24', 'payload': anchor,
                 'content_digest': digest(anchor)}
    market_row = {'source_id': transition['market_source_id'], 'book_id': 'BOOK',
                  'source_day': '2026-09-26', 'model_publication_id': market['model_publication_id'],
                  **identity, 'source_version': 'synthetic-market-v1',
                  'policy_revision': 1,
                  'as_of': '2026-09-26T00:00:00Z', 'valid_until': '2026-09-26T02:00:00Z',
                  'payload': market, 'content_digest': digest(market)}
    transition.update(original_run_result_digest=digest(original_output),
                      original_observation_digest=digest(observation),
                      predecessor_finalization_digest=digest(anchor),
                      unchanged_execution_digest=digest([execution]),
                      market_source_digest=digest(market))
    transition_row = {'finalization_id': transition['finalization_id'], 'decision_id': decision['decision_id'],
                      'market_source_id': market_row['source_id'], 'book_id': 'BOOK',
                      'source_day': '2026-09-25', 'valuation_day': '2026-09-26', **identity,
                      'policy_revision': 1,
                      'created_at': '2026-09-26T01:00:00Z',
                      'input_digest': digest(original_input), 'output_digest': digest(original_output),
                      'payload': transition, 'content_digest': digest(transition)}
    accounting = {'decision_id': decision['decision_id'], 'portfolio_id': 'BOOK', 'date': '2026-09-25',
                  'input_id': input_row['input_id'], 'payload': original_output,
                  'content_digest': digest(original_output), 'input_row': input_row,
                  'finalization_row': final_row, 'successor': {'transition_row': transition_row,
                  'market_row': market_row, 'model_publication': {
                      'publication_id': market['model_publication_id'], 'portfolio_id': 'BOOK',
                      'source_day': '2026-09-26', 'system_components': [],
                      'seed_digest': qt_digest_v1({'seed_rows': []})}}}
    return accounting, decision


def test_proven_finalization_changes_only_linked_pnl_and_equity():
    accounting, decision = finalized_fixture()
    frozen = deepcopy(accounting)
    after = verified_finalization_successor(accounting, decision)
    assert after == accounting['successor']['transition_row']['payload']['after_financial']
    assert after['positions'][0]['quantity_exact'] == '5'
    assert after['positions'][0]['average_price_exact'] == '90'
    assert after['positions'][0]['daily_realized_pnl_exact'] == '250'
    assert after['live_results'][0]['daily_pnl_exact'] == '248'
    assert after['equity_curve'][0]['equity_exact'] == '1248'
    assert accounting == frozen


def test_absent_successor_keeps_original_proof_required():
    accounting, decision = finalized_fixture()
    del accounting['successor']
    assert verified_finalization_successor(accounting, decision) is None


@pytest.mark.parametrize('part', [
    'quantity', 'basis', 'double_cost', 'mark_source', 'basis_as_reference', 'missing_owner',
    'duplicate_owner', 'execution_digest', 'original_digest', 'lease', 'publication',
    'policy', 'market_digest', 'timestamp', 'row_input_digest', 'row_output_digest',
    'row_policy_revision', 'market_policy_revision', 'original_producer', 'original_policy_version', 'late_finalization',
])
def test_self_consistent_hash_does_not_authorize_a_forged_successor(part):
    accounting, decision = finalized_fixture()
    successor = accounting['successor']
    row = successor['transition_row']
    payload = row['payload']
    if part == 'quantity': payload['after_financial']['positions'][0]['quantity_exact'] = '7'
    elif part == 'basis': payload['after_financial']['positions'][0]['average_price_exact'] = '100'
    elif part == 'double_cost': payload['after_financial']['live_results'][0]['daily_pnl_exact'] = '246'
    elif part == 'mark_source': payload['components'][0]['settlement_source_id'] = 'other-close'
    elif part == 'basis_as_reference': payload['components'][0]['reference_price_model_number'] = '90'
    elif part == 'missing_owner': payload['components'] = []
    elif part == 'duplicate_owner': payload['components'].append(deepcopy(payload['components'][0]))
    elif part == 'execution_digest': payload['unchanged_execution_digest'] = '0' * 64
    elif part == 'original_digest': payload['original_run_result_digest'] = '0' * 64
    elif part == 'lease': row['created_at'] = '2026-09-26T03:00:00Z'
    elif part == 'publication': successor['model_publication']['portfolio_id'] = 'OTHER'
    elif part == 'policy': payload['policy_identity']['producer_id'] = 'unrelated'
    elif part == 'market_digest': payload['market_source_digest'] = '0' * 64
    elif part == 'timestamp': payload['after_financial']['positions'][0]['last_update'] = '2026-09-25T00:00:00Z'
    elif part == 'row_input_digest': row['input_digest'] = '0' * 64
    elif part == 'row_output_digest': row['output_digest'] = '0' * 64
    elif part == 'row_policy_revision': row['policy_revision'] = 2
    elif part == 'market_policy_revision': successor['market_row']['policy_revision'] = 2
    elif part == 'original_producer': accounting['input_row']['producer_id'] = 'different-producer'
    elif part == 'original_policy_version': accounting['input_row']['policy_version'] = 'different-version'
    elif part == 'late_finalization':
        row['created_at'] = '2026-09-27T01:00:00Z'
        successor['market_row']['valid_until'] = '2026-09-27T02:00:00Z'
    row['content_digest'] = digest(payload)
    with pytest.raises(ValueError, match='unproven_finalization'):
        verified_finalization_successor(accounting, decision)


def rehash(accounting):
    """Tamper cases keep hashes coherent so semantic checks must reject them."""
    inputs, output = accounting['input_row'], accounting['payload']
    successor = accounting['successor']
    row, market = successor['transition_row'], successor['market_row']
    payload = row['payload']
    inputs['content_digest'] = digest(inputs['payload'])
    output['input_digest'] = inputs['content_digest']
    accounting['content_digest'] = digest(output)
    market['content_digest'] = digest(market['payload'])
    row['input_digest'] = inputs['content_digest']
    row['output_digest'] = accounting['content_digest']
    payload.update(original_run_result_digest=accounting['content_digest'],
                   original_observation_digest=digest(output['observation']),
                   unchanged_execution_digest=digest(output['executions']),
                   market_source_digest=market['content_digest'])
    row['content_digest'] = digest(payload)


@pytest.mark.parametrize('part', ['missing_finance', 'extra_reference', 'wrong_live_scope'])
def test_original_financial_scope_must_be_complete_before_successor(part):
    accounting, decision = finalized_fixture()
    output = accounting['payload']
    transition = accounting['successor']['transition_row']['payload']
    if part == 'missing_finance':
        output['live_results'] = []
        for side in ('before_financial', 'after_financial'):
            transition[side]['live_results'] = []
            transition[side]['equity_curve'] = []
    elif part == 'extra_reference':
        reference = deepcopy(accounting['input_row']['payload']['instruments'][0])
        reference['symbol'] = 'UNUSED'
        accounting['input_row']['payload']['instruments'].append(reference)
    else:
        output['live_results'][0]['portfolio_id'] = 'OTHER'
        for side in ('before_financial', 'after_financial'):
            transition[side]['live_results'][0]['portfolio_id'] = 'OTHER'
    rehash(accounting)
    with pytest.raises(ValueError, match='unproven_finalization'):
        verified_finalization_successor(accounting, decision)


@pytest.mark.parametrize(('quantity', 'reference', 'reference_model', 'close', 'gross_model', 'gross', 'net', 'equity', 'total'), [
    ('29157344791', '100', '100', '100.01', '14578672395.507462',
     '14578672395.50746112', '14578672393.50746112', '14578673393.50746112', '14578672413.50746112'),
    ('5', '64943593822.49847298', '64943593822.49848', '64943593822.4985', '0.003814697265625',
     '0.0038147', '-1.9961853', '998.0038147', '18.0038147'),
])
def test_binary64_operands_reproduce_native_decimal_raw_conversion(
        quantity, reference, reference_model, close, gross_model, gross, net, equity, total):
    # Native Decimal::as_double() converts its exact int64 raw value to double
    # BEFORE dividing by 1e8. Parsing the decimal text directly differs here.
    accounting, decision = finalized_fixture()
    source = accounting['input_row']['payload']
    source['instruments'][0]['price_exact'] = reference
    accounting['payload']['executions'][0]['price_exact'] = reference
    accounting['payload']['observation']['fills'][0]['selected_quantity_exact'] = quantity
    successor = accounting['successor']
    successor['market_row']['payload']['instruments'][0]['price_model_number'] = close
    transition = successor['transition_row']['payload']
    for side in ('before_financial', 'after_financial'):
        transition[side]['positions'][0]['quantity_exact'] = quantity
    transition['components'][0].update(quantity_exact=quantity, reference_price_model_number=reference_model,
        settlement_price_model_number=close, gross_pnl_model_number=gross_model, gross_pnl_exact=gross)
    transition['engine_totals'][0].update(gross_pnl_model_number=gross_model, gross_pnl_exact=gross,
        net_pnl_exact=net, equity_exact=equity, total_pnl_exact=total)
    after = transition['after_financial']
    after['positions'][0]['daily_realized_pnl_exact'] = gross
    after['live_results'][0].update(daily_realized_pnl_exact=gross, daily_pnl_exact=net,
        current_portfolio_value_exact=equity, total_pnl_exact=total)
    after['equity_curve'][0]['equity_exact'] = equity
    rehash(accounting)
    assert verified_finalization_successor(accounting, decision) == after


def physical_financial_rows(accounting):
    output = accounting['payload']
    after = accounting['successor']['transition_row']['payload']['after_financial']
    executions = []
    for execution in output['executions']:
        row = {**execution['key'], 'is_partial': False}
        for name, value in execution.items():
            if name == 'key': continue
            if name.endswith('_exact'): row[name[:-6]] = Decimal(value)
            elif name == 'execution_time': row[name] = datetime.fromisoformat(value.replace('Z', '+00:00'))
            else: row[name] = value
        executions.append(row)
    results = [{(name[:-6] if name.endswith('_exact') else name):
                (Decimal(value) if name.endswith('_exact') else value)
                for name, value in row.items()} for row in after['live_results']]
    equity = [{(name[:-6] if name.endswith('_exact') else name):
               (Decimal(value) if name.endswith('_exact') else value)
               for name, value in row.items()} for row in after['equity_curve']]
    return {'executions': executions, 'live_results': results, 'equity_curve': equity}


@pytest.mark.parametrize('tamper', [None, 'execution', 'equity', 'cost', 'missing_successor'])
def test_physical_financial_proof_accepts_only_verified_successor(tamper):
    from algolens.infrastructure.portfolio.qt_accounting_proof import _verify_current_financial_rows
    accounting, decision = finalized_fixture()
    accounting['financial_rows'] = physical_financial_rows(accounting)
    if tamper == 'execution': accounting['financial_rows']['executions'][0]['quantity'] = Decimal(2)
    elif tamper == 'equity': accounting['financial_rows']['equity_curve'][0]['equity'] += 1
    elif tamper == 'cost': accounting['financial_rows']['live_results'][0]['daily_transaction_costs'] += 1
    elif tamper == 'missing_successor': del accounting['successor']
    def require(ok):
        if not ok: raise ValueError('unproven_accounting')
    if tamper:
        with pytest.raises(ValueError):
            _verify_current_financial_rows(accounting, require, Decimal)
    else:
        _verify_current_financial_rows(accounting, require, Decimal)


def finalized_receipt_fixture(monkeypatch):
    from tests.test_qt_decision_read import processed_fixture
    from algolens.domain.portfolio.qt_canonical import qt_digest_v1
    evidence = processed_fixture(monkeypatch)
    accounting, _ = finalized_fixture()
    decision, observation, preview = (evidence[name] for name in ('decision', 'observation', 'preview'))
    key = observation['payload']['fills'][0]['key']
    old_id = accounting['decision_id']
    def bind(value):
        if isinstance(value, list): return [bind(item) for item in value]
        if isinstance(value, dict):
            if set(value) == set(key): return deepcopy(key)
            return {name: bind(item) for name, item in value.items()}
        if value == old_id: return decision['decision_id']
        if value == 'ENGINE': return key['strategy_id']
        if value == 'SYN': return key['symbol']
        if value == 'execution-policy-v1': return observation['policy_version']
        return value
    accounting = bind(accounting)
    inputs = accounting['input_row']
    inputs.update(input_id=observation['observation_id'], as_of=observation['as_of'], valid_until=observation['valid_until'])
    inputs['source_version'] = observation['source_version'] = 'synthetic-accounting-source-v1'
    inputs['payload']['previous_positions'] = []
    accounting['input_id'] = observation['observation_id']
    output = accounting['payload']
    observed = deepcopy(observation['payload'])
    observed.update(schema_version='qt-execution/v2', accounting_input_id=observation['observation_id'])
    fill = observed['fills'][0]
    fill.update(daily_realized_pnl_exact='0', daily_unrealized_pnl_exact='0', last_update='2026-09-25T00:00:00Z')
    observed['results']['currency_totals'][0].update(daily_realized_pnl_exact='0', daily_unrealized_pnl_exact='0')
    output['observation'] = observation['payload'] = observed
    execution = output['executions'][0]
    execution.update(exec_id=fill['execution_id'], commissions_fees_exact='0.02', total_transaction_costs_exact='0.02')
    output['live_results'][0].update(daily_pnl_exact='-0.02', daily_transaction_costs_exact='0.02',
                                    current_portfolio_value_exact='999.98', total_pnl_exact='19.98')
    transition = accounting['successor']['transition_row']['payload']
    transition['original_accounting_input_id'] = observation['observation_id']
    before = transition['before_financial']
    before['positions'] = [{'key': key, 'quantity_exact': '2', **{name: fill[name] for name in (
        'average_price_exact', 'daily_realized_pnl_exact', 'daily_unrealized_pnl_exact', 'last_update')}}]
    before['live_results'] = [{**output['live_results'][0], 'daily_realized_pnl_exact': '0', 'daily_unrealized_pnl_exact': '0'}]
    before['equity_curve'][0]['equity_exact'] = '999.98'
    after = deepcopy(before)
    after['positions'][0].update(daily_realized_pnl_exact='100', last_update=transition['valuation_time'])
    after['live_results'][0].update(daily_realized_pnl_exact='100', daily_pnl_exact='99.98',
                                    current_portfolio_value_exact='1099.98', total_pnl_exact='119.98')
    after['equity_curve'][0]['equity_exact'] = '1099.98'
    transition['after_financial'] = after
    transition['components'][0].update(quantity_exact='2', average_price_exact='101', gross_pnl_model_number='100', gross_pnl_exact='100')
    transition['engine_totals'][0].update(actual_cash_cost_exact='0.02', gross_pnl_model_number='100', gross_pnl_exact='100',
                                         net_pnl_exact='99.98', equity_exact='1099.98', total_pnl_exact='119.98')
    preview['payload']['selection_rows'][0]['asset_type'] = 'FUTURE'
    preview['payload']['payload_digest'] = qt_digest_v1({name: value for name, value in preview['payload'].items() if name != 'payload_digest'})
    preview['payload_digest'] = preview['payload']['payload_digest']
    decision['payload']['preview_payload_digest'] = preview['payload_digest']
    observation['content_digest'] = digest(observed)
    evidence['result']['payload']['results'] = deepcopy(observed['results'])
    evidence['result']['content_digest'] = digest(evidence['result']['payload'])
    evidence['receipt']['publication_payload'].update(after_accounting=deepcopy(before['positions']),
        observation_digest=observation['content_digest'], results_digest=evidence['result']['content_digest'],
        preview_payload_digest=preview['payload_digest'])
    evidence['audits'][0]['risk_check_result'].update(observation_digest=observation['content_digest'],
                                                   preview_payload_digest=preview['payload_digest'])
    evidence['current_facts']['saved_accounting'] = deepcopy(after['positions'])
    accounting['finalization_row']['content_digest'] = digest(accounting['finalization_row']['payload'])
    transition['predecessor_finalization_digest'] = accounting['finalization_row']['content_digest']
    rehash(accounting)
    accounting['financial_rows'] = physical_financial_rows(accounting)
    evidence['accounting'] = accounting
    return evidence


def test_report_and_human_origin_follow_finalization_without_rewriting_receipt(monkeypatch):
    from algolens.infrastructure.portfolio.qt_publication_proof import validate_qt_publication_chain
    from algolens.infrastructure.portfolio.qt_decision_report_proof import processed_report_blocked_reasons
    from algolens.infrastructure.portfolio.qt_receipt_provenance import verified_receipt_chain
    from datetime import date
    evidence = finalized_receipt_fixture(monkeypatch)
    frozen = deepcopy(evidence)
    # The historical receipt is still the independently checked original.
    proof = validate_qt_publication_chain(evidence)
    assert next(iter(proof['after'].values()))['daily_realized_pnl_exact'] == '0'
    assert processed_report_blocked_reasons(evidence) == ()
    provenance = verified_receipt_chain('BOOK', date(2026, 9, 25), [evidence], evidence['audits'],
                                       evidence['current_facts']['saved_accounting'])
    assert next(iter(provenance['choices'].values()))['quantity_exact'] == '2'
    assert evidence == frozen


@pytest.mark.parametrize('damage', [None, 'history', 'volatility', 'seed_digest', 'boolean_count'])
def test_market_superset_retains_complete_admission_proof(damage):
    accounting, decision = finalized_fixture()
    context = accounting['successor']
    extra = deepcopy(context['market_row']['payload']['instruments'][0])
    extra['symbol'] = 'NEXT_DAY_ONLY'
    context['market_row']['payload']['instruments'].append(extra)
    if damage == 'history': extra.pop('history_digest')
    elif damage == 'volatility': extra['volatility_multiplier_model_number'] = '-1'
    elif damage == 'seed_digest': context['model_publication']['seed_digest'] = '0' * 64
    elif damage == 'boolean_count': extra['history_observation_count'] = True
    rehash(accounting)
    if damage:
        with pytest.raises(ValueError): verified_finalization_successor(accounting, decision)
    else:
        assert verified_finalization_successor(accounting, decision) is not None


def upstream_fixture(monkeypatch):
    from tests.test_qt_original_processing_proof import processing_context
    evidence = finalized_receipt_fixture(monkeypatch)
    prior = evidence['accounting']
    prior['processing_context'] = processing_context(evidence)
    context = prior['successor']
    transition = context['transition_row']
    market = context['market_row']
    after = transition['payload']['after_financial']
    totals = [{'strategy_id': row['strategy_id'], 'equity_exact': row['current_portfolio_value_exact'],
               'total_pnl_exact': row['total_pnl_exact']} for row in after['live_results']]
    anchor = {'schema_version': 'qt-finalized-accounting/v2', 'book_id': 'BOOK', 'source_day': '2026-09-25',
              'currency': 'USD', 'finalization_id': transition['finalization_id'],
              'finalization_digest': transition['content_digest'], 'policy_revision': 1, 'previous_totals': totals}
    final = {'source_id': 'qt-finalization/' + transition['finalization_id'], 'book_id': 'BOOK',
             'source_day': '2026-09-25', 'producer_id': market['producer_id'], 'policy_version': market['policy_version'],
             'payload': anchor, 'content_digest': digest(anchor)}
    decision = {'decision_id': '10000000-0000-4000-8000-000000000002', 'book_id': 'BOOK',
                'source_day': '2026-09-26', 'model_publication_id': market['model_publication_id']}
    previous = [{name: deepcopy(row[name]) for name in ('key', 'quantity_exact', 'average_price_exact')}
                for row in after['positions']]
    source = {'schema_version': 'qt-futures-accounting-input/v2', **{name: decision[name] for name in ('decision_id','book_id','source_day')},
              'timestamp': '2026-09-26T00:00:00Z', 'previous_day': '2026-09-25', 'currency': 'USD',
              'prior_finalization_source_id': final['source_id'], 'prior_finalization_digest': final['content_digest'],
              'market_source_id': market['source_id'], 'market_source_digest': market['content_digest'],
              'accounting_source_id': market['source_id'], 'cost_config': deepcopy(market['payload']['cost_config']),
              'instruments': deepcopy(market['payload']['instruments']), 'previous_positions': previous, 'previous_totals': deepcopy(totals)}
    row = {'decision_id': decision['decision_id'], 'input_id': 'd0000000-0000-4000-8000-000000000001',
           'producer_id': market['producer_id'], 'policy_version': market['policy_version'],
           'created_at': '2026-09-26T01:00:00Z', 'as_of': market['as_of'], 'valid_until': market['valid_until'],
           'payload': source, 'content_digest': digest(source)}
    accounting = {'input_row': row, 'finalization_row': final, 'input_market': deepcopy(context), 'prior_accounting': prior}
    selection = [{'key': {**deepcopy(previous[0]['key']), 'date': '2026-09-26', 'portfolio_type': 'qt_proposal'},
                  'asset_type': 'FUTURE', 'quantity_exact': '7'}]
    return accounting, decision, selection


@pytest.mark.parametrize('damage', [None, 'missing_prior', 'anchor_digest', 'prior_quantity', 'prior_total',
    'market_reference', 'cost_config', 'lease', 'publication', 'revision', 'foreign_previous', 'extra_reference',
    'anchor_alias', 'input_as_of', 'input_valid_until', 'missing_original_context',
    'pending_original_receipt', 'missing_original_observation', 'foreign_original_model'])
def test_assembled_input_proves_prior_successor_and_current_admission(monkeypatch, damage):
    from algolens.infrastructure.portfolio.qt_upstream_input_proof import verify_upstream_accounting_input
    accounting, decision, selection = upstream_fixture(monkeypatch)
    source = accounting['input_row']['payload']
    if damage == 'missing_prior': del accounting['prior_accounting']
    elif damage == 'anchor_digest': source['prior_finalization_digest'] = '0' * 64
    elif damage == 'prior_quantity': source['previous_positions'][0]['quantity_exact'] = '6'
    elif damage == 'prior_total': source['previous_totals'][0]['equity_exact'] = '1249'
    elif damage == 'market_reference': source['instruments'][0]['price_model_number'] = '102'
    elif damage == 'cost_config': source['cost_config']['explicit_fee_per_contract'] = '0'
    elif damage == 'lease': accounting['input_row']['created_at'] = '2026-09-26T03:00:00Z'
    elif damage == 'publication': decision['model_publication_id'] = '60000000-0000-4000-8000-000000000099'
    elif damage == 'revision': accounting['finalization_row']['payload']['policy_revision'] = 2
    elif damage == 'foreign_previous': source['previous_positions'][0]['key']['portfolio_id'] = 'OTHER'
    elif damage == 'extra_reference':
        extra = deepcopy(source['instruments'][0]); extra['symbol'] = 'UNSELECTED'; source['instruments'].append(extra)
    elif damage == 'anchor_alias':
        source['prior_finalization_source_id'] = accounting['finalization_row']['source_id'] = 'foreign-finalization-alias'
    elif damage == 'input_as_of': accounting['input_row']['as_of'] = '2026-09-25T00:00:00Z'
    elif damage == 'input_valid_until': accounting['input_row']['valid_until'] = '2026-09-27T02:00:00Z'
    elif damage == 'missing_original_context': del accounting['prior_accounting']['processing_context']
    elif damage == 'pending_original_receipt': accounting['prior_accounting']['processing_context']['receipt']['status'] = 'pending'
    elif damage == 'missing_original_observation': accounting['prior_accounting']['processing_context']['observation'] = None
    elif damage == 'foreign_original_model': accounting['prior_accounting']['processing_context']['model_publication']['portfolio_id'] = 'OTHER'
    accounting['input_row']['content_digest'] = digest(source)
    if damage:
        with pytest.raises(ValueError): verify_upstream_accounting_input(accounting, decision, selection)
    else:
        assert verify_upstream_accounting_input(accounting, decision, selection) is None


@pytest.mark.parametrize('damage', ['none', 'equivalent_timezone', 'source_changed',
    'source_input_missing', 'source_observation_missing', 'source_empty',
    'as_of_changed', 'valid_until_changed', 'as_of_missing', 'valid_until_missing'])
def test_current_accounting_requires_copied_observation_metadata_without_successor(monkeypatch, damage):
    from datetime import timedelta, timezone
    from algolens.infrastructure.portfolio.qt_accounting_proof import producer_prior_carries
    evidence = finalized_receipt_fixture(monkeypatch)
    accounting = evidence['accounting']
    accounting.pop('successor')
    accounting.pop('financial_rows')
    inputs, observation = accounting['input_row'], evidence['observation']
    if damage == 'equivalent_timezone':
        for name in ('as_of', 'valid_until'):
            observation[name] = datetime.fromisoformat(observation[name].replace('Z', '+00:00')).astimezone(
                timezone(timedelta(hours=-4))).isoformat()
    elif damage == 'source_changed': inputs['source_version'] = 'changed-version'
    elif damage == 'source_input_missing': del inputs['source_version']
    elif damage == 'source_observation_missing': del observation['source_version']
    elif damage == 'source_empty': inputs['source_version'] = observation['source_version'] = ''
    elif damage in ('as_of_changed', 'valid_until_changed'):
        name = damage.removesuffix('_changed')
        shift = timedelta(seconds=-1 if name == 'as_of' else 1)
        inputs[name] = (datetime.fromisoformat(inputs[name].replace('Z', '+00:00')) + shift).isoformat()
    elif damage in ('as_of_missing', 'valid_until_missing'):
        del observation[damage.removesuffix('_missing')]
    before = deepcopy(evidence)
    if damage in ('none', 'equivalent_timezone'):
        assert producer_prior_carries(evidence) == {}
    else:
        with pytest.raises((ValueError, KeyError)):
            producer_prior_carries(evidence)
    assert evidence == before


@pytest.mark.parametrize('stamp,accepted', [
    ('2026-09-25T00:00:00+00:00', True),
    ('2026-09-24T20:00:00-04:00', True),
    ('2026-09-25T00:00:01+00:00', False),
    ('2026-09-25T00:00:00', False),
])
def test_physical_daily_timestamp_is_exact_utc_midnight(stamp, accepted):
    from algolens.infrastructure.portfolio.qt_accounting_proof import _verify_current_financial_rows
    accounting, _ = finalized_fixture()
    accounting['financial_rows'] = physical_financial_rows(accounting)
    accounting['financial_rows']['live_results'][0]['date'] = datetime.fromisoformat(stamp)
    def require(ok):
        if not ok: raise ValueError('unproven_accounting')
    if accepted:
        _verify_current_financial_rows(accounting, require, Decimal)
    else:
        with pytest.raises(ValueError):
            _verify_current_financial_rows(accounting, require, Decimal)
