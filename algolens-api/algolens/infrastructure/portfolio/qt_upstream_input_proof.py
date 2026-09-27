"""Bounded historical proof for native assembled QT accounting input."""
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.portfolio.qt_original_processing_proof import verify_original_processing
from algolens.infrastructure.portfolio.qt_finalization_proof import (
    _need, _digest, _indexed, _key, _same_rows, _time,
    verified_finalization_successor, verified_market_source,
)


def _verify(accounting, decision, selection):
    inputs, final, prior = (accounting[name] for name in ('input_row', 'finalization_row', 'prior_accounting'))
    source, anchor = inputs['payload'], final['payload']
    book, day = decision['book_id'], str(decision['source_day'])
    _need(source['schema_version'] == 'qt-futures-accounting-input/v2' and
          anchor['schema_version'] == 'qt-finalized-accounting/v2')
    _need(inputs['content_digest'] == _digest(source) and final['content_digest'] == _digest(anchor))
    _need(str(inputs['decision_id']) == source['decision_id'] == str(decision['decision_id']))
    _need(source['book_id'] == final['book_id'] == anchor['book_id'] == prior['portfolio_id'] == book)
    _need(source['source_day'] == day and source['timestamp'] == day + 'T00:00:00Z')
    _need(str(final['source_day']) == anchor['source_day'] == source['previous_day'] == str(prior['date']) < day)
    _need(source['prior_finalization_source_id'] == final['source_id'] and
          source['prior_finalization_digest'] == final['content_digest'])
    market_context = accounting['input_market']
    market = verified_market_source(market_context, book, day)
    market_row = market_context['market_row']
    _need(source['market_source_id'] == str(market_row['source_id']) == source['accounting_source_id'] and
          source['market_source_digest'] == market_row['content_digest'])
    _need(str(decision['model_publication_id']) == market['model_publication_id'])
    _need(market['previous_day'] == source['previous_day'] and
          source['currency'] == market['currency'] == anchor['currency'] and
          source['cost_config'] == market['cost_config'])
    _need(_time(market_row['as_of']) <= _time(inputs['created_at']) <= _time(market_row['valid_until']))
    _need(_time(inputs['as_of']) == _time(market_row['as_of']) and
          _time(inputs['valid_until']) == _time(market_row['valid_until']))
    for name in ('producer_id', 'policy_version'):
        _need(inputs[name] == market_row[name] == final[name])
    verify_original_processing(prior)
    prior_decision = {'decision_id': prior['decision_id'], 'book_id': book, 'source_day': prior['date']}
    after = verified_finalization_successor(prior, prior_decision)
    _need(after is not None)
    transition = prior['successor']['transition_row']
    _need(anchor['finalization_id'] == str(transition['finalization_id']) and
          anchor['finalization_digest'] == transition['content_digest'] and
          type(anchor['policy_revision']) is int and anchor['policy_revision'] == transition['policy_revision'])
    _need(final['source_id'] == 'qt-finalization/' + anchor['finalization_id'])
    _need(transition['payload']['valuation_day'] == day and
          transition['payload']['market_source_id'] == source['market_source_id'] and
          transition['payload']['market_source_digest'] == source['market_source_digest'])
    expected_positions = [{name: row[name] for name in ('key', 'quantity_exact', 'average_price_exact')}
                          for row in after['positions']]
    _same_rows(source['previous_positions'], expected_positions, _key)
    expected_totals = [{'strategy_id': row['strategy_id'], 'equity_exact': row['current_portfolio_value_exact'],
                        'total_pnl_exact': row['total_pnl_exact']} for row in after['live_results']]
    for totals in (source['previous_totals'], anchor['previous_totals']):
        _same_rows(totals, expected_totals, lambda item: item['strategy_id'])
    selected = _indexed(selection, _key)
    _need(selected)
    for row in selected.values():
        _need(row['key']['portfolio_id'] == book and row['key']['date'] == day and
              row['key']['portfolio_type'] in {'qt', 'qt_proposal'} and row['asset_type'] == 'FUTURE')
    symbols = {row['key']['symbol'] for row in selected.values()}
    admitted = _indexed(market['instruments'], lambda item: item['symbol'])
    _need(symbols <= set(admitted))
    _same_rows(source['instruments'], [admitted[symbol] for symbol in sorted(symbols)], lambda item: item['symbol'])


def verify_upstream_accounting_input(accounting, decision, selection):
    try:
        _verify(accounting, decision, selection)
    except (ValueError, TypeError, KeyError, ArithmeticError, QtWorkflowError) as exc:
        raise ValueError('unproven_upstream_input') from exc
