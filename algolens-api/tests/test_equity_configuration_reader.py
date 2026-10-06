"""SQL seam controls using synthetic cursor rows, not native capture evidence."""
from datetime import date
import json
from pathlib import Path
import pytest
from test_equity_configuration_inspection import sample, NOW

from algolens.infrastructure.portfolio import configuration_inspection as reader


class Cursor:
    def __init__(self,document,damage=None):
        self.calls=[];identity=document['identity'];self.identity=identity
        self.registry={'id':identity['registry_id'],'strategy_type':identity['engine_strategy_id'],
            'portfolio_id':identity['portfolio_id'],'runtime_revision':identity['registry_revision']}
        if damage=='revision':self.registry['runtime_revision']+=1
        raw=json.dumps(document)
        self.metadata={'date':date.fromisoformat(identity['run_date']),'strategy_id':identity['engine_strategy_id'],
            'portfolio_id':identity['portfolio_id'],'child_bytes':len(raw.encode()),'child_text':raw}
        self.result={'run_date':self.metadata['date'] if damage!='date' else date(2026,9,25)}
        self.attempt={'attempt_id':identity['publication_id'],'attempt_revision':identity['registry_revision'],
            'attempt_run_date':self.metadata['date'],'attempt_status':'applied','attempt_outcome':'published',
            'attempt_publication_id':identity['publication_id'],'intent_registry_id':identity['registry_id'],
            'intent_revision':identity['registry_revision'],'intent_engine_id':identity['engine_strategy_id'],
            'intent_portfolio_id':identity['portfolio_id'],'intent_action':'run'}
        if damage=='attempt':self.attempt['intent_portfolio_id']='OTHER'
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def execute(self,sql,parameters=None):
        self.calls.append((sql,parameters))
        if 'strategy_registry' in sql:self.rows=[self.registry]
        elif 'strategy_book_memberships' in sql:self.rows=[{'portfolio_id':self.identity['portfolio_id']}]
        elif 'live_run_metadata' in sql:self.rows=[self.metadata]
        elif 'live_results' in sql:self.rows=[self.result]
        elif 'LIMIT 0' in sql:self.rows=[]
        elif 'runtime_attempts' in sql:self.rows=[self.attempt]
        else:raise AssertionError('unexpected query')
    def fetchone(self):return self.rows[0] if self.rows else None
    def fetchall(self):return self.rows


class Connection:
    def __init__(self,cursor):self.current=cursor;self.commits=0;self.rollbacks=0;self.closed=False
    def set_session(self,**kwargs):assert kwargs=={'readonly':True,'isolation_level':'REPEATABLE READ'}
    def cursor(self):return self.current
    def commit(self):self.commits+=1
    def rollback(self):self.rollbacks+=1
    def close(self):self.closed=True


@pytest.mark.parametrize('controlled',[False,True])
def test_sealed_schema3_uses_actual_registry_metadata_and_runtime_rows(controlled):
    document=sample();identity=document['identity']
    if controlled:identity.update(control_mode='controlled',runtime_attempt_id=identity['publication_id'])
    cur=Cursor(document);conn=Connection(cur)
    result=reader.PostgresConfigurationInspectionReader(lambda:conn).read(identity['registry_id'],identity['portfolio_id'],NOW)
    assert result==('available',document,identity['portfolio_id'])
    assert conn.commits==1 and conn.rollbacks==0 and conn.closed
    queries=[sql for sql,_ in cur.calls]
    assert any("portfolio_config -> 'config_inspection'" in sql and 'octet_length' in sql for sql in queries)
    assert not any('config.equity_run_consumption' in sql or 'INSERT' in sql or 'UPDATE' in sql for sql in queries)
    assert any('WHERE a.id = %s' in sql for sql in queries)==controlled


@pytest.mark.parametrize('damage,reason',[('revision','scope_changed'),('date','publication_date_mismatch'),('attempt','invalid_publication')])
def test_same_child_claims_cannot_override_actual_capture_authority(damage,reason):
    document=sample();identity=document['identity'];identity.update(control_mode='controlled',runtime_attempt_id=identity['publication_id'])
    cur=Cursor(document,damage);conn=Connection(cur)
    assert reader.PostgresConfigurationInspectionReader(lambda:conn).read(identity['registry_id'],identity['portfolio_id'],NOW)==('unavailable',reason,identity['portfolio_id'])
    assert conn.commits==1 and conn.closed
