"""STAGED independent equity source, physical and native-mathematical proof.

The SQL loader and closed-schema dispatcher are owned by the composition lane.
Do not install this module as an available financial authority. Matching MODEL
identities, self-rehashed payloads, or caller flags cannot supply missing proof.
The server must retain the exact historical native artifact closure.
"""
from decimal import Decimal
from datetime import datetime, date, timezone
from hashlib import sha256
import json
import math
import re

from algolens.domain.portfolio.consumption_catalog import CATALOG
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.domain.portfolio.qt_workflow_models import QtKey, QtPreviewResponse
from algolens.domain.portfolio.qt_canonical import qt_book_digest_v1
from algolens.domain.shared.fixed_decimal8 import parse_fixed_decimal8
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from algolens.infrastructure.portfolio.qt_evaluator_process import QtEvaluatorUnavailable
from algolens.infrastructure.portfolio.qt_read_set import canonical_internal_snapshot_bytes
from algolens.infrastructure.portfolio.qt_original_processing_proof import _archived_bindings, PUBLICATION_FIELDS


def _load_equity_local_context(cursor, decision, accounting, *, current=False):
    """Borrow an ordered transaction; read real immutable and physical rows.

    Composition must first select the exact equity schema. No writes, mutable
    policy lookup, inferred operands or fallback records are supplied here.
    """
    source=accounting['input_row']['payload'];output=accounting['payload']
    def one(sql,args):
        cursor.execute(sql,args);row=cursor.fetchone()
        return dict(row) if row is not None else None
    market=one('SELECT * FROM trading.qt_desk_market_sources WHERE source_id=%s', (source['market_source_id'],))
    from algolens.infrastructure.portfolio.qt_empty_owner_sql import load_original_model_publication
    model=load_original_model_publication(cursor,str(decision['model_publication_id']))
    actions=one('SELECT * FROM trading.qt_equity_desk_evidence_sources WHERE source_id=%s', (market['payload']['actions_source_id'],)) if market else None
    basis_ids=[row['basis_evidence']['source_id'] for row in source['previous_positions']]
    cursor.execute('SELECT * FROM trading.qt_equity_desk_evidence_sources WHERE source_id=ANY(%s)', (basis_ids,))
    basis=[dict(row) for row in cursor.fetchall()]
    snapshot=one('SELECT * FROM trading.qt_evaluation_snapshots WHERE snapshot_id=%s', (output['producer_authority']['snapshot_id'],))
    # prior_binding / action_candidates are filled by the lineage loader only when the input market is
    # not the market of the finalization that produced the anchor (equity day 2); otherwise they stay unread.
    accounting['equity_sources']={'market_row':market,'model_publication':model,'actions_row':actions,
                                 'basis_rows':basis,'evaluation_snapshot':snapshot,
                                 'prior_binding':None,'action_candidates':None}
    if source.get('schema_version')=='qt-equity-accounting-input-empty-owner/v2':
        # No position sentinel exists for this source kind. A real scoped QT
        # totals row supplies the prior day; complete rows/curve are proved below.
        cursor.execute("SELECT max(day) AS latest_day FROM ("
            "SELECT date AS day FROM trading.positions WHERE portfolio_id=%s AND portfolio_type='qt' AND date<%s "
            "UNION ALL SELECT (CASE WHEN pg_typeof(date)='date'::regtype THEN date::text "
            "ELSE to_char(date::timestamptz AT TIME ZONE 'UTC','YYYY-MM-DD') END)::date AS day "
            "FROM trading.live_results WHERE portfolio_id=%s AND portfolio_type='qt' AND "
            "(CASE WHEN pg_typeof(date)='date'::regtype THEN date::text "
            "ELSE to_char(date::timestamptz AT TIME ZONE 'UTC','YYYY-MM-DD') END)::date<%s "
            "UNION ALL SELECT (timestamp AT TIME ZONE 'UTC')::date AS day FROM trading.equity_curve "
            "WHERE portfolio_id=%s AND portfolio_type='qt' AND (timestamp AT TIME ZONE 'UTC')::date<%s) scoped_prior",
            (decision['book_id'],decision['source_day'],decision['book_id'],decision['source_day'],
             decision['book_id'],decision['source_day']))
    else:
        cursor.execute("SELECT max(date) AS latest_day FROM trading.positions WHERE portfolio_id=%s AND portfolio_type='qt' AND date<%s", (decision['book_id'],decision['source_day']))
    latest=cursor.fetchone()['latest_day']
    def physical(day,with_executions):
        result={}
        for table,day_column in [('positions','date'),('live_results','date'),('equity_curve','timestamp')]+([('executions','date')] if with_executions else []):
            if table=='live_results':
                condition="(CASE WHEN pg_typeof(date)='date'::regtype THEN date::text ELSE to_char(date::timestamptz AT TIME ZONE 'UTC','YYYY-MM-DD') END)=%s"
            elif table=='equity_curve':condition="to_char(timestamp AT TIME ZONE 'UTC','YYYY-MM-DD')=%s"
            else:condition=day_column+'=%s'
            cursor.execute('SELECT * FROM trading.'+table+" WHERE portfolio_id=%s AND portfolio_type='qt' AND "+condition, (decision['book_id'],str(day)))
            result[table]=[dict(row) for row in cursor.fetchall()]
        return result
    accounting['physical_prior']={'latest_day':latest,**physical(source['previous_day'],False)}
    if current:accounting['financial_rows']=physical(decision['source_day'],True)
    return accounting


def load_equity_accounting_context(cursor, decision, accounting, *, current=False):
    from algolens.infrastructure.portfolio.qt_equity_finalization_evidence import load_equity_lineage_context
    return load_equity_lineage_context(cursor,decision,accounting,
        load_local_context=_load_equity_local_context,current=current)

_HEX = re.compile(r'[0-9a-f]{64}\Z')
_OUTPUT = {'schema_version','calculation_version','observation','executions','live_results','equity_curve',
    'distance','corporate_action_adjustments','layers_applied','selection_policy','input_digest','producer_authority','consumption'}
_FILL = {'key','observation_kind','selected_quantity_exact','average_price_exact','actual_cash_cost_exact',
    'currency','execution_id','accounting_source_id','daily_realized_pnl_exact','daily_unrealized_pnl_exact','last_update'}
_EXECUTION = {'key','exec_id','order_id','side','quantity_exact','price_exact','execution_time',
    'commissions_fees_exact','implicit_price_impact_exact','slippage_market_impact_exact','total_transaction_costs_exact'}
_LIVE = {'strategy_id','portfolio_id','date','portfolio_type','initial_capital_exact','daily_realized_pnl_exact',
    'daily_unrealized_pnl_exact','daily_pnl_exact','daily_transaction_costs_exact','total_realized_pnl_exact',
    'total_unrealized_pnl_exact','total_transaction_costs_exact','total_pnl_exact','current_portfolio_value_exact'}
_DISTANCE = {'key','selected_quantity_exact','previous_quantity_exact','restated_previous_quantity_exact','execution_delta_exact','selection_moved_by'}
_ADJUSTMENT = {'key','type','source_id','source_digest','basis_provenance','basis_provenance_evidence',
    'frame_before','frame_after','event_date','quantity_before_exact','quantity_after_exact','average_price_before_exact',
    'average_price_after_exact','event_value_model_number','ratio_change_model_number'}
_READS = {row['field']:row for row in CATALOG['fields'] if row['consumer']=='cost.execution'}
_BASE_READS = {'cost.spread.baseline_spread_ticks','cost.spread.min_spread_ticks','cost.spread.max_spread_ticks',
    'cost.spread.spread_cost_multiplier','cost.spread.tick_size','cost.spread.tick_constrained',
    'cost.impact.min_adv','cost.impact.min_participation','cost.impact.max_participation','cost.impact.max_impact_bps',
    'cost.charge.point_value','cost.charge.commission_per_unit','cost.charge.max_commission_pct',
    'cost.charge.min_commission_per_order','cost.charge.apply_regulatory_fees','cost.charge.max_total_implicit_bps'}
_SELL_READS = {'cost.charge.sec_fee_per_million','cost.charge.finra_taf_per_share','cost.charge.finra_taf_cap_per_trade'}


def _need(ok):
    if not ok: raise ValueError('unproven_equity_output')


def _shape(value,names): _need(type(value) is dict and set(value)==names)
def _hash(value): return sha256(canonical_qt_input_bytes(value)).hexdigest()
def _digest(value): _need(type(value) is str and _HEX.fullmatch(value) is not None)


def _exact(value):
    _need(type(value) is str and parse_fixed_decimal8(value) is not None)
    return Decimal(value)


def _walk_exact(value):
    if type(value) is dict:
        for name,item in value.items():
            if name.endswith('_exact'): _exact(item)
            _walk_exact(item)
    elif type(value) is list:
        for item in value: _walk_exact(item)


def _key(value,book,day):
    result=QtKey.from_wire(value)
    _need(result.portfolio_id==book and result.date==day and result.portfolio_type=='qt')
    return result


def _indexed(rows,fields,book,day):
    _need(type(rows) is list and len(rows)<=2048)
    result={}
    for row in rows:
        _shape(row,fields);key=_key(row['key'],book,day)
        _need(key not in result);result[key]=row
    return result


def _closed_output(value):
    _shape(value,_OUTPUT)
    empty_owner=value['schema_version']=='qt-equity-accounting-empty-owner/v2'
    _need(value['schema_version'] in {'qt-equity-accounting/v1','qt-equity-accounting-empty-owner/v2'} and value['calculation_version']=='qt-equity-main08b15c/v1'
          and value['selection_policy']=='exact-confirmed-choice')
    financial={name:item for name,item in value.items() if name!='consumption'}
    # Bounds and no floats outside the explicitly closed child. No financial
    # value becomes an observed read just because it was supplied here.
    canonical_qt_input_bytes(financial);_walk_exact(financial);_digest(value['input_digest'])
    observed=value['observation']
    _shape(observed,{'schema_version','decision_id','accounting_input_id','book_id','source_day','fills','results'})
    _need(observed['schema_version']=='qt-execution/v2')
    book,day=observed['book_id'],observed['source_day'];stamp=day+'T00:00:00Z'
    fills=_indexed(observed['fills'],_FILL,book,day);_need(not fills if empty_owner else fills)
    if empty_owner:
        # This is closed shape admission only. Actual original owner/source,
        # prior/current physical rows and native recomputation remain mandatory.
        _need(all(value[name]==[] for name in ('executions','distance','corporate_action_adjustments','layers_applied')))
    distances=_indexed(value['distance'],_DISTANCE,book,day);_need(set(fills)==set(distances))
    executions=_indexed(value['executions'],_EXECUTION,book,day)
    executed=set()
    for key,fill in fills.items():
        distance=distances[key];delta=_exact(distance['execution_delta_exact'])
        _need(distance['selection_moved_by']=='unchanged' and distance['selected_quantity_exact']==fill['selected_quantity_exact']
              and delta==_exact(fill['selected_quantity_exact'])-_exact(distance['restated_previous_quantity_exact']))
        _need(fill['currency']=='USD' and fill['last_update']==stamp and _exact(fill['actual_cash_cost_exact'])>=0)
        if delta==0:
            _need(fill['observation_kind']=='carried' and fill['execution_id'] is None and _exact(fill['actual_cash_cost_exact'])==0 and key not in executions)
        else:
            _need(fill['observation_kind']=='executed' and key in executions);executed.add(key);execution=executions[key]
            _need(execution['exec_id']==fill['execution_id']==execution['order_id'] and execution['execution_time']==stamp
                  and _exact(execution['quantity_exact'])==abs(delta) and execution['side']==('BUY' if delta>0 else 'SELL')
                  and execution['total_transaction_costs_exact']==fill['actual_cash_cost_exact'])
            for name in ('commissions_fees_exact','implicit_price_impact_exact','slippage_market_impact_exact','total_transaction_costs_exact'):
                _need(_exact(execution[name])>=0)
    _need(set(executions)==executed)
    engines={'LIVE_EQUITY_MEAN_REVERSION'} if empty_owner else {key.strategy_id for key in fills};live={};curves={}
    _need(type(value['live_results']) is list and type(value['equity_curve']) is list)
    for row in value['live_results']:
        _shape(row,_LIVE);engine=row['strategy_id'];_need(engine in engines and engine not in live);live[engine]=row
        _need(row['portfolio_id']==book and row['date']==day and row['portfolio_type']=='qt')
        if empty_owner:
            _need(all(_exact(row[name])==0 for name in ('daily_realized_pnl_exact','daily_unrealized_pnl_exact',
                'daily_pnl_exact','daily_transaction_costs_exact','total_unrealized_pnl_exact')))
        owned=[fill for key,fill in fills.items() if key.strategy_id==engine]
        _need(_exact(row['daily_realized_pnl_exact'])==sum((_exact(r['daily_realized_pnl_exact']) for r in owned),Decimal(0)))
        _need(_exact(row['daily_transaction_costs_exact'])==sum((_exact(r['actual_cash_cost_exact']) for r in owned),Decimal(0)))
        _need(_exact(row['total_unrealized_pnl_exact'])==sum((_exact(r['daily_unrealized_pnl_exact']) for r in owned),Decimal(0)))
        _need(_exact(row['daily_pnl_exact'])==_exact(row['daily_realized_pnl_exact'])-_exact(row['daily_transaction_costs_exact'])+_exact(row['daily_unrealized_pnl_exact']))
        _need(_exact(row['total_pnl_exact'])==_exact(row['total_realized_pnl_exact'])-_exact(row['total_transaction_costs_exact'])+_exact(row['total_unrealized_pnl_exact']))
        _need(_exact(row['current_portfolio_value_exact'])==_exact(row['initial_capital_exact'])+_exact(row['total_pnl_exact'])
              and _exact(row['initial_capital_exact'])>0 and _exact(row['current_portfolio_value_exact'])>0 and _exact(row['total_transaction_costs_exact'])>=0)
    for row in value['equity_curve']:
        _shape(row,{'portfolio_id','strategy_id','timestamp','portfolio_type','equity_exact'});engine=row['strategy_id']
        _need(engine in live and engine not in curves);curves[engine]=row
        _need(row['portfolio_id']==book and row['portfolio_type']=='qt' and row['timestamp']==stamp and row['equity_exact']==live[engine]['current_portfolio_value_exact'])
    _need(set(live)==set(curves)==engines)
    results=observed['results'];_shape(results,{'position_count','currency_totals'})
    _need(type(results['position_count']) is int and results['position_count']==len(fills)
          and type(results['currency_totals']) is list and len(results['currency_totals'])==1)
    total=results['currency_totals'][0];_shape(total,{'currency','actual_cash_cost_exact','daily_realized_pnl_exact','daily_unrealized_pnl_exact'})
    _need(total['currency']=='USD')
    for name in ('actual_cash_cost_exact','daily_realized_pnl_exact','daily_unrealized_pnl_exact'):
        _need(_exact(total[name])==sum((_exact(fill[name]) for fill in fills.values()),Decimal(0)))
    _need(type(value['corporate_action_adjustments']) is list and len(value['corporate_action_adjustments'])<=2048)
    for row in value['corporate_action_adjustments']:
        _shape(row,_ADJUSTMENT);_need(_key(row['key'],book,day) in fills and row['type'] in {'SPLIT','ADR_SPLIT','DIVIDEND'});_digest(row['source_digest'])
    _need(value['layers_applied']==(['corporate-action-basis-restatement'] if value['corporate_action_adjustments'] else []))
    child=value['consumption'];_shape(child,{'schema_version','profile','authority','identity','coverage','charges'})
    _need(child['schema_version']=='qt-equity-cost-consumption/v1' and child['profile']=='qt_equity_accounting_costs' and child['authority']=='inspection_only')
    _need(child['coverage']=={'scope':'executed_equity_cost_calls','status':'complete'})
    identity=child['identity'];_shape(identity,{'decision_id','accounting_input_id','book_id','source_day','input_digest','financial_output_digest','producer_version'})
    for name in ('decision_id','accounting_input_id','book_id','source_day'): _need(identity[name]==observed[name])
    _need(identity['input_digest']==value['input_digest'] and identity['financial_output_digest']==_hash(financial)
          and identity['producer_version']==value['producer_authority']['evaluator_build'])
    charges=_indexed(child['charges'],{'key','outcome','meta','reads'},book,day);_need(set(charges)==executed)
    _need([_key(row['key'],book,day) for row in child['charges']]==sorted(charges))
    read_count=0
    for key,charge in charges.items():
        _need(charge['outcome']=='returned_ok' and charge['meta']=={'input_source':'explicit_values','asset_lookup':'exact_symbol'})
        _need(type(charge['reads']) is list and len(charge['reads'])<=32);reads={}
        for read in charge['reads']:
            _shape(read,{'field','value_type','value','origin'});field=read['field']
            _need(field in _READS and field not in reads and read['origin']=='runtime_effective' and read['value_type']==_READS[field]['type'])
            item=read['value']
            if read['value_type']=='bool': _need(type(item) is bool)
            else: _need(read['value_type']=='number' and type(item) in {int,float} and math.isfinite(item) and len(json.dumps(item,allow_nan=False))<=25)
            reads[field]=read;read_count+=1
        expected=set(_BASE_READS)
        if reads.get('cost.charge.max_commission_pct',{}).get('value',0)<0: expected.add('cost.charge.max_commission_per_order')
        if reads.get('cost.charge.apply_regulatory_fees',{}).get('value') is True and executions[key]['side']=='SELL': expected|=_SELL_READS
        _need(set(reads)==expected)
    _need(read_count<=16384)
    child_bytes=json.dumps(child,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8','strict')
    _need(len(child_bytes)<=2*1024*1024)
    return financial


def canonical_equity_accounting_output_bytes(value):
    """Bound only a complete closed output; never prove source or mathematics."""
    try:
        _closed_output(value)
        wire=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8','strict')
        _need(len(wire)<=8*1024*1024)
        return wire
    except (ValueError,TypeError,KeyError,ArithmeticError,QtWorkflowError,UnicodeError,RecursionError):
        raise ValueError('unproven_equity_output') from None


def verify_equity_output_recomputation(decision,selection_rows,accounting_input,producer_authority,output,
                                      *,recompute_client,expected_authority_digest):
    """Obligatory mathematical digest comparison after durable SQL proof.

    This is a subproof, not source authority or report readiness. Its client is
    a server-composed pinned native transport; a fixture fake is not admission.
    """
    try:
        wire=canonical_equity_accounting_output_bytes(output)
        _need(recompute_client is not None and _hash(producer_authority)==expected_authority_digest
              and output['producer_authority']==producer_authority and output['input_digest']==_hash(accounting_input))
        summary=recompute_client.recompute(decision,selection_rows,accounting_input,producer_authority,
                                          expected_authority_digest=expected_authority_digest)
        _need(summary['input_digest']==_hash(accounting_input) and summary['selection_digest']==_hash(selection_rows)
              and summary['financial_output_digest']==_hash({k:v for k,v in output.items() if k!='consumption'})
              and summary['output_digest']==sha256(wire).hexdigest())
    except (ValueError,TypeError,KeyError,ArithmeticError,QtWorkflowError,UnicodeError,RecursionError,QtEvaluatorUnavailable):
        raise ValueError('unproven_equity_recomputation') from None


def _sql_time(value):
    if type(value) is str:
        _need(re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)',value) is not None)
        value=datetime.fromisoformat(value.replace('Z','+00:00'))
    _need(isinstance(value,datetime) and value.tzinfo is not None and value.utcoffset() is not None)
    return value.astimezone(timezone.utc)


def _sql_number(value):
    _need(type(value) in {Decimal,int})
    number=Decimal(value);_need(number.is_finite())
    _exact(format(number.normalize(),'f'))
    return number


def _raw_key(row):
    return QtKey.from_wire({name:str(row[name]) for name in QtKey.__dataclass_fields__})


def _unique(rows,identity):
    _need(type(rows) is list and len(rows)<=4096);answer={}
    for row in rows:
        _need(type(row) is dict);key=identity(row);_need(key not in answer);answer[key]=row
    return answer


def _physical_positions(rows,expected,book,day):
    actual=_unique(rows,_raw_key)
    wanted=_unique(expected,lambda row:_key(row['key'],book,day))
    _need(set(actual)==set(wanted))
    for key,row in wanted.items():
        observed=actual[key]
        for field in ('quantity','average_price','daily_realized_pnl','daily_unrealized_pnl'):
            _need(_sql_number(observed[field])==_exact(row[field+'_exact']))
        _need(_sql_time(observed['last_update'])==_sql_time(row['last_update']))


def _physical_engines(physical,expected,book,day,*,prior=False):
    live=_unique(physical['live_results'],lambda row:row['strategy_id'])
    curves=_unique(physical['equity_curve'],lambda row:row['strategy_id'])
    wanted=_unique(expected,lambda row:row['strategy_id'])
    _need(set(live)==set(curves)==set(wanted))
    midnight=_sql_time(day+'T00:00:00Z')
    for engine,row in wanted.items():
        observed=live[engine];curve=curves[engine]
        for item in (observed,curve):_need(item['portfolio_id']==book and item['portfolio_type']=='qt')
        actual_day=observed['date']
        _need((_sql_time(actual_day)==midnight) if isinstance(actual_day,datetime) else type(actual_day) is date and str(actual_day)==day)
        _need(_sql_time(curve['timestamp'])==midnight)
        mapping={'current_portfolio_value':'equity_exact'} if prior else {'current_portfolio_value':'current_portfolio_value_exact'}
        names=('total_pnl','total_realized_pnl','total_unrealized_pnl','total_transaction_costs')
        if not prior:names+=('daily_pnl','daily_realized_pnl','daily_unrealized_pnl','daily_transaction_costs')
        mapping.update({name:name+'_exact' for name in names})
        for name,field in mapping.items():_need(_sql_number(observed[name])==_exact(row[field]))
        equity=_exact(row['equity_exact' if prior else 'current_portfolio_value_exact'])
        _need(_sql_number(curve['equity'])==equity)
        _need(_exact(row['initial_capital_exact'])>0 and equity==_exact(row['initial_capital_exact'])+_exact(row['total_pnl_exact']))


def _physical_current(row,output,book,day):
    actual=row['financial_rows'];_shape(actual,{'positions','executions','live_results','equity_curve'})
    expected=[{'key':fill['key'],'quantity_exact':fill['selected_quantity_exact'],
        **{field:fill[field] for field in ('average_price_exact','daily_realized_pnl_exact','daily_unrealized_pnl_exact','last_update')}}
        for fill in output['observation']['fills']]
    _physical_positions(actual['positions'],expected,book,day)
    _physical_engines(actual,output['live_results'],book,day)
    _physical_executions(actual['executions'],output['executions'],book,day)


def _physical_executions(rows,expected,book,day):
    executions=_unique(rows,_raw_key)
    wanted=_unique(expected,lambda item:_key(item['key'],book,day));_need(set(executions)==set(wanted))
    for key,execution in wanted.items():
        observed=executions[key]
        for name in ('exec_id','order_id','side'):_need(observed[name]==execution[name])
        for name in ('quantity','price','commissions_fees','implicit_price_impact','slippage_market_impact','total_transaction_costs'):
            _need(_sql_number(observed[name])==_exact(execution[name+'_exact']))
        _need(observed['is_partial'] is False and _sql_time(observed['execution_time'])==_sql_time(execution['execution_time']))


def _row_digest(row):
    _need(type(row) is dict and row['content_digest']==_hash(row['payload'])
          and type(row['source_version']) is str and bool(row['source_version'].strip()))


def _metadata(a,b):
    for name in ('producer_id','policy_version'):
        _need(type(a[name]) is str and bool(a[name].strip()) and a[name]==b[name])


def _source_input(accounting,decision,selection,*,prior_anchor_validator=None):
    inputs,final=accounting['input_row'],accounting['finalization_row'];source,anchor=inputs['payload'],final['payload']
    context=accounting['equity_sources']
    base={'market_row','model_publication','actions_row','basis_rows','evaluation_snapshot'}
    _need(type(context) is dict and set(context) in (base,base|{'prior_binding','action_candidates'}))
    market,events=context['market_row'],context['actions_row'];_row_digest(inputs);_row_digest(final);_row_digest(market);_row_digest(events)
    m=market['payload'];e=events['payload'];book,day=decision['book_id'],str(decision['source_day'])
    _shape(m,{'schema_version','calculation_version','book_id','source_day','model_publication_id','previous_day','valuation_time','day_mode','currency','cost_config','instruments','actions_source_id','actions_source_digest'})
    empty_owner=source.get('schema_version')=='qt-equity-accounting-input-empty-owner/v2'
    derived=anchor.get('schema_version') in {'qt-equity-finalized-accounting/v2','qt-equity-finalized-accounting-empty-owner/v3'}
    fields={'schema_version','calculation_version','book_id','source_day','currency','policy_revision','previous_positions','previous_totals'}
    _shape(anchor,fields|({'finalization_id','finalization_digest'} if derived else set()))
    market_schema='qt-equity-accounting-market-empty-owner/v2' if empty_owner else 'qt-equity-accounting-market/v1'
    anchor_schemas=({'qt-equity-finalized-accounting/v1','qt-equity-finalized-accounting-empty-owner/v3'} if empty_owner
                    else {'qt-equity-finalized-accounting/v1','qt-equity-finalized-accounting/v2'})
    _need(m['schema_version']==market_schema and anchor['schema_version'] in anchor_schemas
          and m['calculation_version']==anchor['calculation_version']=='qt-equity-main08b15c/v1')
    if derived:
        _need(callable(prior_anchor_validator) and prior_anchor_validator(accounting,decision)==anchor)
    for name in ('book_id','source_day','model_publication_id'):_need(m[name]==str(decision[name])==str(market[name]))
    prior=m['previous_day'];_need(type(prior) is str and date.fromisoformat(prior).isoformat()==prior and prior<day)
    _need(anchor['book_id']==final['book_id']==book and anchor['source_day']==str(final['source_day'])==prior
          and anchor['currency']==m['currency']=='USD' and m['day_mode']=='open' and m['valuation_time']==day+'T00:00:00Z')
    _need(type(anchor['policy_revision']) is int and 0<anchor['policy_revision']<(1<<63)
          and type(market['policy_revision']) is int and 0<market['policy_revision']<(1<<63))
    _need(re.fullmatch(r'qt-finalization/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',final['source_id']) is not None
          and final['source_version']==final['source_id'])
    _metadata(inputs,market);_metadata(inputs,final)
    _need(_sql_time(inputs['as_of'])==_sql_time(market['as_of']) and _sql_time(inputs['valid_until'])==_sql_time(market['valid_until'])
          and _sql_time(market['as_of'])<_sql_time(market['valid_until']))
    for row in (inputs,market):_need(_sql_time(market['as_of'])<=_sql_time(row['created_at'])<=_sql_time(market['valid_until']))
    _need(str(inputs['decision_id'])==str(decision['decision_id']) and inputs['source_version']=='qt-input/'+str(inputs['input_id']))
    positions=_unique(anchor['previous_positions'],lambda row:_key(row['key'],book,prior));_need(not positions if empty_owner else positions)
    if empty_owner:
        from algolens.infrastructure.portfolio.qt_empty_owner_sql import OwnerPublication
        model=context['model_publication']
        _need(type(model) is OwnerPublication)
        document=model.document
        _need(document['publication_id']==str(decision['model_publication_id']) and document['book_id']==book
              and document['source_day']==day and len(document['configured_owner_names'])==1
              and all(document[name]==[] for name in ('system_components','proposal_components','qt_components'))
              and selection==[] and m['instruments']==[] and e['events']==[] and context['basis_rows']==[])
    basis=_unique(context['basis_rows'],lambda row:row['source_id']);used=set()
    for key,position in positions.items():
        _shape(position,_FILL-{'observation_kind','selected_quantity_exact','actual_cash_cost_exact','currency','execution_id','accounting_source_id'}|{'quantity_exact','basis_evidence'})
        bound=position['basis_evidence'];_shape(bound,{'source_id','source_digest','price_frame_id','formed_day'})
        record=basis[bound['source_id']];used.add(bound['source_id']);_row_digest(record);_metadata(record,final)
        _need(record['purpose']=='basis' and record['policy_revision']==anchor['policy_revision'] and record['book_id']==book
              and str(record['source_day'])==prior and record['content_digest']==bound['source_digest'])
        payload=record['payload'];_shape(payload,{'schema_version','book_id','source_day','key','quantity_exact','average_price_exact','price_frame_id','formed_day'})
        _need(payload['schema_version']=='qt-equity-basis-source/v1' and payload['book_id']==book and payload['source_day']==prior)
        for field in ('key','quantity_exact','average_price_exact'):_need(payload[field]==position[field])
        for field in ('price_frame_id','formed_day'):_need(payload[field]==bound[field])
        _need(type(bound['price_frame_id']) is str and bool(bound['price_frame_id'])
              and date.fromisoformat(bound['formed_day']).isoformat()==bound['formed_day']<=prior)
        _need(_sql_time(prior+'T00:00:00Z')<=_sql_time(position['last_update'])<=_sql_time(day+'T00:00:00Z'))
    _need(used==set(basis))
    _metadata(events,market);_need(events['purpose']=='actions' and events['policy_revision']==market['policy_revision']
        and events['book_id']==book and str(events['source_day'])==day and events['source_id']==m['actions_source_id']
        and events['content_digest']==m['actions_source_digest'])
    _shape(e,{'schema_version','book_id','source_day','previous_day','valuation_time','events'})
    _need(e['schema_version']=='qt-equity-actions-source/v1')
    for field in ('book_id','source_day','previous_day','valuation_time'):_need(e[field]==m[field])
    _need(type(e['events']) is list and len(e['events'])<=4096)
    actions=[]
    for event in e['events']:
        _need(type(event) is dict and 'source_id' not in event and 'source_digest' not in event)
        actions.append({**event,'source_id':events['source_id'],'source_digest':events['content_digest']})
    admitted=_unique(m['instruments'],lambda item:item['symbol']);wanted={item['key']['symbol'] for item in selection}
    _need(wanted<=set(admitted) and all(item['asset_type']=='EQUITY' for item in admitted.values()))
    reconstructed={'schema_version':('qt-equity-accounting-input-empty-owner/v2' if empty_owner else 'qt-equity-accounting-input/v1'),'calculation_version':m['calculation_version'],
        'decision_id':str(decision['decision_id']),'book_id':book,'source_day':day,'accounting_input_id':str(inputs['input_id']),
        'market_source_id':str(market['source_id']),'market_source_digest':market['content_digest'],'accounting_source_id':str(market['source_id']),
        'prior_finalization_source_id':final['source_id'],'prior_finalization_digest':final['content_digest'],
        'previous_day':prior,'timestamp':m['valuation_time'],'day_mode':m['day_mode'],'currency':m['currency'],
        'previous_positions':anchor['previous_positions'],'previous_totals':anchor['previous_totals'],
        'instruments':[admitted[symbol] for symbol in sorted(wanted)],'actions':actions,'cost_config':m['cost_config']}
    _need(source==reconstructed)
    physical=accounting['physical_prior'];_shape(physical,{'latest_day','positions','live_results','equity_curve'})
    _need(str(physical['latest_day'])==prior)
    _physical_positions(physical['positions'],list(positions.values()),book,prior)
    totals=_unique(anchor['previous_totals'],lambda item:item['strategy_id'])
    _need(set(totals)==({'LIVE_EQUITY_MEAN_REVERSION'} if empty_owner else {key.strategy_id for key in positions}))
    for engine,total in totals.items():
        _shape(total,{'strategy_id','initial_capital_exact','equity_exact','total_pnl_exact','total_realized_pnl_exact','total_transaction_costs_exact','total_unrealized_pnl_exact'})
        _need(_exact(total['total_unrealized_pnl_exact'])==sum((_exact(p['daily_unrealized_pnl_exact']) for key,p in positions.items() if key.strategy_id==engine),Decimal(0))
              and _exact(total['total_pnl_exact'])==_exact(total['total_realized_pnl_exact'])-_exact(total['total_transaction_costs_exact'])+_exact(total['total_unrealized_pnl_exact'])
              and _exact(total['total_transaction_costs_exact'])>=0)
    _physical_engines(physical,list(totals.values()),book,prior,prior=True)
    return source,totals


def _captured_authority(evidence,output):
    decision,preview=evidence['decision'],evidence['preview'];row=evidence['accounting'];authority=output['producer_authority']
    fields={'schema_version','book_id','source_day','model_publication_id','snapshot_id','source_version','as_of','valid_until','content_digest','producer_id','policy_version','policy_revision','policy_updated_at','evaluator_build','evaluator_sha256','evaluator_bundle_sha256','allowed_override_codes'}
    _shape(authority,fields);_need(authority['schema_version']=='qt-input-authority/v1')
    for name in ('book_id','source_day','model_publication_id'):_need(authority[name]==str(decision[name]))
    _need(type(authority['snapshot_id']) is int and 0<authority['snapshot_id']<(1<<63)
          and type(authority['policy_revision']) is int and 0<authority['policy_revision']<(1<<63))
    for name in ('content_digest','evaluator_sha256','evaluator_bundle_sha256'):_digest(authority[name])
    _need(authority['evaluator_build']==preview['evaluator_build'] and authority['policy_version']==preview['policy_version'])
    original=preview['read_set_payload'];digest=_hash(authority)
    external=_unique(original['external_sources'],lambda item:item['name'])
    _need(set(external)=={'mark','history','cost','multiplier','universe','instrument_type','quantity_rule','evaluator_policy'})
    for record in external.values():
        _need(record['status']=='available' and record['digest']==digest and record['reason'] is None
              and record['source_id']=='qt_evaluation_snapshots:'+str(authority['snapshot_id'])
              and record['version']==authority['source_version'] and record['as_of']==authority['as_of'] and record['valid_until']==authority['valid_until'])
    snapshot=row['equity_sources']['evaluation_snapshot'];_row_digest(snapshot)
    _need(snapshot['snapshot_id']==authority['snapshot_id'])
    for name in ('book_id','source_day','model_publication_id','source_version','content_digest','producer_id','policy_version'):
        _need(str(snapshot[name])==str(authority[name]))
    for name in ('as_of','valid_until'):_need(_sql_time(snapshot[name])==_sql_time(authority[name]))
    _need(_sql_time(authority['as_of'])<_sql_time(authority['valid_until'])
          and _sql_time(authority['as_of'])<=_sql_time(evidence['receipt']['processed_at'])<=_sql_time(authority['valid_until']))
    _archived_bindings(original,row['equity_sources']['model_publication'],decision,preview,decision['book_id'],str(decision['source_day']))
    return authority,digest


def _prove_original_sql(evidence,recompute_client_factory,*,prior_anchor_validator=None):
    """Immutable original links, sources and native math; no current marks.

    Historical proof never compares the original result to a later marked
    physical inventory. Successor authority remains a separate subproof.
    """
    _shape(evidence['receipt']['publication_payload'],PUBLICATION_FIELDS)
    d,p,r,o,result=(evidence[name] for name in ('decision','preview','receipt','observation','result'))
    row=evidence['accounting'];_need(row is not None and callable(recompute_client_factory))
    inputs=row['input_row'];output=row['payload'];wire=canonical_equity_accounting_output_bytes(output)
    _need(row['content_digest']==sha256(wire).hexdigest())
    _need(str(row['decision_id'])==str(inputs['decision_id'])==str(d['decision_id']))
    _need(str(row['input_id'])==str(inputs['input_id'])==str(o['observation_id']))
    _need(row['portfolio_id']==d['book_id'])
    _need(str(row['date'])==str(d['source_day']))
    _need(d['status']=='confirmed_decision' and p['state']=='confirmed_decision' and p['availability']=='ready' and r['status']=='processed')
    payload=QtPreviewResponse.from_wire(p['payload']).to_wire();book,day=d['book_id'],str(d['source_day'])
    for name in ('preview_id','book_id','source_day','draft_id','draft_revision','provenance_digest'):_need(str(p[name])==str(d[name]))
    for name in ('payload_digest','read_set_digest','selected_book_digest'):_need(payload[name]==p[name])
    _need(payload['book_id']==book and payload['source_day']==day and payload['preview_id']==str(d['preview_id']))
    _need(sha256(canonical_internal_snapshot_bytes('qt-read-set/v1',p['read_set_payload'])).hexdigest()==d['read_set_digest']==p['read_set_digest'])
    _need(d['selected_book_digest']==p['selected_book_digest'] and str(r['decision_id'])==str(d['decision_id']))
    reference={'schema_version':'qt-desk-decision/v1','decision_id':str(d['decision_id']),'preview_id':str(d['preview_id']),
        'book_id':book,'source_day':day,'preview_payload_digest':p['payload_digest'],'read_set_digest':d['read_set_digest'],'selected_book_digest':d['selected_book_digest']}
    _need(d['payload']==reference)
    pub=r['publication_payload'];_need(pub['schema_version']=='qt-desk-publication/v1')
    for name in ('decision_id','book_id','source_day','model_publication_id','read_set_digest','selected_book_digest'):_need(pub[name]==str(d[name]))
    _need(pub['attempt_id']==str(r['attempt_id']) and pub['observation_id']==str(o['observation_id']) and pub['preview_payload_digest']==p['payload_digest']
          and pub['published_book_digest']==r['published_book_digest']==d['selected_book_digest'])
    _need(output['observation']==o['payload'] and o['content_digest']==pub['observation_digest']==_hash(o['payload'])
          and str(o['decision_id'])==str(d['decision_id']) and o['payload']['accounting_input_id']==str(inputs['input_id'])
          and inputs['content_digest']==output['input_digest']==_hash(inputs['payload']))
    for name in ('producer_id','policy_version','source_version'):_need(inputs[name]==o[name])
    for name in ('as_of','valid_until'):_need(_sql_time(inputs[name])==_sql_time(o[name]))
    _need(_sql_time(inputs['as_of'])<=_sql_time(r['processed_at'])<=_sql_time(inputs['valid_until']))
    _need(str(result['decision_id'])==str(d['decision_id']) and str(result['attempt_id'])==str(r['attempt_id'])
          and str(result['observation_id'])==str(o['observation_id']) and result['content_digest']==pub['results_digest']==_hash(result['payload']))
    expected_result={'schema_version':'qt-desk-result/v1','decision_id':str(d['decision_id']),'observation_id':str(o['observation_id']),
        'book_id':book,'source_day':day,'selected_book_digest':d['selected_book_digest'],'results':o['payload']['results']}
    _need(result['payload']==expected_result)
    selected=_unique(payload['selection_rows'],lambda item:_key({**item['key'],'portfolio_type':'qt'},book,day))
    fills=_unique(output['observation']['fills'],lambda item:_key(item['key'],book,day));_need(set(selected)==set(fills))
    for key,selection in selected.items():_need(selection['asset_type']=='EQUITY' and selection['quantity_exact']==fills[key]['selected_quantity_exact'])
    after=[{'key':fill['key'],'quantity_exact':fill['selected_quantity_exact'],**{field:fill[field] for field in ('average_price_exact','daily_realized_pnl_exact','daily_unrealized_pnl_exact','last_update')}} for fill in fills.values()]
    _need(_unique(pub['after_accounting'],lambda item:_key(item['key'],book,day))==_unique(after,lambda item:_key(item['key'],book,day)))
    _need(pub['before_accounting']==p['read_set_payload']['saved_accounting'])
    _need(qt_book_digest_v1([{'key':item['key'],'quantity_exact':item['quantity_exact']} for item in after],source_portfolio_type='qt')==d['selected_book_digest'])
    source,totals=_source_input(row,d,payload['selection_rows'],prior_anchor_validator=prior_anchor_validator);authority,digest=_captured_authority(evidence,output)
    for current in output['live_results']:
        previous=totals[current['strategy_id']]
        _need(current['initial_capital_exact']==previous['initial_capital_exact']
              and _exact(current['total_realized_pnl_exact'])==_exact(previous['total_realized_pnl_exact'])+_exact(current['daily_realized_pnl_exact'])
              and _exact(current['total_transaction_costs_exact'])==_exact(previous['total_transaction_costs_exact'])+_exact(current['daily_transaction_costs_exact'])
              and _exact(current['daily_unrealized_pnl_exact'])==_exact(current['total_unrealized_pnl_exact'])-_exact(previous['total_unrealized_pnl_exact']))
    client=recompute_client_factory(authority)
    verify_equity_output_recomputation({name:str(d[name]) for name in ('decision_id','book_id','source_day')},
        payload['selection_rows'],source,authority,output,recompute_client=client,expected_authority_digest=digest)
    return output


def _prove_sql(evidence,recompute_client_factory):
    """Preserved original current wrapper; unknown successors still refuse."""
    row=evidence['accounting'];_need(row is not None and row.get('successor') is None)
    output=_prove_original_sql(evidence,recompute_client_factory)
    if 'financial_rows' in row:
        d=evidence['decision'];_physical_current(row,output,d['book_id'],str(d['source_day']))
    return output


def validate_qt_equity_accounting_proof(evidence, *, recompute_client_factory=None,
        finalization_recompute_client_factory=None):
    """Prove EQ accounting after real SQL loading; audit proof remains separate.

    A server-owned retained-bundle factory is obligatory. Missing records,
    unsupported successor, inconsistent exact physical accounting and failed
    native recomputation never become successful empty financial evidence.
    """
    try:
        row=evidence['accounting']
        if row.get('successor') is not None or row['finalization_row']['payload'].get('schema_version') in {'qt-equity-finalized-accounting/v2','qt-equity-finalized-accounting-empty-owner/v3'}:
            from algolens.infrastructure.portfolio.qt_equity_finalization_proof import (
                validate_qt_equity_original_accounting_proof,verified_qt_equity_finalization_successor)
            factories={'recompute_client_factory':recompute_client_factory,
                       'finalization_recompute_client_factory':finalization_recompute_client_factory}
            output=validate_qt_equity_original_accounting_proof(evidence,**factories)
            if row.get('successor') is not None:
                verified_qt_equity_finalization_successor(evidence,current='financial_rows' in row,**factories)
            elif 'financial_rows' in row:
                d=evidence['decision'];_physical_current(row,output,d['book_id'],str(d['source_day']))
            return output
        return _prove_sql(evidence,recompute_client_factory)
    except (ValueError,TypeError,KeyError,AttributeError,ArithmeticError,QtWorkflowError,UnicodeError,RecursionError,QtEvaluatorUnavailable):
        raise ValueError('qt_equity_accounting_proof_unavailable') from None


def producer_equity_prior_carries(evidence, *, recompute_client_factory=None,
        finalization_recompute_client_factory=None):
    """Equity counterpart of producer_prior_carries; never a default fallback."""
    output=validate_qt_equity_accounting_proof(evidence,recompute_client_factory=recompute_client_factory,
        finalization_recompute_client_factory=finalization_recompute_client_factory)
    return {QtKey.from_wire(fill['key']):fill for fill in output['observation']['fills'] if fill['observation_kind']=='carried'}
