"""Staged unavailable equity-successor seams; no hash-only admission.

Implementation follows actual native S/D behavioral RED. Original publication
and native recomputation factories are separate, obligatory authorities.
"""
from copy import deepcopy
from uuid import UUID
from hashlib import sha256
from datetime import date
from decimal import Decimal

from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.portfolio.qt_evaluator_process import QtEvaluatorUnavailable
from algolens.infrastructure.portfolio import qt_equity_accounting_proof as _original_core
from algolens.infrastructure.portfolio.qt_equity_accounting_proof import canonical_equity_accounting_output_bytes
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from algolens.infrastructure.portfolio.qt_original_processing_proof import PUBLICATION_FIELDS
from algolens.domain.portfolio.qt_canonical import qt_digest_v1

_PROVENANCE={'finalization_id','original_accounting_input_id','original_run_result_digest',
    'original_observation_digest','predecessor_finalization_source_id','predecessor_finalization_digest',
    'market_source_id','market_source_digest','actions_source_id','actions_source_digest',
    'unchanged_execution_digest','policy_identity','finalizer_authority'}
_SUCCESSOR={'schema_version','calculation_version','decision_id','book_id','source_day','valuation_day',
    'valuation_time','currency','components','engine_totals','before_financial','after_financial'}|_PROVENANCE
_POSITION={'key','quantity_exact','average_price_exact','daily_realized_pnl_exact','daily_unrealized_pnl_exact','last_update'}
_TOTAL={'strategy_id','initial_capital_exact','equity_exact','total_pnl_exact','total_realized_pnl_exact',
    'total_transaction_costs_exact','total_unrealized_pnl_exact'}
_ANCHOR={'schema_version','calculation_version','book_id','source_day','currency','policy_revision',
    'previous_positions','previous_totals','finalization_id','finalization_digest'}
_FAILURES=(ValueError,TypeError,KeyError,AttributeError,ArithmeticError,QtWorkflowError,
           UnicodeError,RecursionError,QtEvaluatorUnavailable)
_MAX_NODES=4096
_MAX_RECORD_BYTES=256*1024*1024


def _need(value):
    if not value:raise ValueError('unproven_equity_finalization')


def _shape(value,fields):_need(type(value) is dict and set(value)==fields)
def _hash(value):return sha256(canonical_qt_input_bytes(value)).hexdigest()
def _owner(key):return canonical_qt_input_bytes({k:v for k,v in key.items() if k!='date'})
def _index(rows,identity):return _original_core._unique(rows,identity)
def _rows_equal(a,b,identity):_need(_index(a,identity)==_index(b,identity))


def _financial(value,book,day,stamp,*,empty_owner=False):
    _shape(value,{'positions','live_results','equity_curve'})
    positions=_index(value['positions'],lambda r:_original_core._key(r['key'],book,day))
    for row in positions.values():
        _shape(row,_POSITION);_need(row['last_update']==stamp);_original_core._walk_exact(row)
    engines={'LIVE_EQUITY_MEAN_REVERSION'} if empty_owner else {key.strategy_id for key in positions}
    live=_index(value['live_results'],lambda r:r['strategy_id'])
    curves=_index(value['equity_curve'],lambda r:r['strategy_id'])
    _need((not positions if empty_owner else bool(positions)) and set(live)==set(curves)==engines)
    for engine,row in live.items():
        _shape(row,_original_core._LIVE);_original_core._walk_exact(row)
        _need(row['portfolio_id']==book and row['portfolio_type']=='qt' and row['date']==day)
        c=curves[engine];_shape(c,{'portfolio_id','strategy_id','portfolio_type','timestamp','equity_exact'})
        _original_core._walk_exact(c)
        _need(c['portfolio_id']==book and c['portfolio_type']=='qt' and c['timestamp']==day+'T00:00:00Z')
        if empty_owner:
            _need(_original_core._exact(row['initial_capital_exact'])>0
                and _original_core._exact(row['current_portfolio_value_exact'])>0
                and row['current_portfolio_value_exact']==c['equity_exact'])
            for name in ('daily_realized_pnl','daily_unrealized_pnl','daily_pnl',
                         'daily_transaction_costs','total_unrealized_pnl'):
                _need(row[name+'_exact']=='0')


def _closed_successor(value,decision):
    _shape(value,_SUCCESSOR);canonical_qt_input_bytes(value);_original_core._walk_exact(value)
    book,day=decision['book_id'],str(decision['source_day']);valuation=value['valuation_day']
    _need(date.fromisoformat(valuation).isoformat()==valuation and valuation>day)
    empty_owner=value['schema_version']=='qt-equity-desk-finalization-empty-owner/v2'
    _need(value['schema_version'] in {'qt-equity-desk-finalization/v1','qt-equity-desk-finalization-empty-owner/v2'}
        and value['calculation_version']=='equity-prior-close-mark/v1' and value['currency']=='USD'
        and value['book_id']==book and value['source_day']==day
        and value['decision_id']==str(decision['decision_id']) and value['valuation_time']==valuation+'T00:00:00Z')
    _financial(value['before_financial'],book,day,day+'T00:00:00Z',empty_owner=empty_owner)
    _financial(value['after_financial'],book,day,value['valuation_time'],empty_owner=empty_owner)
    components=_index(value['components'],lambda r:_original_core._key(r['key'],book,day))
    for row in components.values():
        _shape(row,{'key','quantity_exact','average_price_exact','price_frame_id','close_price_model_number',
            'close_source_id','close_source_digest','prior_unrealized_pnl_exact','current_unrealized_pnl_exact'})
    totals=_index(value['engine_totals'],lambda r:r['strategy_id'])
    for row in totals.values():_shape(row,_TOTAL)
    _need(set(components)==set(_index(value['after_financial']['positions'],lambda r:_original_core._key(r['key'],book,day)))
          and set(totals)==({'LIVE_EQUITY_MEAN_REVERSION'} if empty_owner else {key.strategy_id for key in components}))
    if empty_owner:
        _need(not components)
        for rows in (value['before_financial']['live_results'],value['after_financial']['live_results']):
            row=rows[0];total=totals[row['strategy_id']]
            for name in ('initial_capital','total_pnl','total_realized_pnl','total_transaction_costs','total_unrealized_pnl'):
                _need(total[name+'_exact']==row[name+'_exact'])
            _need(total['equity_exact']==row['current_portfolio_value_exact'])


def verify_equity_finalization_recomputation(decision,original_input,original_output,market_payload,
        actions_payload,before_financial,provenance,finalizer_authority,successor,*,
        recompute_client,expected_authority_digest):
    """Required native mathematics subproof; never SQL/source readiness alone."""
    try:
        _closed_successor(successor,decision)
        _need(recompute_client is not None and _hash(finalizer_authority)==expected_authority_digest
              and original_output['producer_authority']==finalizer_authority
              and successor['finalizer_authority']==finalizer_authority)
        _shape(provenance,_PROVENANCE)
        for name in _PROVENANCE:_need(successor[name]==provenance[name])
        _need(successor['before_financial']==before_financial==original_equity_financial_projection(original_output))
        summary=recompute_client.recompute(decision,original_input,original_output,market_payload,
            actions_payload,before_financial,provenance,finalizer_authority,
            expected_authority_digest=expected_authority_digest)
        _need(summary['successor_digest']==_hash(successor))
        return deepcopy(successor['after_financial'])
    except _FAILURES:raise ValueError('unproven_equity_finalization_recomputation') from None


def original_equity_financial_projection(output):
    """Closed immutable projection only, never durable source/math authority."""
    canonical_equity_accounting_output_bytes(output)
    positions = [{**{name:fill[name] for name in ('key','average_price_exact',
        'daily_realized_pnl_exact','daily_unrealized_pnl_exact','last_update')},
        'quantity_exact':fill['selected_quantity_exact']} for fill in output['observation']['fills']]
    positions.sort(key=lambda item:canonical_qt_input_bytes(item['key']))
    return deepcopy({'positions':positions,'live_results':output['live_results'],
                     'equity_curve':output['equity_curve']})


def _derived_anchor(accounting,successor):
    """Identity/formation projection of native output, no monetary algorithm."""
    source,output=accounting['input_row']['payload'],accounting['payload']
    previous=_index(source['previous_positions'],lambda r:_owner(r['key']))
    distance=_index(output['distance'],lambda r:_owner(r['key']))
    components=_index(successor['components'],lambda r:_owner(r['key']))
    rows=[]
    for observed in successor['after_financial']['positions']:
        row=deepcopy(observed);owner=_owner(row['key']);_need(owner in distance and owner in components)
        restated=_original_core._exact(distance[owner]['restated_previous_quantity_exact'])
        selected=_original_core._exact(row['quantity_exact']);formed=successor['source_day']
        if owner in previous and ((restated>0 and selected<=restated) or restated==selected==0):
            formed=previous[owner]['basis_evidence']['formed_day']
        basis={'schema_version':'qt-equity-basis-source/v1','book_id':successor['book_id'],
            'source_day':successor['source_day'],'key':row['key'],'quantity_exact':row['quantity_exact'],
            'average_price_exact':row['average_price_exact'],'price_frame_id':components[owner]['price_frame_id'],
            'formed_day':formed}
        row['basis_evidence']={'source_id':'qt-basis/'+successor['finalization_id']+'/'+_hash(row['key']),
            'source_digest':_hash(basis),'price_frame_id':basis['price_frame_id'],'formed_day':formed}
        rows.append(row)
    empty_owner=successor['schema_version']=='qt-equity-desk-finalization-empty-owner/v2'
    if empty_owner:
        _need(source['schema_version']=='qt-equity-accounting-input-empty-owner/v2'
            and output['schema_version']=='qt-equity-accounting-empty-owner/v2'
            and not previous and not distance and not components and not rows)
    return {'schema_version':('qt-equity-finalized-accounting-empty-owner/v3' if empty_owner else 'qt-equity-finalized-accounting/v2'),'calculation_version':'qt-equity-main08b15c/v1',
        'book_id':successor['book_id'],'source_day':successor['source_day'],'currency':successor['currency'],
        'policy_revision':successor['policy_identity']['version'],'previous_positions':rows,
        'previous_totals':successor['engine_totals'],'finalization_id':successor['finalization_id'],
        'finalization_digest':_hash(successor)}


def _prove_anchor_record(accounting,successor,record,basis_rows):
    expected=_derived_anchor(accounting,successor);_shape(record['payload'],_ANCHOR)
    _original_core._row_digest(record);_need(record['payload']==expected)
    _need(record['source_id']=='qt-finalization/'+successor['finalization_id']
          and record['source_version']==record['source_id'] and record['book_id']==expected['book_id']
          and str(record['source_day'])==expected['source_day'])
    policy=successor['policy_identity']
    for name in ('producer_id','policy_version'):_need(record[name]==policy[name])
    basis=_index(basis_rows,lambda r:r['source_id']);wanted=set()
    for position in expected['previous_positions']:
        b=position['basis_evidence'];actual=basis[b['source_id']];wanted.add(b['source_id'])
        _original_core._row_digest(actual);_original_core._metadata(actual,record)
        payload={'schema_version':'qt-equity-basis-source/v1','book_id':expected['book_id'],
            'source_day':expected['source_day'],'key':position['key'],'quantity_exact':position['quantity_exact'],
            'average_price_exact':position['average_price_exact'],'price_frame_id':b['price_frame_id'],
            'formed_day':b['formed_day']}
        _need(actual['payload']==payload and actual['content_digest']==b['source_digest']
            and actual['policy_revision']==expected['policy_revision'] and actual['purpose']=='basis'
            and actual['book_id']==expected['book_id'] and str(actual['source_day'])==expected['source_day']
            and actual['source_version']==b['source_id'])
    _need(set(basis)==wanted)
    return expected


def _prove_successor(node,original_output,factory):
    d=node['decision'];accounting=node['accounting'];linked=accounting.get('successor')
    if linked is None:return None
    _need(callable(factory))
    f,m,model,events=(linked[name] for name in ('transition_row','market_row','model_publication','actions_row'))
    successor=f['payload'];market=m['payload'];actions=events['payload'];source=accounting['input_row']
    _closed_successor(successor,d);_original_core._row_digest(f);_original_core._row_digest(m);_original_core._row_digest(events)
    empty_owner=successor['schema_version']=='qt-equity-desk-finalization-empty-owner/v2'
    if empty_owner:
        from algolens.infrastructure.portfolio.qt_empty_owner_sql import OwnerPublication
        _need(isinstance(model,OwnerPublication)
            and source['payload']['schema_version']=='qt-equity-accounting-input-empty-owner/v2'
            and original_output['schema_version']=='qt-equity-accounting-empty-owner/v2'
            and market['schema_version']=='qt-equity-accounting-market-empty-owner/v2'
            and market['instruments']==[] and actions['events']==[]
            and all(model.document[k]==[] for k in ('system_components','proposal_components','qt_components'))
            and len(model.document['configured_owner_names'])==1)
    else:
        _need(source['payload']['schema_version']=='qt-equity-accounting-input/v1'
            and original_output['schema_version']=='qt-equity-accounting/v1'
            and market['schema_version']=='qt-equity-accounting-market/v1')
    book,day=d['book_id'],str(d['source_day']);valuation=successor['valuation_day']
    _need(str(f['decision_id'])==str(d['decision_id'])==successor['decision_id']
        and f['book_id']==book and str(f['source_day'])==day and str(f['valuation_day'])==valuation
        and str(f['finalization_id'])==successor['finalization_id'] and str(f['market_source_id'])==str(m['source_id'])
        and f['source_version']=='qt-finalization/'+successor['finalization_id']
        and f['input_digest']==source['content_digest'] and f['output_digest']==accounting['content_digest'])
    for name in ('book_id','source_day','model_publication_id'):_need(str(m[name])==market[name])
    _need(m['book_id']==book and str(m['source_day'])==valuation and market['previous_day']==day
        and model['portfolio_id']==book and str(model['source_day'])==valuation
        and str(model['publication_id'])==market['model_publication_id']
        and model['seed_digest']==qt_digest_v1({'seed_rows':model['system_components']}))
    _need(type(f['policy_revision']) is int and 0<f['policy_revision']<(1<<63)
        and f['policy_revision']==m['policy_revision']==events['policy_revision'])
    _original_core._metadata(f,m);_original_core._metadata(f,source);_original_core._metadata(events,m)
    start,end=_original_core._sql_time(m['as_of']),_original_core._sql_time(m['valid_until'])
    created=_original_core._sql_time(f['created_at'])
    _need(start<end and start<=created<=end and start<=_original_core._sql_time(m['created_at'])<=end
          and created.date().isoformat()==valuation)
    _need(events['purpose']=='actions' and events['book_id']==book and str(events['source_day'])==valuation
        and events['source_id']==market['actions_source_id'] and events['content_digest']==market['actions_source_digest'])
    policy={'book_id':book,'purpose':'execution','version':f['policy_revision'],
            'producer_id':f['producer_id'],'policy_version':f['policy_version']}
    authority,digest=_original_core._captured_authority(node,original_output)
    provenance={'finalization_id':str(f['finalization_id']),'original_accounting_input_id':str(source['input_id']),
        'original_run_result_digest':accounting['content_digest'],'original_observation_digest':node['observation']['content_digest'],
        'predecessor_finalization_source_id':accounting['finalization_row']['source_id'],
        'predecessor_finalization_digest':accounting['finalization_row']['content_digest'],
        'market_source_id':str(m['source_id']),'market_source_digest':m['content_digest'],
        'actions_source_id':events['source_id'],'actions_source_digest':events['content_digest'],
        'unchanged_execution_digest':_hash(original_output['executions']),
        'policy_identity':policy,'finalizer_authority':authority}
    verify_equity_finalization_recomputation({name:str(d[name]) for name in
        ('decision_id','book_id','source_day','model_publication_id')},source['payload'],original_output,market,actions,
        original_equity_financial_projection(original_output),provenance,authority,successor,
        recompute_client=factory(authority),expected_authority_digest=digest)
    _prove_anchor_record(accounting,successor,linked['anchor_row'],linked['basis_rows'])
    return successor


def _same_root_sql_record(left,right,*,uuid_columns=(),time_columns=(),date_columns=()):
    """Bind identical SQL records across the reader's explicit conversions.

    Only declared SQL UUID/timestamp columns have representation equivalence.
    The immutable JSON operands and every other storage column remain exact.
    """
    _need(type(left) is dict and type(right) is dict and set(left)==set(right))
    left,right=dict(left),dict(right)
    for name in uuid_columns:
        if name not in left:continue
        for row in (left,right):
            value=row[name]
            _need(type(value) in {UUID,str})
            parsed=UUID(value) if type(value) is str else value
            _need(type(value) is UUID or str(parsed)==value)
            row[name]=str(parsed)
    for name in time_columns:
        if name not in left:continue
        for row in (left,right):row[name]=_original_core._sql_time(row[name])
    for name in date_columns:
        if name not in left:continue
        for row in (left,right):
            value=row[name]
            _need(type(value) in {date,str})
            parsed=date.fromisoformat(value) if type(value) is str else value
            _need(type(value) is date or parsed.isoformat()==value)
            row[name]=parsed
    return left==right


def _prove_graph(evidence,original_factory,finalizer_factory,*,root_successor=False):
    """Bounded oldest-first mathematical closure; never recursive public proof."""
    _need(callable(original_factory))
    root=evidence['accounting'];nodes=root.get('equity_lineage')
    if nodes is None:
        # v1 bootstrap original-only historical callers keep their old seam.
        output=_original_core._prove_original_sql(evidence,original_factory)
        return output,(_prove_successor(evidence,output,finalizer_factory) if root_successor else None)
    _need(type(nodes) is list and 0<len(nodes)<=_MAX_NODES)
    _need(_same_root_sql_record(nodes[0]['decision'],evidence['decision'],uuid_columns=('decision_id',))
          and nodes[0]['accounting']['payload']==root['payload']
          and nodes[0]['accounting']['content_digest']==root['content_digest'])
    _need(_same_root_sql_record(nodes[0]['preview'],evidence['preview'],
        time_columns=('created_at',),date_columns=('source_day',)))
    _need(_same_root_sql_record(nodes[0]['result'],evidence['result'],time_columns=('created_at',)))
    _need(_same_root_sql_record(nodes[0]['receipt'],evidence['receipt'],time_columns=('processed_at',)))
    _need(_same_root_sql_record(nodes[0]['observation'],evidence['observation'],time_columns=('as_of','valid_until')))
    seen=set();book=evidence['decision']['book_id'];previous_day=None
    for node in nodes:
        d=node['decision'];identity=str(d['decision_id']);day=str(d['source_day'])
        _need(identity not in seen and d['book_id']==book and date.fromisoformat(day).isoformat()==day
              and (previous_day is None or day<previous_day));seen.add(identity);previous_day=day
    # Loader enforces a decoded SQL budget; proof independently counts all
    # actual supplied records as UTF8. This only limits work, never hashes SQL.
    import json
    used=0
    for node in nodes:
        from algolens.infrastructure.portfolio.qt_empty_owner_sql import OwnerPublication
        used+=len(json.dumps(node,default=lambda value:value.row if isinstance(value,OwnerPublication) else str(value),ensure_ascii=False,allow_nan=False).encode('utf-8','strict'))
        _need(used<=_MAX_RECORD_BYTES)
    preceding=None;preceding_node=None;root_output=None;root_mark=None
    for index in range(len(nodes)-1,-1,-1):
        node=nodes[index];accounting=node['accounting'];anchor=accounting['finalization_row']['payload']
        validator=None
        if anchor.get('schema_version') in {'qt-equity-finalized-accounting/v2','qt-equity-finalized-accounting-empty-owner/v3'}:
            empty_owner=anchor['schema_version']=='qt-equity-finalized-accounting-empty-owner/v3'
            _need((accounting['input_row']['payload']['schema_version'],accounting['payload']['schema_version'])==
                (('qt-equity-accounting-input-empty-owner/v2','qt-equity-accounting-empty-owner/v2') if empty_owner else
                 ('qt-equity-accounting-input/v1','qt-equity-accounting/v1')))
            _need(preceding is not None and preceding_node is not None)
            expected=_prove_anchor_record(preceding_node['accounting'],preceding,accounting['finalization_row'],
                accounting['equity_sources']['basis_rows'])
            source=accounting['input_row']['payload']
            _need(preceding['market_source_id']==source['market_source_id']
                  and preceding['market_source_digest']==source['market_source_digest']
                  and preceding['source_day']==str(preceding_node['decision']['source_day'])
                  and preceding['valuation_day']==str(node['decision']['source_day']))
            def validator(actual,decision,expected=expected,target=accounting):
                _need(actual is target);return expected
        else:
            _need(index==len(nodes)-1 and anchor.get('schema_version')=='qt-equity-finalized-accounting/v1')
        output=_original_core._prove_original_sql(node,original_factory,prior_anchor_validator=validator)
        mark=_prove_successor(node,output,finalizer_factory) if index>0 or root_successor else None
        if index>0:_need(mark is not None)
        preceding,preceding_node=mark,node
        if index==0:root_output,root_mark=output,mark
    return root_output,root_mark


def validate_qt_equity_original_accounting_proof(evidence, *, recompute_client_factory=None,
        finalization_recompute_client_factory=None):
    """Require the complete named immutable original SQL/source/native proof.

    This returns the original producer output, never current report readiness.
    The current wrapper separately proves/comparisons any successor inventory.
    Unknown v2 anchors remain unavailable until bounded lineage is implemented.
    """
    try:
        if not callable(recompute_client_factory): raise ValueError('missing_original_native_factory')
        pub=evidence['receipt']['publication_payload']
        if type(pub) is not dict or set(pub)!=PUBLICATION_FIELDS:
            raise ValueError('unproven_original_publication_shape')
        return _prove_graph(evidence,recompute_client_factory,finalization_recompute_client_factory)[0]
    except (ValueError,TypeError,KeyError,AttributeError,ArithmeticError,QtWorkflowError,
            UnicodeError,RecursionError,QtEvaluatorUnavailable):
        raise ValueError('qt_equity_original_accounting_proof_unavailable') from None


def verified_qt_equity_finalization_successor(evidence, *, recompute_client_factory=None,
        finalization_recompute_client_factory=None, current=False):
    try:
        output,successor=_prove_graph(evidence,recompute_client_factory,finalization_recompute_client_factory,root_successor=True)
        _need(successor is not None)
        if current:
            row=evidence['accounting'];_need('financial_rows' in row)
            d=evidence['decision'];physical=row['financial_rows'];_shape(physical,{'positions','live_results','equity_curve','executions'})
            after=successor['after_financial'];_original_core._physical_positions(physical['positions'],after['positions'],d['book_id'],str(d['source_day']))
            _original_core._physical_engines(physical,after['live_results'],d['book_id'],str(d['source_day']))
            _original_core._physical_executions(physical['executions'],output['executions'],d['book_id'],str(d['source_day']))
        return deepcopy(successor['after_financial'])
    except _FAILURES:raise ValueError('qt_equity_finalization_proof_unavailable') from None


def validate_qt_equity_finalized_anchor(evidence, *, recompute_client_factory=None,
        finalization_recompute_client_factory=None):
    try:
        _need(evidence['accounting']['finalization_row']['payload']['schema_version'] in
            {'qt-equity-finalized-accounting/v2','qt-equity-finalized-accounting-empty-owner/v3'})
        _prove_graph(evidence,recompute_client_factory,finalization_recompute_client_factory)
        return deepcopy(evidence['accounting']['finalization_row']['payload'])
    except _FAILURES:raise ValueError('qt_equity_finalized_anchor_unavailable') from None
