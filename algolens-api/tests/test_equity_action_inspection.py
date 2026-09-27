"""Synthetic action protocol controls through production imports only."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import pytest

from algolens.domain.portfolio.qt_equity_run_consumption import validate_equity_run_consumption
from algolens.domain.portfolio.equity_configuration_inspection import parse_publication, PublicationError

RAW=(Path(__file__).parent/'fixtures/equity_action_inspection_synthetic.json').read_bytes()
assert sha256(RAW).hexdigest()=='13903c37d122f5617158c7c36d6d0fd65e1a4a3c22222ac7b9e8935b2744a627'
VECTORS=json.loads(RAW)
assert VECTORS['actual_published_source'] is False and VECTORS['native_financial_proof'] is False
NOW=datetime(2026,9,27,12,tzinfo=timezone.utc)

def sample(name='original_S_and_derived_D'):
    return deepcopy(VECTORS['publications'][name])

def scope(value):
    return {field:value['identity'][field] for field in
        ('registry_id','registry_revision','engine_strategy_id','portfolio_id','run_date')}

def child(value):return value['equity_run_consumption']
def reads(value):return child(value)['stages']['corporate_actions']['reads']

@pytest.mark.parametrize('name',list(VECTORS['publications']))
def test_production_import_accepts_exact_shared_synthetic_publication(name):
    value=sample(name);before=deepcopy(value)
    admitted=validate_equity_run_consumption(child(value),expected_run_key=child(value)['run_key'])
    assert admitted==child(before) and admitted is not child(value)
    assert parse_publication(json.dumps(value),scope(value),NOW)==before
    assert value==before and value['authority']=='inspection_only'

@pytest.mark.parametrize('field',['original_action_count','successor_action_count'])
def test_production_import_preserves_exact_int32_count_boundary(field):
    value=sample();reads(value)[field]=2147483647
    assert parse_publication(json.dumps(value),scope(value),NOW)==value

@pytest.mark.parametrize('damage',['zero_counts','bool','negative','overflow','float','reapplication',
    'missing_original_digest','missing_successor_digest','missing_basis','unknown_read',
    'unknown_schema','unknown_catalog','mixed_catalog','mixed_schema','v1_action_fields',
    'v2_action_free','wrong_prior','foreign_book','foreign_day','extra_outer','wrong_capture'])
def test_production_composition_refuses_malformed_action_or_publication(damage):
    value=sample();run=child(value);actual=reads(value);expected=scope(value)
    if damage=='zero_counts':actual.update(original_action_count=0,successor_action_count=0)
    elif damage=='bool':actual['original_action_count']=True
    elif damage=='negative':actual['successor_action_count']=-1
    elif damage=='overflow':actual['original_action_count']=2147483648
    elif damage=='float':actual['original_action_count']=1.0
    elif damage=='reapplication':actual['effective_event_count']=1
    elif damage.startswith('missing_'):actual.pop({'missing_original_digest':'original_action_digest','missing_successor_digest':'successor_action_digest','missing_basis':'basis_frame_digest'}[damage])
    elif damage=='unknown_read':actual['trusted_actions']=True
    elif damage=='unknown_schema':run['schema_version']='qt-equity-run-consumption/v3'
    elif damage=='unknown_catalog':run['catalog_version']='qt-equity-main08b15c-run/v3'
    elif damage=='mixed_catalog':run['catalog_version']='qt-equity-main08b15c-run/v1'
    elif damage=='mixed_schema':run['schema_version']='qt-equity-run-consumption/v1'
    elif damage=='v1_action_fields':run.update(schema_version='qt-equity-run-consumption/v1',catalog_version='qt-equity-main08b15c-run/v1')
    elif damage=='v2_action_free':actual.clear();actual.update(path='proved_action_free_prior',effective_event_count=0)
    elif damage=='wrong_prior':run['stages']['prior']['reads']={'mode':'system_reference','source_day':'2026-09-25'}
    elif damage=='foreign_book':run['run_key']['portfolio_id']='FOREIGN'
    elif damage=='foreign_day':run['run_key']['date']='2026-09-25'
    elif damage=='extra_outer':value['proved_actions']=True
    else:value['identity']['capture_id']='81000000-0000-4000-8000-000000000002'
    with pytest.raises(PublicationError):parse_publication(json.dumps(value),expected,NOW)

@pytest.mark.parametrize('field',['original_action_digest','successor_action_digest','basis_frame_digest'])
@pytest.mark.parametrize('invalid',['A'*64,'a'*63,'a'*64+'\n','g'*64,True])
def test_production_composition_refuses_noncanonical_digest(field,invalid):
    value=sample();reads(value)[field]=invalid
    with pytest.raises(PublicationError):parse_publication(json.dumps(value),scope(value),NOW)

@pytest.mark.parametrize('field,value',[('spinoff_child_policy_requested','hold'),
    ('spinoff_child_policy_effective','hold'),('effective_event_count',1),('effective_event_count',True)])
def test_failed_partial_never_admits_contradictory_action_reads(field,value):
    document=sample('unavailable_partial');reads(document)[field]=value
    with pytest.raises(PublicationError):parse_publication(json.dumps(document),scope(document),NOW)

def test_failed_adjusted_trace_still_requires_verified_prior_and_unavailable_outer():
    value=sample('unavailable_partial');run=child(value)
    assert parse_publication(json.dumps(value),scope(value),NOW)==value
    assert set(reads(value))=={'path','original_action_count'}
    run['stages']['prior']['reads']={'mode':'system_reference','source_day':'2026-09-25'}
    run['stages']['eod'].update(outcome='not_reached',skip_reason=None,reads={})
    with pytest.raises(PublicationError):parse_publication(json.dumps(value),scope(value),NOW)

def test_unchanged_v1_synthetic_bytes_and_claims_remain_exact():
    value=sample('unchanged_v1');before=json.dumps(value,sort_keys=True,separators=(',',':'))
    assert parse_publication(before,scope(value),NOW)==value
    assert json.dumps(value,sort_keys=True,separators=(',',':'))==before
    assert child(value)['schema_version']=='qt-equity-run-consumption/v1'
