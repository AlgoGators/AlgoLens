"""Current authority/CAS and real sealed native validation on owned PostgreSQL."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
import pytest
from tests.integration.conftest import claim_schema, require_test_dsn, OWNERSHIP_MARK
from tests.qt_native_artifacts import require_native_artifact_paths
from tests.live_config_native import native_pin
from tests.test_live_config import baseline
from algolens.application.live_config import LiveConfigService, LiveConfigError
from algolens.infrastructure.config.live_config import LiveConfigConfig
from algolens.infrastructure.portfolio.live_config import PostgresLiveConfigRepository
from algolens.infrastructure.portfolio.runtime_control import PostgresRuntimeControlRepository
from algolens.application.runtime_control import RuntimeControlError

pytestmark=pytest.mark.integration
API=Path(__file__).resolve().parents[2]

@pytest.fixture
def database(tmp_path):
    dsn=require_test_dsn(); paths=require_native_artifact_paths()
    conn=psycopg2.connect(dsn); conn.autocommit=True
    with conn.cursor() as cur:
        claim_schema(cur)
        cur.execute("SELECT obj_description(oid,'pg_namespace') FROM pg_namespace WHERE nspname='auth'")
        existing=cur.fetchone()
        if existing:
            assert existing[0]==OWNERSHIP_MARK, 'refuse unowned auth schema'
            cur.execute('DROP SCHEMA auth CASCADE')
        cur.execute('CREATE SCHEMA auth'); cur.execute('COMMENT ON SCHEMA auth IS %s',(OWNERSHIP_MARK,))
        cur.execute('''CREATE TABLE auth.users(id bigint PRIMARY KEY,role text);
          INSERT INTO auth.users VALUES(1,'admin'),(2,'admin'),(3,'admin');
          CREATE TABLE auth.account_retirements(user_id bigint PRIMARY KEY REFERENCES auth.users(id));
          CREATE TABLE trading.strategy_registry(id text PRIMARY KEY,strategy_type text,portfolio_id text,lifecycle text,is_active boolean);
          CREATE TABLE trading.strategy_book_memberships(strategy_id text REFERENCES trading.strategy_registry(id),portfolio_id text);
          INSERT INTO trading.strategy_registry VALUES('test','LIVE_TREND_FOLLOWING','CONSERVATIVE_PORTFOLIO','live',true);''')
        for table in ('positions','risk_limits','live_results','equity_curve','executions','signals','live_run_metadata','run_inputs'):
            cur.execute(f'CREATE TABLE trading.{table}(strategy_id text,portfolio_id text,portfolio_type text)')
        cur.execute((API/'migrations/003_qt_decision_workflow.sql').read_text())
        cur.execute((paths.source_dir/'migrations/013_runtime_control.sql').read_text())
        cur.execute((paths.source_dir/'migrations/031_live_config_overrides.sql').read_text())
        cur.execute((API/'migrations/011_live_config_authority.sql').read_text())
        cur.execute("INSERT INTO trading.qt_action_grants VALUES(1,'config_submit',true,1,now()),(1,'config_approve',true,1,now()),(2,'config_approve',true,1,now())")
        cur.execute("INSERT INTO trading.qt_approver_allowlist VALUES('xander_robbins','xander robbins',1,true,1,now()),('hemdutt_rao','hemdutt rao',2,true,1,now())")
    def factory(): return psycopg2.connect(dsn,cursor_factory=RealDictCursor,options='-c statement_timeout=15000 -c lock_timeout=5000')
    repo=PostgresLiveConfigRepository(factory)
    manifest=tmp_path/'manifest.json'
    data={'version':1,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
          'validator':native_pin(),'scopes':[{'registry_id':'test','portfolio_id':'CONSERVATIVE_PORTFOLIO',
          'engine_strategy_id':'LIVE_TREND_FOLLOWING','config_snapshot':baseline()}]}
    manifest.write_text(json.dumps(data))
    config=LiveConfigConfig({'LIVE_CONFIG_MANIFEST':str(manifest)})
    service=LiveConfigService(repo,config)
    yield conn,service,manifest
    conn.close()

def body(previous=None, operation='override'):
    return {'portfolio_id':'CONSERVATIVE_PORTFOLIO','reason':'reviewed',
            'expected_active_version':previous,'operation':operation,
            'changes':{} if operation=='reset_to_baseline' else {'/optimization/cost_penalty_scalar':12.75}}

def submit(service,**kwargs): return service.submit('test',body(**kwargs),1)
def approve(service,row, actor=2):
    return service.approve('test',row['version_id'],{'portfolio_id':row['portfolio_id'],'reason':'checked',
        'expected_active_version':row['previous_version_id']},actor)

def test_submit_distinct_approve_active_and_governed_reset(database):
    conn,svc,_=database
    preview=svc.preview('test',body(),1)
    row=submit(svc); assert row['effective_sha256']==preview['effective_sha256']
    result=approve(svc,row); assert result['execution_authorized'] is False
    selected=svc.repository.selected_scope('test',row['portfolio_id'],svc.config)
    assert selected['config_snapshot']['optimization']['cost_penalty_scalar']==12.75
    reset=submit(svc,previous=row['version_id'],operation='reset_to_baseline'); approve(svc,reset)
    status=svc.status('test',row['portfolio_id']); assert status['active']['version_id']==reset['version_id']
    assert reset['base_sha256']==reset['effective_sha256']
    with conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM trading.runtime_intents'); assert cur.fetchone()[0]==0
        cur.execute('SELECT authority_versions FROM trading.live_config_activations LIMIT 1')
        assert cur.fetchone()[0]['submitter']['grant_version']==1

@pytest.mark.parametrize('mutation',['self','revoke','regrant','retire','unmap','remap','revision','baseline','expiry','bundle'])
def test_activation_revalidates_every_gate(database,mutation):
    conn,svc,manifest=database; row=submit(svc)
    with conn.cursor() as cur:
        if mutation=='revoke': cur.execute("UPDATE trading.qt_action_grants SET active=false,version=2 WHERE user_id=2")
        if mutation=='regrant': cur.execute("UPDATE trading.qt_action_grants SET active=false,version=2 WHERE user_id=1"); cur.execute("UPDATE trading.qt_action_grants SET active=true,version=3 WHERE user_id=1")
        if mutation=='retire': cur.execute('INSERT INTO auth.account_retirements VALUES(2)')
        if mutation=='unmap': cur.execute('UPDATE trading.qt_approver_allowlist SET active=false WHERE user_id=2')
        if mutation=='remap': cur.execute('UPDATE trading.qt_approver_allowlist SET mapping_version=2 WHERE user_id=1')
        if mutation=='revision': cur.execute('UPDATE trading.strategy_registry SET runtime_revision=1')
    data=json.loads(manifest.read_text())
    if mutation=='baseline': data['scopes'][0]['config_snapshot']['optimization']['cost_penalty_scalar']=2.0
    if mutation=='expiry': data['expires_at']='2000-01-01T00:00:00+00:00'
    if mutation=='bundle': data['validator']['bundle_sha256']='a'*64
    manifest.write_text(json.dumps(data))
    with pytest.raises(LiveConfigError): approve(svc,row,actor=1 if mutation=='self' else 2)
    with conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM trading.live_config_active'); assert cur.fetchone()[0]==0
        cur.execute('SELECT count(*) FROM trading.live_config_activations'); assert cur.fetchone()[0]==0

def test_concurrent_activation_one_winner(database):
    conn,svc,_=database; rows=[submit(svc),submit(svc)]
    def run(row):
        try: approve(svc,row); return 'ok'
        except LiveConfigError as e: return e.code
    with ThreadPoolExecutor(2) as pool: outcomes=list(pool.map(run,rows))
    assert sorted(outcomes)==['live_config_active_changed','ok']

def test_unmapped_submitter_even_with_explicit_grant(database):
    conn,svc,_=database
    with conn.cursor() as cur: cur.execute("INSERT INTO trading.qt_action_grants VALUES(3,'config_submit',true,1,now())")
    with pytest.raises(LiveConfigError,match='authorization'): svc.submit('test',body(),3)

def test_status_lookup_failure_never_file_fallback(database):
    conn,svc,_=database
    with conn.cursor() as cur: cur.execute('ALTER TABLE trading.live_config_active RENAME TO broken_active')
    with pytest.raises(LiveConfigError,match='storage'): svc.status('test','CONSERVATIVE_PORTFOLIO')

def test_runtime_request_current_v2_and_active_change_stales_approval(database):
    _,svc,_=database
    def scope(registry,book,*,cursor=None): return svc.repository.selected_scope(registry,book,svc.config,cursor=cursor)
    repo=PostgresRuntimeControlRepository(svc.repository.connection_factory,scope_loader=scope)
    base=scope('test','CONSERVATIVE_PORTFOLIO')
    intent=repo.request(strategy_id='test',action='run',reason='run',user_id='1',scope=base)
    row=submit(svc); approve(svc,row)
    with pytest.raises(RuntimeControlError,match='stale'):
        repo.approve(strategy_id='test',intent_id=intent['id'],reason='run',user_id='2',scope_loader=scope)
    effective=scope('test','CONSERVATIVE_PORTFOLIO')
    fresh=repo.request(strategy_id='test',action='run',reason='run',user_id='1',scope=effective)
    assert repo.approve(strategy_id='test',intent_id=fresh['id'],reason='run',user_id='2',scope_loader=scope)['status']=='approved'

def test_schema_rollback_refuses_audit_and_no_auto_grants(database):
    conn,svc,_=database; row=submit(svc)
    with conn.cursor() as cur:
        cur.execute((API/'migrations/011_live_config_authority.sql').read_text())
        cur.execute('SELECT count(*) FROM trading.qt_action_grants'); assert cur.fetchone()[0]==3
        with pytest.raises(psycopg2.Error,match='history'): cur.execute((API/'migrations/011_live_config_authority_rollback.sql').read_text())
        cur.execute('ROLLBACK')

@pytest.mark.parametrize('profile,engine,key',[
    ('equity_mr','LIVE_EQUITY_MEAN_REVERSION','MEAN_REVERSION'),
    ('equity_composite','LIVE_EQUITY_ALPHA_BETA','ALPHA')])
def test_raw_equity_native_export_runtime_approval(database,profile,engine,key):
    conn,svc,manifest=database; data=json.loads(manifest.read_text()); snapshot=baseline(profile)
    with conn.cursor() as cur:
        cur.execute('UPDATE trading.strategy_registry SET strategy_type=%s,portfolio_id=%s',(engine,snapshot['portfolio_id']))
    data['scopes'][0].update(engine_strategy_id=engine,portfolio_id=snapshot['portfolio_id'],config_snapshot=snapshot)
    manifest.write_text(json.dumps(data))
    request={**body(),'portfolio_id':snapshot['portfolio_id'],'changes':{f'/strategies/{key}/config/entry_threshold':2.5}}
    row=svc.submit('test',request,1); approve(svc,row)
    def scope(registry,book,*,cursor=None): return svc.repository.selected_scope(registry,book,svc.config,cursor=cursor)
    runtime=PostgresRuntimeControlRepository(svc.repository.connection_factory,scope_loader=scope)
    intent=runtime.request(strategy_id='test',action='run',reason='run',user_id='1',scope=scope('test',snapshot['portfolio_id']))
    result=runtime.approve(strategy_id='test',intent_id=intent['id'],reason='approved',user_id='2',scope_loader=scope)
    assert result['engine_strategy_id']==engine and result['status']=='approved'
    with conn.cursor() as cur:
        cur.execute('SELECT config_snapshot FROM trading.runtime_intents WHERE id=%s',(intent['id'],))
        stored=cur.fetchone()[0]
    assert sorted(stored['strategies'])==sorted(snapshot['strategies'])
    assert stored['strategies'][key]['config']['entry_threshold']==2.5


def test_authority_revocation_waits_for_activation_transaction(database):
    from threading import Event
    conn,svc,_=database; row=submit(svc)
    entered,release,started=Event(),Event(),Event()
    original=svc.config.validate
    def paused(*args):
        entered.set(); assert release.wait(10); return original(*args)
    svc.config.validate=paused
    def revoke():
        other=svc.repository.connection_factory()
        try:
            with other.cursor() as cur:
                started.set(); cur.execute("UPDATE trading.qt_action_grants SET active=false,version=2 WHERE user_id=2")
            other.commit()
        finally: other.close()
    with ThreadPoolExecutor(2) as pool:
        activation=pool.submit(approve,svc,row)
        assert entered.wait(10)
        revocation=pool.submit(revoke); assert started.wait(10)
        # The authority row itself proves we still hold the lock: NOWAIT from another connection refuses.
        check=svc.repository.connection_factory()
        try:
            with check.cursor() as cur:
                with pytest.raises(psycopg2.errors.LockNotAvailable): cur.execute('SELECT * FROM auth.users WHERE id=2 FOR UPDATE NOWAIT')
        finally: check.close()
        assert not revocation.done(); release.set()
        assert activation.result(timeout=10)['activation_id']; revocation.result(timeout=10)


def test_http_session_to_real_database_and_native(client,database,monkeypatch):
    import algolens.adapters.http.live_config as http
    import algolens.adapters.http.capability_guard as guard
    from tests.test_incubation_routes import _set_jwt_cookie
    conn,svc,_=database
    monkeypatch.setattr(http,'_service',lambda:svc)
    def grants(user):
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT capability,active FROM trading.qt_action_grants WHERE user_id=%s',(user,)); rows=cur.fetchall()
            cur.execute('SELECT person_id,active FROM trading.qt_approver_allowlist WHERE user_id=%s',(user,)); return rows,cur.fetchall()
    monkeypatch.setattr(guard,'_authority_rows',grants)
    csrf=_set_jwt_cookie(client,role='admin',identity='1')
    response=client.post('/portfolio/strategies/test/config/requests',json=body(),headers={'X-CSRF-TOKEN':csrf})
    assert response.status_code==201
    candidate=response.json
    csrf=_set_jwt_cookie(client,role='admin',identity='2')
    response=client.post('/portfolio/strategies/test/config/requests/'+candidate['version_id']+'/approve',
        json={'portfolio_id':candidate['portfolio_id'],'reason':'distinct review','expected_active_version':None},headers={'X-CSRF-TOKEN':csrf})
    assert response.status_code==200 and response.json['execution_authorized'] is False
    response=client.get('/portfolio/strategies/test/config?portfolio_id='+candidate['portfolio_id'])
    assert response.status_code==200 and response.json['active']['version_id']==candidate['version_id']

def test_corrupt_dangling_active_pointer_never_falls_back_to_file(database):
    conn,svc,_=database; row=submit(svc); approve(svc,row)
    with conn.cursor() as cur:
        # Explicit corruption injection belongs only to the owned fixture.
        cur.execute('ALTER TABLE trading.live_config_activations DISABLE TRIGGER ALL')
        cur.execute('DELETE FROM trading.live_config_activations')
        cur.execute('ALTER TABLE trading.live_config_activations ENABLE TRIGGER ALL')
    with pytest.raises(LiveConfigError): svc.repository.selected_scope('test',row['portfolio_id'],svc.config)

def test_reset_no_active_authority_and_stale_pointer(database):
    _,svc,_=database
    with pytest.raises(LiveConfigError,match='active_changed'):
        submit(svc,previous='00000000-0000-0000-0000-000000000001',operation='reset_to_baseline')
    first=submit(svc); approve(svc,first)
    reset=submit(svc,previous=first['version_id'],operation='reset_to_baseline')
    with pytest.raises(LiveConfigError,match='distinct_person'):
        approve(svc,reset,actor=1)
    competitor=submit(svc,previous=first['version_id']); approve(svc,competitor)
    with pytest.raises(LiveConfigError,match='active_changed'): approve(svc,reset)
