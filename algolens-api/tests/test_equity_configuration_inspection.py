"""Synthetic publication3 protocol controls, no source/runtime evidence."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
from algolens.domain.portfolio.configuration_inspection import PublicationError
from algolens.domain.portfolio import configuration_inspection as legacy

BASE=Path(__file__).parent
from algolens.domain.portfolio import equity_configuration_inspection as parser
BASE=Path(__file__).parent.parent
NOW=datetime(2026,9,27,12,tzinfo=timezone.utc)


def sample(available=True):
    from equity_inspection_samples import PUBLICATIONS
    return deepcopy(PUBLICATIONS[available])


def scope(document):
    return {key:document['identity'][key] for key in
        ('registry_id','registry_revision','engine_strategy_id','portfolio_id','run_date')}


@pytest.mark.parametrize('available',[True,False])
def test_schema3_preserves_closed_claims_and_partial_invocation(available):
    document=sample(available)
    assert parser.parse_publication(json.dumps(document),scope(document),NOW)==document
    assert document['authority']=='inspection_only'
    if available:
        assert document['equity_run_consumption']['stages']['primary']['reads']['strategy_invocation']['full_run_certification'] is False


def test_futures_v1_delegate_preserves_existing_catalog():
    path=Path(legacy.__file__).resolve().parents[3]/'tests/fixtures/configuration_inspection_v1.json'
    document=json.loads(path.read_bytes())
    assert parser.parse_publication(json.dumps(document),scope(document),NOW)==document


def test_futures_v2_delegate_preserves_existing_consumption_catalog():
    api=Path(legacy.__file__).resolve().parents[3]
    document=json.loads((api/'tests/fixtures/configuration_inspection_v1.json').read_bytes())
    cases=json.loads((api.parent/'contracts/consumption-v2-cases.json').read_bytes())
    document.update(publication_schema_version=2,consumption=deepcopy(cases['accepted']['ordinary']))
    assert parser.parse_publication(json.dumps(document),scope(document),NOW)==document


@pytest.mark.parametrize('damage',['unknown_root','futures_child','wrong_profile','bool_version','status','scope',
    'child_owner','child_day','capture_id','attempt_id','recorded_before_capture','future_capture','future_run','malformed_child'])
def test_schema3_never_admits_wrong_scope_or_capture(damage):
    document=sample();expected=scope(document)
    if damage=='unknown_root':document['caller_trusted']=True
    elif damage=='futures_child':document['consumption']={'status':'not_collected'}
    elif damage=='wrong_profile':document['profile']='live_portfolio_runner_futures'
    elif damage=='bool_version':document['publication_schema_version']=True
    elif damage=='status':document['status']='unavailable';document['reason']='consumption_unavailable'
    elif damage=='scope':expected['registry_revision']+=1
    elif damage=='child_owner':document['equity_run_consumption']['run_key']['portfolio_id']='OTHER'
    elif damage=='child_day':document['equity_run_consumption']['run_key']['date']='2026-09-25'
    elif damage=='capture_id':document['identity']['capture_id']='81000000-0000-4000-8000-000000000002'
    elif damage=='attempt_id':document['identity']['control_mode']='controlled';document['identity']['runtime_attempt_id']='81000000-0000-4000-8000-000000000002'
    elif damage=='recorded_before_capture':document['publication_recorded_at']='2026-09-26T00:00:00Z'
    elif damage=='future_capture':document['captured_at']='2026-09-28T12:00:00Z'
    elif damage=='future_run':document['identity']['run_date']='2026-09-28'
    elif damage=='malformed_child':document['equity_run_consumption']=[]
    with pytest.raises(PublicationError):parser.parse_publication(json.dumps(document),expected,NOW)


def test_schema3_duplicate_keys_refuse_before_child_admission():
    document=sample();raw=json.dumps(document)
    raw=raw.replace('"publication_schema_version": 3','"publication_schema_version": 3, "publication_schema_version": 3')
    with pytest.raises(PublicationError):parser.parse_publication(raw,scope(document),NOW)
