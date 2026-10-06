"""Production-import schema controls, synthetic test data only."""
from copy import deepcopy
import pytest
from algolens.domain.portfolio import qt_equity_run_consumption as reader
from algolens.domain.portfolio import qt_equity_portfolio_consumption as helper
from equity_inspection_samples import KEY,CONTRACT,value,sample,portfolio
import equity_inspection_samples as samples

def document(enabled=False):
    doc=samples.sample();doc['stages']['setup']['reads']['use_risk_management']=enabled
    doc['stages']['cost_history']['symbols']['SYN'].update(previous_close_source='stored_previous_close',
        previous_close_forwarded=0.5,log_return_lookback_days=21)
    meta=reader._C['stages']['execution']['per_execution_reads']
    cost={name:samples.value(meta[name]) for name in reader._C['execution_cost_conditions']['common_required']}
    cost.update(commission_per_unit=0.005,min_commission_per_order=0.35,max_commission_pct=0.01,
        volatility_calculation_reached=False,retrieved_volatility_multiplier=1.0,effective_volatility_multiplier=1.0)
    doc['stages']['execution']['executions'][0]['reads']=cost
    doc['stages']['primary']['reads']['portfolio_invocation']=portfolio(enabled)
    return doc


@pytest.mark.parametrize('damage',['lone_start','lone_end','valuation_missing_mode','valuation_system_mode'])
def test_every_observed_partial_date_has_the_actual_run_bound(damage):
    doc=document();doc.update(available=False,complete=False,unavailable_reason='stage_failed')
    if damage in ('lone_start','lone_end'):
        stage=doc['stages']['market_input'];stage['outcome']='returned_error'
        stage['reads']={('start_day' if damage=='lone_start' else 'end_day'):'2026-09-27'}
    else:
        stage=doc['stages']['prior'];stage['outcome']='returned_error'
        stage['reads']={'source_day':'2026-09-25','valuation_day':'2026-09-25'}
        if damage=='valuation_system_mode':stage['reads']['mode']='system_reference'
    with pytest.raises(ValueError):reader.validate_equity_run_consumption(doc,expected_run_key=samples.KEY)


def test_matching_partial_dates_keep_observed_unavailability():
    doc=document();doc.update(available=False,complete=False,unavailable_reason='stage_failed')
    doc['stages']['market_input'].update(outcome='returned_error',reads={'start_day':'2026-09-25'})
    doc['stages']['prior'].update(outcome='returned_error',
        reads={'source_day':'2026-09-25','valuation_day':'2026-09-26'})
    assert reader.validate_equity_run_consumption(doc,expected_run_key=samples.KEY)==doc


@pytest.mark.parametrize('enabled',[False,True])
def test_complete_v4_preserves_real_invocation_roles_and_enabled_risk(enabled):
    doc=document(enabled)
    assert reader.validate_equity_run_consumption(doc,expected_run_key=samples.KEY)==doc
    child=doc['stages']['primary']['reads']['portfolio_invocation']
    assert child['full_run_certification'] is False
    assert child['compatibility_charges'][0]['purpose']=='compatibility'
    assert doc['stages']['execution']['executions'][0]['execution_id']=='actual-fixture-ID'


@pytest.mark.parametrize('damage',['missing_child','fake_full','unknown_pass','bool_index','foreign_charge',
    'charge_as_execution','missing_charge_read','duplicate_pass','setup_risk_mismatch','disabled_risk_called',
    'enabled_optimizer','nonfinite_risk','uncalled_risk_reads','skip_with_charge','failed_helper_complete'])
def test_incomplete_or_foreign_helper_cannot_claim_full_run(damage):
    doc=document();primary=doc['stages']['primary']['reads'];child=primary['portfolio_invocation'];p=child['passes'][0]
    if damage=='missing_child':primary.pop('portfolio_invocation')
    elif damage=='fake_full':child['full_run_certification']=True
    elif damage=='unknown_pass':p['caller_trusted']=True
    elif damage=='bool_index':p['index']=True
    elif damage=='foreign_charge':child['strategy_charges'][0]['strategy_id']='OTHER'
    elif damage=='charge_as_execution':child['compatibility_charges'][0]['execution_id']='forged'
    elif damage=='missing_charge_read':child['strategy_charges'][0]['reads'].pop('reference_price')
    elif damage=='duplicate_pass':child['passes'].append(deepcopy(p))
    elif damage=='setup_risk_mismatch':doc['stages']['setup']['reads']['use_risk_management']=True
    elif damage=='disabled_risk_called':p['risk_helper']='returned_ok';p['risk']['call']='returned_ok'
    elif damage=='enabled_optimizer':p['reads']['use_optimization']=True;doc['stages']['setup']['reads']['use_optimization']=True
    elif damage=='nonfinite_risk':p['risk']['reads']['var_limit']=float('nan')
    elif damage=='uncalled_risk_reads':p['risk']['reads']['var_limit']=0.2
    elif damage=='skip_with_charge':child['skip_execution_generation']=True
    elif damage=='failed_helper_complete':p['risk_helper']='returned_error'
    with pytest.raises(ValueError):reader.validate_equity_run_consumption(doc,expected_run_key=samples.KEY)


@pytest.mark.parametrize('skip,source',[('absent_risk_manager','absent'),('no_positions','internal')])
def test_actual_risk_skip_branches_preserve_manager_identity(skip,source):
    doc=document(True);child=doc['stages']['primary']['reads']['portfolio_invocation']
    child['passes'][0]['risk']={'call':'not_reached','skip':skip,'reads':{},'manager_source':source}
    if skip=='no_positions':child['passes'][0]['risk']['lookback_period']=21
    assert reader.validate_equity_run_consumption(doc,expected_run_key=samples.KEY)==doc


@pytest.mark.parametrize('skip,source',[('absent_optimizer','internal'),('insufficient_history','internal'),
    ('no_eligible_symbols','internal'),('absent_risk_manager','internal'),('no_positions','absent')])
def test_optimizer_skips_and_wrong_manager_cannot_be_risk_evidence(skip,source):
    doc=document(True);child=doc['stages']['primary']['reads']['portfolio_invocation']
    child['passes'][0]['risk']={'call':'not_reached','skip':skip,'reads':{},'manager_source':source}
    with pytest.raises(ValueError):reader.validate_equity_run_consumption(doc,expected_run_key=samples.KEY)


def test_nonfatal_actual_risk_failure_stays_visible_and_unavailable():
    doc=document(True);doc.update(available=False,complete=False,unavailable_reason='stage_failed')
    child=doc['stages']['primary']['reads']['portfolio_invocation']
    child.update(available=False,unavailable_reason='stage_failed')
    child['passes'][0]['risk']['call']='returned_error'
    assert reader.validate_equity_run_consumption(doc,expected_run_key=samples.KEY)==doc


@pytest.mark.parametrize('damage',['missing_lookback','absent_manager_lookback','unavailable_setup_mismatch'])
def test_actual_reached_fields_and_setup_flags_stay_bound_when_unavailable(damage):
    doc=document(True);child=doc['stages']['primary']['reads']['portfolio_invocation'];risk=child['passes'][0]['risk']
    if damage=='missing_lookback':risk.update(call='not_reached',skip='no_positions',reads={});risk.pop('lookback_period')
    elif damage=='absent_manager_lookback':risk.update(call='not_reached',skip='absent_risk_manager',reads={},manager_source='absent')
    else:
        doc.update(available=False,complete=False,unavailable_reason='stage_failed');child.update(available=False,unavailable_reason='stage_failed')
        risk['call']='returned_error';doc['stages']['setup']['reads']['use_risk_management']=False
    with pytest.raises(ValueError):reader.validate_equity_run_consumption(doc,expected_run_key=samples.KEY)


def test_portfolio_reason_must_be_one_the_actual_projector_emits():
    doc=document();doc.update(available=False,complete=False,unavailable_reason='invalid_observed_identity')
    doc['stages']['primary']['reads']['portfolio_invocation'].update(available=False,unavailable_reason='invalid_observed_identity')
    with pytest.raises(ValueError):reader.validate_equity_run_consumption(doc,expected_run_key=samples.KEY)


@pytest.mark.parametrize('damage',['prior','valuation','market'])
def test_partial_failure_cannot_hide_malformed_observed_chronology(damage):
    doc=document();doc.update(available=False,complete=False,unavailable_reason='stage_failed')
    if damage=='prior':
        doc['stages']['prior']['outcome']='returned_error';doc['stages']['prior']['reads']['source_day']='2026-09-27'
    elif damage=='valuation':
        p=doc['stages']['prior'];p['outcome']='returned_error';p['reads'].update(mode='verified_desk_prior',valuation_day='2026-09-25')
    else:
        doc['stages']['market_input']['outcome']='returned_error';doc['stages']['market_input']['reads']['end_day']='2026-09-27'
    with pytest.raises(ValueError):reader.validate_equity_run_consumption(doc,expected_run_key=samples.KEY)


def test_nil_uuid_is_not_a_proven_desk_source_reference():
    doc=document();p=doc['stages']['prior']
    p['reads']={name:samples.value(reader._C['stages']['prior']['reads'][name])
        for name in reader._C['conditional_readsets']['prior']['verified_desk_prior']['required']}
    p['reads'].update(mode='verified_desk_prior',valuation_day=samples.KEY['date'],decision_id='00000000-0000-0000-0000-000000000000')
    with pytest.raises(ValueError):reader.validate_equity_run_consumption(doc,expected_run_key=samples.KEY)
