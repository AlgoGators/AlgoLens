import { describe, expect, it } from 'vitest';
import { validateEquityPortfolioConsumption } from './equityPortfolioConsumption';

const example = (): any => ({
  schema_version: 'qt-equity-portfolio-consumption/v1', scope: 'portfolio_invocation',
  full_run_certification: false, available: true, unavailable_reason: null,
  outcome: 'returned_ok', skip_execution_generation: false,
  passes: [{ index: 0, reads: { use_optimization: false, use_risk_management: true },
    optimization_helper: 'not_reached', risk_helper: 'returned_ok',
    risk: { call: 'returned_ok', skip: 'none', manager_source: 'internal', lookback_period: 20,
      reads: { var_limit: .05, capital_exact: '100000.00000001' } } }],
  strategy_charges: [{ index: 0, purpose: 'per_strategy', strategy_id: 'LIVE_EQUITY_MEAN_REVERSION',
    symbol: 'SYN', call: 'returned_ok', reads: { quantity: -1.25, reference_price: 20,
      input_source: 'internally_tracked', asset_lookup_path: 'exact_symbol', commission_per_unit: .005 } }],
  compatibility_charges: [{ index: 0, purpose: 'compatibility', strategy_id: '', symbol: 'SYN',
    call: 'returned_ok', reads: { quantity: 1.25, reference_price: 20,
      input_source: 'explicit_values', asset_lookup_path: 'fallback', explicit_fee_per_contract: .3 } }],
});
describe('actual equity portfolio invocation observations', () => {
  it('preserves actual risk and separate internal charges exactly', () => {
    const value = example(); const before = JSON.stringify(value);
    expect(() => validateEquityPortfolioConsumption(value)).not.toThrow();
    expect(JSON.stringify(value)).toBe(before);
  });
  it('admits a reached risk helper with an actual no-positions skip', () => {
    const value = example(); value.passes[0].risk = { call: 'not_reached', skip: 'no_positions', reads: {}, manager_source: 'internal', lookback_period: 20 };
    expect(() => validateEquityPortfolioConsumption(value)).not.toThrow();
  });
  it('keeps a failed reached risk helper visibly unavailable', () => {
    const value = example(); value.available = false; value.unavailable_reason = 'stage_failed';
    value.passes[0].risk_helper = 'returned_error'; value.passes[0].risk.call = 'threw';
    expect(() => validateEquityPortfolioConsumption(value)).not.toThrow();
  });
  it('accepts explicit disabled helpers without inventing reads', () => {
    const value = example(); value.passes[0].reads.use_risk_management = false;
    value.passes[0].risk_helper = 'not_reached'; value.passes[0].risk = { call: 'not_reached', skip: 'none', reads: {} };
    expect(() => validateEquityPortfolioConsumption(value)).not.toThrow();
  });
  it('accepts unobserved partial state without inventing false', () => {
    const value = example(); Object.assign(value, { outcome: 'not_reached', available: false,
      unavailable_reason: 'instrumentation_missing', skip_execution_generation: null, passes: [], strategy_charges: [], compatibility_charges: [] });
    expect(() => validateEquityPortfolioConsumption(value)).not.toThrow();
  });
  it('preserves the actual absent-manager skip without a lookback', () => {
    const value = example(); value.passes[0].risk = { call: 'not_reached', skip: 'absent_risk_manager', reads: {}, manager_source: 'absent' };
    expect(() => validateEquityPortfolioConsumption(value)).not.toThrow();
  });
  it.each([
    { call: 'not_reached', skip: 'no_positions', reads: {} },
    { call: 'not_reached', skip: 'no_positions', reads: {}, manager_source: 'internal' },
    { call: 'not_reached', skip: 'absent_risk_manager', reads: {}, manager_source: 'internal' },
    { call: 'not_reached', skip: 'absent_risk_manager', reads: {}, manager_source: 'absent', lookback_period: 20 },
    { call: 'not_reached', skip: 'absent_optimizer', reads: {} },
    { call: 'not_reached', skip: 'insufficient_history', reads: {} },
  ])('refuses a risk skip not produced by its actual helper: %j', risk => {
    const value = example(); value.passes[0].risk = risk;
    expect(() => validateEquityPortfolioConsumption(value)).toThrow();
  });
  it.each([
    ['unknown field', (v: any) => { v.authorized = true; }],
    ['false full-run authority', (v: any) => { v.full_run_certification = true; }],
    ['false availability', (v: any) => { v.passes[0].risk_helper = 'returned_error'; }],
    ['disabled risk reads', (v: any) => { v.passes[0].reads.use_risk_management = false; }],
    ['missing observed switch', (v: any) => { delete v.passes[0].reads.use_risk_management; }],
    ['enabled unsupported optimizer', (v: any) => { v.passes[0].reads.use_optimization = true; }],
    ['risk skip while called', (v: any) => { v.passes[0].risk.skip = 'no_positions'; }],
    ['risk without actual manager', (v: any) => { delete v.passes[0].risk.manager_source; }],
    ['risk decimal overflow', (v: any) => { v.passes[0].risk.reads.capital_exact = '92233720368.54775808'; }],
    ['risk decimal converted number', (v: any) => { v.passes[0].risk.reads.capital_exact = 1; }],
    ['unreached internal cost reads', (v: any) => { v.strategy_charges[0].call = 'not_reached'; }],
    ['missing actual charge read', (v: any) => { delete v.strategy_charges[0].reads.quantity; }],
    ['wrong strategy', (v: any) => { v.strategy_charges[0].strategy_id = 'OTHER'; }],
    ['compatibility labelled as strategy', (v: any) => { v.compatibility_charges[0].strategy_id = 'LIVE_EQUITY_MEAN_REVERSION'; }],
    ['skipped executions with charges', (v: any) => { v.skip_execution_generation = true; }],
    ['noncontiguous pass', (v: any) => { v.passes[0].index = 1; }],
    ['nonfinite cost', (v: any) => { v.strategy_charges[0].reads.quantity = Infinity; }],
  ])('refuses %s', (_name, change) => {
    const value = example(); change(value); expect(() => validateEquityPortfolioConsumption(value)).toThrow();
  });
  it.each(['/passes/0/index', '/passes/0/risk/lookback_period', '/strategy_charges/0/index'])('refuses a JSON noninteger token at %s', pointer => {
    expect(() => validateEquityPortfolioConsumption(example(), new Set([pointer]))).toThrow();
  });
});
