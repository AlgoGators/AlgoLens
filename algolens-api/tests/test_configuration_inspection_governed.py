"""Actual native captures, including raw file allocations; no reconstructed observations."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
from algolens.domain.portfolio.equity_configuration_inspection import parse_publication, PublicationError
from algolens.application.runtime_control import validate_snapshot, RuntimeControlError

FIXTURES = Path(__file__).parent/'fixtures/configuration_inspection_v4_v5'
NOW = datetime(2027, 1, 1, tzinfo=timezone.utc)

def captured(name='equity_multi-v5'):
    return json.loads((FIXTURES/(name+'.json')).read_text())

def parse(value):
    identity=value['identity']
    scope={key:identity[key] for key in ('registry_id','registry_revision','engine_strategy_id','portfolio_id','run_date')}
    return parse_publication(json.dumps(value),scope,NOW)

@pytest.mark.parametrize('name',['equity_multi-v5','equity_now-v5','equity_empty_now-v5','equity_house-v5','futures-v4'])
def test_actual_native_capture(name):
    value=captured(name)
    assert parse(value)==value

@pytest.mark.parametrize('mutation',[
    lambda d:d.update(publication_schema_version=6),
    lambda d:d['identity'].update(config_attempt_id='00000000-0000-0000-0000-000000000000'),
    lambda d:d['configuration_selection'].update(effective_sha256='a'*64),
    lambda d:d['supplied']['fields'][0].update(consumer='invented'),
    lambda d:d['supplied']['fields'].pop(),
    lambda d:d['supplied']['effective_snapshot'].update(portfolio_id='WRONG'),
    lambda d:d['equity_multi_consumption']['coverage'].update(legacy_run_stages='observed'),
    lambda d:d['equity_multi_consumption']['portfolio_invocation']['passes'][0].update(risk_helper='fabricated'),
    lambda d:d['equity_multi_consumption']['strategy_invocations']['ALPHA']['symbols']['SYN']['reads'].update(secret_parameter=1),
])
def test_mutations_fail_closed(mutation):
    value=captured();mutation(value)
    with pytest.raises(PublicationError):parse(value)

def test_raw_file_allocation_is_not_approval_eligible():
    value=captured('equity_now-v5');s=value['supplied']['effective_snapshot'];i=value['identity']
    assert s['strategies']['MEAN_REVERSION']['default_allocation']==2
    assert parse(value)==value
    with pytest.raises(RuntimeControlError):validate_snapshot(s,i['portfolio_id'],i['engine_strategy_id'],governed=True)
    value['configuration_selection'].update(source='approved_override',version_id='00000000-0000-0000-0000-000000000001')
    with pytest.raises(PublicationError):parse(value)

@pytest.mark.parametrize('damage',['investor_approved','investor_revision','investor_controlled','future_day'])
def test_investor_identity_and_completed_day_fail_closed(damage):
    document=captured('equity_multi-v5')
    if damage=='investor_approved':
        document['configuration_selection']['source']='approved_override'
        document['configuration_selection']['version_id']='11111111-1111-4111-8111-111111111111'
    elif damage=='investor_revision':document['identity']['registry_revision']=1
    elif damage=='investor_controlled':
        document['identity']['control_mode']='controlled'
        document['identity']['runtime_attempt_id']=document['identity']['publication_id']
    else:document['identity']['run_date']='2099-01-01'
    with pytest.raises(PublicationError):parse(document)
