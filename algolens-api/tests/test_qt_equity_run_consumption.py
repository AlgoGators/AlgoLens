"""Production-import schema controls, synthetic test data only."""
from copy import deepcopy
import pytest
from algolens.domain.portfolio import qt_equity_run_consumption as reader
from algolens.domain.portfolio import qt_equity_portfolio_consumption as helper
from equity_inspection_samples import KEY,CONTRACT,value,sample,portfolio
import equity_inspection_samples as samples

def test_valid_synthetic_full_run_is_inspection_only_and_preserves_partial_primary():
    document=sample();before=deepcopy(document)
    observed=reader.validate_equity_run_consumption(document,expected_run_key=KEY)
    assert observed==before and document==before and observed is not document
    assert observed['stages']['primary']['reads']['strategy_invocation']['full_run_certification'] is False

def test_valid_explicit_not_reached_document_retains_unavailability():
    document=sample();document.update(available=False,complete=False,unavailable_reason='instrumentation_missing')
    for stage in document['stages'].values():stage.update(outcome='not_reached',skip_reason=None,reads={},symbols={},executions=[])
    assert reader.validate_equity_run_consumption(document,expected_run_key=KEY)==document

@pytest.mark.parametrize('damage',['foreign_owner','unknown_root','unknown_read','bool_integer','nonfinite','missing_stage',
    'execution_owner','execution_index','duplicate_execution','illegal_symbols','enabled_helper','unreached_complete',
    'fake_skip','partial_as_full','forged_prior','bad_exact','partial_nonfinite'])
def test_invalid_or_unreached_full_run_never_gains_admission(damage):
    document=sample();stage=document['stages']
    if damage=='foreign_owner':document['run_key']['portfolio_id']='OTHER'
    elif damage=='unknown_root':document['caller_trusted']=True
    elif damage=='unknown_read':stage['setup']['reads']['unknown']=1
    elif damage=='bool_integer':stage['market_input']['reads']['historical_days']=True
    elif damage=='nonfinite':stage['setup']['reads']['capital_allocation']=float('nan')
    elif damage=='missing_stage':stage.pop('prior')
    elif damage=='execution_owner':stage['execution']['executions'][0]['strategy_name']='OTHER'
    elif damage=='execution_index':stage['execution']['executions'][0]['index']=True
    elif damage=='duplicate_execution':stage['execution']['executions'].append(deepcopy(stage['execution']['executions'][0]))
    elif damage=='illegal_symbols':stage['setup']['symbols']={'SYN':{}}
    elif damage=='enabled_helper':stage['setup']['reads']['use_optimization']=True
    elif damage=='unreached_complete':stage['execution'].update(outcome='not_reached',reads={},executions=[])
    elif damage=='fake_skip':stage['eod'].update(outcome='skipped',skip_reason='not_needed')
    elif damage=='partial_as_full':stage['primary']['reads']['strategy_invocation']['full_run_certification']=True
    elif damage=='forged_prior':stage['prior']['reads']['decision_id']='81000000-0000-4000-8000-000000000001'
    elif damage=='bad_exact':stage['result_assembly']['reads']['total_transaction_costs_exact']='0.14000000'
    elif damage=='partial_nonfinite':stage['primary']['reads']['strategy_invocation']['symbols']['SYN']['reads']['entry_threshold']=float('inf')
    with pytest.raises(ValueError):reader.validate_equity_run_consumption(document,expected_run_key=KEY)


@pytest.mark.parametrize('field,value',[('lookback_period',-1),('maximum_price_history',1<<32),('volume_sample_count',1<<32)])
def test_partial_native_integer_domains_are_observed_without_defaulting(field,value):
    document=sample();partial=document['stages']['primary']['reads']['strategy_invocation']['symbols']['SYN']
    if field=='volume_sample_count':
        partial['reads']['fractional_min_adv']=10.0
        partial['observed_state'].update(volume_sample_count=value,average_daily_volume=100000.0)
    else:partial['reads'][field]=value
    assert reader.validate_equity_run_consumption(document,expected_run_key=KEY)==document


@pytest.mark.parametrize('damage',['future_prior','market_reversed','market_future','missing_mode','partial_wrong_type'])
def test_complete_source_days_and_fixed_refusals_are_closed(damage):
    document=sample();stages=document['stages']
    if damage=='future_prior':stages['prior']['reads']['source_day']='2026-09-27'
    elif damage=='market_reversed':stages['market_input']['reads'].update(start_day='2026-09-26',end_day='2026-09-25')
    elif damage=='market_future':stages['market_input']['reads']['end_day']='2026-09-27'
    elif damage=='missing_mode':stages['prior']['reads'].pop('mode')
    elif damage=='partial_wrong_type':stages['primary']['reads']['strategy_invocation']=[]
    with pytest.raises(ValueError):reader.validate_equity_run_consumption(document,expected_run_key=KEY)


def test_book_identity_is_distinct_from_instrument_symbol_bounds():
    document=sample();key=deepcopy(KEY);key['portfolio_id']='B'*100;document['run_key']=key
    document['stages']['execution']['executions'][0]['portfolio_id']=key['portfolio_id']
    assert reader.validate_equity_run_consumption(document,expected_run_key=key)==document


def test_instrument_punctuation_is_not_admitted_as_a_book_identity():
    document=sample();key=deepcopy(KEY);key['portfolio_id']='BOOK/OTHER';document['run_key']=key
    document['stages']['execution']['executions'][0]['portfolio_id']=key['portfolio_id']
    with pytest.raises(ValueError):reader.validate_equity_run_consumption(document,expected_run_key=key)


def test_explicit_nontrading_skips_preserve_empty_actual_invocation():
    document=sample()
    for name in ('preparation','primary','execution'):
        document['stages'][name].update(outcome='skipped',skip_reason='non_trading_day',reads={},symbols={},executions=[])
    assert reader.validate_equity_run_consumption(document,expected_run_key=KEY)==document


def test_verified_prior_action_free_and_successor_skip_have_distinct_closed_reads():
    document=sample()
    for name,mode in [('prior','verified_desk_prior'),('corporate_actions','proved_action_free_prior'),('eod','proved_desk_successor')]:
        definition=CONTRACT['stages'][name];condition=CONTRACT['conditional_readsets'][name][mode]
        reads={field:value(definition['reads'][field]) for field in condition['required']}
        reads['mode' if name=='prior' else 'path']=mode
        if name=='prior':reads['valuation_day']=KEY['date']
        if name=='corporate_actions':reads['effective_event_count']=0
        document['stages'][name]['reads']=reads
        if name=='eod':document['stages'][name].update(outcome='skipped',skip_reason='proved_desk_successor')
    assert reader.validate_equity_run_consumption(document,expected_run_key=KEY)==document
