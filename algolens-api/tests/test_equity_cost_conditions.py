"""Source-audited read-set shape only; no Python cost recomputation."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from test_equity_portfolio_consumption import document,reader,samples

from equity_inspection_samples import PROPOSED_V6 as CONTRACT


def cost_document(*,sell=False,hot=False,fallback=False,order=False):
    doc=document();meta=CONTRACT['stages']['execution']['per_execution_reads']
    conditions=CONTRACT['execution_cost_conditions']
    reads={name:samples.value(meta[name]) for name in conditions['common_required']}
    reads.update(quantity=-0.5 if sell else 0.5,reference_price=16.0,
        commission_per_unit=-1.0 if fallback else 0.005,apply_regulatory_fees=True,
        volatility_calculation_reached=hot)
    branch=conditions['commission_fallback' if fallback else 'commission_nonnegative']
    for name in branch['required']:reads[name]=samples.value(meta[name])
    if not fallback:
        reads['max_commission_pct']=-1.0 if order else 0.01
        if order:reads['max_commission_per_order']=5.0
    if sell:
        for name in conditions['regulatory_sell']['required']:reads[name]=samples.value(meta[name])
    if hot:
        for name in conditions['volatility_calculated']['required']:reads[name]=samples.value(meta[name])
    else:reads.update(retrieved_volatility_multiplier=1.0,effective_volatility_multiplier=1.0)
    doc['stages']['execution']['executions'][0]['reads']=reads
    return doc


@pytest.mark.parametrize('arguments',[{},dict(sell=True,hot=True),dict(fallback=True),dict(order=True)])
def test_called_cost_reads_keep_only_the_actual_equity_branch(arguments):
    doc=cost_document(**arguments)
    assert reader.validate_equity_run_consumption(doc,expected_run_key=samples.KEY)==doc


def test_initial_previous_close_does_not_invent_a_return_window_read():
    doc=cost_document();reads=doc['stages']['cost_history']['symbols']['SYN']
    reads.update(previous_close_source='no_previous_close',previous_close_forwarded=0.0)
    reads.pop('log_return_lookback_days')
    assert reader.validate_equity_run_consumption(doc,expected_run_key=samples.KEY)==doc


@pytest.mark.parametrize('damage',['buy_regulatory','cold_volatility','fake_order_ceiling','fake_fallback_fee',
    'missing_minimum','missing_sell_fee','missing_hot_volatility','neutral_not_one','zero_quantity','negative_price',
    'initial_return_read','initial_forwarded_price','stored_zero'])
def test_uncalled_or_missing_branch_reads_cannot_be_certified(damage):
    doc=cost_document(sell=damage=='missing_sell_fee',hot=damage=='missing_hot_volatility')
    reads=doc['stages']['execution']['executions'][0]['reads'];history=doc['stages']['cost_history']['symbols']['SYN']
    if damage=='buy_regulatory':reads['sec_fee_per_million']=1.0
    elif damage=='cold_volatility':reads['volatility_lambda']=0.9
    elif damage=='fake_order_ceiling':reads['max_commission_per_order']=5.0
    elif damage=='fake_fallback_fee':reads['explicit_fee_per_contract']=0.01
    elif damage=='missing_minimum':reads.pop('min_commission_per_order')
    elif damage=='missing_sell_fee':reads.pop('finra_taf_per_share')
    elif damage=='missing_hot_volatility':reads.pop('volatility_lambda')
    elif damage=='neutral_not_one':reads['effective_volatility_multiplier']=0.9
    elif damage=='zero_quantity':reads['quantity']=0.0
    elif damage=='negative_price':reads['reference_price']=-16.0
    elif damage=='initial_return_read':history.update(previous_close_source='no_previous_close',previous_close_forwarded=0.0)
    elif damage=='initial_forwarded_price':history.update(previous_close_source='no_previous_close',previous_close_forwarded=16.0);history.pop('log_return_lookback_days')
    elif damage=='stored_zero':history.update(previous_close_source='stored_previous_close',previous_close_forwarded=0.0)
    with pytest.raises(ValueError):reader.validate_equity_run_consumption(doc,expected_run_key=samples.KEY)
