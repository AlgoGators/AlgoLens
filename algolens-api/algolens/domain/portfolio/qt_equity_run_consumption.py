"""Staged closed inspection DTO; no publication/finance/runtime certification.

The original producer/capture/storage identity must be bound by composition.
This validator reports only the instrumented document's closed claims.
"""
from copy import deepcopy
from datetime import date
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from uuid import UUID
from algolens.domain.shared.fixed_decimal8 import parse_fixed_decimal8
from .qt_equity_portfolio_consumption import validate_equity_portfolio_invocation

_BYTES=(Path(__file__).parent/'qt_equity_run_consumption_contract.json').read_bytes()
if sha256(_BYTES).hexdigest()!='d695c74986459fb432d6bbfa82ca8af0a0a987ad69d6d51bcf66e5ade1f08432':
    raise ValueError('equity_run_contract_pin_mismatch')
_C=json.loads(_BYTES)
_ACTION_BYTES=(Path(__file__).parent/'qt_equity_run_consumption_action_contract.json').read_bytes()
if sha256(_ACTION_BYTES).hexdigest()!='ae4a443f84a7e6e636068a2540c60e229828244cc9b294fe831a4dc6bc3e2ce6':
    raise ValueError('equity_run_contract_pin_mismatch')
_ACTION_C=json.loads(_ACTION_BYTES)
if _ACTION_C['base_contract_sha256']!=sha256(_BYTES).hexdigest():
    raise ValueError('equity_run_contract_pin_mismatch')
_CONTRACTS={
    (_C['document_schema_version'],_C['catalog_version']):_C,
    (_ACTION_C['document_schema_version'],_ACTION_C['catalog_version']):_ACTION_C,
}
_ID=re.compile(r'[A-Za-z0-9_.\-/]{1,64}\Z',re.ASCII)
_BOOK=re.compile(r'[A-Za-z0-9_-]{1,100}\Z',re.ASCII)
_MAX_NUMBER=((1<<53)-1)<<971
_PARTIAL_INTS={'lookback_period','vol_lookback','maximum_price_history','maximum_volatility_history'}
_PARTIAL_SIGNED_INTS={'lookback_period','vol_lookback'}
_SAFE_INTEGER=(1<<53)-1
_PARTIAL_BOOLS={'use_stop_loss','allow_fractional_shares','position_limit_present'}
_PARTIAL_NUMBERS={'entry_threshold','exit_threshold','stop_loss_pct','capital_allocation','position_size',
    'risk_target','fractional_min_price','fractional_min_adv','position_limit'}
_STATE={'volume_sample_count':'integer','average_daily_volume':'number','fractional_eligible':'boolean','short_allowed':'boolean'}

def _need(value):
    if not value:raise ValueError('invalid_equity_run_consumption')

def _shape(value,keys):_need(type(value) is dict and set(value)==set(keys))
def _day(value):
    _need(type(value) is str and len(value)==10 and date.fromisoformat(value).isoformat()==value)
def _identity(value):_need(type(value) is str and _ID.fullmatch(value) is not None)
def _number(value):
    _need((type(value) is int and -_MAX_NUMBER<=value<=_MAX_NUMBER) or
        (type(value) is float and math.isfinite(value)))

def _value(value,definition):
    if 'ref' in definition:
        if definition['ref']=='qt-equity-strategy-consumption/v1':validate_equity_strategy_invocation(value)
        elif definition['ref']=='qt-equity-portfolio-consumption/v1':validate_equity_portfolio_invocation(value)
        else:raise ValueError('invalid_equity_run_consumption')
        return
    if 'const' in definition:_need(type(value) is type(definition['const']) and value==definition['const']);return
    if 'enum' in definition:_need(type(value) is str and value in definition['enum']);return
    kind=definition.get('type')
    if kind=='boolean':_need(type(value) is bool)
    elif kind=='integer':_need(type(value) is int and definition['minimum']<=value<=definition['maximum'])
    elif kind=='number':_number(value)
    elif kind=='string':
        _need(type(value) is str)
        if definition.get('format')=='date':_day(value)
        elif definition.get('format')=='canonical-uuid':_need(str(UUID(value))==value and UUID(value).int!=0)
        elif definition.get('format')=='canonical-decimal8-checked-int64':_need(parse_fixed_decimal8(value) is not None)
        elif 'pattern' in definition:_need(re.fullmatch(definition['pattern'],value) is not None)
        else:_need(definition.get('minLength',0)<=len(value)<=definition.get('maxLength',256))
    else:raise ValueError('invalid_equity_run_consumption')

def _reads(values,definitions,required=()):
    _need(type(values) is dict and set(required)<=set(values)<=set(definitions))
    for name,value in values.items():_value(value,definitions[name])


def _branch_reads(values,condition):
    """Validate the observed source branch; never calculate financial output."""
    _need(set(condition.get('required',()))<=set(values) and not(set(condition.get('forbidden',()))&set(values)))
    for field,expected in condition.get('equal',{}).items():_need(values.get(field)==expected)


def _cost_reads(values,contract):
    conditions=contract['execution_cost_conditions']
    _need(values['quantity']!=0 and values['reference_price']>0)
    if values['commission_per_unit']>=0:
        branch=conditions['commission_nonnegative'];_branch_reads(values,branch)
        _branch_reads(values,branch['percentage_ceiling' if values['max_commission_pct']>=0 else 'order_ceiling'])
    else:_branch_reads(values,conditions['commission_fallback'])
    _branch_reads(values,conditions['regulatory_sell' if values['apply_regulatory_fees'] and values['quantity']<0 else 'regulatory_unreached'])
    _branch_reads(values,conditions['volatility_calculated' if values['volatility_calculation_reached'] else 'volatility_neutral'])

def _validate_equity_strategy_invocation(document):
    """Independent partial schema; never relabelled as full-run consumption."""
    base={'schema_version','available','profile','scope','full_run_certification','symbols'}
    _shape(document,base if document.get('available') is True else base|{'reason'})
    _need(document['schema_version']=='qt-equity-strategy-consumption/v1' and document['profile']=='mean_reversion'
        and document['scope']=='strategy_invocation' and document['full_run_certification'] is False
        and type(document['available']) is bool)
    if not document['available']:_need(document['reason']=='non_trading_invocation_not_reached' and document['symbols']=={})
    symbols=document['symbols'];_need(type(symbols) is dict and len(symbols)<=256)
    for symbol,row in symbols.items():
        _identity(symbol);_shape(row,{'reads','observed_state'});reads=row['reads'];state=row['observed_state']
        _need(type(reads) is dict and set(reads)<=_PARTIAL_INTS|_PARTIAL_BOOLS|_PARTIAL_NUMBERS
            and type(state) is dict and set(state)<=set(_STATE))
        for field,value in reads.items():
            if field in _PARTIAL_SIGNED_INTS:_need(type(value) is int and -(1<<31)<=value<(1<<31))
            elif field in _PARTIAL_INTS:_need(type(value) is int and 0<=value<=_SAFE_INTEGER)
            elif field in _PARTIAL_BOOLS:_need(type(value) is bool)
            else:_number(value)
        for field,value in state.items():
            if _STATE[field]=='boolean':_need(type(value) is bool)
            elif _STATE[field]=='integer':_need(type(value) is int and 0<=value<=_SAFE_INTEGER)
            else:_number(value)
        if 'position_limit_present' in reads:_need(reads['position_limit_present']==('position_limit' in reads))
        else:_need('position_limit' not in reads)
        if reads.get('allow_fractional_shares') is False:_need('fractional_min_price' not in reads)
        if reads.get('use_stop_loss') is False:_need('stop_loss_pct' not in reads)
        adv=('fractional_min_adv' in reads,'volume_sample_count' in state,'average_daily_volume' in state)
        _need(all(adv) or not any(adv))
    return deepcopy(document)

def _validate_equity_run_consumption(document, *, expected_run_key):
    _C=_CONTRACTS.get((document.get('schema_version'),document.get('catalog_version')))
    _need(_C is not None)
    _shape(document,_C['root_fields']);_shape(document['run_key'],_C['run_key_fields'])
    key=document['run_key'];_need(key==expected_run_key)
    _need(type(key['portfolio_id']) is str and _BOOK.fullmatch(key['portfolio_id']) is not None)
    for name in ('strategy_id','strategy_name'):_identity(key[name])
    _day(key['date'])
    _need(key['strategy_id']==_C['fixed_strategy_id'] and key['strategy_name']==_C['fixed_strategy_name'])
    _need(document['schema_version']==_C['document_schema_version'] and document['catalog_version']==_C['catalog_version']
        and document['scope']==_C['scope'] and document['profile']==_C['profile'])
    _need(type(document['available']) is bool and type(document['complete']) is bool
        and document['available']==document['complete'])
    if document['available']:_need(document['unavailable_reason'] is None)
    else:_need(document['unavailable_reason'] in _C['unavailable_reasons'])
    stages=document['stages'];_shape(stages,_C['stages']);success=True
    if _C is _ACTION_C:
        action_reads=stages['corporate_actions']['reads']
        condition=_C['conditional_readsets']['corporate_actions'][_C['variant_path']]
        _need(action_reads.get('path')==_C['variant_path'])
        _need(stages['prior']['reads'].get('mode')==condition['must_match_prior_mode'])
        _need(not(set(action_reads)&set(condition['forbidden'])))
        if 'effective_event_count' in action_reads:
            _need(type(action_reads['effective_event_count']) is int and
                action_reads['effective_event_count']==condition['effective_event_count'])
    for name,definition in _C['stages'].items():
        stage=stages[name];_shape(stage,_C['stage_fields']);outcome=stage['outcome']
        _need(outcome in _C['outcomes']);successful=outcome in ('returned_ok','skipped')
        success=success and successful
        if outcome=='not_reached':_need(stage=={'outcome':'not_reached','skip_reason':None,'reads':{},'symbols':{},'executions':[]})
        if outcome!='skipped':_need(stage['skip_reason'] is None)
        else:_need(stage['skip_reason'] in _C['skip_reasons'].get(name,[]))
        required=definition['required'] if successful else ()
        reads=stage['reads']
        if name in ('prior','corporate_actions','eod') and successful:
            field='mode' if name=='prior' else 'path'
            condition=_C['conditional_readsets'][name][reads[field]]
            required=condition['required'];_need(not(set(reads)&set(condition['forbidden'])))
            if 'effective_event_count' in condition:_need(reads.get('effective_event_count')==condition['effective_event_count'])
            if 'positive_count_fields' in condition:
                _need(sum(reads[field] for field in condition['positive_count_fields'])>=condition['minimum_count_sum'])
            if 'must_match_prior_mode' in condition:_need(stages['prior']['reads'].get('mode')==condition['must_match_prior_mode'])
            if 'outcome' in condition:_need(outcome==condition['outcome'] and stage['skip_reason']==condition['skip_reason'])
        nontrading=outcome=='skipped' and stage['skip_reason']=='non_trading_day'
        if nontrading:required=();_need(reads=={})
        _reads(reads,definition.get('reads',{}),required)
        if name=='prior':
            if 'source_day' in reads:_need(reads['source_day']<key['date'])
            if 'valuation_day' in reads:_need(reads['valuation_day']==key['date'])
        if name=='market_input':
            for field in ('start_day','end_day'):
                if field in reads:_need(reads[field]<=key['date'])
            if 'start_day' in reads and 'end_day' in reads:_need(reads['start_day']<=reads['end_day'])
        symbols=stage['symbols'];_need(type(symbols) is dict and len(symbols)<=_C['symbol_limit'])
        if name not in _C['collection_shapes']['symbols']['allowed_stages']:_need(symbols=={})
        for symbol,values in symbols.items():
            _identity(symbol);meta=definition['per_symbol_reads']
            required=(_C['cost_history_conditions']['common_required'] if name=='cost_history' else meta) if successful else ()
            _reads(values,meta,required)
            if name=='cost_history' and successful:
                branch=_C['cost_history_conditions'][values['previous_close_source']];_branch_reads(values,branch)
                if 'greater_than_zero' in branch:_need(values[branch['greater_than_zero']]>0)
        executions=stage['executions'];_need(type(executions) is list and len(executions)<=_C['execution_limit'])
        if name!='execution':_need(executions==[])
        ids=set()
        for index,execution in enumerate(executions):
            _shape(execution,_C['collection_shapes']['executions']['entry_fields']);_identity(execution['symbol'])
            _need(all(execution[field]==key[field] for field in ('portfolio_id','strategy_id','strategy_name')))
            _need(type(execution['index']) is int and execution['index']==index)
            identity=execution['execution_id'];_need(type(identity) is str and 0<len(identity.encode('utf-8'))<=50 and identity not in ids);ids.add(identity)
            meta=definition['per_execution_reads']
            _reads(execution['reads'],meta,_C['execution_cost_conditions']['common_required'] if successful else ())
            if successful:_cost_reads(execution['reads'],_C)
        if nontrading:_need(symbols=={} and executions==[])
    skips=[stages[name]['outcome']=='skipped' and stages[name]['skip_reason']=='non_trading_day' for name in ('preparation','primary','execution')]
    _need(all(skips) or not any(skips))
    primary=stages['primary']['reads']
    if 'portfolio_invocation' in primary:
        for p in primary['portfolio_invocation']['passes']:
            _need(all(name in stages['setup']['reads'] and value==stages['setup']['reads'][name]
                for name,value in p['reads'].items()))
    if document['available']:
        _need(success and stages['setup']['reads']['use_optimization'] is False)
        if not all(skips):
            portfolio=primary['portfolio_invocation']
            _need(primary['strategy_invocation']['available'] is True and portfolio['available'] is True)
            for p in portfolio['passes']:
                _need(all(p['reads'][name]==stages['setup']['reads'][name] for name in ('use_optimization','use_risk_management')))
    _need(len(json.dumps(document,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8'))<=2*1024*1024)
    return deepcopy(document)


def validate_equity_strategy_invocation(document):
    """Admit only the independent partial schema, with a fixed refusal."""
    try:
        return _validate_equity_strategy_invocation(document)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError):
        raise ValueError('invalid_equity_run_consumption') from None


def validate_equity_run_consumption(document, *, expected_run_key):
    """Admit the closed inspection document without certifying publication."""
    try:
        return _validate_equity_run_consumption(document,expected_run_key=expected_run_key)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError):
        raise ValueError('invalid_equity_run_consumption') from None
