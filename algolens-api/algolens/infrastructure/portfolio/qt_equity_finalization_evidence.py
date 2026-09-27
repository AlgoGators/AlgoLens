"""Fixed SQL historical equity graph, borrowed ordered transaction only.

No current policy substitution, financial recomputation or trusted flags.
Every decoded node is still independently proved by the original and successor
native clients. Missing retained bundles remain unavailable at that proof.
"""
import json


def _need(value):
    if not value:raise ValueError('qt_equity_lineage_records_unavailable')


def load_equity_lineage_context(cursor,decision,accounting,*,load_local_context,current=False):
    def one(sql,args):
        cursor.execute(sql,args);row=cursor.fetchone()
        _need(row is not None);return dict(row)
    def all_rows(sql,args):
        cursor.execute(sql,args);rows=[dict(r) for r in cursor.fetchall()]
        _need(len(rows)<=4096);return rows
    def basis_for(anchor):
        ids=[r['basis_evidence']['source_id'] for r in anchor['previous_positions']]
        return all_rows('SELECT * FROM trading.qt_equity_desk_evidence_sources WHERE source_id=ANY(%s)',(ids,))
    def augment(d,row,with_current):
        local=load_local_context(cursor,d,row,current=with_current)
        cursor.execute('SELECT * FROM trading.qt_desk_finalizations WHERE decision_id=%s',(str(d['decision_id']),))
        transitions=[dict(r) for r in cursor.fetchall()];_need(len(transitions)<=1)
        local['successor']=None
        if transitions:
            f=transitions[0]
            m=one('SELECT * FROM trading.qt_desk_market_sources WHERE source_id=%s',(f['market_source_id'],))
            from algolens.infrastructure.portfolio.qt_empty_owner_sql import load_original_model_publication
            model=load_original_model_publication(cursor,str(m['model_publication_id']))
            events=one('SELECT * FROM trading.qt_equity_desk_evidence_sources WHERE source_id=%s',(m['payload']['actions_source_id'],))
            anchor=one('SELECT * FROM trading.qt_desk_finalization_sources WHERE source_id=%s',('qt-finalization/'+str(f['finalization_id']),))
            local['successor']={'transition_row':f,'market_row':m,'model_publication':model,
                'actions_row':events,'anchor_row':anchor,'basis_rows':basis_for(anchor['payload'])}
        return local
    def node(d,row,with_current):
        receipt=one('SELECT * FROM trading.qt_desk_receipts WHERE decision_id=%s',(str(d['decision_id']),))
        observation=one('SELECT * FROM trading.qt_execution_observations WHERE decision_id=%s AND observation_id=%s',
            (str(d['decision_id']),receipt['publication_payload']['observation_id']))
        return {'decision':d,
            'preview':one('SELECT * FROM trading.qt_previews WHERE preview_id=%s',(str(d['preview_id']),)),
            'receipt':receipt,'observation':observation,
            'result':one('SELECT * FROM trading.qt_desk_results WHERE decision_id=%s AND attempt_id=%s AND observation_id=%s',
                (str(d['decision_id']),receipt['attempt_id'],observation['observation_id'])),
            'accounting':augment(d,row,with_current)}
    nodes=[];seen=set();used=0;d=dict(decision);row=dict(accounting)
    while True:
        identity=str(d['decision_id']);_need(identity not in seen and len(nodes)<4096);seen.add(identity)
        n=node(d,row,current if not nodes else False)
        from algolens.infrastructure.portfolio.qt_empty_owner_sql import OwnerPublication
        used+=len(json.dumps(n,default=lambda value: value.row if type(value) is OwnerPublication else str(value),
            ensure_ascii=False,allow_nan=False).encode('utf-8','strict'))
        _need(used<=256*1024*1024);nodes.append(n)
        prior=n['accounting']['finalization_row'];anchor=prior['payload']
        if anchor.get('schema_version')=='qt-equity-finalized-accounting/v1':break
        _need(anchor.get('schema_version') in {'qt-equity-finalized-accounting/v2','qt-equity-finalized-accounting-empty-owner/v3'})
        empty_owner=anchor['schema_version']=='qt-equity-finalized-accounting-empty-owner/v3'
        _need((n['accounting']['input_row']['payload']['schema_version'],n['accounting']['payload']['schema_version'])==
            (('qt-equity-accounting-input-empty-owner/v2','qt-equity-accounting-empty-owner/v2') if empty_owner else
             ('qt-equity-accounting-input/v1','qt-equity-accounting/v1')))
        f=one('SELECT * FROM trading.qt_desk_finalizations WHERE finalization_id=%s',(anchor['finalization_id'],))
        _need(prior['source_id']=='qt-finalization/'+str(f['finalization_id'])
            and prior['source_version']==prior['source_id'] and f['content_digest']==anchor['finalization_digest']
            and f['book_id']==d['book_id'] and str(f['source_day'])==anchor['source_day']<str(d['source_day']))
        previous=one('SELECT * FROM trading.qt_decisions WHERE decision_id=%s',(f['decision_id'],))
        _need(previous['book_id']==d['book_id'] and str(previous['source_day'])==anchor['source_day'])
        row=one('SELECT r.*,to_jsonb(i) AS input_row,to_jsonb(a) AS finalization_row '
            'FROM trading.desk_run_results r JOIN trading.qt_desk_accounting_inputs i '
            'ON i.input_id=r.input_id AND i.decision_id=r.decision_id '
            "JOIN trading.qt_desk_finalization_sources a ON a.source_id=i.payload->>'prior_finalization_source_id' "
            'WHERE r.decision_id=%s AND r.portfolio_id=%s',(str(previous['decision_id']),previous['book_id']))
        d=previous
    root=dict(nodes[0]['accounting']);root['equity_lineage']=nodes
    return root
