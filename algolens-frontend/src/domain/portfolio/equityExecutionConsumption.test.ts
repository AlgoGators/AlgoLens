import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { validateEquityRunConsumption } from './equityRunConsumption';
const regulatory = ['sec_fee_per_million', 'finra_taf_per_share', 'finra_taf_cap_per_trade'];
const volatility = ['volatility_lambda', 'volatility_min_multiplier', 'volatility_max_multiplier'];
function coldBuy() {
  const value = JSON.parse(readFileSync(resolve('../contracts/equity-inspection-v3-synthetic-available.json'), 'utf8')).publication.equity_run_consumption;
  const reads = value.stages.execution.executions[0].reads;
  reads.quantity = 1.25; reads.reference_price = 20; reads.volatility_calculation_reached = false;
  reads.retrieved_volatility_multiplier = 1; reads.effective_volatility_multiplier = 1;
  reads.commission_per_unit = .005; reads.max_commission_pct = .01; reads.apply_regulatory_fees = false;
  for (const key of [...regulatory, ...volatility, 'max_commission_per_order']) delete reads[key];
  delete value.stages.cost_history.symbols.SYN.log_return_lookback_days;
  value.stages.cost_history.symbols.SYN.previous_close_source = 'no_previous_close';
  value.stages.cost_history.symbols.SYN.previous_close_forwarded = 0;
  return { value, reads };
}
describe('actual conditional equity execution reads', () => {
  it('accepts a cold buy without inventing sell fees, volatility or first-return lookback', () => {
    const { value } = coldBuy(); expect(() => validateEquityRunConsumption(value, value.run_key)).not.toThrow();
  });
  it('accepts a warm sell with the actual regulatory and volatility reads', () => {
    const { value, reads } = coldBuy(); reads.quantity = -1.25; reads.apply_regulatory_fees = true;
    reads.volatility_calculation_reached = true; for (const key of [...regulatory, ...volatility]) reads[key] = .5;
    Object.assign(value.stages.cost_history.symbols.SYN, { previous_close_source: 'stored_previous_close', previous_close_forwarded: 20, log_return_lookback_days: 21 });
    expect(() => validateEquityRunConsumption(value, value.run_key)).not.toThrow();
  });
  it('accepts the actual order ceiling when percentage ceiling is disabled', () => {
    const { value, reads } = coldBuy(); reads.max_commission_pct = -1; reads.max_commission_per_order = 2;
    expect(() => validateEquityRunConsumption(value, value.run_key)).not.toThrow();
  });
  it('accepts the actual explicit-fee fallback without invented commission thresholds', () => {
    const { value, reads } = coldBuy(); reads.commission_per_unit = -1; reads.explicit_fee_per_contract = .5;
    delete reads.min_commission_per_order; delete reads.max_commission_pct;
    expect(() => validateEquityRunConsumption(value, value.run_key)).not.toThrow();
  });
  it.each([
    ['invented buy fee', (_v: any, r: any) => { r.sec_fee_per_million = .5; }],
    ['missing sell fee', (_v: any, r: any) => { r.quantity = -1; r.apply_regulatory_fees = true; }],
    ['invented order ceiling', (_v: any, r: any) => { r.max_commission_per_order = 2; }],
    ['missing order ceiling', (_v: any, r: any) => { r.max_commission_pct = -1; }],
    ['invented fallback fee', (_v: any, r: any) => { r.explicit_fee_per_contract = .5; }],
    ['missing fallback fee', (_v: any, r: any) => { r.commission_per_unit = -1; delete r.max_commission_pct; delete r.min_commission_per_order; }],
    ['invented neutral volatility read', (_v: any, r: any) => { r.volatility_lambda = .5; }],
    ['missing calculated volatility reads', (_v: any, r: any) => { r.volatility_calculation_reached = true; }],
    ['nonneutral multiplier', (_v: any, r: any) => { r.effective_volatility_multiplier = 1.5; }],
    ['missing volatility branch', (_v: any, r: any) => { delete r.volatility_calculation_reached; }],
    ['zero execution', (_v: any, r: any) => { r.quantity = 0; }],
    ['zero price', (_v: any, r: any) => { r.reference_price = 0; }],
    ['invented first return lookback', (v: any) => { v.stages.cost_history.symbols.SYN.log_return_lookback_days = 21; }],
    ['unproved stored previous close', (v: any) => { v.stages.cost_history.symbols.SYN.previous_close_source = 'stored_previous_close'; }],
  ])('refuses %s', (_name, damage) => {
    const { value, reads } = coldBuy(); damage(value, reads);
    expect(() => validateEquityRunConsumption(value, value.run_key)).toThrow();
  });
});
