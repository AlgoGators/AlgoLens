"""Strict evidence for an immutable successor to provisional QT accounting.

The original receipt and its accounting payload remain unchanged. This module
checks the separately recorded transition, including its arithmetic, before a
caller may compare physical rows against the successor instead of the original.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import math
import re

from algolens.domain.shared.fixed_decimal8 import parse_fixed_decimal8
from algolens.domain.portfolio.qt_canonical import qt_digest_v1
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes


def _need(condition):
    if not condition:
        raise ValueError('unproven_finalization')


def _digest(value):
    return sha256(canonical_qt_input_bytes(value)).hexdigest()


def _exact(value):
    _need(type(value) is str and parse_fixed_decimal8(value) is not None)
    return Decimal(value)


def _wire(value):
    result = format(value, 'f')
    if '.' in result:
        result = result.rstrip('0').rstrip('.')
    return '0' if result in {'0', '-0'} else result


def _model(value):
    _need(type(value) is str and len(value) <= 64 and
          re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?', value))
    result = float(value)
    _need(math.isfinite(result) and not (result == 0 and Decimal(value) != 0))
    return result


def _decimal_model(value):
    # Decimal::as_double converts the int64 raw value before division. Parsing
    # its decimal rendering directly can round to a different binary64 value.
    return float(int(_exact(value) * Decimal(100000000))) / 100000000.0


def _cash(value):
    # Match the existing Decimal(double) operation, including its operation
    # order, and check the integer boundary before conversion.
    _need(math.isfinite(value))
    scaled = value * 100000000.0 + (0.5 if value >= 0 else -0.5)
    _need(math.isfinite(scaled) and -(2**63) <= scaled < 2**63)
    return Decimal(int(scaled)) / Decimal(100000000)


def _time(value):
    _need(isinstance(value, datetime) or type(value) is str)
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
    _need(parsed.tzinfo is not None)
    return parsed.astimezone(timezone.utc)


def _indexed(rows, identity):
    _need(type(rows) is list and len(rows) <= 4096)
    result = {}
    for row in rows:
        key = identity(row)
        _need(key not in result)
        result[key] = row
    return result


def _key(row):
    return canonical_qt_input_bytes(row['key'])


def _same_rows(actual, expected, identity):
    _need(_indexed(actual, identity) == _indexed(expected, identity))


def _verify_reader_capture(market, instruments):
    """Recheck the actual legacy one-bar feed, without inventing warm-up data."""
    capture = market['capture']
    _need(set(capture) == {'schema_version', 'convention', 'table', 'rows', 'effective_configuration'})
    _need(capture['schema_version'] == 'qt-market-reader-capture/v1' and
          capture['convention'] == 'legacy-futures-fresh-manager-one-bar/v1' and
          capture['table'] == 'futures_data.ohlcv_1d')
    captured = _indexed(capture['rows'], lambda row: row['symbol'])
    _need(set(captured) == set(instruments))
    raw_fields = {'symbol', 'source_time', 'source_time_sql', 'open', 'high', 'low', 'close', 'volume'}
    consumed_fields = {'consumed_close_model_number', 'consumed_volume_model_number', 'volatility_state'}
    raw_rows = []
    for symbol, row in captured.items():
        _need(set(row) == raw_fields | consumed_fields)
        raw = {name: row[name] for name in raw_fields}
        time = _time(raw['source_time'])
        _need(time.date().isoformat() == market['previous_day'] and
              type(raw['source_time_sql']) is str and raw['source_time_sql'].endswith('+00') and
              _time(raw['source_time_sql']) == time)
        numbers = {name: _model(raw[name]) for name in ('open', 'high', 'low', 'close', 'volume')}
        _need(all(value > 0 for value in numbers.values()))
        _need(numbers['low'] <= min(numbers['open'], numbers['close']) and
              numbers['high'] >= max(numbers['open'], numbers['close']))
        for name in ('open', 'high', 'low', 'close'):
            _need(_cash(numbers[name]) > 0)
        instrument = instruments[symbol]
        # Bar.close is Decimal(double), then consumed through Decimal::as_double.
        close = _decimal_model(_wire(_cash(numbers['close'])))
        _need(_model(row['consumed_close_model_number']) == close == _model(instrument['price_model_number']))
        _need(_model(row['consumed_volume_model_number']) == numbers['volume'] == _model(instrument['adv_model_number']))
        _need(row['volatility_state'] == 'insufficient_returns_neutral' and
              _model(instrument['volatility_multiplier_model_number']) == 1 and
              instrument['history_observation_count'] == 1)
        history = _digest([raw])
        _need(instrument['history_digest'] == history and
              instrument['history_source_id'] == 'legacy-latest-bar/' + history and
              instrument['source_id'] == 'postgres:futures_data.ohlcv_1d/' + history)
        raw_rows.append(raw)
    raw_rows.sort(key=lambda row: (_time(row['source_time']), row['symbol']))
    dataset = _digest(raw_rows)
    _need(market['dataset_digest'] == dataset and
          market['dataset_source_id'] == 'postgres:futures_data.ohlcv_1d/' + dataset)
    effective = capture['effective_configuration']
    _need(set(effective) == {'cost_config', 'adv_lookback_days', 'volatility_lookback_days',
        'volatility_lambda', 'volatility_min_multiplier', 'volatility_max_multiplier', 'instruments', 'engine_build'})
    _need(effective['engine_build'] == market['engine_build'] and effective['cost_config'] == market['cost_config'])
    for name in ('adv_lookback_days', 'volatility_lookback_days'):
        _need(type(effective[name]) is int and effective[name] > 0)
    _need(_model(effective['volatility_lambda']) >= 0 and
          0 < _model(effective['volatility_min_multiplier']) <= _model(effective['volatility_max_multiplier']))
    asset_fields = ('symbol', 'instrument_type', 'asset_lookup', 'baseline_spread_ticks',
        'min_spread_ticks', 'max_spread_ticks', 'spread_cost_multiplier', 'max_impact_bps',
        'tick_size', 'point_value', 'max_total_implicit_bps')
    _same_rows(effective['instruments'], [{name: row[name] for name in asset_fields}
        for row in instruments.values()], lambda row: row['symbol'])
    cost = _digest(effective)
    _need(market['cost_config_digest'] == cost and market['cost_config_source_id'] == 'legacy-futures-default-cost/' + cost)


def verified_market_source(context, book, day):
    """Check the recorded market admission; historical proof has no new lease."""
    row, publication = context['market_row'], context['model_publication']
    market = row['payload']
    _need(row['content_digest'] == _digest(market) and market['schema_version'] == 'qt-accounting-market/v1')
    _need(row['book_id'] == market['book_id'] == publication['portfolio_id'] == book)
    _need(str(row['source_day']) == market['source_day'] == str(publication['source_day']) == day)
    _need(str(row['model_publication_id']) == market['model_publication_id'] == str(publication['publication_id']))
    _need(publication['seed_digest'] == qt_digest_v1({'seed_rows': publication['system_components']}))
    _need(market['previous_day'] < day and market['valuation_time'] == day + 'T00:00:00Z')
    for name in ('currency', 'dataset_source_id', 'cost_config_source_id', 'engine_build'):
        _need(type(market[name]) is str and 0 < len(market[name]) <= 16384)
    for name in ('dataset_digest', 'cost_config_digest'):
        _need(type(market[name]) is str and re.fullmatch('[a-f0-9]{64}', market[name]))
    _need(type(row['policy_revision']) is int and row['policy_revision'] > 0)
    cost = market['cost_config']
    _need(_model(cost['explicit_fee_per_contract']) >= 0 and _model(cost['min_adv']) > 0 and
          0 <= _model(cost['min_participation']) <= _model(cost['max_participation']) <= 1 and
          _model(cost['max_participation']) > 0)
    instruments = _indexed(market['instruments'], lambda item: item['symbol'])
    _need(instruments)
    for instrument in instruments.values():
        _need(instrument['instrument_type'] == 'FUTURE' and instrument['history_complete'] is True and
              type(instrument['history_observation_count']) is int and instrument['history_observation_count'] > 0 and
              instrument['asset_lookup'] in {'exact_symbol', 'pre_dot_root'} and
              instrument['price_time'] == market['previous_day'] + 'T00:00:00Z')
        for name in ('symbol', 'source_id', 'history_source_id'):
            _need(type(instrument[name]) is str and 0 < len(instrument[name]) <= 16384)
        _need(type(instrument['history_digest']) is str and re.fullmatch('[a-f0-9]{64}', instrument['history_digest']))
        for name in ('price_model_number', 'adv_model_number', 'volatility_multiplier_model_number', 'tick_size', 'point_value'):
            _need(_model(instrument[name]) > 0)
        for name in ('baseline_spread_ticks', 'min_spread_ticks', 'max_spread_ticks',
                     'spread_cost_multiplier', 'max_impact_bps', 'max_total_implicit_bps'):
            _need(_model(instrument[name]) >= 0)
        _need(_model(instrument['min_spread_ticks']) <= _model(instrument['max_spread_ticks']))
    actual_capture = type(row.get('source_version')) is str and row['source_version'].startswith('qt-market-capture/')
    _need(actual_capture == ('capture' in market))
    if actual_capture:
        _need(row['source_version'] == 'qt-market-capture/' + str(row['source_id']))
        _verify_reader_capture(market, instruments)
    return market


def _prove(accounting, decision):
    successor = accounting['successor']
    row, market_row, publication = (successor[name] for name in
                                   ('transition_row', 'market_row', 'model_publication'))
    transition, market = row['payload'], market_row['payload']
    original, inputs, predecessor = (accounting[name] for name in
                                     ('payload', 'input_row', 'finalization_row'))
    source = inputs['payload']
    book, day, decision_id = decision['book_id'], str(decision['source_day']), str(decision['decision_id'])
    _need(transition['schema_version'] == 'qt-desk-finalization/v1' and
          transition['calculation_version'] == 'futures-prior-close-mark/v1')
    _need(row['content_digest'] == _digest(transition))
    _need(transition['finalization_id'] == str(row['finalization_id']))
    _need(str(row['decision_id']) == transition['decision_id'] == str(accounting['decision_id']) == decision_id)
    _need(row['book_id'] == transition['book_id'] == accounting['portfolio_id'] == book)
    _need(str(row['source_day']) == transition['source_day'] == str(accounting['date']) == day)
    _need(str(row['valuation_day']) == transition['valuation_day'] == market['source_day'] > day)
    verified_market_source(successor, book, market['source_day'])
    _need(market['previous_day'] == day and str(market_row['source_day']) == market['source_day'])
    _need(transition['valuation_time'] == market['valuation_time'] == market['source_day'] + 'T00:00:00Z')
    _need(_time(market_row['as_of']) <= _time(row['created_at']) <= _time(market_row['valid_until']))
    _need(_time(transition['valuation_time']) <= _time(row['created_at']))
    _need(_time(row['created_at']).date().isoformat() == transition['valuation_day'])
    _need(transition['market_source_id'] == str(row['market_source_id']) == str(market_row['source_id']))
    _need(transition['market_source_digest'] == market_row['content_digest'] == _digest(market))
    _need(market['schema_version'] == 'qt-accounting-market/v1' and market['book_id'] == market_row['book_id'] == book)
    _need(market['model_publication_id'] == str(market_row['model_publication_id']) == str(publication['publication_id']))
    _need(publication['portfolio_id'] == book and str(publication['source_day']) == market['source_day'])
    identity = transition['policy_identity']
    _need(set(identity) == {'book_id', 'purpose', 'version', 'producer_id', 'policy_version'})
    _need(identity['book_id'] == book and identity['purpose'] == 'execution' and
          type(identity['version']) is int and identity['version'] > 0)
    for bound_row in (row, market_row):
        _need(type(bound_row['policy_revision']) is int and
              bound_row['policy_revision'] == identity['version'])
    for name in ('producer_id', 'policy_version'):
        _need(type(identity[name]) is str and bool(identity[name]) and
              identity[name] == row[name] == market_row[name] == inputs[name])
    _need(transition['original_run_result_digest'] == accounting['content_digest'] == _digest(original))
    _need(original['schema_version'] == 'qt-futures-accounting/v1')
    _need(transition['original_accounting_input_id'] == str(accounting['input_id']) == str(inputs['input_id']))
    _need(str(inputs['decision_id']) == source['decision_id'] == decision_id)
    _need(source['book_id'] == book and source['source_day'] == day)
    _need(original['input_digest'] == inputs['content_digest'] == _digest(source))
    _need(row['input_digest'] == inputs['content_digest'] and
          row['output_digest'] == accounting['content_digest'])
    first_day = source['schema_version'] == 'qt-futures-accounting-input-first-day/v1'
    _need(first_day or source['schema_version'] in {'qt-futures-accounting-input/v1', 'qt-futures-accounting-input/v2'})
    _need(source['timestamp'] == day + 'T00:00:00Z')
    if first_day:
        from algolens.infrastructure.portfolio.qt_first_day_proof import verify_first_day_input
        verify_first_day_input(accounting, decision)
        _need(not {'predecessor_finalization_source_id', 'predecessor_finalization_digest'} & transition.keys())
        _need(transition['first_day_anchor_id'] == source['first_day_anchor_id'] and
              transition['first_day_anchor_digest'] == source['first_day_anchor_digest'])
    else:
        _need(not {'first_day_anchor_id', 'first_day_anchor_digest'} & transition.keys())
        _need(transition['predecessor_finalization_source_id'] == predecessor['source_id'] == source['prior_finalization_source_id'])
        _need(transition['predecessor_finalization_digest'] == predecessor['content_digest'] == _digest(predecessor['payload']))
        _need(predecessor['book_id'] == predecessor['payload']['book_id'] == book)
        _need(str(predecessor['source_day']) == predecessor['payload']['source_day'] == source['previous_day'] < day)
        _need(source['previous_totals'] == predecessor['payload']['previous_totals'])
    _need(transition['currency'] == source['currency'] == market['currency'])
    observation = original['observation']
    _need(transition['original_observation_digest'] == _digest(observation))
    _need(observation['decision_id'] == decision_id and observation['book_id'] == book and observation['source_day'] == day)
    _need(transition['unchanged_execution_digest'] == _digest(original['executions']))

    before = {'positions': [], 'live_results': [], 'equity_curve': []}
    costs = {}
    for fill in observation['fills']:
        _need((first_day or (fill['daily_realized_pnl_exact'] == '0' and fill['daily_unrealized_pnl_exact'] == '0')) and
              fill['last_update'] == source['timestamp'] and fill['currency'] == source['currency'])
        charge = _exact(fill['actual_cash_cost_exact'])
        _need(charge >= 0)
        engine = fill['key']['strategy_id']
        costs[engine] = costs.get(engine, Decimal(0)) + charge
        _exact(_wire(costs[engine]))
        before['positions'].append({'key': fill['key'], 'quantity_exact': fill['selected_quantity_exact'],
            **{name: fill[name] for name in ('average_price_exact', 'daily_realized_pnl_exact',
                                            'daily_unrealized_pnl_exact', 'last_update')}})
    for live in original['live_results']:
        _need(live['portfolio_id'] == book and live['date'] == day and live['portfolio_type'] == 'qt')
        before['live_results'].append(dict(live) if first_day else
            {**live, 'daily_realized_pnl_exact': '0', 'daily_unrealized_pnl_exact': '0'})
        before['equity_curve'].append({'portfolio_id': book, 'strategy_id': live['strategy_id'],
            'timestamp': day + 'T00:00:00Z', 'portfolio_type': 'qt', 'equity_exact': live['current_portfolio_value_exact']})
    _need(set(transition['before_financial']) == set(before))
    _same_rows(transition['before_financial']['positions'], before['positions'], _key)
    for name in ('live_results', 'equity_curve'):
        _same_rows(transition['before_financial'][name], before[name], lambda item: item['strategy_id'])

    previous = _indexed(source['previous_totals'], lambda item: item['strategy_id'])
    original_marks = _indexed(source['instruments'], lambda item: item['symbol'])
    marks = _indexed(market['instruments'], lambda item: item['symbol'])
    components = _indexed(transition['components'], _key)
    positions = _indexed(before['positions'], _key)
    _need(positions and set(components) == set(positions))
    engines = set(previous)
    _need(set(_indexed(before['live_results'], lambda item: item['strategy_id'])) == engines and
          set(_indexed(before['equity_curve'], lambda item: item['strategy_id'])) == engines)
    symbols = {position['key']['symbol'] for position in positions.values()}
    _need(set(original_marks) == symbols and symbols <= set(marks))
    after = deepcopy(before)
    after_positions = _indexed(after['positions'], _key)
    gross_by_engine = {}
    for key in sorted(positions):
        position, component = positions[key], components[key]
        scope = position['key']
        _need(set(scope) == {'portfolio_id', 'strategy_id', 'strategy_name', 'symbol', 'date', 'portfolio_type'} and
              all(type(value) is str and 0 < len(value) <= 4096 for value in scope.values()) and
              scope['portfolio_id'] == book and scope['date'] == day and scope['portfolio_type'] == 'qt')
        symbol, engine = scope['symbol'], scope['strategy_id']
        mark, reference = marks[symbol], original_marks[symbol]
        _need(mark['instrument_type'] == 'FUTURE' and mark['price_time'] == day + 'T00:00:00Z')
        quantity = _exact(position['quantity_exact'])
        _need(quantity == quantity.to_integral_value() and _exact(position['average_price_exact']) > 0)
        legacy = source['schema_version'] == 'qt-futures-accounting-input/v1'
        reference_value = _decimal_model(reference['price_exact']) if legacy else _model(reference['price_model_number'])
        settlement = _model(mark['price_model_number'])
        point = _decimal_model(reference['point_value']) if legacy else _model(reference['point_value'])
        _need(reference_value > 0 and settlement > 0 and point > 0 and _model(mark['point_value']) == point)
        gross = _decimal_model(position['quantity_exact']) * (settlement - reference_value) * point
        realized = _wire(_cash(gross))
        _need(component['key'] == scope and component['quantity_exact'] == position['quantity_exact'] and
              component['average_price_exact'] == position['average_price_exact'])
        _need(_model(component['reference_price_model_number']) == reference_value and
              _model(component['settlement_price_model_number']) == settlement and
              _model(component['point_value_model_number']) == point and
              _model(component['gross_pnl_model_number']) == gross and component['gross_pnl_exact'] == realized)
        _need(component['reference_source_id'] == reference['source_id'] and component['settlement_source_id'] == mark['source_id'])
        after_positions[key].update(daily_realized_pnl_exact=_wire(_exact(position['daily_realized_pnl_exact']) + _exact(realized)),
                                    daily_unrealized_pnl_exact=position['daily_unrealized_pnl_exact'],
                                    last_update=transition['valuation_time'])
        gross_by_engine[engine] = gross_by_engine.get(engine, 0.0) + gross
        _need(math.isfinite(gross_by_engine[engine]))
    _need(set(gross_by_engine) == set(previous))
    totals = _indexed(transition['engine_totals'], lambda item: item['strategy_id'])
    _need(set(totals) == set(previous))
    equity_rows = _indexed(after['equity_curve'], lambda item: item['strategy_id'])
    for live in after['live_results']:
        engine = live['strategy_id']
        cost = costs[engine]
        gross, anchor = _cash(gross_by_engine[engine]), previous[engine]
        prior_equity, prior_total = _exact(anchor['equity_exact']), _exact(anchor['total_pnl_exact'])
        opening_daily = _exact(anchor['daily_pnl_exact']) if first_day else Decimal(0)
        opening_cost = _exact(anchor['daily_transaction_costs_exact']) if first_day else Decimal(0)
        _need(prior_equity > 0 and _exact(live['daily_transaction_costs_exact']) == opening_cost + cost and
              _exact(live['daily_pnl_exact']) == opening_daily - cost and
              _exact(live['current_portfolio_value_exact']) == prior_equity - cost and
              _exact(live['total_pnl_exact']) == prior_total - cost)
        net = gross - cost
        equity = prior_equity + net
        total = prior_total + net
        _need(equity > 0)
        for value in (gross, net, equity, total): _exact(_wire(value))
        expected = {'strategy_id': engine, 'actual_cash_cost_exact': _wire(cost),
                    'gross_pnl_exact': _wire(gross), 'net_pnl_exact': _wire(net),
                    'prior_equity_exact': anchor['equity_exact'], 'prior_total_pnl_exact': anchor['total_pnl_exact'],
                    'equity_exact': _wire(equity), 'total_pnl_exact': _wire(total)}
        _need({name: value for name, value in totals[engine].items() if name != 'gross_pnl_model_number'} == expected)
        _need(_model(totals[engine]['gross_pnl_model_number']) == gross_by_engine[engine])
        live.update(daily_realized_pnl_exact=_wire(_exact(live['daily_realized_pnl_exact']) + gross),
                    daily_pnl_exact=_wire(opening_daily + net), total_pnl_exact=_wire(total), current_portfolio_value_exact=_wire(equity))
        equity_rows[engine]['equity_exact'] = _wire(equity)
    _need(set(transition['after_financial']) == set(after))
    _same_rows(transition['after_financial']['positions'], after['positions'], _key)
    for name in ('live_results', 'equity_curve'):
        _same_rows(transition['after_financial'][name], after[name], lambda item: item['strategy_id'])
    return deepcopy(transition['after_financial'])


def verified_finalization_successor(accounting, decision):
    """Return proven successor rows, or None when the original is unfinalized."""
    if 'successor' not in accounting or accounting['successor'] is None:
        return None
    try:
        return _prove(accounting, decision)
    except (KeyError, TypeError, ValueError, ArithmeticError, QtWorkflowError) as exc:
        raise ValueError('unproven_finalization') from exc
