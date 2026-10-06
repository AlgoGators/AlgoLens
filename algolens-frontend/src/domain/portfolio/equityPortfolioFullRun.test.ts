import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { validateEquityRunConsumption } from './equityRunConsumption';
const fixture = () => JSON.parse(readFileSync(resolve('../contracts/equity-inspection-v3-synthetic-available.json'), 'utf8')).publication.equity_run_consumption;
const observed = () => {
  const value = fixture(); value.stages.setup.reads.use_risk_management = true;
  value.stages.primary.reads.portfolio_invocation = {
    schema_version: 'qt-equity-portfolio-consumption/v1', scope: 'portfolio_invocation',
    full_run_certification: false, available: true, unavailable_reason: null,
    outcome: 'returned_ok', skip_execution_generation: true,
    passes: [{ index: 0, reads: { use_optimization: false, use_risk_management: true },
      optimization_helper: 'not_reached', risk_helper: 'returned_ok',
      risk: { call: 'returned_ok', skip: 'none', manager_source: 'external', reads: { var_limit: .05 } } }],
    strategy_charges: [], compatibility_charges: [],
  }; return value;
};
describe('full equity run with actual portfolio helper observations', () => {
  it('admits the equity feed first bar with no previous close', () => {
    const value = observed(); const symbol = Object.keys(value.stages.cost_history.symbols)[0];
    value.stages.cost_history.symbols[symbol].previous_close_source = 'no_previous_close';
    value.stages.cost_history.symbols[symbol].previous_close_forwarded = 0;
    expect(() => validateEquityRunConsumption(value, value.run_key)).not.toThrow();
  });
  it('admits complete risk-enabled evidence only with the matching actual helper child', () => {
    const value = observed(); expect(() => validateEquityRunConsumption(value, value.run_key)).not.toThrow();
  });
  it('retains partial failed risk evidence with unavailable full-run status', () => {
    const value = observed(); value.available = false; value.complete = false; value.unavailable_reason = 'stage_failed';
    const child = value.stages.primary.reads.portfolio_invocation;
    child.available = false; child.unavailable_reason = 'stage_failed'; child.passes[0].risk_helper = 'returned_error';
    child.passes[0].risk.call = 'returned_error';
    expect(() => validateEquityRunConsumption(value, value.run_key)).not.toThrow();
  });
  it.each([
    ['setup switch differs', (v: any) => { v.stages.setup.reads.use_risk_management = false; }],
    ['nested risk failure claimed complete', (v: any) => { const p = v.stages.primary.reads.portfolio_invocation; p.available = false; p.unavailable_reason = 'stage_failed'; p.passes[0].risk.call = 'returned_error'; }],
    ['child omitted', (v: any) => { delete v.stages.primary.reads.portfolio_invocation; }],
    ['nested pass integer token', (_v: any) => {}],
  ])('refuses %s', (name, damage) => {
    const value = observed(); damage(value);
    const lexical = name === 'nested pass integer token' ? new Set(['/publication/equity_run_consumption/stages/primary/reads/portfolio_invocation/passes/0/index']) : undefined;
    expect(() => validateEquityRunConsumption(value, value.run_key, lexical)).toThrow();
  });
});
