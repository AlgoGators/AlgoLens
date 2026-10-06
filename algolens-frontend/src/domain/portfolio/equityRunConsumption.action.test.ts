import { describe, expect, it } from 'vitest';
import { validateEquityRunConsumption } from './equityRunConsumption';
import { parseConfigurationInspection } from './configurationInspection';
import { adjusted, original } from './actionFixtures';
import sharedVectors from '../../test/fixtures/equityActionSyntheticVectors.json';

const validate = (value: any, tokens?: ReadonlySet<string>) => {
  const run = value.publication.equity_run_consumption;
  validateEquityRunConsumption(run, run.run_key, tokens);
};
const action = (value: any) => value.publication.equity_run_consumption.stages.corporate_actions.reads;
describe('explicit adjusted-action inspection protocol', () => {
  it.each([[1, 0], [0, 1], [2, 3]])('admits recorded original=%i successor=%i without mutation', (before, after) => {
    const value = adjusted(before, after); const bytes = JSON.stringify(value);
    expect(() => validate(value)).not.toThrow();
    expect(JSON.stringify(value)).toBe(bytes);
    expect(action(value).effective_event_count).toBe(0);
  });
  it('preserves unchanged v1 bytes', () => {
    const value = original(); const bytes = JSON.stringify(value);
    expect(() => validate(value)).not.toThrow(); expect(JSON.stringify(value)).toBe(bytes);
  });
  it('composes through the unchanged schema3 parser', () => {
    const value = adjusted();
    expect(() => parseConfigurationInspection(JSON.stringify(value), value.scope.registry_id, value.scope.portfolio_id)).not.toThrow();
  });
  it.each(['path', 'effective_event_count', 'original_action_count', 'successor_action_count', 'original_action_digest', 'successor_action_digest', 'basis_frame_digest'])('refuses missing %s', field => {
    const value = adjusted(); delete action(value)[field]; expect(() => validate(value)).toThrow();
  });
  it.each([
    ['unknown read', (v: any) => { action(v).trusted = true; }],
    ['no recorded actions', (v: any) => { action(v).original_action_count = 0; }],
    ['new applications', (v: any) => { action(v).effective_event_count = 1; }],
    ['wrong prior', (v: any) => { v.publication.equity_run_consumption.stages.prior.reads = {mode:'system_reference', source_day:'2026-09-25'}; }],
    ['wrong branch', (v: any) => { action(v).path = 'proved_action_free_prior'; }],
    ['mixed catalog', (v: any) => { v.publication.equity_run_consumption.catalog_version = 'qt-equity-main08b15c-run/v1'; }],
    ['unknown schema', (v: any) => { v.publication.equity_run_consumption.schema_version = 'qt-equity-run-consumption/v3'; }],
    ['spinoff requested', (v: any) => { action(v).spinoff_child_policy_requested = 'hold'; }],
    ['spinoff effective', (v: any) => { action(v).spinoff_child_policy_effective = 'hold'; }],
  ] as const)('refuses %s', (_name, damage) => { const value = adjusted(); damage(value); expect(() => validate(value)).toThrow(); });
  it.each(['original_action_count', 'successor_action_count'])('closes %s type and bounds', field => {
    for (const invalid of [true, -1, 1.5, 2147483648, Infinity, '1']) {
      const value = adjusted(1, 1); action(value)[field] = invalid; expect(() => validate(value)).toThrow();
    }
    const value = adjusted(2147483647, 2147483647); expect(() => validate(value)).not.toThrow();
  });
  it.each(['original_action_count', 'successor_action_count'])('refuses lexical noninteger %s through schema3', field => {
    const value = adjusted(1, 1);
    for (const token of ['1.0', '1e0']) {
      const raw = JSON.stringify(value).replace(`"${field}":1`, `"${field}":${token}`);
      expect(() => parseConfigurationInspection(raw, value.scope.registry_id, value.scope.portfolio_id)).toThrow();
    }
  });
  it.each(['original_action_digest', 'successor_action_digest', 'basis_frame_digest'])('closes %s', field => {
    for (const invalid of ['A'.repeat(64), 'a'.repeat(63), 123, 'g'.repeat(64)]) {
      const value = adjusted(); action(value)[field] = invalid; expect(() => validate(value)).toThrow();
    }
  });
  it('does not reinterpret the action path as v1', () => {
    const value = adjusted(); const run = value.publication.equity_run_consumption;
    run.schema_version = 'qt-equity-run-consumption/v1'; run.catalog_version = 'qt-equity-main08b15c-run/v1';
    expect(() => validate(value)).toThrow();
  });
});

it('refuses an adjusted partial stage whose prior is not verified', () => {
  const value = adjusted(); const run = value.publication.equity_run_consumption;
  run.available = false; run.complete = false; run.unavailable_reason = 'stage_failed';
  run.stages.corporate_actions.outcome = 'returned_error';
  run.stages.prior.reads = {mode:'system_reference', source_day:'2026-09-25'};
  expect(() => validate(value)).toThrow();
});
it.each(Object.entries(sharedVectors.publications))('admits the shared cross-language %s vector without mutation', (_name, publication) => {
  const child = structuredClone(publication.equity_run_consumption); const before = JSON.stringify(child);
  expect(() => validateEquityRunConsumption(child, child.run_key)).not.toThrow();
  expect(JSON.stringify(child)).toBe(before);
});
it.each(['spinoff_child_policy_requested', 'spinoff_child_policy_effective', 'effective_event_count'])('refuses contradictory observed %s on a failed adjusted trace', field => {
  const value = adjusted(); const run = value.publication.equity_run_consumption;
  run.available = false; run.complete = false; run.unavailable_reason = 'stage_failed';
  run.stages.corporate_actions.outcome = 'returned_error';
  action(value)[field] = field === 'effective_event_count' ? 1 : 'hold';
  expect(() => validate(value)).toThrow();
});
it('preserves genuinely unobserved counts and digests on an unavailable adjusted trace', () => {
  const value = adjusted(); const run = value.publication.equity_run_consumption;
  run.available = false; run.complete = false; run.unavailable_reason = 'stage_failed';
  run.stages.corporate_actions.outcome = 'returned_error';
  run.stages.corporate_actions.reads = {path:'proved_action_adjusted_prior'};
  const bytes = JSON.stringify(value); expect(() => validate(value)).not.toThrow();
  expect(JSON.stringify(value)).toBe(bytes);
});