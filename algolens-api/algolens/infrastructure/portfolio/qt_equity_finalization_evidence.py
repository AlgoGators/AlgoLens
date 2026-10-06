"""Fixed SQL historical equity graph, borrowed ordered transaction only.

No current policy substitution, financial recomputation or trusted flags.
Every decoded node is still independently proved by the original and successor
native clients. Missing retained bundles remain unavailable at that proof.
"""
import json


def _need(value):
    if not value:raise ValueError('qt_equity_lineage_records_unavailable')


def market_model_publication(cursor,market_row,*,loader=None):
    """The model publication a market row is bound to; the finalization-only market binds to none."""
    if market_row['model_publication_id'] is None:return None
    if loader is None:
        from algolens.infrastructure.portfolio.qt_empty_owner_sql import load_original_model_publication as loader
    return loader(cursor,str(market_row['model_publication_id']))


def load_continuation_evidence(cursor,decision,accounting,finalization):
    """Day-2 evidence for "same market or proven continuation"; reads nothing on the same-market path.

    Only when the D input market is not the market of the finalization that produced the anchor is
    the immutable model->prior binding of the node's own model publication loaded, together with the
    current nonempty D action source ids of the market's producer, policy and revision (the validator's
    "no other candidate" set). A database without the binding table simply yields no binding.
    """
    sources=accounting.get('equity_sources')
    if type(sources) is not dict or sources.get('market_row') is None:return
    market=sources['market_row']
    if str(market['source_id'])==str(finalization['market_source_id']):return
    # A relation the API role cannot SELECT behaves like an absent one (no binding, no aborted transaction);
    # to_regclass alone does not check privilege.
    cursor.execute("SELECT CASE WHEN to_regclass('trading.qt_equity_model_prior_bindings') IS NULL THEN false "
        "ELSE has_table_privilege(to_regclass('trading.qt_equity_model_prior_bindings'),'SELECT') END AS present")
    present=cursor.fetchone()
    binding=None
    if present is not None and present['present']:
        # The native wrapper refuses a loaded row above 2 MiB of to_jsonb text; such a row is simply not returned here.
        cursor.execute('SELECT * FROM trading.qt_equity_model_prior_bindings b WHERE publication_id=%s '
            'AND octet_length(to_jsonb(b)::text)<=2097152',
            (str(decision['model_publication_id']),))
        row=cursor.fetchone();binding=None if row is None else dict(row)
        if binding is not None:
            # Exact PG-side 2 MiB cap on the other rows the native wrapper loads (qt_equity_prior_continuation_db.cpp:11):
            # the finalization market, the prior decision and A's actions row. An oversize or missing row means no binding.
            cursor.execute("SELECT (SELECT octet_length(to_jsonb(m)::text) FROM trading.qt_desk_market_sources m WHERE m.source_id=%s) AS market_octets, "
                "(SELECT octet_length(to_jsonb(d)::text) FROM trading.qt_decisions d WHERE d.decision_id=%s) AS decision_octets, "
                "(SELECT octet_length(to_jsonb(e)::text) FROM trading.qt_equity_desk_evidence_sources e WHERE e.source_id=%s) AS actions_octets",
                (str(finalization['market_source_id']),str(finalization['decision_id']),market['payload']['actions_source_id']))
            octets=cursor.fetchone()
            if octets is None or any(octets[name] is None or octets[name]>2097152
                                     for name in ('market_octets','decision_octets','actions_octets')):binding=None
    # The MODEL's own selection (equity_model_action_source.cpp:44), predicate for predicate: the current NONEMPTY D
    # action rows of the input market's governed role. The table CHECK makes events an array; a scalar would raise in
    # SQL exactly as it does for the MODEL, never be skipped.
    cursor.execute("SELECT source_id FROM trading.qt_equity_desk_evidence_sources WHERE book_id=%s AND source_day=%s::date "
        "AND purpose='actions' AND payload->>'previous_day'=%s AND producer_id=%s AND policy_version=%s AND policy_revision=%s "
        "AND jsonb_array_length(payload->'events')>0 ORDER BY source_id LIMIT 4097",
        (market['book_id'],str(market['source_day']),market['payload']['previous_day'],market['producer_id'],
         market['policy_version'],market['policy_revision']))
    candidates=[str(r['source_id']) for r in cursor.fetchall()];_need(len(candidates)<=4096)
    sources['prior_binding']=binding;sources['action_candidates']=candidates


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
            model=market_model_publication(cursor,m)
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
        load_continuation_evidence(cursor,d,n['accounting'],f)
        row=one('SELECT r.*,to_jsonb(i) AS input_row,to_jsonb(a) AS finalization_row '
            'FROM trading.desk_run_results r JOIN trading.qt_desk_accounting_inputs i '
            'ON i.input_id=r.input_id AND i.decision_id=r.decision_id '
            "JOIN trading.qt_desk_finalization_sources a ON a.source_id=i.payload->>'prior_finalization_source_id' "
            'WHERE r.decision_id=%s AND r.portfolio_id=%s',(str(previous['decision_id']),previous['book_id']))
        d=previous
    root=dict(nodes[0]['accounting']);root['equity_lineage']=nodes
    return root
