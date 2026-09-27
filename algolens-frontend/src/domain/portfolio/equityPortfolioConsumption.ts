import contract from './equityPortfolioConsumptionCatalog.json';
import { parseFixedDecimal8 } from '../numbers/fixedDecimal8';
export type EquityPortfolioConsumption = {
  schema_version: 'qt-equity-portfolio-consumption/v1'; scope: 'portfolio_invocation';
  full_run_certification: false; available: boolean; unavailable_reason: string | null;
  outcome: string; skip_execution_generation: boolean | null;
  passes: Array<{ index: number; reads: Record<string, unknown>; optimization_helper: string;
    risk_helper: string; risk: { call: string; skip: string; reads: Record<string, unknown>;
      manager_source?: string; lookback_period?: number } }>;
  strategy_charges: EquityPortfolioCharge[]; compatibility_charges: EquityPortfolioCharge[];
};
export type EquityPortfolioCharge = { index: number; purpose: string; strategy_id: string;
  symbol: string; call: string; reads: Record<string, unknown> };
type Row = Record<string, unknown>;
function need(ok: unknown): asserts ok { if (!ok) throw new Error('Equity portfolio observations could not be verified.'); }
function closed(value: unknown, allowed: readonly string[], required = allowed): asserts value is Row {
  need(value !== null && typeof value === 'object' && !Array.isArray(value) &&
    [Object.prototype, null].includes(Object.getPrototypeOf(value)));
  need(Reflect.ownKeys(value).every(key => typeof key === 'string' && allowed.includes(key)) &&
    required.every(key => Object.hasOwn(value, key)));
}
const entered = (call: unknown) => call !== 'not_reached';
const keys = (row: Row) => Object.keys(row);
export function validateEquityPortfolioConsumption(value: unknown,
  nonIntegers?: ReadonlySet<string>, pointer = ''): asserts value is EquityPortfolioConsumption {
  const integer = (v: unknown, path: string, maximum: number) => need(typeof v === 'number' &&
    Number.isSafeInteger(v) && v >= 0 && v <= maximum && !nonIntegers?.has(`${pointer}${path}`));
  const call = (v: unknown) => need(contract.call_outcomes.includes(v as string));
  closed(value, contract.root_fields);
  need(value.schema_version === contract.schema_version && value.scope === contract.scope && value.full_run_certification === false);
  need(typeof value.available === 'boolean'); call(value.outcome);
  need(value.skip_execution_generation === null || typeof value.skip_execution_generation === 'boolean');
  need(value.available ? value.unavailable_reason === null :
    ['instrumentation_missing', 'unsupported_enabled_helper', 'capacity_exceeded', 'invalid_observed_value', 'stage_failed'].includes(value.unavailable_reason as string));
  need(Array.isArray(value.passes) && value.passes.length <= contract.pass_limit);
  let complete = value.outcome === 'returned_ok' && value.skip_execution_generation !== null && value.passes.length > 0;
  let unsupported = false;
  for (const [index, pass] of value.passes.entries()) {
    closed(pass, contract.pass_fields); integer(pass.index, `/passes/${index}/index`, contract.pass_limit - 1); need(pass.index === index);
    closed(pass.reads, keys(contract.pass_reads), []);
    for (const flag of Object.values(pass.reads)) need(typeof flag === 'boolean');
    call(pass.optimization_helper); call(pass.risk_helper);
    closed(pass.risk, [...contract.risk_fields, ...contract.risk_optional_fields], contract.risk_fields);
    const risk = pass.risk; call(risk.call); need(contract.risk_skips.includes(risk.skip as string));
    closed(risk.reads, keys(contract.risk_reads), []);
    for (const [key, observed] of Object.entries(risk.reads)) {
      if (key === 'capital_exact') { need(typeof observed === 'string'); parseFixedDecimal8(observed); }
      else need(typeof observed === 'number' && Number.isFinite(observed));
    }
    if (Object.hasOwn(risk, 'manager_source')) need(contract.manager_source.includes(risk.manager_source as string));
    if (Object.hasOwn(risk, 'lookback_period')) integer(risk.lookback_period, `/passes/${index}/risk/lookback_period`, 2147483647);
    if (!Object.hasOwn(pass.reads, 'use_optimization') || !Object.hasOwn(pass.reads, 'use_risk_management')) complete = false;
    if (pass.reads.use_optimization === false) need(!entered(pass.optimization_helper));
    if (pass.reads.use_optimization === true) unsupported = true;
    if (pass.reads.use_risk_management === false) need(!entered(pass.risk_helper) && !entered(risk.call) &&
      risk.skip === 'none' && keys(risk.reads).length === 0 && !Object.hasOwn(risk, 'manager_source') && !Object.hasOwn(risk, 'lookback_period'));
    if (pass.reads.use_risk_management === true) {
      if (pass.risk_helper !== 'returned_ok') complete = false;
      if (entered(risk.call)) {
        need(risk.skip === 'none' && ['internal', 'external'].includes(risk.manager_source as string));
        if (risk.call !== 'returned_ok') complete = false;
      } else {
        need(keys(risk.reads).length === 0); if (risk.skip === 'none') complete = false;
        if (risk.skip === 'absent_risk_manager') need(risk.manager_source === 'absent' && !Object.hasOwn(risk, 'lookback_period'));
        if (risk.skip === 'no_positions') need(['internal', 'external'].includes(risk.manager_source as string) && Object.hasOwn(risk, 'lookback_period'));
      }
    }
  }
  for (const [name, purpose] of Object.entries(contract.charge_purpose)) {
    const charges = value[name]; need(Array.isArray(charges) && charges.length <= contract.charge_limit);
    for (const [index, charge] of charges.entries()) {
      closed(charge, contract.charge_fields); integer(charge.index, `/${name}/${index}/index`, contract.charge_limit - 1);
      need(charge.index === index && charge.purpose === purpose);
      need(charge.strategy_id === (purpose === 'per_strategy' ? 'LIVE_EQUITY_MEAN_REVERSION' : ''));
      need(typeof charge.symbol === 'string' && /^[A-Za-z0-9_.\/-]{1,64}$/.test(charge.symbol)); call(charge.call);
      closed(charge.reads, [...contract.charge_reads_number, ...contract.charge_reads_boolean, ...keys(contract.charge_reads_enums)], []);
      for (const [key, observed] of Object.entries(charge.reads)) {
        if (contract.charge_reads_number.includes(key)) need(typeof observed === 'number' && Number.isFinite(observed));
        else if (contract.charge_reads_boolean.includes(key)) need(typeof observed === 'boolean');
        else need((contract.charge_reads_enums as Record<string, string[]>)[key].includes(observed as string));
      }
      need(value.skip_execution_generation !== true);
      need(entered(charge.call) || keys(charge.reads).length === 0);
      const actualReads = charge.reads;
      if (charge.call !== 'returned_ok' || !contract.success_required_charge_reads.every(key => Object.hasOwn(actualReads, key))) complete = false;
    }
  }
  if (value.available) need(complete && !unsupported);
}
