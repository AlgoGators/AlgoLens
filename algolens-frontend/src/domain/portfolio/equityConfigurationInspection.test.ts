import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { parseConfigurationInspection } from './configurationInspection';

const available = JSON.parse(readFileSync(new URL('../../../../contracts/equity-inspection-v3-synthetic-available.json', import.meta.url), 'utf8'));
const unavailable = JSON.parse(readFileSync(new URL('../../../../contracts/equity-inspection-v3-synthetic-unavailable.json', import.meta.url), 'utf8'));
const parse = (value: typeof available) => parseConfigurationInspection(JSON.stringify(value), value.scope.registry_id, value.scope.portfolio_id);
describe('equity publication schema3', () => {
  it('accepts an exact scoped equity publication without invented futures fields', () => {
    const result = parse(available);
    expect(result).toEqual(available);
    expect(result.publication).not.toHaveProperty('supplied');
    expect(result.publication).not.toHaveProperty('selected_trend');
  });
  it('shows a recorded unavailable run without claiming complete coverage', () => {
    expect(parse(unavailable)).toEqual(unavailable);
  });
  it.each(['historical_days', 'adv_lookback_days', 'index', 'lookback_period', 'maximum_price_history', 'volume_sample_count'])('refuses decimal/exponent JSON tokens for integer field %s', field => {
    const value = structuredClone(available);
    const nested = value.publication.equity_run_consumption.stages.primary.reads.strategy_invocation;
    nested.symbols.SYN = { reads: { lookback_period: 21, maximum_price_history: 21, fractional_min_adv: 2 },
      observed_state: { volume_sample_count: 21, average_daily_volume: 200 } };
    const raw = JSON.stringify(value);
    const pattern = new RegExp(`("${field}":)([0-9]+)`);
    expect(raw).toMatch(pattern);
    for (const suffix of ['.0', 'e0']) {
      const changed = raw.replace(pattern, `$1$2${suffix}`);
      expect(() => parseConfigurationInspection(changed, value.scope.registry_id, value.scope.portfolio_id)).toThrow();
    }
  });
  it('preserves decimal/exponent notation for number-valued observed settings', () => {
    const raw = JSON.stringify(available).replace(/("max_leverage":)[0-9.]+/, '$11e2');
    expect(() => parseConfigurationInspection(raw, available.scope.registry_id, available.scope.portfolio_id)).not.toThrow();
  });
  it.each([
    ['wrong profile', (v: any) => { v.publication.profile = 'live_portfolio_runner_futures'; }],
    ['foreign native owner', (v: any) => { v.publication.equity_run_consumption.run_key.portfolio_id = 'OTHER'; }],
    ['foreign source date', (v: any) => { v.publication.equity_run_consumption.run_key.date = '2026-09-25'; }],
    ['unbound publication', (v: any) => { v.publication.identity.publication_id = '81000000-0000-4000-8000-000000000099'; }],
    ['invented futures fields', (v: any) => { v.publication.consumption = { status: 'complete' }; }],
    ['claimed available for incomplete child', (v: any) => { v.publication.equity_run_consumption.complete = false; }],
    ['missing native child', (v: any) => { delete v.publication.equity_run_consumption; }],
    ['wrong stream', (v: any) => { v.publication.stream = 'qt'; }],
  ] as const)('refuses %s', (_name, damage) => {
    const value = structuredClone(available); damage(value); expect(() => parse(value)).toThrow();
  });
});
