"""Actual native v4/v5 captures and immutable row evidence through JSONB and HTTP."""
from copy import deepcopy
from datetime import datetime,timedelta
import json
import os
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
import pytest
from tests.integration.conftest import claim_schema,require_test_dsn
from tests.test_incubation_routes import _set_jwt_cookie
from algolens.application.configuration_inspection import ConfigurationInspectionService
from algolens.infrastructure.portfolio.configuration_inspection import PostgresConfigurationInspectionReader

FIXTURES=Path(__file__).parents[1]/'fixtures/configuration_inspection_v4_v5'

def connect():return psycopg2.connect(require_test_dsn(),cursor_factory=RealDictCursor)

def install(name):
    raw=(FIXTURES/(name+'.json')).read_text();p=json.loads(raw)
    e=json.loads((FIXTURES/(name+'.evidence.json')).read_text());i=p['identity']
    conn=psycopg2.connect(require_test_dsn())
    with conn,conn.cursor() as c:
        claim_schema(c)
        c.execute('''CREATE TABLE trading.strategy_registry(id text,strategy_type text,portfolio_id text,runtime_revision bigint);
        CREATE TABLE trading.strategy_book_memberships(strategy_id text,portfolio_id text);
        CREATE TABLE trading.live_run_metadata(strategy_id text,portfolio_id text,date date,portfolio_config jsonb);
        CREATE TABLE trading.live_results(strategy_id text,portfolio_id text,portfolio_type text,date timestamptz);
        CREATE TABLE trading.runtime_intents(id bigint,registry_id text,registry_revision bigint,engine_strategy_id text,portfolio_id text,action text);
        CREATE TABLE trading.runtime_attempts(id text,intent_id bigint,registry_revision bigint,run_date date,status text,outcome text,publication_id text);
        CREATE TABLE trading.live_config_attempt_selections(attempt_id text,portfolio_id text,engine_strategy_id text,run_date date,engine_build text,selection jsonb,config_snapshot jsonb);
        CREATE TABLE trading.live_config_attempt_safety(attempt_id text,classification_version integer,state text,lifecycle text,publication_id text);''')
        c.execute('INSERT INTO trading.strategy_registry VALUES(%s,%s,%s,%s)',(i['registry_id'],i['engine_strategy_id'],i['portfolio_id'],i['registry_revision']))
        c.execute("INSERT INTO trading.live_run_metadata VALUES(%s,%s,%s,jsonb_build_object('config_inspection',%s::jsonb,'private','must-not-escape'))",(i['engine_strategy_id'],i['portfolio_id'],i['run_date'],raw))
        c.execute("INSERT INTO trading.live_results VALUES(%s,%s,'system',%s)",(i['engine_strategy_id'],i['portfolio_id'],i['run_date']+'T00:00:00Z'))
        a=e['selection'];c.execute('INSERT INTO trading.live_config_attempt_selections VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)',tuple(a[k] for k in ('attempt_id','portfolio_id','engine_strategy_id','run_date','engine_build'))+(json.dumps(a['selection']),json.dumps(a['config_snapshot'])))
        a=e['safety'];c.execute('INSERT INTO trading.live_config_attempt_safety VALUES(%s,%s,%s,%s,%s)',tuple(a[k] for k in ('attempt_id','classification_version','state','lifecycle','publication_id')))
        a=e['runtime_attempt']
        if a:c.execute('INSERT INTO trading.runtime_attempts VALUES(%s,%s,%s,%s,%s,%s,%s)',tuple(a[k] for k in ('id','intent_id','registry_revision','run_date','status','outcome','publication_id')))
        a=e['runtime_intent']
        if a:c.execute('INSERT INTO trading.runtime_intents VALUES(%s,%s,%s,%s,%s,%s)',tuple(a[k] for k in ('id','registry_id','registry_revision','engine_strategy_id','portfolio_id','action')))
    conn.close();return p

def get(client,monkeypatch,p):
    from algolens.adapters.http import configuration_inspection as http
    now=datetime.fromisoformat(p['publication_recorded_at'].replace('Z','+00:00'))+timedelta(minutes=1)
    service=ConfigurationInspectionService(PostgresConfigurationInspectionReader(connect),clock=lambda:now)
    monkeypatch.setattr(http,'create_configuration_inspection_service',lambda:service)
    _set_jwt_cookie(client,role='admin',identity='7')
    return client.get(f"/portfolio/strategies/{p['identity']['registry_id']}/configuration?portfolio_id={p['identity']['portfolio_id']}")

@pytest.mark.parametrize('name',['futures-v4','equity_house-v5','equity_now-v5','equity_empty_now-v5'])
def test_native_jsonb_http(name,client,monkeypatch):
    p=install(name);response=get(client,monkeypatch,p)
    assert response.status_code==200
    assert response.json['publication']==p
    assert response.json['status']=='available'
    assert 'must-not-escape' not in response.get_data(as_text=True)
    if destination:=os.environ.get('ISSUE88_HTTP_CAPTURE_DIR'):
        path=Path(destination);path.mkdir(parents=True,exist_ok=True);(path/(name+'.http.json')).write_bytes(response.data)

@pytest.mark.parametrize('damage',['hash','scope','attempt','unclassified','running','wrong_publication','snapshot','runtime_attempt','startup','newest','malformed_selection'])
def test_governed_evidence_refuses_incomplete_or_inconsistent_latest(damage,client,monkeypatch):
    p=install('equity_house-v5')
    statements={
      'hash':"UPDATE trading.live_config_attempt_selections SET selection=jsonb_set(selection,'{effective_sha256}',to_jsonb(repeat('a',64)))",
      'scope':"UPDATE trading.live_config_attempt_selections SET portfolio_id='OTHER'",
      'attempt':'DELETE FROM trading.live_config_attempt_selections',
      'unclassified':'UPDATE trading.live_config_attempt_safety SET classification_version=NULL',
      'running':"UPDATE trading.live_config_attempt_safety SET lifecycle='running'",
      'wrong_publication':"UPDATE trading.live_config_attempt_safety SET publication_id='other'",
      'malformed_selection':"UPDATE trading.live_config_attempt_selections SET selection='[]'",
      'snapshot':"UPDATE trading.live_config_attempt_selections SET config_snapshot='{}'",
      'runtime_attempt':"UPDATE trading.runtime_attempts SET outcome='failed'",
      'startup':'DELETE FROM trading.live_run_metadata',
      'newest':"INSERT INTO trading.live_run_metadata SELECT strategy_id,portfolio_id,date+1,'{\"config_inspection\":{}}' FROM trading.live_run_metadata; UPDATE trading.live_results SET date=date+interval '1 day'",
    }
    with connect() as conn,conn.cursor() as c:c.execute(statements[damage])
    response=get(client,monkeypatch,p)
    assert response.status_code==200
    assert response.json['status']=='unavailable' and response.json['publication'] is None
