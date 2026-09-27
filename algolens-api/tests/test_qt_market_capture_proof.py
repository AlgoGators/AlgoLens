"""Synthetic raw-reader traces require their own complete immutable closure."""
from copy import deepcopy
import pytest
from tests.test_qt_finalization_proof import finalized_fixture, digest
from algolens.infrastructure.portfolio.qt_finalization_proof import verified_market_source


ASSET_FIELDS = ('symbol', 'instrument_type', 'asset_lookup', 'baseline_spread_ticks',
    'min_spread_ticks', 'max_spread_ticks', 'spread_cost_multiplier', 'max_impact_bps',
    'tick_size', 'point_value', 'max_total_implicit_bps')


def captured_context():
    accounting, _ = finalized_fixture()
    context = deepcopy(accounting['successor'])
    market = context['market_row']['payload']
    context['market_row']['source_version'] = 'qt-market-capture/' + context['market_row']['source_id']
    instrument = market['instruments'][0]
    instrument['volatility_multiplier_model_number'] = '1'
    instrument['history_observation_count'] = 1
    raw = {'symbol': instrument['symbol'], 'source_time': '2026-09-25T16:30:00Z',
        'source_time_sql': '2026-09-25 16:30:00+00',
        **{name: instrument['price_model_number'] for name in ('open', 'high', 'low', 'close')},
        'volume': instrument['adv_model_number']}
    history = digest([raw])
    instrument.update(source_id='postgres:futures_data.ohlcv_1d/' + history,
        history_source_id='legacy-latest-bar/' + history, history_digest=history)
    effective = {'cost_config': deepcopy(market['cost_config']), 'adv_lookback_days': 20,
        'volatility_lookback_days': 20, 'volatility_lambda': '0.5',
        'volatility_min_multiplier': '0.5', 'volatility_max_multiplier': '2',
        'instruments': [{name: instrument[name] for name in ASSET_FIELDS}],
        'engine_build': market['engine_build']}
    market.update(dataset_digest=history, dataset_source_id='postgres:futures_data.ohlcv_1d/' + history,
        cost_config_digest=digest(effective), cost_config_source_id='legacy-futures-default-cost/' + digest(effective))
    market['capture'] = {'schema_version': 'qt-market-reader-capture/v1',
        'convention': 'legacy-futures-fresh-manager-one-bar/v1', 'table': 'futures_data.ohlcv_1d',
        'rows': [{**raw, 'consumed_close_model_number': instrument['price_model_number'],
            'consumed_volume_model_number': instrument['adv_model_number'],
            'volatility_state': 'insufficient_returns_neutral'}], 'effective_configuration': effective}
    context['market_row']['content_digest'] = digest(market)
    return context


@pytest.mark.parametrize('damage', [None, 'dataset_digest', 'cost_digest', 'source_time',
    'source_time_sql', 'raw_close', 'consumed_close', 'consumed_volume', 'volatility_state',
    'history_digest', 'history_count', 'effective_asset', 'effective_cost', 'raw_ohlc',
    'duplicate_row', 'extra_row', 'build', 'unknown_convention', 'missing_capture', 'wrong_capture_version'])
def test_reader_capture_evidence_is_bound_to_admitted_operands(damage):
    context = captured_context()
    market = context['market_row']['payload']
    capture = market['capture']; row = capture['rows'][0]
    instrument = market['instruments'][0]
    if damage == 'dataset_digest': market['dataset_digest'] = '0' * 64
    elif damage == 'cost_digest': market['cost_config_digest'] = '0' * 64
    elif damage == 'source_time': row['source_time'] = '2026-09-24T16:30:00Z'
    elif damage == 'source_time_sql': row['source_time_sql'] = '2026-09-25 16:30:00-04'
    elif damage == 'raw_close': row['close'] = '102'
    elif damage == 'consumed_close': row['consumed_close_model_number'] = '102'
    elif damage == 'consumed_volume': row['consumed_volume_model_number'] = '1'
    elif damage == 'volatility_state': row['volatility_state'] = 'observed_market_volatility'
    elif damage == 'history_digest': instrument['history_digest'] = '0' * 64
    elif damage == 'history_count': instrument['history_observation_count'] = 2
    elif damage == 'effective_asset': capture['effective_configuration']['instruments'][0]['point_value'] = '1'
    elif damage == 'effective_cost': capture['effective_configuration']['cost_config']['explicit_fee_per_contract'] = '0'
    elif damage == 'raw_ohlc': row['low'] = '200'
    elif damage == 'duplicate_row': capture['rows'].append(deepcopy(row))
    elif damage == 'extra_row': capture['rows'].append({**row, 'symbol': 'UNADMITTED'})
    elif damage == 'build': capture['effective_configuration']['engine_build'] = 'foreign'
    elif damage == 'unknown_convention': capture['convention'] = 'invented-warmup'
    elif damage == 'missing_capture': del market['capture']
    elif damage == 'wrong_capture_version': context['market_row']['source_version'] = 'generic-supplied-market/v1'
    context['market_row']['content_digest'] = digest(market)
    before = deepcopy(context)
    if damage:
        with pytest.raises(ValueError): verified_market_source(context, 'BOOK', '2026-09-26')
    else:
        assert verified_market_source(context, 'BOOK', '2026-09-26') == market
    assert context == before


def test_reader_dataset_digest_uses_query_order_even_when_capture_rows_differ():
    context = captured_context()
    market = context['market_row']['payload']; capture = market['capture']
    instrument = deepcopy(market['instruments'][0]); instrument['symbol'] = 'ZZZ'
    second = {**capture['rows'][0], 'symbol': 'ZZZ', 'source_time': '2026-09-25T09:00:00Z',
              'source_time_sql': '2026-09-25 09:00:00+00'}
    raw_fields = ('symbol', 'source_time', 'source_time_sql', 'open', 'high', 'low', 'close', 'volume')
    raw_second = {name: second[name] for name in raw_fields}
    history = digest([raw_second])
    instrument.update(source_id='postgres:futures_data.ohlcv_1d/' + history,
        history_source_id='legacy-latest-bar/' + history, history_digest=history)
    market['instruments'].append(instrument)
    capture['rows'].append(second)  # Symbol order; query time order is reversed.
    configuration = capture['effective_configuration']
    configuration['instruments'].append({name: instrument[name] for name in ASSET_FIELDS})
    cost = digest(configuration)
    market.update(cost_config_digest=cost, cost_config_source_id='legacy-futures-default-cost/' + cost)
    raw_first = {name: capture['rows'][0][name] for name in raw_fields}
    dataset = digest([raw_second, raw_first])
    market.update(dataset_digest=dataset, dataset_source_id='postgres:futures_data.ohlcv_1d/' + dataset)
    context['market_row']['content_digest'] = digest(market)
    assert verified_market_source(context, 'BOOK', '2026-09-26') == market
