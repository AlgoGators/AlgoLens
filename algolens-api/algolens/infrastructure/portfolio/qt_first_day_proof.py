"""Read-only closure of the admitted first-day System anchor, never a bootstrap authority.

Mutable policy/configuration/storage witnesses must still match the captured
anchor. A later rotation fails closed; this reader does not invent an archive.
"""
from copy import deepcopy
from decimal import Decimal
import re

from algolens.domain.portfolio.qt_canonical import qt_digest_v1
from algolens.domain.portfolio.qt_workflow_models import QtKey
from algolens.infrastructure.portfolio.qt_finalization_proof import (
    _cash, _digest, _exact, _indexed, _key, _model, _need, _same_rows, _time, _wire, verified_market_source,
)
from algolens.infrastructure.portfolio.qt_read_set import internal_snapshot_digest

FIRST_DAY = 'qt-futures-accounting-input-first-day/v1'
POSITION_FIELDS = {'key', 'quantity_exact', 'average_price_exact',
                   'daily_realized_pnl_exact', 'daily_unrealized_pnl_exact'}
TOTAL_FIELDS = {'strategy_id', 'equity_exact', 'total_pnl_exact', 'daily_pnl_exact',
                'daily_realized_pnl_exact', 'daily_unrealized_pnl_exact',
                'daily_transaction_costs_exact', 'total_transaction_costs_exact'}


def load_first_day_context(cursor, accounting):
    source = accounting['input_row']['payload']
    cursor.execute("SELECT to_jsonb(a) AS anchor,to_jsonb(d) AS decision,to_jsonb(p) AS preview,"
        "to_jsonb(m) AS model_publication,to_jsonb(e) AS evaluation_policy,"
        "to_jsonb(x) AS execution_policy,to_jsonb(r) AS run_input "
        "FROM trading.qt_first_day_anchors a "
        "JOIN trading.qt_decisions d ON d.decision_id=a.decision_id "
        "JOIN trading.qt_previews p ON p.preview_id=d.preview_id "
        "JOIN trading.qt_model_seed_publications m ON m.publication_id=a.model_publication_id "
        "LEFT JOIN trading.qt_source_policies e ON e.book_id=a.book_id AND e.purpose='evaluation' "
        "LEFT JOIN trading.qt_source_policies x ON x.book_id=a.book_id AND x.purpose='execution' "
        "LEFT JOIN trading.run_inputs r ON r.portfolio_id=a.book_id AND r.strategy_id=m.strategy_id "
        "AND r.date=a.source_day WHERE a.anchor_id::text=%s", (source.get('first_day_anchor_id'),))
    contexts = cursor.fetchall()
    _need(len(contexts) == 1)
    context = dict(contexts[0])
    cursor.execute("SELECT to_jsonb(s) AS snapshot FROM trading.qt_evaluation_snapshots s "
        "WHERE s.book_id=%s AND s.source_day=%s AND s.content_digest=%s",
        (context['anchor']['book_id'], context['anchor']['source_day'],
         context['anchor']['payload']['bindings'].get('evaluation_snapshot_digest')))
    context['snapshots'] = [row['snapshot'] for row in cursor.fetchall()]
    cursor.execute("SELECT to_jsonb(c) AS capability FROM trading.qt_storage_capabilities c ORDER BY capability_name")
    context['storage_capabilities'] = [row['capability'] for row in cursor.fetchall()]
    cursor.execute("SELECT to_jsonb(m) AS market_row,to_jsonb(p) AS model_publication "
        "FROM trading.qt_desk_market_sources m JOIN trading.qt_model_seed_publications p "
        "ON p.publication_id=m.model_publication_id WHERE m.source_id::text=%s", (source.get('market_source_id'),))
    context['market'] = cursor.fetchone()
    accounting['first_day_context'] = context


def verify_first_day_input(accounting, decision, selection_rows=None):
    """Bind the exact anchor and opening balances to actual SQL witnesses."""
    source, context = accounting['input_row']['payload'], accounting['first_day_context']
    inputs, anchor = accounting['input_row'], context['anchor']
    payload, bindings = anchor['payload'], anchor['payload']['bindings']
    book, day, identity = decision['book_id'], str(decision['source_day']), str(decision['decision_id'])
    _need(source['schema_version'] == FIRST_DAY and payload['schema_version'] == 'qt-first-day-anchor/v1')
    _need(set(source) == {'schema_version', 'decision_id', 'book_id', 'source_day', 'opening_day',
        'timestamp', 'currency', 'accounting_source_id', 'market_source_id', 'market_source_digest',
        'first_day_anchor_id', 'first_day_anchor_digest', 'previous_positions', 'previous_totals',
        'cost_config', 'instruments'})
    _need(set(payload) == {'schema_version', 'anchor_id', 'decision_id', 'book_id', 'source_day',
        'model_publication_id', 'currency', 'opening_positions', 'opening_totals', 'bindings'})
    _need(set(bindings) == {'model_seed_digest', 'proposal_manifest_digest', 'producer_version',
        'decision_read_set_digest', 'preview_payload_digest', 'evaluation_snapshot_digest',
        'evaluation_policy_revision', 'evaluation_policy_version', 'evaluator_sha256',
        'evaluator_bundle_sha256', 'execution_policy_revision', 'execution_policy_version',
        'execution_producer_id', 'config_digest', 'schema_digest'})
    _need(accounting.get('finalization_row') is None and source['opening_day'] == day)
    for name, expected in (('decision_id', identity), ('book_id', book), ('source_day', day)):
        _need(source[name] == str(anchor[name]) == payload[name] == str(context['decision'][name]) == expected)
    _need(inputs['content_digest'] == _digest(source))
    _need(source['first_day_anchor_id'] == payload['anchor_id'] == str(anchor['anchor_id']))
    _need(source['first_day_anchor_digest'] == anchor['content_digest'] == _digest(payload))
    model, preview = context['model_publication'], context['preview']
    _need(str(anchor['model_publication_id']) == payload['model_publication_id'] ==
          str(context['decision']['model_publication_id']) == str(model['publication_id']))
    _need(model['portfolio_id'] == book and str(model['source_day']) == day)
    _need(model['seed_digest'] == bindings['model_seed_digest'] == qt_digest_v1({'seed_rows': model['system_components']}))
    _need(model['proposal_manifest_digest'] == bindings['proposal_manifest_digest'] ==
          internal_snapshot_digest('qt-proposal-manifest/v1', {'proposal_rows': model['proposal_components']}))
    _need(model['producer_version'] == bindings['producer_version'])
    _need(str(preview['preview_id']) == str(context['decision']['preview_id']) and
          preview['book_id'] == book and str(preview['source_day']) == day)
    _need(preview['read_set_digest'] == context['decision']['read_set_digest'] == bindings['decision_read_set_digest'] ==
          internal_snapshot_digest('qt-read-set/v1', preview['read_set_payload']))
    _need(preview['payload_digest'] == bindings['preview_payload_digest'] == preview['payload']['payload_digest'])
    _need(preview['payload_digest'] == qt_digest_v1({k: v for k, v in preview['payload'].items() if k != 'payload_digest'}))
    if selection_rows is not None:
        _need(selection_rows == preview['payload']['selection_rows'])
    selected = preview['payload']['selection_rows']
    _need(type(selected) is list and 0 < len(selected) <= 4096 and all(r['asset_type'] == 'FUTURE' for r in selected))
    for purpose in ('evaluation', 'execution'):
        policy = context[purpose + '_policy']
        _need(policy['book_id'] == book and policy['purpose'] == purpose and policy['enabled'] is True)
        _need(type(policy['version']) is int and policy['version'] > 0 and
              policy['version'] == anchor[purpose + '_policy_revision'] == bindings[purpose + '_policy_revision'])
        _need(policy['policy_version'] == bindings[purpose + '_policy_version'])
    for field in ('evaluator_sha256', 'evaluator_bundle_sha256'):
        _need(re.fullmatch('[a-f0-9]{64}', bindings[field]) is not None and
              bindings[field] == context['evaluation_policy'][field])
    _need(bindings['execution_producer_id'] == context['execution_policy']['producer_id'] == inputs['producer_id'])
    _need(bindings['execution_policy_version'] == inputs['policy_version'])
    _need(inputs['source_version'] == 'qt-first-day-input/' + str(inputs['input_id']))
    _need(len(context['snapshots']) == 1)
    snapshot = context['snapshots'][0]
    _need(snapshot['book_id'] == book and str(snapshot['source_day']) == day and
          str(snapshot['model_publication_id']) == str(model['publication_id']))
    _need(snapshot['content_digest'] == bindings['evaluation_snapshot_digest'] == _digest(snapshot['payload']))
    _need(snapshot['producer_id'] == context['evaluation_policy']['producer_id'] and
          snapshot['policy_version'] == bindings['evaluation_policy_version'])
    _need(preview['read_set_payload']['portfolio_inputs']['content_digest'] == snapshot['content_digest'])
    run = context['run_input']
    _need(run['portfolio_id'] == book and run['strategy_id'] == model['strategy_id'] and str(run['date']) == day)
    _need(bindings['config_digest'] == _digest(run['config_snapshot']))
    _need(context['storage_capabilities'] and bindings['schema_digest'] == _digest(context['storage_capabilities']))
    market = verified_market_source(context['market'], book, day)
    market_row = context['market']['market_row']
    _need(str(market_row['model_publication_id']) == str(model['publication_id']))
    _need(source['market_source_id'] == source['accounting_source_id'] == str(market_row['source_id']) and
          source['market_source_digest'] == market_row['content_digest'])
    _need(source['cost_config'] == market['cost_config'] and source['currency'] == market['currency'] == payload['currency'])
    _need(source['timestamp'] == market['valuation_time'] == day + 'T00:00:00Z')
    _need(market_row['policy_revision'] == anchor['execution_policy_revision'])
    for field in ('producer_id', 'policy_version'):
        _need(market_row[field] == inputs[field])
    for field in ('as_of', 'valid_until'):
        _need(_time(market_row[field]) == _time(inputs[field]))
    _need(_time(inputs['as_of']) <= _time(inputs['created_at']) <= _time(inputs['valid_until']))
    _need(_time(anchor['created_at']) <= _time(inputs['created_at']))
    instruments = _indexed(market['instruments'], lambda row: row['symbol'])
    symbols = {row['key']['symbol'] for row in selected}
    _need(symbols <= instruments.keys())
    _same_rows(source['instruments'], [instruments[symbol] for symbol in symbols], lambda row: row['symbol'])
    opening = _indexed(payload['opening_positions'], _key)
    _need(bool(opening))
    for row in opening.values():
        _need(set(row) == POSITION_FIELDS)
        key = row['key']
        QtKey.from_wire(key)
        _need(key['portfolio_id'] == book and key['date'] == day and key['portfolio_type'] == 'system')
        for field in POSITION_FIELDS - {'key'}:
            _exact(row[field])
        _need(_exact(row['quantity_exact']) == _exact(row['quantity_exact']).to_integral_value() and
              _exact(row['average_price_exact']) > 0)
    cores = [{field: row[field] for field in ('key', 'quantity_exact', 'average_price_exact')} for row in opening.values()]
    _same_rows(cores, model['system_components'], _key)
    translated = deepcopy(list(opening.values()))
    for row in translated:
        row['key']['portfolio_type'] = 'qt'
    _same_rows(source['previous_positions'], translated, _key)
    totals = _indexed(payload['opening_totals'], lambda row: row['strategy_id'])
    _need(set(totals) == {row['key']['strategy_id'] for row in opening.values()})
    for row in totals.values():
        _need(set(row) == TOTAL_FIELDS)
        for field in TOTAL_FIELDS - {'strategy_id'}:
            _exact(row[field])
        _need(_exact(row['equity_exact']) > 0 and _exact(row['daily_transaction_costs_exact']) >= 0 and
              _exact(row['total_transaction_costs_exact']) >= _exact(row['daily_transaction_costs_exact']))
    _same_rows(source['previous_totals'], list(totals.values()), lambda row: row['strategy_id'])
    selected_qt = [{**row, 'key': {**row['key'], 'portfolio_type': 'qt'}} for row in selected]
    expected = _indexed(selected_qt, _key)
    fills = _indexed(accounting['payload']['observation']['fills'], _key)
    _need(set(expected) == set(fills))
    for key, fill in fills.items():
        QtKey.from_wire(fill['key'])
        _need(fill['selected_quantity_exact'] == expected[key]['quantity_exact'])
        _need(_exact(fill['selected_quantity_exact']) == _exact(fill['selected_quantity_exact']).to_integral_value())
        price = _wire(_cash(_model(instruments[fill['key']['symbol']]['price_model_number'])))
        _need(fill['average_price_exact'] == (expected[key]['average_price_exact'] or price))
    for execution in accounting['payload']['executions']:
        _need(execution['price_exact'] == _wire(_cash(_model(instruments[execution['key']['symbol']]['price_model_number']))))
    verify_first_day_financials(accounting)


def verify_first_day_financials(accounting):
    """Reconcile inherited balances and only incremental QT execution cash."""
    source, output = accounting['input_row']['payload'], accounting['payload']
    _need(output['input_digest'] == accounting['input_row']['content_digest'] and
          accounting['content_digest'] == _digest(output))
    previous = _indexed(source['previous_positions'], _key)
    totals = _indexed(source['previous_totals'], lambda row: row['strategy_id'])
    fills = _indexed(output['observation']['fills'], _key)
    _need(previous.keys() <= fills.keys())  # New MODEL proposals require real executions.
    executions = _indexed(output['executions'], _key)
    _need(executions.keys() <= fills.keys())
    costs = {engine: Decimal(0) for engine in totals}
    for key, fill in fills.items():
        prior = previous.get(key, {'quantity_exact': '0', 'daily_realized_pnl_exact': '0',
                                   'daily_unrealized_pnl_exact': '0'})
        _need(fill['currency'] == source['currency'] and fill['last_update'] == source['timestamp'] and
              fill['accounting_source_id'] == source['accounting_source_id'])
        for field in ('daily_realized_pnl_exact', 'daily_unrealized_pnl_exact'):
            _need(fill[field] == prior[field])
        cost = _exact(fill['actual_cash_cost_exact'])
        _need(cost >= 0)
        delta = _exact(fill['selected_quantity_exact']) - _exact(prior['quantity_exact'])
        if delta == 0:
            _need(key not in executions and cost == 0 and fill['execution_id'] is None and fill['observation_kind'] == 'carried')
        else:
            _need(key in executions and fill['observation_kind'] == 'executed')
            execution = executions[key]
            _need(execution['exec_id'] == fill['execution_id'] and
                  execution['side'] == ('BUY' if delta > 0 else 'SELL') and
                  _exact(execution['quantity_exact']) == abs(delta) and
                  execution['execution_time'] == source['timestamp'])
            charges = [_exact(execution[field]) for field in ('commissions_fees_exact', 'slippage_market_impact_exact')]
            # Implicit price impact is in price units, not cash. The native
            # kernel rounds each component and the total independently; their
            # sum can differ by one Decimal8 atom. The persisted total itself
            # must match the fill and all balance adjustments exactly.
            _need(_exact(execution['implicit_price_impact_exact']) >= 0 and
                  all(charge >= 0 for charge in charges) and abs(sum(charges) - cost) <= Decimal('0.00000001') and
                  cost == _exact(execution['total_transaction_costs_exact']))
        costs[fill['key']['strategy_id']] += cost
    live = _indexed(output['live_results'], lambda row: row['strategy_id'])
    _need(set(live) == set(totals))
    for engine, row in live.items():
        opening, cost = totals[engine], costs[engine]
        _need(row['portfolio_id'] == source['book_id'] and row['date'] == source['source_day'] and row['portfolio_type'] == 'qt')
        for field in ('daily_realized_pnl_exact', 'daily_unrealized_pnl_exact'):
            _need(row[field] == opening[field])
        for field, before in (('daily_pnl_exact', 'daily_pnl_exact'), ('total_pnl_exact', 'total_pnl_exact'),
                              ('current_portfolio_value_exact', 'equity_exact')):
            _need(_exact(row[field]) == _exact(opening[before]) - cost)
        for field in ('daily_transaction_costs_exact', 'total_transaction_costs_exact'):
            _need(_exact(row[field]) == _exact(opening[field]) + cost)
