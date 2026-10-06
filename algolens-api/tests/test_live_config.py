import copy
import json
from pathlib import Path
import pytest
from algolens.domain.identity.capabilities import resolve_capabilities
from algolens.application.runtime_control import validate_snapshot, RuntimeControlError

FIXTURES = Path(__file__).parent/'fixtures/live_config'
def baseline(name='conservative'):
    return json.loads((FIXTURES/(name+'.json')).read_text())

def test_explicit_config_grants_do_not_grant_qt_authority():
    mappings=[{'person_id':'xander_robbins','active':True}]
    caps=resolve_capabilities('admin',grants=[{'capability':'config_submit','active':True},
                                            {'capability':'config_approve','active':True}],mappings=mappings)
    assert {'edit_config','approve_config'} <= set(caps)
    assert not {'edit_qt_book','approve_qt_override'} & set(caps)
    assert not {'edit_config','approve_config'} & set(resolve_capabilities('admin'))

@pytest.mark.parametrize('name,engine',[('conservative','LIVE_TREND_FOLLOWING'),('equity_mr','LIVE_EQUITY_MEAN_REVERSION')])
def test_native_export_v2_raw_identity(name,engine):
    data=baseline(name)
    validate_snapshot(data,data['portfolio_id'],engine)
    with pytest.raises(RuntimeControlError): validate_snapshot(data,data['portfolio_id'],'LIVE_FAKE')

def test_equity_composite_raw_identity():
    data=baseline('equity_mr'); definition=data['strategies'].pop('MEAN_REVERSION')
    data['strategies']={'ALPHA':copy.deepcopy(definition),'BETA':copy.deepcopy(definition)}
    for entry in data['strategies'].values(): entry['default_allocation']=.5
    validate_snapshot(data,data['portfolio_id'],'LIVE_EQUITY_ALPHA_BETA')

from algolens.application.live_config import body_fields, resolve_person, LiveConfigError, native_reply

def authority():
    return {'account':{'id':1,'role':'admin'},'retired':False,
        'grants':[{'capability':'config_submit','active':True,'version':3}],
        'mappings':[{'person_id':'xander_robbins','active':True,'mapping_version':4}]}

@pytest.mark.parametrize('mutation',['unmapped','retired','revoked','unknown_person','missing_grant','role'])
def test_current_authority_fails_closed(mutation):
    value=authority()
    if mutation=='unmapped': value['mappings']=[]
    if mutation=='retired': value['retired']=True
    if mutation=='revoked': value['grants'][0]['active']=False
    if mutation=='unknown_person': value['mappings'][0]['person_id']='john_riley'
    if mutation=='missing_grant': value['grants']=[]
    if mutation=='role': value['account']['role']='subscriber_individual'
    with pytest.raises(LiveConfigError): resolve_person(1,value,'config_submit')

def test_config_identity_independent_of_qt_quorum():
    assert resolve_person(1,authority(),'config_submit')=={'user_id':1,'person_id':'xander_robbins','grant_version':3,'mapping_version':4}

@pytest.mark.parametrize('changes,previous',[({},None),({'/x':1},'00000000-0000-0000-0000-000000000001')])
def test_reset_requires_existing_version_and_empty_changes(changes,previous):
    with pytest.raises(LiveConfigError): body_fields({'portfolio_id':'BOOK','reason':'reset','operation':'reset_to_baseline',
        'changes':changes,'expected_active_version':previous})

@pytest.mark.parametrize('result',[{}, {'schema':'live-config-validation/v1'}, None, [], {'error':'private'}])
def test_malformed_native_response_refuses(result):
    with pytest.raises(LiveConfigError): native_reply(result,{'portfolio_id':'BOOK','engine_strategy_id':'LIVE_TEST'},{'/x':1},'override')

def test_legacy_snapshots_are_history_only():
    from tests.test_runtime_control import snapshot
    from algolens.infrastructure.portfolio.runtime_control import _intent, PostgresRuntimeControlRepository
    data=snapshot(); data['snapshot_version']=1
    for key in ('use_optimization','covariance_history_prices','sleeve_risk_modules'): del data[key]
    validate_snapshot(data,'TEST_BOOK','LIVE_TEST')
    with pytest.raises(RuntimeControlError): validate_snapshot(data,'TEST_BOOK','LIVE_TEST',governed=True)
    with pytest.raises(RuntimeControlError): PostgresRuntimeControlRepository._check(
        {'id':'test','strategy_type':'LIVE_TEST','portfolio_id':'TEST_BOOK','lifecycle':'live','is_active':True},
        {'registry_id':'test','portfolio_id':'TEST_BOOK','engine_strategy_id':'LIVE_TEST','config_snapshot':data},'run')

def test_v2_default_futures_type_matches_native():
    data=baseline(); del data['strategies']['TREND_FOLLOWING']['type']
    validate_snapshot(data,data['portfolio_id'],'LIVE_TREND_FOLLOWING')

@pytest.mark.parametrize('schema',['live-config-validation/v1','live-config-baseline-validation/v1'])
def test_wrong_native_protocol_and_error_envelope_are_not_approved(schema):
    data=baseline(); scope={'portfolio_id':data['portfolio_id'],'engine_strategy_id':'LIVE_TREND_FOLLOWING'}
    with pytest.raises(LiveConfigError): native_reply({'schema':schema,'error':'live_config_invalid_request'},scope,{},'reset_to_baseline')
    if schema=='live-config-validation/v1':
        with pytest.raises(LiveConfigError): native_reply({'schema':schema,'base_sha256':'a'*64,'effective_sha256':'a'*64,
            'effective_snapshot':data,'changed_paths':[]},scope,{},'reset_to_baseline')
