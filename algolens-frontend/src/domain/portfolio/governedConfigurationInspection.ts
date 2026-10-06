/** Versioned inspection only: compare native identities, never compute their hashes. */
import { validateConsumptionV2 } from './consumptionInspection';
import { validateEquityRunConsumption, validateEquityStrategyInvocation } from './equityRunConsumption';
import { validateEquityPortfolioConsumption } from './equityPortfolioConsumption';

type R=Record<string,unknown>;
export type SuppliedFieldV2={path:string;classification:string;consumer:string;consumption_evidence:'not_collected';value_type:string;value:unknown};
export type SuppliedV2={projection_version:2;fields:SuppliedFieldV2[];effective_snapshot:R};
export type ConfigurationSelection={source:'file'|'approved_override';version_id:string|null;base_sha256:string;effective_sha256:string};
export type MultiConsumption={coverage:{primary:'observed'|'skipped_non_trading_day';legacy_run_stages:'not_collected';account_execution_costs:'not_collected'};portfolio_invocation:unknown;strategy_invocations:Record<string,unknown>};
function need(ok:unknown):asserts ok {if(!ok)throw new Error('Invalid governed publication');}
function object(value:unknown):R {need(value!==null&&typeof value==='object'&&!Array.isArray(value));return value as R;}
function keys(value:unknown,names:string[]):R {const row=object(value);need(Object.keys(row).length===names.length&&names.every(k=>Object.hasOwn(row,k)));return row;}
const equal=(a:unknown,b:unknown):boolean=>{
  if(a===b)return true;
  if(Array.isArray(a)&&Array.isArray(b))return a.length===b.length&&a.every((v,i)=>equal(v,b[i]));
  if(a&&b&&typeof a==='object'&&typeof b==='object'&&!Array.isArray(a)&&!Array.isArray(b))return Object.keys(a).length===Object.keys(b).length&&Object.entries(a).every(([k,v])=>Object.hasOwn(b,k)&&equal(v,(b as R)[k]));
  return false;
};
const numeric=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v);
const escape=(v:string)=>v.replace(/~/g,'~0').replace(/\//g,'~1');
const risk=['var_limit','jump_risk_limit','max_correlation','max_gross_leverage','max_net_leverage','confidence_level','lookback_period'];
const trend=['weight','risk_target','idm','max_symbol_concentration','use_position_buffering','carver_buffer_floor','carver_buffer_position_factor','ema_windows','vol_lookback_short','vol_lookback_long'];
const mr=['lookback_period','entry_threshold','exit_threshold','risk_target','position_size','vol_lookback','stop_loss_pct','allow_fractional_shares','fractional_min_price','fractional_min_adv'];
const trendTypes=['TrendFollowingStrategy','TrendFollowingFastStrategy','TrendFollowingSlowStrategy'];
function editable(snapshot:R,selected:Record<string,R>):Set<string>{
  const paths=new Set<string>();const leaves=(node:unknown,root:string,names:string[])=>{const row=object(node);for(const name of names)if(Object.hasOwn(row,name))paths.add(root+escape(name));};
  leaves(snapshot,'/',['covariance_history_prices']);
  if(Object.values(selected).some(v=>trendTypes.includes((v.type??'TrendFollowingStrategy') as string))){
    leaves(snapshot,'/',['use_optimization']);leaves(snapshot.optimization,'/optimization/',['tau','cost_penalty_scalar','max_iterations','convergence_threshold','use_buffering','buffer_size_factor']);
  }
  leaves(snapshot.execution,'/execution/',['position_limit_live']);
  for(const name of ['carver_buffer_floor','carver_buffer_position_factor'])if(Object.values(selected).some(v=>trendTypes.includes((v.type??'TrendFollowingStrategy') as string)&&v.config!==undefined&&!Object.hasOwn(object(v.config),name)))leaves(snapshot.strategy_defaults,'/strategy_defaults/',[name]);
  const r=object(snapshot.risk);leaves(r,'/risk/',['max_drawdown','max_leverage']);leaves(r.risk_reporting,'/risk/risk_reporting/',risk);
  const modules=(value:unknown,root:string)=>{need(Array.isArray(value));value.forEach((v,i)=>{const row=object(v);need(['carver','none','constant_scale','warn','refuse'].includes(row.type as string));leaves(row,root+i+'/',row.type==='carver'?[...risk,'min_gate_dates']:row.type==='constant_scale'?['scale']:[]);});};
  modules(r.modules,'/risk/modules/');for(const [owner,rows]of Object.entries(object(snapshot.sleeve_risk_modules)))if(Object.hasOwn(selected,owner))modules(rows,`/sleeve_risk_modules/${escape(owner)}/`);
  for(const [owner,row]of Object.entries(selected))if(row.config!==undefined)leaves(row.config,`/strategies/${escape(owner)}/config/`,row.type==='MeanReversionStrategy'?mr:trend);
  return paths;
}
function descriptors(path:string,paths:Set<string>,equity:boolean):string[]{
  const unsupported=['/execution/commission_rate','/execution/slippage_bps','/execution/position_limit_backtest','/optimization/asymmetric_risk_buffer','/strategy_defaults/fdm'].includes(path)||(equity&&path.startsWith('/optimization/'))||path.startsWith('/backtest/');
  let consumer='configuration_identity_or_control';
  if(paths.has(path))consumer=path.startsWith('/strategies/')?(equity?'selected_mean_reversion_strategy':'selected_trend_strategy'):path.startsWith('/risk/risk_reporting/')?'reporting_risk_manager':path.startsWith('/risk/modules/')||path.startsWith('/sleeve_risk_modules/')?'assigned_risk_module':path.startsWith('/optimization/')||path==='/use_optimization'?'portfolio_optimizer_when_enabled':path==='/covariance_history_prices'?'portfolio_covariance_history':path.startsWith('/strategy_defaults/')?'selected_trend_factory_fallback':'base_strategy_risk_or_position_check';
  if(unsupported)consumer='no_active_profile_reader';return [paths.has(path)?'editable_config_input':unsupported?'unsupported_in_profile':'protected_config_input',consumer];
}
function supplied(raw:unknown,identity:R,selection:R,equity:boolean,nonIntegers:ReadonlySet<string>):{snapshot:R;selected:Record<string,R>}{
  const value=keys(raw,['projection_version','profile','coverage','authority','consumption_evidence','effective_snapshot','fields']);
  need(value.projection_version===2&&!nonIntegers.has('/publication/supplied/projection_version')&&value.profile===(equity?'live_equity':'live_portfolio_runner_futures')&&value.coverage==='complete_runtime_snapshot_v2'&&value.authority==='inspection_only'&&value.consumption_evidence==='not_collected');
  const s=keys(value.effective_snapshot,['snapshot_version','portfolio_id','initial_capital','reserve_capital_pct','benchmark_mode','execution','optimization','risk','max_drawdown','max_leverage','backtest','live','strategy_defaults','strategies','use_optimization','covariance_history_prices','sleeve_risk_modules']);
  need(s.snapshot_version===2&&!nonIntegers.has('/publication/supplied/effective_snapshot/snapshot_version')&&s.portfolio_id===identity.portfolio_id&&typeof s.use_optimization==='boolean');
  need(numeric(s.covariance_history_prices)&&Number.isSafeInteger(s.covariance_history_prices)&&s.covariance_history_prices>=2&&!nonIntegers.has('/publication/supplied/effective_snapshot/covariance_history_prices'));
  need(numeric(s.initial_capital)&&s.initial_capital>0&&numeric(s.reserve_capital_pct)&&s.reserve_capital_pct>=0&&s.reserve_capital_pct<1&&numeric(s.max_drawdown)&&s.max_drawdown>=0&&s.max_drawdown<=1&&numeric(s.max_leverage)&&s.max_leverage>0&&['live','deferred'].includes(s.benchmark_mode as string));
  const r=object(s.risk);need(r.schema===2&&r.max_drawdown===s.max_drawdown&&r.max_leverage===s.max_leverage);
  const selected:Record<string,R>={};let sum=0;
  for(const [owner,v]of Object.entries(object(s.strategies))){const row=object(v);need(row.enabled_live===undefined||typeof row.enabled_live==='boolean');if(row.enabled_live===true){need(/^[A-Za-z0-9_-]{1,128}$/.test(owner)&&numeric(row.default_allocation)&&row.default_allocation>0);need(equity?row.type==='MeanReversionStrategy':trendTypes.includes((row.type??'TrendFollowingStrategy') as string));selected[owner]=row;sum+=row.default_allocation;}}
  need(Object.keys(selected).length>0&&Number.isFinite(sum));if(selection.source==='approved_override')need(Math.abs(sum-1)<=1e-9);
  need((equity?'LIVE_EQUITY_':'LIVE_')+Object.keys(selected).sort().join('_')===identity.engine_strategy_id);
  const inventory=new Map<string,unknown>();
  const visit=(v:unknown,path:string)=>{if(v!==null&&typeof v==='object'&&Object.keys(v).length>0&&(!Array.isArray(v)||path==='/risk/modules'||path.startsWith('/sleeve_risk_modules/'))){for(const [key,child]of Object.entries(v)){need(!/password|secret|token|credential/i.test(key)&&!/^smtp/i.test(key));visit(child,path+'/'+escape(key));}}else inventory.set(path,v);};visit(s,'');
  const paths=editable(s,selected);need(Array.isArray(value.fields)&&value.fields.length===inventory.size);
  const ordered=[...inventory.keys()].sort();value.fields.forEach((v,i)=>{const row=keys(v,['path','classification','consumer','consumption_evidence','value_type','value']);need(row.path===ordered[i]);const path=ordered[i],actual=inventory.get(path);const kind=actual===null?'null':Array.isArray(actual)?'array':typeof actual;need(row.value_type===kind&&equal(row.value,actual)&&equal([row.classification,row.consumer],descriptors(path,paths,equity))&&row.consumption_evidence==='not_collected');});
  return {snapshot:s,selected};
}
export function validateGovernedPublication(pub:R,nonIntegers:ReadonlySet<string>,validateStage:(raw:unknown,tokens:Set<string>,path:string)=>void):void{
  const identity=object(pub.identity),selection=keys(pub.configuration_selection,['source','version_id','base_sha256','effective_sha256']);
  need(identity.config_attempt_id===identity.publication_id&&identity.producer_version!=='unversioned');
  need(['file','approved_override'].includes(selection.source as string));for(const k of ['base_sha256','effective_sha256'])need(typeof selection[k]==='string'&&/^[0-9a-f]{64}$/.test(selection[k] as string));
  if(selection.source==='file')need(selection.version_id===null&&selection.base_sha256===selection.effective_sha256);else need(typeof selection.version_id==='string'&&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(selection.version_id));
  if(identity.registry_id==='')need(identity.registry_revision===0&&identity.control_mode==='uncontrolled'&&selection.source==='file');
  const equity=pub.publication_schema_version===5,{selected}=supplied(pub.supplied,identity,selection,equity,nonIntegers);
  const names=Object.keys(selected);const legacyMR=equity&&names.length===1&&names[0]==='MEAN_REVERSION';const owners=Object.fromEntries(names.map(n=>[n,legacyMR?'EQUITY_MEAN_REVERSION':n]));need(equal(pub.source_to_storage_owners,owners));
  if(equity&&pub.profile==='live_equity_multi_sleeve'){
    need(!legacyMR);const c=keys(pub.equity_multi_consumption,['schema_version','profile','scope','full_run_certification','run_key','effective_sha256','source_to_storage_owners','coverage','portfolio_invocation','strategy_invocations']);
    need(c.schema_version==='live-equity-multi-consumption/v1'&&c.profile===pub.profile&&c.scope==='primary_invocation'&&c.full_run_certification===false&&c.effective_sha256===selection.effective_sha256&&equal(c.source_to_storage_owners,owners)&&equal(c.run_key,{portfolio_id:identity.portfolio_id,strategy_id:identity.engine_strategy_id,date:identity.run_date}));
    const coverage=keys(c.coverage,['primary','legacy_run_stages','account_execution_costs']);need(coverage.legacy_run_stages==='not_collected'&&coverage.account_execution_costs==='not_collected');
    if(coverage.primary==='skipped_non_trading_day')need(c.portfolio_invocation===null&&equal(c.strategy_invocations,{}));else{
      need(coverage.primary==='observed');validateEquityPortfolioConsumption(c.portfolio_invocation,nonIntegers,'/publication/equity_multi_consumption/portfolio_invocation',new Set(Object.values(owners)));need(c.portfolio_invocation.available===true);
      const observations=keys(c.strategy_invocations,Object.values(owners));for(const [owner,row]of Object.entries(observations)){validateEquityStrategyInvocation(row,{nonIntegers,pointer:`/publication/equity_multi_consumption/strategy_invocations/${escape(owner)}`});need(object(row).available===true);}
    }
    need(pub.status==='available'&&pub.reason==='none');
  }else if(equity){need(legacyMR);validateEquityRunConsumption(pub.equity_run_consumption,{portfolio_id:identity.portfolio_id as string,strategy_id:identity.engine_strategy_id as string,strategy_name:'EQUITY_MEAN_REVERSION',date:identity.run_date as string},nonIntegers);need(pub.status===(pub.equity_run_consumption.available?'available':'unavailable')&&pub.reason===(pub.equity_run_consumption.available?'none':'consumption_unavailable'));
  }else{
    validateConsumptionV2(pub.consumption);need(pub.status==='available'&&pub.reason==='none');const t=keys(pub.selected_trend,['schema_version','provenance','slow_concentration_override','strategies']);need(t.schema_version===1&&!nonIntegers.has('/publication/selected_trend/schema_version')&&t.provenance==='shared_resolver_same_inputs');const override=object(t.slow_concentration_override);if(override.state==='absent')keys(override,['state']);else{keys(override,['state','value']);need(override.state==='present'&&numeric(override.value));}
    need(Array.isArray(t.strategies)&&t.strategies.length===names.length);const seen=new Set();t.strategies.forEach((v,i)=>{const row=keys(v,['strategy_id','strategy_type','selected_allocation','factory_resolved','constructor_normalized']);need(typeof row.strategy_id==='string'&&Object.hasOwn(selected,row.strategy_id)&&!seen.has(row.strategy_id));seen.add(row.strategy_id);need(row.strategy_type===(selected[row.strategy_id].type??'TrendFollowingStrategy')&&numeric(row.selected_allocation));for(const key of ['factory_resolved','constructor_normalized'])validateStage(row[key],new Set(nonIntegers),`/publication/selected_trend/strategies/${i}/${key}`);});
  }
}
