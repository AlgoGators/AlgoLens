import { describe, expect, it } from 'vitest';
import { validateEquityRunConsumption, type EquityRunKey } from './equityRunConsumption';

export const runKey: EquityRunKey = { portfolio_id: 'EQUITY_MR_PORTFOLIO',
  strategy_id: 'LIVE_EQUITY_MEAN_REVERSION', strategy_name: 'EQUITY_MEAN_REVERSION', date: '2026-09-26' };
// Explicit synthetic read evidence for protocol tests, never a native capture.
export function syntheticQuietRun() {
  const stage = (reads: Record<string, unknown> = {}) =>
    ({ outcome: 'returned_ok', skip_reason: null, reads, symbols: {}, executions: [] });
  const skipped = () => ({ ...stage(), outcome: 'skipped', skip_reason: 'non_trading_day' });
  return {
    schema_version: 'qt-equity-run-consumption/v1', catalog_version: 'qt-equity-main08b15c-run/v1',
    scope: 'full_run', profile: 'mean_reversion', run_key: { ...runKey },
    available: true, complete: true, unavailable_reason: null,
    stages: {
      setup: stage({ capital_allocation: 100000, max_leverage: 2, max_drawdown: .2,
        reserve_capital: 10000, use_optimization: false, use_risk_management: false, allow_fractional_positions: true }),
      market_input: stage({ historical_days: 100, asset_type: 'EQUITY', frequency: 'DAILY', start_day: '2026-06-18', end_day: '2026-09-26' }),
      cost_history: stage(), prior: stage({ mode: 'system_reference', source_day: '2026-09-25' }),
      corporate_actions: stage({ path: 'system_history', spinoff_child_policy_requested: 'hold',
        spinoff_child_policy_effective: 'hold', effective_event_count: 0 }),
      preparation: skipped(), primary: skipped(), execution: skipped(),
      eod: stage({ path: 'system_finalization', previous_equity_exact: '100000', previous_total_pnl_exact: '0',
        previous_total_realized_pnl_exact: '0', previous_total_transaction_costs_exact: '0', initial_capital_exact: '100000' }),
      result_assembly: stage({ currency: 'USD', current_portfolio_value_exact: '100000.00000001',
        total_realized_pnl_exact: '0', total_unrealized_pnl_exact: '0', total_transaction_costs_exact: '0' }),
    },
  };
}
describe('closed equity full-run consumption', () => {
  it.each(['start_day', 'end_day'])('refuses a lone observed %s beyond the run date on a failed stage', field => {
    const value = syntheticQuietRun(); value.available = false; value.complete = false;
    Object.assign(value, { unavailable_reason: 'stage_failed' });
    value.stages.market_input = { outcome: 'returned_error', skip_reason: null,
      reads: { [field]: '2026-09-27' }, symbols: {}, executions: [] };
    expect(() => validateEquityRunConsumption(value, runKey)).toThrow();
  });
  it.each([undefined, 'system_reference'])('refuses an observed wrong valuation day before complete prior evidence (%s)', mode => {
    const value = syntheticQuietRun(); value.available = false; value.complete = false;
    Object.assign(value, { unavailable_reason: 'stage_failed' });
    value.stages.prior = { outcome: 'threw', skip_reason: null,
      reads: { valuation_day: '2026-09-27', ...(mode ? { mode } : {}) }, symbols: {}, executions: [] };
    expect(() => validateEquityRunConsumption(value, runKey)).toThrow();
  });
  it('retains valid individually observed dates in incomplete stages', () => {
    const value = syntheticQuietRun(); value.available = false; value.complete = false;
    Object.assign(value, { unavailable_reason: 'stage_failed' });
    value.stages.market_input = { outcome: 'returned_error', skip_reason: null,
      reads: { start_day: '2026-09-25' }, symbols: {}, executions: [] };
    value.stages.prior = { outcome: 'threw', skip_reason: null,
      reads: { valuation_day: runKey.date }, symbols: {}, executions: [] };
    expect(() => validateEquityRunConsumption(value, runKey)).not.toThrow();
  });
  it('preserves a valid quiet run and exact fixed decimal text without defaults', () => {
    const value = syntheticQuietRun(); const before = JSON.stringify(value);
    expect(() => validateEquityRunConsumption(value, runKey)).not.toThrow();
    expect(JSON.stringify(value)).toBe(before);
    expect(value.stages.result_assembly.reads.current_portfolio_value_exact).toBe('100000.00000001');
  });
  it('preserves truthful unavailable partial evidence', () => {
    const value = syntheticQuietRun(); value.available = false; value.complete = false;
    Object.assign(value, { unavailable_reason: 'stage_failed' });
    value.stages.result_assembly = { outcome: 'returned_error', skip_reason: null, reads: {}, symbols: {}, executions: [] };
    expect(() => validateEquityRunConsumption(value, runKey)).not.toThrow();
  });
  it.each([
    ['different owner', (v: any) => { v.run_key.portfolio_id = 'OTHER'; }],
    ['different date', (v: any) => { v.run_key.date = '2026-09-25'; }],
    ['impossible date', (v: any) => { v.stages.market_input.reads.start_day = '2026-02-30'; }],
    ['unknown stage', (v: any) => { v.stages.caller_trusted = v.stages.setup; }],
    ['missing stage', (v: any) => { delete v.stages.cost_history; }],
    ['unknown read', (v: any) => { v.stages.setup.reads.caller_trusted = true; }],
    ['missing actual read', (v: any) => { delete v.stages.setup.reads.capital_allocation; }],
    ['boolean integer', (v: any) => { v.stages.market_input.reads.historical_days = true; }],
    ['nonfinite', (v: any) => { v.stages.setup.reads.max_leverage = Infinity; }],
    ['numeric exact quantity', (v: any) => { v.stages.result_assembly.reads.current_portfolio_value_exact = 1; }],
    ['decimal overflow', (v: any) => { v.stages.result_assembly.reads.current_portfolio_value_exact = '92233720368.54775808'; }],
    ['inconsistent quiet day', (v: any) => { v.stages.execution.outcome = 'returned_ok'; v.stages.execution.skip_reason = null; }],
    ['invented skipped reads', (v: any) => { v.stages.primary.reads.strategy_invocation = {}; }],
    ['unreached is not complete', (v: any) => { v.stages.cost_history.outcome = 'not_reached'; }],
    ['wrong successor branch', (v: any) => { v.stages.eod.outcome = 'skipped'; v.stages.eod.skip_reason = 'proved_desk_successor'; v.stages.eod.reads.path = 'proved_desk_successor'; }],
    ['enabled uninstrumented helper', (v: any) => { v.stages.setup.reads.use_optimization = true; }],
  ] as const)('refuses %s', (_name, damage) => {
    const value = syntheticQuietRun(); damage(value);
    expect(() => validateEquityRunConsumption(value, runKey)).toThrow();
  });
});
