import pytest
from tests.test_incubation_routes import _set_jwt_cookie
from algolens.application.live_config import LiveConfigService
URL='/portfolio/strategies/test/config'
BODY={'portfolio_id':'BOOK','changes':{'/optimization/cost_penalty_scalar':12.75},'reason':'reviewed','expected_active_version':None}

@pytest.fixture
def repo(monkeypatch):
    import algolens.adapters.http.live_config as http
    class Repository:
        calls=[]
        def candidate(self,strategy,body,actor,config,*,persist):
            self.calls.append((strategy,body,actor,persist)); return {'version_id':'candidate','execution_authorized':False}
        def status(self,*args): return {'active':None}
        def approve(self,*args): self.calls.append(args); return {'execution_authorized':False}
    instance=Repository(); instance.calls=[]
    monkeypatch.setattr(http,'_service',lambda:LiveConfigService(instance,object()))
    return instance

def grant(monkeypatch, capability):
    import algolens.adapters.http.capability_guard as guard
    monkeypatch.setattr(guard,'_authority_rows',lambda _:([{'capability':capability,'active':True}],
        [{'person_id':'xander_robbins','active':True}]))

def test_no_implicit_config_grants(client,repo):
    csrf=_set_jwt_cookie(client,role='admin',identity='7')
    assert client.post(URL+'/requests',json=BODY,headers={'X-CSRF-TOKEN':csrf}).status_code==403
    assert not repo.calls

def test_session_and_csrf_and_identity(client,repo,monkeypatch):
    assert client.get(URL+'?portfolio_id=BOOK').status_code==401
    csrf=_set_jwt_cookie(client,role='admin',identity='7'); grant(monkeypatch,'config_submit')
    assert client.post(URL+'/requests',json=BODY).status_code==401
    response=client.post(URL+'/requests',json=BODY,headers={'X-CSRF-TOKEN':csrf})
    assert response.status_code==201 and repo.calls[0][2]==7
    assert response.json['execution_authorized'] is False

@pytest.mark.parametrize('extra',['submitted_by','base_snapshot','validator_sha256','submission_authority','executable','approved_by'])
def test_no_client_authority(client,repo,monkeypatch,extra):
    csrf=_set_jwt_cookie(client,role='admin',identity='7'); grant(monkeypatch,'config_submit')
    assert client.post(URL+'/requests',json={**BODY,extra:'forged'},headers={'X-CSRF-TOKEN':csrf}).status_code==400
    assert not repo.calls

def test_grants_are_separate_and_deleted_account_refuses(client,repo,monkeypatch):
    csrf=_set_jwt_cookie(client,role='admin',identity='7'); grant(monkeypatch,'config_approve')
    assert client.post(URL+'/requests',json=BODY,headers={'X-CSRF-TOKEN':csrf}).status_code==403
    client.current_users.remove('7')
    assert client.get(URL+'?portfolio_id=BOOK').status_code==403

def test_error_details_not_reflected(client,repo,monkeypatch):
    csrf=_set_jwt_cookie(client,role='admin',identity='7'); grant(monkeypatch,'config_submit')
    def fail(*a,**kw): raise RuntimeError('cookie-secret and sql-secret')
    repo.candidate=fail
    response=client.post(URL+'/requests',json=BODY,headers={'X-CSRF-TOKEN':csrf})
    assert response.status_code==503 and 'secret' not in response.text

@pytest.mark.parametrize('raw',['{"reason":"one","reason":"two"}','{"changes":{"/x":NaN}}'])
def test_duplicate_and_nonfinite_json_refused(client,repo,monkeypatch,raw):
    csrf=_set_jwt_cookie(client,role='admin',identity='7'); grant(monkeypatch,'config_submit')
    response=client.post(URL+'/requests',data=raw,content_type='application/json',headers={'X-CSRF-TOKEN':csrf})
    assert response.status_code==400 and not repo.calls

def test_config_payloads_never_logged(client,repo,monkeypatch,caplog):
    csrf=_set_jwt_cookie(client,role='admin',identity='7'); grant(monkeypatch,'config_submit')
    response=client.post(URL+'/requests',json={**BODY,'credential':'must-not-be-logged'},headers={'X-CSRF-TOKEN':csrf})
    assert response.status_code==400 and 'must-not-be-logged' not in caplog.text
