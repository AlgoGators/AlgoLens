"""Closed partial portfolio invocation; no publication or finance authority."""
from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from algolens.domain.shared.fixed_decimal8 import parse_fixed_decimal8

_BYTES=(Path(__file__).parent/'qt_equity_portfolio_consumption_contract.json').read_bytes()
if sha256(_BYTES).hexdigest()!='94ca88b15ca2a9a6d99d40ed169cd0e196cd3ec9cb4c1dab757c93196fda8cfe':
    raise ValueError('equity_portfolio_contract_pin_mismatch')
_C=json.loads(_BYTES)
_SYMBOL=re.compile(r'[A-Za-z0-9_.\-/]{1,64}\Z',re.ASCII)
_REASONS={'instrumentation_missing','unsupported_enabled_helper','capacity_exceeded','invalid_observed_value','stage_failed'}


def _need(condition):
    if not condition:raise ValueError('invalid_equity_portfolio_consumption')


def _shape(value,keys,required=None):
    _need(type(value) is dict and set(keys if required is None else required)<=set(value)<=set(keys))


def _number(value):
    _need(type(value) in (int,float) and math.isfinite(float(value)))


def _validate(document):
    _shape(document,_C['root_fields'])
    _need(document['schema_version']==_C['schema_version'] and document['scope']==_C['scope']
        and document['full_run_certification'] is False and type(document['available']) is bool)
    available=document['available']
    _need(document['unavailable_reason'] is None if available else document['unavailable_reason'] in _REASONS)
    _need(document['outcome'] in _C['call_outcomes'])
    skip=document['skip_execution_generation'];_need(skip is None or type(skip) is bool)
    passes=document['passes'];_need(type(passes) is list and len(passes)<=_C['pass_limit'])
    complete=document['outcome']=='returned_ok' and type(skip) is bool and bool(passes)
    for index,p in enumerate(passes):
        _shape(p,_C['pass_fields']);_need(type(p['index']) is int and p['index']==index)
        _shape(p['reads'],_C['pass_reads'],())
        for value in p['reads'].values():_need(type(value) is bool)
        _need(p['optimization_helper'] in _C['call_outcomes'] and p['risk_helper'] in _C['call_outcomes'])
        risk=p['risk'];_shape(risk,_C['risk_fields']+_C['risk_optional_fields'],_C['risk_fields'])
        _need(risk['call'] in _C['call_outcomes'] and risk['skip'] in _C['risk_skips'])
        _shape(risk['reads'],_C['risk_reads'],())
        for name,value in risk['reads'].items():
            if name=='capital_exact':_need(parse_fixed_decimal8(value) is not None)
            else:_number(value)
        if 'manager_source' in risk:_need(risk['manager_source'] in _C['manager_source'])
        if 'lookback_period' in risk:_need(type(risk['lookback_period']) is int and 0<=risk['lookback_period']<=2147483647)
        opt=p['reads'].get('use_optimization');enabled=p['reads'].get('use_risk_management')
        if opt is False:_need(p['optimization_helper']=='not_reached')
        if opt is not False:complete=False
        if enabled is None:complete=False
        elif enabled is False:
            _need(p['risk_helper']=='not_reached' and risk=={'call':'not_reached','skip':'none','reads':{}})
        else:
            if p['risk_helper']!='returned_ok':complete=False
            if risk['call']=='not_reached':
                _need(risk['reads']=={})
                if risk['skip']=='none':complete=False
                elif risk['skip']=='absent_risk_manager':
                    _need(risk.get('manager_source')=='absent' and 'lookback_period' not in risk)
                elif risk['skip']=='no_positions':
                    _need(risk.get('manager_source') in ('internal','external') and 'lookback_period' in risk)
            else:
                _need(risk['skip']=='none' and risk.get('manager_source') in ('internal','external'))
                if risk['call']!='returned_ok':complete=False
    allowed_reads=set(_C['charge_reads_number'])|set(_C['charge_reads_boolean'])|set(_C['charge_reads_enums'])
    for name in ('strategy_charges','compatibility_charges'):
        charges=document[name];_need(type(charges) is list and len(charges)<=_C['charge_limit'])
        if skip is True:_need(charges==[])
        purpose=_C['charge_purpose'][name]
        for index,charge in enumerate(charges):
            _shape(charge,_C['charge_fields']);_need(type(charge['index']) is int and charge['index']==index)
            owner='' if purpose=='compatibility' else _C['charge_owner'][purpose]
            _need(charge['purpose']==purpose and charge['strategy_id']==owner
                and type(charge['symbol']) is str and _SYMBOL.fullmatch(charge['symbol']) is not None
                and charge['call'] in _C['call_outcomes'])
            reads=charge['reads'];_shape(reads,allowed_reads,())
            for field,value in reads.items():
                if field in _C['charge_reads_boolean']:_need(type(value) is bool)
                elif field in _C['charge_reads_enums']:_need(type(value) is str and value in _C['charge_reads_enums'][field])
                else:_number(value)
            if charge['call']=='not_reached':_need(reads=={})
            if charge['call']!='returned_ok' or not set(_C['success_required_charge_reads'])<=set(reads):complete=False
    if available:_need(complete)
    _need(len(json.dumps(document,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8'))<=2*1024*1024)
    return deepcopy(document)


def validate_equity_portfolio_invocation(document):
    try:
        return _validate(document)
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,UnicodeError,RecursionError):
        raise ValueError('invalid_equity_portfolio_consumption') from None
