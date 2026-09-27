import fixture from '../../../../contracts/equity-inspection-v3-synthetic-available.json';

// These are structural protocol vectors, not captured financial authority.
export const original = () => structuredClone(fixture);
export function adjusted(originalCount = 1, successorCount = 0) {
  const value: any = original();
  const run = value.publication.equity_run_consumption;
  run.schema_version = 'qt-equity-run-consumption/v2';
  run.catalog_version = 'qt-equity-main08b15c-run/v2';
  run.stages.prior.reads = {
    mode: 'verified_desk_prior', source_day: '2026-09-25', valuation_day: run.run_key.date,
    decision_id: '11111111-1111-4111-8111-111111111111',
    finalization_id: '22222222-2222-4222-8222-222222222222',
    finalization_digest: 'a'.repeat(64), finalization_source_digest: 'b'.repeat(64),
    accounting_input_digest: 'c'.repeat(64), observation_digest: 'd'.repeat(64), results_digest: 'e'.repeat(64),
  };
  run.stages.corporate_actions.reads = {
    path: 'proved_action_adjusted_prior', effective_event_count: 0,
    original_action_count: originalCount, successor_action_count: successorCount,
    original_action_digest: 'a'.repeat(64), successor_action_digest: 'b'.repeat(64), basis_frame_digest: 'c'.repeat(64),
  };
  return value;
}
