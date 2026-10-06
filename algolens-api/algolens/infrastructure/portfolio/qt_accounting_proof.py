"""Linked immutable producer evidence for prior-day QT carries.

Consumer-only observations retain the original same-day carry proof. This
module neither grants processing authority nor accepts caller-supplied flags.
"""
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from algolens.domain.portfolio.qt_workflow_models import QtKey
from algolens.domain.shared.fixed_decimal8 import parse_fixed_decimal8
from algolens.infrastructure.portfolio.qt_finalization_proof import verified_finalization_successor
from algolens.infrastructure.portfolio.qt_upstream_input_proof import verify_upstream_accounting_input


def _uses_equity_accounting(row):
    schemas = (row['input_row']['payload'].get('schema_version'),
        row['payload'].get('schema_version'), (row.get('finalization_row') or {}).get('payload', {}).get('schema_version'))
    if not any(isinstance(value, str) and value.startswith('qt-equity-') for value in schemas):
        return False
    legacy = (schemas[:2] == ('qt-equity-accounting-input/v1', 'qt-equity-accounting/v1')
              and schemas[2] in {'qt-equity-finalized-accounting/v1','qt-equity-finalized-accounting/v2'})
    empty_owner = (schemas[:2] == ('qt-equity-accounting-input-empty-owner/v2', 'qt-equity-accounting-empty-owner/v2')
                   and schemas[2] in {'qt-equity-finalized-accounting/v1','qt-equity-finalized-accounting-empty-owner/v3'})
    if not (legacy or empty_owner):
        raise ValueError('unproven_accounting')
    return True


def _load_successor(cursor, decision_id):
    cursor.execute("SELECT to_jsonb(f) AS transition_row,to_jsonb(m) AS market_row,"
        "to_jsonb(p) AS model_publication FROM trading.qt_desk_finalizations f "
        "LEFT JOIN trading.qt_desk_market_sources m ON m.source_id=f.market_source_id "
        "LEFT JOIN trading.qt_model_seed_publications p ON p.publication_id=m.model_publication_id "
        "WHERE f.decision_id=%s", (str(decision_id),))
    successor=cursor.fetchone()
    return dict(successor) if successor is not None else None


def _load_upstream_context(cursor, evidence):
    source=evidence['input_row']['payload']
    cursor.execute("SELECT to_jsonb(m) AS market_row,to_jsonb(p) AS model_publication "
        "FROM trading.qt_desk_market_sources m LEFT JOIN trading.qt_model_seed_publications p "
        "ON p.publication_id=m.model_publication_id WHERE m.source_id::text=%s", (source.get('market_source_id'),))
    market=cursor.fetchone()
    evidence['input_market']=dict(market) if market is not None else None
    # One immediate immutable predecessor: never recursively walk arbitrary
    # historical ledgers in an API request. Its transition proves its output.
    cursor.execute("SELECT r.*,to_jsonb(i) AS input_row,to_jsonb(f) AS finalization_row "
        "FROM trading.qt_desk_finalizations t JOIN trading.desk_run_results r ON r.decision_id=t.decision_id "
        "JOIN trading.qt_desk_accounting_inputs i ON i.input_id=r.input_id AND i.decision_id=r.decision_id "
        "LEFT JOIN trading.qt_desk_finalization_sources f ON f.source_id=i.payload->>'prior_finalization_source_id' "
        "WHERE t.finalization_id::text=%s", (evidence['finalization_row']['payload'].get('finalization_id'),))
    prior=cursor.fetchone()
    evidence['prior_accounting']=dict(prior) if prior is not None else None
    if prior is not None:
        evidence['prior_accounting']['successor']=_load_successor(cursor,prior['decision_id'])
        _load_processing_context(cursor, evidence['prior_accounting'])
        if prior['input_row']['payload'].get('schema_version') == 'qt-futures-accounting-input-first-day/v1':
            from algolens.infrastructure.portfolio.qt_first_day_proof import load_first_day_context
            load_first_day_context(cursor, evidence['prior_accounting'])


def _load_processing_context(cursor, accounting):
    cursor.execute("SELECT to_jsonb(d) AS decision,to_jsonb(p) AS preview,"
            "to_jsonb(r) AS receipt,to_jsonb(o) AS observation,to_jsonb(s) AS result,"
            "to_jsonb(m) AS model_publication FROM trading.qt_decisions d "
            "LEFT JOIN trading.qt_previews p ON p.preview_id=d.preview_id "
            "LEFT JOIN trading.qt_desk_receipts r ON r.decision_id=d.decision_id "
            "LEFT JOIN trading.qt_execution_observations o ON o.decision_id=d.decision_id AND o.observation_id=%s "
            "LEFT JOIN trading.qt_desk_results s ON s.decision_id=d.decision_id "
            "AND s.observation_id=o.observation_id AND s.attempt_id=r.attempt_id "
            "LEFT JOIN trading.qt_model_seed_publications m ON m.publication_id=d.model_publication_id "
            "WHERE d.decision_id=%s", (str(accounting['input_id']),str(accounting['decision_id'])))
    original=cursor.fetchone()
    accounting['processing_context']=dict(original) if original is not None else None


def load_accounting_evidence(cursor, decision, observation_id, *, current=False):
    cursor.execute("SELECT to_regclass('trading.desk_run_results') IS NOT NULL "
                   "AND to_regclass('trading.qt_desk_accounting_inputs') IS NOT NULL "
                   "AND to_regclass('trading.qt_desk_finalization_sources') IS NOT NULL AS ready")
    if not cursor.fetchone()['ready']:
        return None
    cursor.execute("SELECT r.*,to_jsonb(i) AS input_row,to_jsonb(f) AS finalization_row "
        "FROM trading.desk_run_results r JOIN trading.qt_desk_accounting_inputs i ON i.input_id=r.input_id "
        "LEFT JOIN trading.qt_desk_finalization_sources f ON f.source_id=i.payload->>'prior_finalization_source_id' "
        "WHERE r.decision_id=%s AND i.decision_id=r.decision_id AND r.input_id=%s AND r.portfolio_id=%s",
        (str(decision['decision_id']),observation_id,decision['book_id']))
    raw=cursor.fetchone()
    if raw is None:return None
    evidence=dict(raw)
    if evidence['input_row']['payload'].get('schema_version') == 'qt-futures-accounting-input-first-day/v1':
        from algolens.infrastructure.portfolio.qt_first_day_proof import load_first_day_context
        load_first_day_context(cursor, evidence)
        _load_processing_context(cursor, evidence)
    cursor.execute("SELECT to_regclass('trading.qt_desk_finalizations') IS NOT NULL "
                   "AND to_regclass('trading.qt_desk_market_sources') IS NOT NULL AS ready")
    if cursor.fetchone()['ready']:
        evidence['successor']=_load_successor(cursor,decision['decision_id'])
        if evidence['input_row']['payload'].get('schema_version')=='qt-futures-accounting-input/v2':
            _load_upstream_context(cursor,evidence)
    if _uses_equity_accounting(evidence):
        from algolens.infrastructure.portfolio.qt_equity_accounting_proof import load_equity_accounting_context
        return load_equity_accounting_context(cursor, decision, evidence, current=current)
    if current:
        engines=[row['strategy_id'] for row in evidence['payload']['live_results']]
        args=(decision['book_id'],decision['source_day'],engines)
        tables={}
        for name,date_column in (('executions','date'),('live_results','date'),('equity_curve','timestamp')):
            bound_args = ((args[0],str(decision['source_day'])+'T00:00:00Z',args[2])
                          if name=='equity_curve' else args)
            day_expression=date_column
            if name=='live_results':
                # Existing installations use either DATE or TIMESTAMPTZ.
                # A daily timestamp is a UTC label, regardless of session TZ.
                day_expression=("(CASE WHEN pg_typeof(date)='date'::regtype THEN date::text "
                    "ELSE to_char(date::timestamptz AT TIME ZONE 'UTC','YYYY-MM-DD') END)")
                bound_args=(args[0],str(decision['source_day']),args[2])
            cursor.execute('SELECT * FROM trading.'+name+' WHERE portfolio_id=%s AND '+day_expression+
                "=%s AND portfolio_type='qt' AND strategy_id=ANY(%s)",bound_args)
            tables[name]=[dict(row) for row in cursor.fetchall()]
        evidence['financial_rows']=tables
    return evidence


def current_accounting_after(evidence, original_after, *, recompute_client_factory=None,
                             finalization_recompute_client_factory=None):
    """Current positions may follow only a proven immutable finalization.

    Callers first validate the original publication, which remains the audit
    and report-quantity authority. A successor cannot rewrite that receipt.
    """
    accounting=evidence.get('accounting')
    if accounting is None:return original_after
    if _uses_equity_accounting(accounting):
        if accounting.get('successor') is None:return original_after
        from algolens.infrastructure.portfolio.qt_equity_finalization_proof import verified_qt_equity_finalization_successor
        successor=verified_qt_equity_finalization_successor(evidence,current=True,
            recompute_client_factory=recompute_client_factory,
            finalization_recompute_client_factory=finalization_recompute_client_factory)
        return {QtKey.from_wire(row['key']):row for row in successor['positions']}
    successor=verified_finalization_successor(accounting,evidence['decision'])
    if successor is None:return original_after
    return {QtKey.from_wire(row['key']): row for row in successor['positions']}


def _verify_current_financial_rows(row, require, exact):
    # Original executions never change; only a separately proven immutable
    # successor can supply the current PnL/equity expected from physical rows.
    successor = verified_finalization_successor(row, {'decision_id': row['decision_id'],
        'book_id': row['portfolio_id'], 'source_day': row['date']})
    if 'financial_rows' not in row:return
    output,actual=row['payload'],row['financial_rows']
    live_expected = successor['live_results'] if successor else output['live_results']
    executions={}
    for item in actual['executions']:
        identity=(item['strategy_id'],item['strategy_name'],item['symbol'],item['exec_id'])
        require(identity not in executions);executions[identity]=item
    require(len(executions)==len(output['executions']))
    for expected in output['executions']:
        key=expected['key'];identity=(key['strategy_id'],key['strategy_name'],key['symbol'],expected['exec_id'])
        require(identity in executions);item=executions[identity]
        require(item['portfolio_id']==key['portfolio_id'] and str(item['date'])==key['date'] and item['portfolio_type']=='qt')
        for name in ('exec_id','order_id','side'):require(item[name]==expected[name])
        for name in ('quantity','price','commissions_fees','implicit_price_impact','slippage_market_impact','total_transaction_costs'):
            require(item[name]==exact(expected[name+'_exact']))
        expected_time=datetime.fromisoformat(expected['execution_time'].replace('Z','+00:00'))
        require(item['execution_time']==expected_time and item['is_partial'] is False)
    results={item['strategy_id']:item for item in actual['live_results']}
    equity={item['strategy_id']:item for item in actual['equity_curve']}
    require(len(results)==len(actual['live_results'])==len(live_expected)==len(equity)==len(actual['equity_curve']))
    for expected in live_expected:
        engine=expected['strategy_id'];require(engine in results and engine in equity)
        item=results[engine]
        # The physical daily row is either a SQL DATE or exactly UTC midnight.
        # Selecting the UTC day alone does not prove the stored timestamp.
        if isinstance(item['date'], datetime):
            require(item['date'].tzinfo is not None and item['date'].utcoffset() is not None)
            require(item['date'] == datetime.fromisoformat(expected['date'] + 'T00:00:00+00:00'))
        else:
            require(str(item['date']) == expected['date'])
        for name in ('daily_pnl','daily_transaction_costs','total_pnl','current_portfolio_value'):
            require(item[name]==exact(expected[name+'_exact']))
        first_day = row['input_row']['payload']['schema_version'] == 'qt-futures-accounting-input-first-day/v1'
        for name in ('daily_realized_pnl','daily_unrealized_pnl'):
            require(item[name] == (exact(expected[name+'_exact']) if successor or first_day else 0))
        if first_day:
            require(item['total_transaction_costs'] == exact(expected['total_transaction_costs_exact']))
        require(equity[engine]['equity']==exact(expected['current_portfolio_value_exact']))


def producer_prior_carries(evidence, *, recompute_client_factory=None, finalization_recompute_client_factory=None):
    row=evidence.get('accounting')
    if row is None:
        return {}
    if _uses_equity_accounting(row):
        from algolens.infrastructure.portfolio.qt_equity_accounting_proof import producer_equity_prior_carries
        return producer_equity_prior_carries(evidence, recompute_client_factory=recompute_client_factory,
            finalization_recompute_client_factory=finalization_recompute_client_factory)
    def require(ok):
        if not ok:raise ValueError('unproven_accounting')
    def digest(value):return sha256(canonical_qt_input_bytes(value)).hexdigest()
    def exact(value):
        require(type(value) is str and parse_fixed_decimal8(value) is not None)
        return Decimal(value)
    d,o,r=(evidence[name] for name in ('decision','observation','receipt'))
    inputs,final,output=row['input_row'],row['finalization_row'],row['payload']
    require(str(row['decision_id'])==str(inputs['decision_id'])==str(d['decision_id']))
    require(str(row['input_id'])==str(inputs['input_id'])==str(o['observation_id']))
    require(row['portfolio_id']==d['book_id'] and str(row['date'])==str(d['source_day']))
    require(row['content_digest']==digest(output) and output['schema_version']=='qt-futures-accounting/v1')
    require(inputs['content_digest']==digest(inputs['payload'])==output['input_digest'])
    first_day = inputs['payload']['schema_version'] == 'qt-futures-accounting-input-first-day/v1'
    if not first_day:
        require(final['content_digest']==digest(final['payload']))
    require(output['observation']==o['payload'])
    require(o['payload']['schema_version']=='qt-execution/v2' and
            o['payload']['accounting_input_id']==str(inputs['input_id']))
    for field in ('producer_id','policy_version'):
        require(inputs[field]==o[field] and (first_day or inputs[field]==final[field]))
    require(type(inputs.get('source_version')) is str and bool(inputs['source_version'])
            and inputs['source_version']==o.get('source_version'))
    source=inputs['payload']
    if first_day:
        from algolens.infrastructure.portfolio.qt_first_day_proof import verify_first_day_input
        verify_first_day_input(row, d, evidence['preview']['payload']['selection_rows'])
    elif source['schema_version']=='qt-futures-accounting-input/v2':
        verify_upstream_accounting_input(row,d,evidence['preview']['payload']['selection_rows'])
    else:
        require(source['schema_version']=='qt-futures-accounting-input/v1' and final['payload']['schema_version']=='qt-finalized-accounting/v1')
    for field in ('decision_id','book_id','source_day'):require(source[field]==str(d[field]))
    if not first_day:
        anchor=final['payload']
        require(source['prior_finalization_source_id']==final['source_id'])
        require(final['book_id']==anchor['book_id']==d['book_id'])
        require(str(final['source_day'])==anchor['source_day']==source['previous_day']<source['source_day'])
        require(source['previous_totals']==anchor['previous_totals'])
    _verify_current_financial_rows(row,require,exact)
    def timestamp(value):
        return value if isinstance(value,datetime) else datetime.fromisoformat(value.replace('Z','+00:00'))
    for field in ('as_of','valid_until'):
        require(timestamp(inputs[field])==timestamp(o[field]))
    require(timestamp(inputs['as_of'])<=timestamp(r['processed_at'])<=timestamp(inputs['valid_until']))
    previous={}
    for item in source['previous_positions']:
        key=QtKey.from_wire(item['key'])
        require(key.portfolio_id==d['book_id'] and key.date==source['opening_day' if first_day else 'previous_day'] and key.portfolio_type=='qt')
        normalized=QtKey.from_wire({**item['key'],'date':source['source_day']})
        require(normalized not in previous)
        exact(item['quantity_exact']);exact(item['average_price_exact']);previous[normalized]=item
    selected={QtKey.from_wire({**item['key'],'portfolio_type':'qt'}):item for item in evidence['preview']['payload']['selection_rows']}
    require(len(selected)==len(evidence['preview']['payload']['selection_rows']))
    carries={}
    for fill in output['observation']['fills']:
        key=QtKey.from_wire(fill['key']);require(key in selected and selected[key]['asset_type']=='FUTURE')
        if fill['observation_kind']!='carried':continue
        require(key in previous and key not in carries and fill['execution_id'] is None and exact(fill['actual_cash_cost_exact'])==0)
        require(fill['selected_quantity_exact']==previous[key]['quantity_exact']==selected[key]['quantity_exact'])
        require(fill['average_price_exact']==selected[key]['average_price_exact']==previous[key]['average_price_exact'])
        require(not any(item['key']==fill['key'] for item in output['executions']))
        carries[key]=fill
    return carries
