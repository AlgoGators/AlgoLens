"""Publication4/5 readers; native identities are compared, never re-hashed here."""
from datetime import date
import math
import re
from algolens.application.runtime_control import validate_snapshot, RuntimeControlError
from . import configuration_inspection as legacy
from .consumption_inspection import validate_consumption_v2
from .qt_equity_run_consumption import validate_equity_run_consumption, validate_equity_strategy_invocation
from .qt_equity_portfolio_consumption import validate_equity_portfolio_invocation

need=legacy._require
keys=legacy._keys
RISK={'var_limit','jump_risk_limit','max_correlation','max_gross_leverage','max_net_leverage','confidence_level','lookback_period'}
TREND={'weight','risk_target','idm','max_symbol_concentration','use_position_buffering','carver_buffer_floor','carver_buffer_position_factor','ema_windows','vol_lookback_short','vol_lookback_long'}
MR={'lookback_period','entry_threshold','exit_threshold','risk_target','position_size','vol_lookback','stop_loss_pct','allow_fractional_shares','fractional_min_price','fractional_min_adv'}
DIGEST=re.compile(r'[0-9a-f]{64}\Z')


def escape(key):
    return str(key).replace('~','~0').replace('/','~1')


def editable_paths(snapshot):
    """Versioned inspection catalog mirrors native policy, without authorizing edits."""
    result=set()
    def leaves(node,root,names):
        result.update(root+escape(key) for key in names if key in node)
    selected={k:v for k,v in snapshot['strategies'].items() if v.get('enabled_live') is True}
    trend=any(v.get('type','TrendFollowingStrategy') in legacy.TYPES for v in selected.values())
    leaves(snapshot,'/',{'covariance_history_prices'})
    if trend:
        leaves(snapshot,'/',{'use_optimization'})
        leaves(snapshot['optimization'],'/optimization/',{'tau','cost_penalty_scalar','max_iterations','convergence_threshold','use_buffering','buffer_size_factor'})
    leaves(snapshot['execution'],'/execution/',{'position_limit_live'})
    for key in ('carver_buffer_floor','carver_buffer_position_factor'):
        if any(v.get('type','TrendFollowingStrategy') in legacy.TYPES and type(v.get('config')) is dict and key not in v['config'] for v in selected.values()):
            leaves(snapshot['strategy_defaults'],'/strategy_defaults/',{key})
    risk=snapshot['risk']
    leaves(risk,'/risk/',{'max_drawdown','max_leverage'})
    leaves(risk['risk_reporting'],'/risk/risk_reporting/',RISK)
    def modules(rows,root):
        need(type(rows) is list)
        for i,row in enumerate(rows):
            need(type(row) is dict and row.get('type') in ('carver','none','constant_scale','warn','refuse'))
            leaves(row,root+str(i)+'/',RISK|{'min_gate_dates'} if row['type']=='carver' else {'scale'} if row['type']=='constant_scale' else set())
    modules(risk['modules'],'/risk/modules/')
    for owner,rows in snapshot['sleeve_risk_modules'].items():
        if owner in selected:modules(rows,'/sleeve_risk_modules/'+escape(owner)+'/')
    for owner,row in selected.items():
        if 'config' in row:
            leaves(row['config'],'/strategies/'+escape(owner)+'/config/',MR if row.get('type')=='MeanReversionStrategy' else TREND)
    return result


def leaf_inventory(snapshot):
    result={}
    def visit(value,path):
        module_array=path=='/risk/modules' or path.startswith('/sleeve_risk_modules/')
        if value and (type(value) is dict or (type(value) is list and module_array)):
            for key,child in (value.items() if type(value) is dict else enumerate(value)):
                visit(child,path+'/'+escape(key))
        else:result[path]=value
    visit(snapshot,'')
    return result


def descriptors(path,editable,equity):
    unsupported=path in {'/execution/commission_rate','/execution/slippage_bps','/execution/position_limit_backtest','/optimization/asymmetric_risk_buffer','/strategy_defaults/fdm'} or (equity and path.startswith('/optimization/')) or path.startswith('/backtest/')
    consumer='configuration_identity_or_control'
    if path in editable:
        consumer=('selected_mean_reversion_strategy' if equity else 'selected_trend_strategy') if path.startswith('/strategies/') else 'reporting_risk_manager' if path.startswith('/risk/risk_reporting/') else 'assigned_risk_module' if path.startswith(('/risk/modules/','/sleeve_risk_modules/')) else 'portfolio_optimizer_when_enabled' if path.startswith('/optimization/') or path=='/use_optimization' else 'portfolio_covariance_history' if path=='/covariance_history_prices' else 'selected_trend_factory_fallback' if path.startswith('/strategy_defaults/') else 'base_strategy_risk_or_position_check'
    if unsupported:consumer='no_active_profile_reader'
    return ('editable_config_input' if path in editable else 'unsupported_in_profile' if unsupported else 'protected_config_input',consumer)


def validate_supplied(value,identity,selection,equity):
    keys(value,{'projection_version','profile','coverage','authority','consumption_evidence','effective_snapshot','fields'})
    need(type(value['projection_version']) is int and value['projection_version']==2 and value['coverage']=='complete_runtime_snapshot_v2' and value['authority']=='inspection_only' and value['consumption_evidence']=='not_collected')
    need(value['profile']==('live_equity' if equity else 'live_portfolio_runner_futures'))
    snapshot=value['effective_snapshot']
    try:validate_snapshot(snapshot,identity['portfolio_id'],identity['engine_strategy_id'],governed=selection['source']=='approved_override',inspection_file_source=selection['source']=='file')
    except RuntimeControlError:raise legacy.PublicationError() from None
    need(type(snapshot['snapshot_version']) is int and snapshot['snapshot_version']==2)
    need(snapshot['max_drawdown']==snapshot['risk']['max_drawdown'] and snapshot['max_leverage']==snapshot['risk']['max_leverage'])
    inventory=leaf_inventory(snapshot);editable=editable_paths(snapshot)
    fields=value['fields'];need(type(fields) is list and len(fields)==len(inventory))
    need([row['path'] for row in fields]==sorted(inventory))
    for row in fields:
        keys(row,{'path','classification','consumer','consumption_evidence','value_type','value'})
        path=row['path'];actual=inventory[path]
        kind='null' if actual is None else 'boolean' if type(actual) is bool else 'number' if type(actual) in (int,float) else 'object' if type(actual) is dict else 'array' if type(actual) is list else 'string'
        need(row['value_type']==kind and type(row['value']) is type(actual) and row['value']==actual)
        need((row['classification'],row['consumer'])==descriptors(path,editable,equity) and row['consumption_evidence']=='not_collected')
    return snapshot


def validate_multi(value,identity,snapshot,selection,owners):
    keys(value,{'schema_version','profile','scope','full_run_certification','run_key','effective_sha256','source_to_storage_owners','coverage','portfolio_invocation','strategy_invocations'})
    need(value['schema_version']=='live-equity-multi-consumption/v1' and value['profile']=='live_equity_multi_sleeve' and value['scope']=='primary_invocation' and value['full_run_certification'] is False)
    need(value['run_key']=={'portfolio_id':identity['portfolio_id'],'strategy_id':identity['engine_strategy_id'],'date':identity['run_date']} and value['effective_sha256']==selection['effective_sha256'] and value['source_to_storage_owners']==owners)
    coverage=value['coverage'];keys(coverage,{'primary','legacy_run_stages','account_execution_costs'})
    need(coverage['legacy_run_stages']=='not_collected' and coverage['account_execution_costs']=='not_collected')
    if coverage['primary']=='skipped_non_trading_day':
        need(value['portfolio_invocation'] is None and value['strategy_invocations']=={});return
    need(coverage['primary']=='observed')
    portfolio=validate_equity_portfolio_invocation(value['portfolio_invocation'],expected_owners=set(owners.values()))
    need(portfolio['available'] is True)
    keys(value['strategy_invocations'],set(owners.values()))
    for observation in value['strategy_invocations'].values():
        validate_equity_strategy_invocation(observation);need(observation['available'] is True)


def validate_publication(value,scope,now):
    version=value['publication_schema_version'];equity=version==5
    composite=equity and value['profile']=='live_equity_multi_sleeve'
    child='equity_multi_consumption' if composite else 'equity_run_consumption'
    root=(legacy.ROOT_KEYS-{'selected_trend','consumption'}|{child}) if equity else legacy.ROOT_KEYS
    keys(value,root|{'configuration_selection','source_to_storage_owners'})
    need(value['profile'] in (('live_equity_multi_sleeve','live_equity_mean_reversion') if equity else ('live_portfolio_runner_futures',)),'unsupported_publication')
    need(value['authority']=='inspection_only' and value['stream']=='system')
    identity=value['identity'];keys(identity,legacy.IDENTITY_KEYS|{'config_attempt_id'})
    for key in ('engine_strategy_id','portfolio_id'):
        need(type(identity[key]) is str and legacy.IDENTIFIER.fullmatch(identity[key]) is not None)
    need(type(identity['registry_id']) is str and (identity['registry_id']=='' or legacy.IDENTIFIER.fullmatch(identity['registry_id']) is not None))
    need(legacy._integer(identity['registry_revision']) and identity['registry_revision']>=0)
    day=date.fromisoformat(identity['run_date']);need(day.isoformat()==identity['run_date'] and day<=now.date())
    for key in ('capture_id','publication_id','config_attempt_id'):legacy._uuid(identity[key])
    need(identity['capture_id']==identity['publication_id']==identity['config_attempt_id'])
    need(identity['control_mode'] in ('controlled','uncontrolled'))
    need(identity['runtime_attempt_id']==identity['publication_id'] if identity['control_mode']=='controlled' else identity['runtime_attempt_id'] is None)
    need(type(identity['producer_version']) is str and legacy.BUILD_TOKEN.fullmatch(identity['producer_version']) is not None and identity['producer_version']!='unversioned')
    need(legacy._utc(value['captured_at'],now)<=legacy._utc(value['publication_recorded_at'],now) and day<=legacy._utc(value['publication_recorded_at'],now).date())
    need(all(identity[k]==scope[k] for k in ('registry_id','registry_revision','engine_strategy_id','portfolio_id','run_date')),'scope_changed')
    selection=value['configuration_selection'];keys(selection,{'source','version_id','base_sha256','effective_sha256'})
    need(selection['source'] in ('file','approved_override'))
    for key in ('base_sha256','effective_sha256'):need(type(selection[key]) is str and DIGEST.fullmatch(selection[key]) is not None)
    if selection['source']=='file':need(selection['version_id'] is None and selection['base_sha256']==selection['effective_sha256'])
    else:legacy._uuid(selection['version_id'])
    if identity['registry_id']=='':
        need(identity['registry_revision']==0 and identity['control_mode']=='uncontrolled' and selection['source']=='file')
    snapshot=validate_supplied(value['supplied'],identity,selection,equity)
    selected={k:v for k,v in snapshot['strategies'].items() if v.get('enabled_live') is True}
    owners={k:('EQUITY_MEAN_REVERSION' if equity and set(selected)=={'MEAN_REVERSION'} else k) for k in selected}
    need(value['source_to_storage_owners']==owners)
    if composite:
        need(set(selected)!={'MEAN_REVERSION'})
        validate_multi(value[child],identity,snapshot,selection,owners)
        need((value['status'],value['reason'])==('available','none'))
    elif equity:
        need(set(selected)=={'MEAN_REVERSION'})
        observed=validate_equity_run_consumption(value[child],expected_run_key={'portfolio_id':identity['portfolio_id'],'strategy_id':identity['engine_strategy_id'],'strategy_name':'EQUITY_MEAN_REVERSION','date':identity['run_date']})
        need((value['status'],value['reason'])==(('available','none') if observed['available'] else ('unavailable','consumption_unavailable')))
    else:
        validate_consumption_v2(value['consumption'])
        need((value['status'],value['reason'])==('available','none'))
        trend=value['selected_trend'];keys(trend,{'schema_version','provenance','slow_concentration_override','strategies'})
        need(type(trend['schema_version']) is int and trend['schema_version']==1 and trend['provenance']=='shared_resolver_same_inputs')
        override=trend['slow_concentration_override'];need(override=={'state':'absent'} or (type(override) is dict and set(override)=={'state','value'} and override['state']=='present' and type(override['value']) in (int,float) and math.isfinite(override['value'])))
        need(type(trend['strategies']) is list and {r['strategy_id'] for r in trend['strategies']}==set(selected) and len(trend['strategies'])==len(selected))
        for row in trend['strategies']:
            keys(row,{'strategy_id','strategy_type','selected_allocation','factory_resolved','constructor_normalized'})
            need(row['strategy_type']==selected[row['strategy_id']].get('type','TrendFollowingStrategy'))
            legacy._value(row['selected_allocation'],'number','')
            for name in ('factory_resolved','constructor_normalized'):
                stage=row[name];keys(stage,legacy.TREND_KEYS)
                for key,actual in stage.items():
                    kind='boolean' if key=='use_position_buffering' else 'integer_pairs' if key=='ema_windows' else 'integer_number_pairs' if key=='fdm' else 'unsigned64' if key=='max_history_size' else 'integer' if key in ('vol_lookback_short','vol_lookback_long') else 'number'
                    legacy._value(actual,kind,'')
    return value
