"""Staged unavailable equity-successor seams; no hash-only admission.

Implementation follows actual native S/D behavioral RED. Original publication
and native recomputation factories are separate, obligatory authorities.
"""
from copy import deepcopy
import json
import math
import re
from uuid import UUID
from hashlib import sha256
from datetime import date, datetime, timezone
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
FINALIZATION_MARKET_SCHEMA='qt-equity-finalization-market/v1'
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


def _prove_market_scope(m,market,model,*,book,day,valuation,empty_owner):
    """Bind the S-to-D market M to its D model publication, or (finalization-only schema) to none.

    Only the finalization proof's M checks accept ``qt-equity-finalization-market/v1``. This is the native
    ``market()`` + ``qt_equity_finalization_only_market_row`` rule: the row is sealed, the payload has exactly
    the accounting-market key set, the row column and the payload model are both null (no publication is
    loaded), and the row's book and day equal the payload's. Every other schema keeps the publication/seed
    proof unchanged, and the empty-owner path never accepts the new schema.
    """
    _original_core._row_digest(m)
    finalization_only=market['schema_version']==FINALIZATION_MARKET_SCHEMA
    _need(not(finalization_only and empty_owner))
    _need(m['book_id']==book and str(m['source_day'])==valuation and market['previous_day']==day)
    if finalization_only:
        _shape(market,_MARKET_PAYLOAD)
        _need('model_publication_id' in m and m['model_publication_id'] is None and market['model_publication_id'] is None and model is None)
        for name in ('book_id','source_day'):_need(_text(market[name]) and str(m[name])==market[name])
        return
    _need(model is not None)
    for name in ('book_id','source_day','model_publication_id'):_need(str(m[name])==market[name])
    _need(model['portfolio_id']==book and str(model['source_day'])==valuation
        and str(model['publication_id'])==market['model_publication_id']
        and model['seed_digest']==qt_digest_v1({'seed_rows':model['system_components']}))


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
            and market['schema_version'] in {'qt-equity-accounting-market/v1',FINALIZATION_MARKET_SCHEMA})
    book,day=d['book_id'],str(d['source_day']);valuation=successor['valuation_day']
    _need(str(f['decision_id'])==str(d['decision_id'])==successor['decision_id']
        and f['book_id']==book and str(f['source_day'])==day and str(f['valuation_day'])==valuation
        and str(f['finalization_id'])==successor['finalization_id'] and str(f['market_source_id'])==str(m['source_id'])
        and f['source_version']=='qt-finalization/'+successor['finalization_id']
        and f['input_digest']==source['content_digest'] and f['output_digest']==accounting['content_digest'])
    _prove_market_scope(m,market,model,book=book,day=day,valuation=valuation,empty_owner=empty_owner)
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
            _need(_market_continues(preceding,preceding_node,node)
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



# ---------------------------------------------------------------------------------------------
# Equity day 2 (verified-desk-prior): "same market or proven continuation".
#
# Python port of trade-ngin ``validate_qt_equity_verified_prior_continuation`` (lane N4,
# src/apps/qt_equity_prior_continuation.cpp): pure, no SQL, the same rules in the same order.
# The D input market A (bound to the D model publication P2) may stand in for the S->D
# finalization's market M only when rules (a)-(d) hold.  The restatement mirrors
# equity_model_action_frame.cpp:80 exactly: the Decimal (1e-8, C++ ``Decimal(double)``) screening
# of every price, IEEE double division, events in the order (symbol, split before dividend),
# factor = value for a split and 1+value/close for a dividend, and the ``Decimal::to_string``
# spelling of the result.  Failure is always the fixed code below.
# ---------------------------------------------------------------------------------------------
CONTINUATION_UNAVAILABLE='qt_equity_prior_continuation_unavailable'
_ENGINE='LIVE_EQUITY_MEAN_REVERSION'
_OWNER='EQUITY_MEAN_REVERSION'
_CONTINUATION_INPUTS={'decision','prior_decision','finalization_market','input_market','finalization','anchor',
    'binding','actions_row','candidate_action_sources'}
_MARKET_PAYLOAD={'schema_version','calculation_version','book_id','source_day','model_publication_id','previous_day',
    'valuation_time','day_mode','currency','cost_config','instruments','actions_source_id','actions_source_digest'}
_ANCHOR_PAYLOAD={'schema_version','calculation_version','book_id','source_day','currency','policy_revision',
    'previous_positions','previous_totals','finalization_id','finalization_digest'}
_BINDING={'publication_id','book_id','source_day','strategy_id','decision_id','finalization_id','finalization_digest',
    'finalization_source_id','finalization_source_digest','actions_source_id','actions_source_digest','replay_reference',
    'replay_reference_digest','created_at'}
_REPLAY_V1={'schema_version','mode','book_id','source_day','valuation_day','decision_id','finalization_id',
    'finalization_digest','finalization_source_id','finalization_source_digest','model_publication_id','model_seed_digest',
    'accounting_input_id','accounting_input_digest','attempt_id','observation_id','observation_digest','results_digest',
    'basis_positions','action_admission'}
_REPLAY_V2=_REPLAY_V1|{'action_frame','action_frame_digest'}
_ACTION_FRAME={'schema_version','owner','original_action_count','original_action_digest','successor_action_count',
    'successor_action_digest','original_basis_positions','derived_model_basis_positions','actions_source','policy_identity',
    'raw_capture','adjustments'}
_ACTIONS_PAYLOAD={'schema_version','book_id','source_day','previous_day','valuation_time','events'}
_ACTION_EVENT={'key','type','ex_date','value_model_number','basis_provenance','basis_provenance_evidence',
    'frame_before','frame_after','raw_close_model_number','eligible_quantity_exact'}
_EVENT_KEY={'portfolio_id','strategy_id','strategy_name','date','symbol','portfolio_type'}
_INSTRUMENT={'symbol','asset_type','reference','mark','cost_evidence','cost_parameters'}
_QUOTE={'source_id','source_digest','date','price_frame_id','price_model_number'}
_HEX64=re.compile(r'[0-9a-f]{64}\Z')
_MODEL_NUMBER=re.compile(r'-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?\Z')
_CONTINUATION_FAILURES=_FAILURES+(OverflowError,)
_LOADED_ROWS={'finalization_market','prior_decision','binding','actions_row'}
_DECIMAL_SCALE=100000000
_INT64=(-(1<<63),(1<<63)-1)


def _text(value):
    """Non-empty text of at most 4096 UTF-8 BYTES (native ``text()``); a lone surrogate is refused, not raised."""
    _need(type(value) is str and 0<len(value.encode('utf-8'))<=4096)
    return value


def _eq(left,right):
    """JSON equality as nlohmann has it: a boolean equals only a boolean, numbers compare numerically."""
    if type(left) is bool or type(right) is bool:return type(left) is type(right) and left==right
    if type(left) is dict:return type(right) is dict and left.keys()==right.keys() and all(_eq(left[name],right[name]) for name in left)
    if type(left) is list:return type(right) is list and len(left)==len(right) and all(_eq(a,b) for a,b in zip(left,right))
    if type(left) in (int,float):return type(right) in (int,float) and left==right
    return type(left) is type(right) and left==right


def _digest_hex(value):_need(type(_text(value)) is str and _HEX64.match(value) is not None)


def _sealed(row):
    _need(type(row) is dict);_digest_hex(row['content_digest']);_need(row['content_digest']==_hash(row['payload']))


def _metadata_same(a,b):
    for name in ('producer_id','policy_version'):_need(_text(a[name])==_text(b[name]))


def _pg_timestamp(value):
    """A timestamptz as ``to_jsonb`` writes it in a UTC session (trailing fraction zeros dropped)."""
    _need(value.tzinfo is not None and value.utcoffset() is not None);value=value.astimezone(timezone.utc)
    fraction=('.'+format(value.microsecond,'06d').rstrip('0')) if value.microsecond else ''
    return value.strftime('%Y-%m-%dT%H:%M:%S')+fraction+'+00:00'


def _jsonb(value,depth=0):
    """The to_jsonb image of a row the way the native validator receives it (UUID/date/datetime as text)."""
    _need(depth<=40)
    if type(value) is dict:
        _need(all(type(name) is str for name in value));return {name:_jsonb(item,depth+1) for name,item in value.items()}
    if type(value) is list:return [_jsonb(item,depth+1) for item in value]
    if type(value) is UUID:return str(value)
    if type(value) is datetime:return _pg_timestamp(value)
    if type(value) is date:return value.isoformat()
    return value


def _model_number(value):
    """A positive finite IEEE double from a model-number string (native ``price()``/``number()``, n>0)."""
    _text(value);_need(len(value)<=64 and _MODEL_NUMBER.match(value) is not None)
    number=float(value);_need(math.isfinite(number) and number>0)
    return number


def _decimal8(value):
    """C++ ``Decimal(double)`` as the native ``checked()``: raw int64 of value*1e8 rounded half away from zero."""
    scaled=value*100000000.0+(0.5 if value>=0 else -0.5)
    _need(math.isfinite(scaled) and _INT64[0]<=scaled<=_INT64[1])
    _need(not(value>float(_INT64[1])/_DECIMAL_SCALE or value<float(_INT64[0])/_DECIMAL_SCALE))
    return int(scaled)


def _decimal8_double(raw):return float(raw)/_DECIMAL_SCALE


def _decimal8_text(raw):
    """C++ ``Decimal::to_string``: no exponent, fraction without trailing zeros, no '.' for whole values."""
    magnitude=-raw if raw<0 else raw;whole,fraction=divmod(magnitude,_DECIMAL_SCALE)
    result=('-' if raw<0 else '')+str(whole)
    if fraction:
        digits=format(fraction,'08d').rstrip('0')
        if digits:result+='.'+digits
    return result


def _namespace(identity):
    """The source-id namespace of a quote: the text before the last '/'."""
    _text(identity);slash=identity.rfind('/');_need(slash>0)
    return identity[:slash]


def _instruments(payload):
    rows=payload['instruments'];_need(type(rows) is list and len(rows)<=4096);result={}
    for row in rows:
        _need(type(row) is dict and set(row)==_INSTRUMENT and row['asset_type']=='EQUITY')
        for field in ('reference','mark'):
            quote=row[field];_need(type(quote) is dict and set(quote)==_QUOTE)
            _text(quote['source_id']);_digest_hex(quote['source_digest']);_need(_eq(quote['date'],payload['previous_day']))
            _text(quote['price_frame_id']);_model_number(quote['price_model_number'])
        _need(row['reference']['price_frame_id']==row['mark']['price_frame_id'])
        cost=row['cost_evidence'];_need(type(cost) is dict and 'date' in cost and _eq(cost['date'],payload['previous_day']))
        symbol=_text(row['symbol']);_need(symbol not in result);result[symbol]=row
    return result


_INSTANT=re.compile(r'([0-9]{4})-([0-9]{2})-([0-9]{2})[T ]([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]{1,6}))?(Z|[+-][0-9]{2}(?::?[0-9]{2})?)\Z')


def _instant(value):
    """An ISO-8601 instant in microseconds since the epoch (native ``instant()``): offsets Z, +HH, +HHMM, +HH:MM.

    A row captured under another session time zone spells the same instant with another offset.
    """
    _text(value);found=_INSTANT.match(value);_need(found is not None)
    year,month,day,hour,minute,second,fraction,zone=found.groups()
    _need(int(hour)<24 and int(minute)<60 and int(second)<60)
    days=(date(int(year),int(month),int(day))-date(1970,1,1)).days
    micros=((days*24+int(hour))*60+int(minute))*60*1000000+int(second)*1000000+int((fraction or '').ljust(6,'0'))
    if zone!='Z':
        sign=-1 if zone[0]=='-' else 1;hours=int(zone[1:3]);minutes=int(zone[-2:]) if len(zone)>3 else 0
        _need(hours<24 and minutes<60);micros-=sign*(hours*60+minutes)*60*1000000
    return micros


def _whole_row_equal(actual,captured):
    """``act==applied``: the WHOLE row, digest included; ``created_at`` is compared as an instant."""
    _need(type(actual) is dict and type(captured) is dict and len(actual)==len(captured))
    for name,value in captured.items():
        _need(name in actual)
        if name=='created_at':_need(_instant(actual[name])==_instant(value))
        else:_need(_eq(actual[name],value))


def _restated(price_text,steps):
    """equity_model_action_frame.cpp:80 with the mark in the basis position; returns the Decimal text.

    The mark is read as a double; the quotient of every step is screened to Decimal (1e-8) before the next.
    """
    current=_model_number(price_text);restated=None
    for event in steps:
        dividend=event['type']=='DIVIDEND';value=_model_number(event['value_model_number'])
        if dividend:
            close=_model_number(event['raw_close_model_number']);_text(event['eligible_quantity_exact'])
            factor=1+value/close
        else:
            _need(value!=1 and event['raw_close_model_number'] is None and event['eligible_quantity_exact'] is None)
            factor=value
        _need(math.isfinite(factor) and factor>0)
        restated=_decimal8(current/factor);_need(restated>0);current=_decimal8_double(restated)
    return _decimal8_text(restated)


def _prove_continuation(inputs):
    _need(type(inputs) is dict and set(inputs)==_CONTINUATION_INPUTS)
    names=('decision','prior_decision','finalization_market','input_market','finalization','anchor','binding','actions_row')
    for name in names:
        _need(type(inputs[name]) is dict)
        # PG ``to_jsonb(row)::text`` spells ', ' and ': '; the native wrapper refuses a LOADED row (M, S, binding, actions)
        # above 2 MiB of that text (qt_equity_prior_continuation_db.cpp:11), the pure validator any row above 8 MiB.
        loaded=name in _LOADED_ROWS
        size=len(json.dumps(_jsonb(inputs[name]),separators=(', ',': ') if loaded else (',',':'),ensure_ascii=False).encode('utf-8'))
        _need(size<=(2 if loaded else 8)*1024*1024)
    d,s,m,a,f,anchor,b,act=(_jsonb(inputs[name]) for name in names)
    candidate_list=inputs['candidate_action_sources'];_need(type(candidate_list) is list and len(candidate_list)<=4096)
    book,day,publication=_text(d['book_id']),_text(d['source_day']),_text(d['model_publication_id']);_text(d['decision_id'])
    # Same market is the unchanged old path, never a continuation.
    _text(m['source_id']);_text(a['source_id']);_need(not _eq(m['source_id'],a['source_id']))
    for row in (m,a,f,anchor,act):_sealed(row)
    mp,ap=m['payload'],a['payload'];_shape(mp,_MARKET_PAYLOAD);_shape(ap,_MARKET_PAYLOAD)
    _need(mp['schema_version']==FINALIZATION_MARKET_SCHEMA and m['model_publication_id'] is None and mp['model_publication_id'] is None)
    _need(ap['schema_version']=='qt-equity-accounting-market/v1' and a['model_publication_id']==publication
          and ap['model_publication_id']==publication)
    # (b) A equals M on every valuation field, policy revision and metadata; only the model differs.
    for name in ('calculation_version','book_id','source_day','previous_day','valuation_time','day_mode','currency','cost_config'):
        _need(_eq(ap[name],mp[name]))
    for name in ('book_id','source_day'):_need(_eq(m[name],mp[name]) and _eq(a[name],ap[name]))
    _need(ap['book_id']==book and ap['source_day']==day);_text(m['source_version']);_text(a['source_version'])
    revision=a['policy_revision'];_need(type(revision) is int and revision>0 and _eq(m['policy_revision'],revision))
    _metadata_same(a,m)
    # F finalized this S decision against M, and the anchor is F's derived v2 anchor.
    fid=_text(f['finalization_id']);fp=f['payload'];_need(type(fp) is dict)
    _need(f['market_source_id']==m['source_id'] and fp['market_source_id']==m['source_id']
          and fp['market_source_digest']==m['content_digest'])
    _need(_eq(fp['actions_source_id'],mp['actions_source_id']) and _eq(fp['actions_source_digest'],mp['actions_source_digest']))
    _need(_eq(fp['finalization_id'],fid) and _eq(fp['decision_id'],f['decision_id']) and f['source_version']=='qt-finalization/'+fid)
    _need(_eq(f['decision_id'],s['decision_id']) and _eq(s['book_id'],book) and _text(s['source_day'])<day
          and len(_text(s['model_publication_id']))>0)
    _need(_eq(f['book_id'],book) and _eq(f['source_day'],s['source_day']) and _eq(f['valuation_day'],day)
          and _eq(ap['previous_day'],f['source_day']))
    _need(_eq(f['policy_revision'],a['policy_revision']));_metadata_same(f,a)
    np=anchor['payload']
    _need(anchor['source_id']=='qt-finalization/'+fid and _eq(anchor['source_version'],anchor['source_id'])
          and _eq(anchor['book_id'],book) and _eq(anchor['source_day'],f['source_day']));_metadata_same(anchor,f)
    _shape(np,_ANCHOR_PAYLOAD)
    _need(np['schema_version']=='qt-equity-finalized-accounting/v2' and _eq(np['book_id'],book)
          and _eq(np['source_day'],f['source_day']) and _eq(np['currency'],ap['currency']))
    _need(_eq(np['finalization_id'],fid) and _eq(np['finalization_digest'],f['content_digest'])
          and _eq(np['policy_revision'],f['policy_revision']))
    basis=np['previous_positions'];_need(type(basis) is list and len(basis)<=4096);held=set()
    for position in basis:
        key=position['key'];_need(key['portfolio_id']==book);held.add(_text(key['symbol']))
    # (a) P2's binding: this decision's model, this finalization and its anchor, and the anchor's basis.
    _shape(b,_BINDING)
    _need(b['publication_id']==publication and b['book_id']==book and b['source_day']==day and b['strategy_id']==_ENGINE)
    _need(_eq(b['decision_id'],s['decision_id']) and _eq(b['finalization_id'],fid) and _eq(b['finalization_digest'],f['content_digest']))
    _need(_eq(b['finalization_source_id'],anchor['source_id']) and _eq(b['finalization_source_digest'],anchor['content_digest']))
    rr=b['replay_reference'];_digest_hex(b['replay_reference_digest']);_need(type(rr) is dict and _hash(rr)==b['replay_reference_digest'])
    v2=rr.get('schema_version')=='qt-equity-model-prior/v2'
    _shape(rr,_REPLAY_V2 if v2 else _REPLAY_V1)
    _need(rr['schema_version']==('qt-equity-model-prior/v2' if v2 else 'qt-equity-model-prior/v1')
          and rr['mode']=='verified_desk_prior'
          and rr['action_admission']==('proved_action_adjusted_prior' if v2 else 'action_free_only'))
    _need(_eq(rr['book_id'],book) and _eq(rr['source_day'],f['source_day']) and _eq(rr['valuation_day'],day)
          and _eq(rr['decision_id'],s['decision_id']))
    _need(_eq(rr['finalization_id'],fid) and _eq(rr['finalization_digest'],f['content_digest'])
          and _eq(rr['finalization_source_id'],anchor['source_id']) and _eq(rr['finalization_source_digest'],anchor['content_digest']))
    _need(_eq(rr['model_publication_id'],s['model_publication_id']) and _eq(rr['basis_positions'],basis))
    applied=None
    if v2:
        frame=rr['action_frame'];_digest_hex(rr['action_frame_digest']);_need(type(frame) is dict and _hash(frame)==rr['action_frame_digest'])
        _shape(frame,_ACTION_FRAME)
        _need(frame['schema_version']=='qt-equity-model-action-frame/v1' and _eq(frame['original_basis_positions'],basis))
        _need(_eq(frame['owner'],{'portfolio_id':book,'strategy_id':_ENGINE,'strategy_name':_OWNER,
                                  'source_day':f['source_day'],'valuation_day':day}))
        applied=frame['actions_source'];_need(type(applied) is dict);applied_events=applied['payload']['events']
        _need(type(applied_events) is list)
        _need(frame['successor_action_digest']==_hash(applied_events) and type(frame['successor_action_count']) is int
              and frame['successor_action_count']==len(applied_events))
        _need(_eq(b['actions_source_id'],applied['source_id']) and _eq(b['actions_source_digest'],applied['content_digest']))
    else:_need(b['actions_source_id'] is None and b['actions_source_digest'] is None)
    # (c) A's actions are exactly the row the MODEL applied, and no other candidate D action row exists.
    ep=act['payload']
    _need(_eq(act['source_id'],ap['actions_source_id']) and _eq(act['content_digest'],ap['actions_source_digest'])
          and act['purpose']=='actions' and _eq(act['source_version'],act['source_id']))
    _need(_eq(act['book_id'],book) and _eq(act['source_day'],day) and _eq(act['policy_revision'],a['policy_revision']));_metadata_same(act,a)
    _shape(ep,_ACTIONS_PAYLOAD);_need(ep['schema_version']=='qt-equity-actions-source/v1')
    for name in ('book_id','source_day','previous_day','valuation_time'):_need(_eq(ep[name],ap[name]))
    events=ep['events'];_need(type(events) is list and len(events)<=4096)
    if v2:_whole_row_equal(act,applied)
    if not events:_need(_eq(ap['actions_source_id'],mp['actions_source_id']) and _eq(ap['actions_source_digest'],mp['actions_source_digest']))
    else:_need(v2)
    candidates=set()
    for item in candidate_list:
        _need(type(item) is str and 0<len(item.encode('utf-8'))<=4096 and item not in candidates);candidates.add(item)
    if not events:_need(not candidates)
    else:_need(len(candidates)==1 and _eq(next(iter(candidates)),_text(act['source_id'])))
    # (d) Instruments: M's marks, with action symbols restated by the MODEL's arithmetic.
    before,after=_instruments(mp),_instruments(ap);actions={};previous=('',-1)
    for event in events:
        _shape(event,_ACTION_EVENT);key=event['key'];_shape(key,_EVENT_KEY)
        _need(key['portfolio_id']==book and key['strategy_id']==_ENGINE and key['strategy_name']==_OWNER
              and key['date']==day and key['portfolio_type']=='qt' and event['ex_date']==day)
        symbol=_text(key['symbol']);_need(symbol in before and symbol in held)
        kind=_text(event['type']);dividend=kind=='DIVIDEND';_need(dividend or kind in {'SPLIT','ADR_SPLIT'})
        order=(symbol,1 if dividend else 0);_need(order>previous);previous=order
        actions.setdefault(symbol,[]).append(event)
    for symbol,row in before.items():
        _need(symbol in after);expected=deepcopy(row)
        if symbol in actions:
            steps=actions[symbol];frame_id=_text(row['mark']['price_frame_id'])
            for event in steps:
                _need(event['frame_before']==frame_id);following=_text(event['frame_after']);_need(following!=frame_id);frame_id=following
            for field in ('reference','mark'):
                expected[field]['price_frame_id']=frame_id
                expected[field]['price_model_number']=_restated(row[field]['price_model_number'],steps)
        _need(_eq(after[symbol],expected))
    # Spec default 6: an open on D, never a held owner, never an action symbol; priced by the same governed source
    # as M: its quotes share M's single source-id namespace (dates and frame are checked by _instruments()).
    # M's quote-id namespaces are consulted ONLY when an open exists (nothing constrains the spelling of a quote id
    # otherwise): the opens then share M's single namespace.
    opens=[symbol for symbol in after if symbol not in before]
    if opens:
        namespaces={_namespace(item[field]['source_id']) for item in before.values() for field in ('reference','mark')}
        _need(len(namespaces)==1);governed=next(iter(namespaces))
        for symbol in opens:
            row=after[symbol];_need(symbol not in held and symbol not in actions)
            for field in ('reference','mark'):_need(_namespace(row[field]['source_id'])==governed)


def validate_qt_equity_verified_prior_continuation(inputs):
    """Port of the native validator; ``inputs`` has exactly the nine operands of its input struct.

    Returns None when the D input market A is a proven continuation of the finalization market M.
    Any failure, including a malformed operand, is the single fixed code.
    """
    try:_prove_continuation(inputs)
    except _CONTINUATION_FAILURES:raise ValueError(CONTINUATION_UNAVAILABLE) from None


def qt_equity_prior_continuation_holds(inputs):
    try:validate_qt_equity_verified_prior_continuation(inputs)
    except ValueError:return False
    return True


def _continuation_inputs(preceding_node,node):
    linked=preceding_node['accounting']['successor'];accounting=node['accounting'];sources=accounting['equity_sources']
    return {'decision':node['decision'],'prior_decision':preceding_node['decision'],
        'finalization_market':linked['market_row'],'input_market':sources['market_row'],
        'finalization':linked['transition_row'],'anchor':accounting['finalization_row'],
        'binding':sources['prior_binding'],'actions_row':sources['actions_row'],
        'candidate_action_sources':sources['action_candidates']}


def _market_continues(preceding,preceding_node,node):
    """The D input market is F's market (the old path, byte for byte) or a proven continuation of it."""
    source=node['accounting']['input_row']['payload']
    if (preceding['market_source_id']==source['market_source_id']
            and preceding['market_source_digest']==source['market_source_digest']):
        return True
    try:
        inputs=_continuation_inputs(preceding_node,node);market=inputs['input_market']
        # The accounting input must name exactly the market row the continuation was proved for.
        return (str(market['source_id'])==str(source['market_source_id'])
                and market['content_digest']==source['market_source_digest']
                and qt_equity_prior_continuation_holds(inputs))
    except _CONTINUATION_FAILURES:return False
