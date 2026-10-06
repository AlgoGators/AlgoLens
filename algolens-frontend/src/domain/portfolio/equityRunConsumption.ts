/** Equity run evidence is separate from futures v2 and from report readiness. */
import contract from './equityRunConsumptionCatalog.json';
import actionContract from './equityRunConsumptionActionCatalog.json';
import { parseFixedDecimal8 } from '../numbers/fixedDecimal8';
import { validateEquityPortfolioConsumption, type EquityPortfolioConsumption } from './equityPortfolioConsumption';
export type EquityRunKey = {
  portfolio_id: string; strategy_id: string; strategy_name: string; date: string;
};
export type EquityRunStage = {
  outcome: 'not_reached' | 'returned_ok' | 'returned_error' | 'threw' | 'skipped';
  skip_reason: string | null;
  reads: Record<string, unknown>;
  symbols: Record<string, Record<string, unknown>>;
  executions: Array<{
    symbol: string; portfolio_id: string; strategy_id: string; strategy_name: string;
    index: number; execution_id: string; reads: Record<string, unknown>;
  }>;
};
export type EquityRunConsumption = {
  schema_version: 'qt-equity-run-consumption/v1' | 'qt-equity-run-consumption/v2';
  catalog_version: 'qt-equity-main08b15c-run/v1' | 'qt-equity-main08b15c-run/v2';
  scope: 'full_run'; profile: 'mean_reversion'; run_key: EquityRunKey;
  available: boolean; complete: boolean; unavailable_reason: string | null;
  stages: Record<string, EquityRunStage>;
};
export class EquityRunProtocolError extends Error {
  constructor() { super('Equity setting observations could not be verified.'); }
}
type ObjectValue = Record<string, unknown>;
type Spec = { type?: string; const?: unknown; enum?: unknown[]; format?: string; pattern?: string;
  minimum?: number; maximum?: number; minLength?: number; maxLength?: number; ref?: string };
type StageSpec = { required: string[]; reads?: Record<string, Spec>;
  per_symbol_reads?: Record<string, Spec>; per_execution_reads?: Record<string, Spec> };

const symbolPattern = /^[A-Za-z0-9_.\/-]{1,64}$/;
const identityPattern = /^[A-Za-z0-9_-]{1,100}$/;
type Lexical = { nonIntegers: ReadonlySet<string>; pointer: string };
const at = (context: Lexical | undefined, key: string): Lexical | undefined => context && ({
  nonIntegers: context.nonIntegers,
  pointer: `${context.pointer}/${key.replaceAll('~', '~0').replaceAll('/', '~1')}`,
});
const has = (row: ObjectValue, name: string) => Object.hasOwn(row, name);
function need(ok: unknown): asserts ok { if (!ok) throw new EquityRunProtocolError(); }
function object(value: unknown): asserts value is ObjectValue {
  need(value !== null && typeof value === 'object' && !Array.isArray(value) &&
    [Object.prototype, null].includes(Object.getPrototypeOf(value)));
  need(Reflect.ownKeys(value).every(key => typeof key === 'string'));
}
function closed(value: unknown, allowed: readonly string[], required: readonly string[] = allowed): asserts value is ObjectValue {
  object(value); need(Object.keys(value).every(key => allowed.includes(key)) && required.every(key => has(value, key)));
}
function date(value: unknown): asserts value is string {
  need(typeof value === 'string' && /^\d{4}-\d\d-\d\d$/.test(value));
  const [year, month, day] = value.split('-').map(Number);
  need(year >= 1 && year <= 9999 && month >= 1 && month <= 12 && day >= 1);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  need(day <= [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]);
}
function typed(value: unknown, spec: Spec, context?: Lexical): void {
  if (has(spec as ObjectValue, 'const')) { need(value === spec.const); return; }
  if (spec.enum) { need(spec.enum.includes(value)); return; }
  if (spec.ref) {
    if (spec.ref === 'qt-equity-portfolio-consumption/v1') validateEquityPortfolioConsumption(value, context?.nonIntegers, context?.pointer);
    else { need(spec.ref === 'qt-equity-strategy-consumption/v1'); strategy(value, context); }
    return;
  }
  if (spec.type === 'number') { need(typeof value === 'number' && Number.isFinite(value)); return; }
  if (spec.type === 'integer') {
    need(typeof value === 'number' && Number.isSafeInteger(value) && value >= spec.minimum! && value <= spec.maximum! &&
      (!context || !context.nonIntegers.has(context.pointer))); return;
  }
  if (spec.type === 'boolean') { need(typeof value === 'boolean'); return; }
  need(spec.type === 'string' && typeof value === 'string' && value.length <= (spec.maxLength ?? 256));
  need(value.length >= (spec.minLength ?? 0));
  if (spec.pattern) need(new RegExp(spec.pattern).test(value));
  if (spec.format === 'date') date(value);
  else if (spec.format === 'canonical-uuid') need(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value) && value !== '00000000-0000-0000-0000-000000000000');
  else if (spec.format === 'canonical-decimal8-checked-int64') { try { parseFixedDecimal8(value); } catch { need(false); } }
  else need(spec.format === undefined);
}
function reads(value: unknown, specs: Record<string, Spec>, required: readonly string[] = [], context?: Lexical): asserts value is ObjectValue {
  closed(value, Object.keys(specs), required);
  for (const [key, item] of Object.entries(value)) typed(item, specs[key], at(context, key));
}
function readSet(values: ObjectValue, condition: { required?: readonly string[]; forbidden?: readonly string[] }): void {
  need((condition.required ?? []).every(key => has(values, key)) && (condition.forbidden ?? []).every(key => !has(values, key)));
}
function executionConditions(values: ObjectValue): void {
  const conditions = contract.execution_cost_conditions;
  need((values.reference_price as number) > 0 && values.quantity !== 0);
  if ((values.commission_per_unit as number) >= 0) {
    readSet(values, conditions.commission_nonnegative);
    readSet(values, (values.max_commission_pct as number) >= 0
      ? conditions.commission_nonnegative.percentage_ceiling : conditions.commission_nonnegative.order_ceiling);
  } else readSet(values, conditions.commission_fallback);
  readSet(values, values.apply_regulatory_fees === true && (values.quantity as number) < 0
    ? conditions.regulatory_sell : conditions.regulatory_unreached);
  if (values.volatility_calculation_reached === true) readSet(values, conditions.volatility_calculated);
  else {
    readSet(values, conditions.volatility_neutral);
    for (const [name, expected] of Object.entries(conditions.volatility_neutral.equal)) need(values[name] === expected);
  }
}
function costHistoryConditions(values: ObjectValue): void {
  const conditions = contract.cost_history_conditions;
  if (values.previous_close_source === 'no_previous_close') {
    readSet(values, conditions.no_previous_close);
    need(values.previous_close_forwarded === conditions.no_previous_close.equal.previous_close_forwarded);
  } else {
    readSet(values, conditions.stored_previous_close); need((values.previous_close_forwarded as number) > 0);
  }
}
function strategy(value: unknown, context?: Lexical): void {
  closed(value, ['schema_version', 'available', 'profile', 'scope', 'full_run_certification', 'symbols']);
  need(value.schema_version === 'qt-equity-strategy-consumption/v1' && value.available === true &&
    value.profile === 'mean_reversion' && value.scope === 'strategy_invocation' && value.full_run_certification === false);
  object(value.symbols); need(Object.keys(value.symbols).length <= contract.symbol_limit);
  const readSpecs: Record<string, Spec> = {};
  for (const name of ['lookback_period', 'vol_lookback']) readSpecs[name] = { type: 'integer', minimum: -2147483648, maximum: 2147483647 };
  for (const name of ['maximum_price_history', 'maximum_volatility_history']) readSpecs[name] = { type: 'integer', minimum: 0, maximum: Number.MAX_SAFE_INTEGER };
  for (const name of ['entry_threshold', 'exit_threshold', 'stop_loss_pct', 'capital_allocation', 'position_size', 'risk_target', 'fractional_min_price', 'fractional_min_adv', 'position_limit']) readSpecs[name] = { type: 'number' };
  for (const name of ['use_stop_loss', 'allow_fractional_shares', 'position_limit_present']) readSpecs[name] = { type: 'boolean' };
  const stateSpecs: Record<string, Spec> = { volume_sample_count: { type: 'integer', minimum: 0, maximum: Number.MAX_SAFE_INTEGER },
    average_daily_volume: { type: 'number' }, fractional_eligible: { type: 'boolean' }, short_allowed: { type: 'boolean' } };
  for (const [symbol, row] of Object.entries(value.symbols)) {
    need(symbolPattern.test(symbol)); closed(row, ['reads', 'observed_state']);
    const symbolContext = at(at(context, 'symbols'), symbol);
    reads(row.reads, readSpecs, [], at(symbolContext, 'reads'));
    reads(row.observed_state, stateSpecs, [], at(symbolContext, 'observed_state'));
    const actual = row.reads, state = row.observed_state;
    need(has(actual, 'position_limit') === (actual.position_limit_present === true));
    need(actual.use_stop_loss !== false || !has(actual, 'stop_loss_pct'));
    need(actual.allow_fractional_shares !== false || !has(actual, 'fractional_min_price'));
    const adv = has(actual, 'fractional_min_adv');
    need(adv === has(state, 'volume_sample_count') && adv === has(state, 'average_daily_volume'));
  }
}
function sameKey(value: unknown, expected: EquityRunKey): asserts value is ObjectValue {
  closed(value, contract.run_key_fields);
  for (const name of contract.run_key_fields) need(value[name] === expected[name as keyof EquityRunKey]);
  need(typeof value.portfolio_id === 'string' && identityPattern.test(value.portfolio_id));
  need(value.strategy_id === 'LIVE_EQUITY_MEAN_REVERSION' && value.strategy_name === 'EQUITY_MEAN_REVERSION');
  date(value.date);
}
export function validateEquityRunConsumption(value: unknown, expected: EquityRunKey,
  nonIntegerTokens?: ReadonlySet<string>): asserts value is EquityRunConsumption {
  const context = nonIntegerTokens ? { nonIntegers: nonIntegerTokens, pointer: '/publication/equity_run_consumption' } : undefined;
  closed(value, contract.root_fields); sameKey(value.run_key, expected);
  const actionVariant = value.schema_version === actionContract.document_schema_version &&
    value.catalog_version === actionContract.catalog_version;
  need(actionVariant || (value.schema_version === contract.document_schema_version && value.catalog_version === contract.catalog_version));
  const selectedContract = actionVariant ? actionContract : contract;
  const stageSpecs = selectedContract.stages as Record<string, StageSpec>;
  need(value.scope === 'full_run' && value.profile === 'mean_reversion');
  need(typeof value.available === 'boolean' && value.available === value.complete);
  need(value.complete ? value.unavailable_reason === null : contract.unavailable_reasons.includes(value.unavailable_reason as never));
  closed(value.stages, Object.keys(stageSpecs));
  for (const [name, spec] of Object.entries(stageSpecs)) {
    const stageContext = at(at(context, 'stages'), name);
    const row = value.stages[name]; closed(row, contract.stage_fields);
    need(contract.outcomes.includes(row.outcome as never));
    const ok = row.outcome === 'returned_ok';
    const skip = row.outcome === 'skipped';
    if (skip) need((contract.skip_reasons as Record<string, string[]>)[name]?.includes(row.skip_reason as string));
    else need(row.skip_reason === null);
    const quiet = skip && row.skip_reason === 'non_trading_day';
    reads(row.reads, spec.reads ?? {}, ok ? spec.required : [], at(stageContext, 'reads'));
    object(row.symbols); need(Object.keys(row.symbols).length <= contract.symbol_limit);
    need(Array.isArray(row.executions) && row.executions.length <= contract.execution_limit);
    if (!spec.per_symbol_reads) need(Object.keys(row.symbols).length === 0);
    for (const [symbol, observed] of Object.entries(row.symbols)) {
      need(symbolPattern.test(symbol));
      const required = name === 'cost_history' ? contract.cost_history_conditions.common_required : Object.keys(spec.per_symbol_reads ?? {});
      reads(observed, spec.per_symbol_reads ?? {}, ok ? required : [], at(at(stageContext, 'symbols'), symbol));
      if (ok && name === 'cost_history') costHistoryConditions(observed);
    }
    if (!spec.per_execution_reads) need(row.executions.length === 0);
    const seen = new Set<string>();
    for (const [index, item] of row.executions.entries()) {
      const executionContext = at(at(stageContext, 'executions'), String(index));
      closed(item, ['symbol', 'portfolio_id', 'strategy_id', 'strategy_name', 'index', 'execution_id', 'reads']);
      need(typeof item.symbol === 'string' && symbolPattern.test(item.symbol) && item.index === index);
      need(!executionContext || !executionContext.nonIntegers.has(at(executionContext, 'index')!.pointer));
      for (const key of ['portfolio_id', 'strategy_id', 'strategy_name'] as const) need(item[key] === expected[key]);
      need(typeof item.execution_id === 'string' && item.execution_id.length > 0 &&
        new TextEncoder().encode(item.execution_id).byteLength <= 50 && !seen.has(item.execution_id));
      seen.add(item.execution_id);
      reads(item.reads, spec.per_execution_reads ?? {}, ok ? contract.execution_cost_conditions.common_required : [], at(executionContext, 'reads'));
      if (ok) executionConditions(item.reads);
    }
    if (row.outcome === 'not_reached' || quiet) need(Object.keys(row.reads).length === 0 && Object.keys(row.symbols).length === 0 && row.executions.length === 0);
    if (value.complete) need(ok || skip);
  }
  const stages = value.stages as unknown as Record<string, EquityRunStage>;
  const quiet = ['preparation', 'primary', 'execution'].map(name => stages[name].skip_reason === 'non_trading_day');
  need(quiet.every(Boolean) || quiet.every(flag => !flag));
  const prior = stages.prior.reads;
  for (const [name, selector] of [['prior', 'mode'], ['corporate_actions', 'path'], ['eod', 'path']] as const) {
    const row = stages[name]; const branch = row.reads[selector];
    if (row.outcome !== 'returned_ok' && row.outcome !== 'skipped') continue;
    const choices = selectedContract.conditional_readsets[name] as Record<string, { required: string[]; forbidden: string[] }>;
    need(typeof branch === 'string' && Object.hasOwn(choices, branch));
    const chosen = choices[branch]; need(chosen.required.every(key => has(row.reads, key)) && chosen.forbidden.every(key => !has(row.reads, key)));
  }
  if (has(prior, 'source_day')) need((prior.source_day as string) < expected.date);
  if (has(prior, 'valuation_day')) need(prior.valuation_day === expected.date);
  if (actionVariant) {
    const actions = stages.corporate_actions;
    need(actions.reads.path === actionContract.variant_path && prior.mode === 'verified_desk_prior');
    need(!has(actions.reads, 'spinoff_child_policy_requested') && !has(actions.reads, 'spinoff_child_policy_effective') &&
      (!has(actions.reads, 'effective_event_count') || actions.reads.effective_event_count === 0));
    if (actions.outcome === 'returned_ok' || actions.outcome === 'skipped') {
      need(actions.reads.effective_event_count === 0 &&
        (actions.reads.original_action_count as number) + (actions.reads.successor_action_count as number) >= 1);
    }
  }
  if (stages.corporate_actions.reads.path === 'proved_action_free_prior') need(prior.mode === 'verified_desk_prior' && stages.corporate_actions.reads.effective_event_count === 0);
  if (stages.eod.reads.path === 'proved_desk_successor' || stages.eod.skip_reason === 'proved_desk_successor') need(prior.mode === 'verified_desk_prior' && stages.eod.reads.path === 'proved_desk_successor' && stages.eod.outcome === 'skipped' && stages.eod.skip_reason === 'proved_desk_successor');
  const market = stages.market_input.reads;
  if (has(market, 'start_day')) need((market.start_day as string) <= expected.date);
  if (has(market, 'end_day')) need((market.end_day as string) <= expected.date);
  if (has(market, 'start_day') && has(market, 'end_day')) need((market.start_day as string) <= (market.end_day as string));
  const portfolio = stages.primary.reads.portfolio_invocation as EquityPortfolioConsumption | undefined;
  if (portfolio) {
    if (value.complete) need(portfolio.available);
    for (const pass of portfolio.passes) for (const flag of ['use_optimization', 'use_risk_management']) {
      if (has(pass.reads, flag)) need(pass.reads[flag] === stages.setup.reads[flag]);
    }
  }
  if (value.complete) need(stages.setup.reads.use_optimization === false);
}
