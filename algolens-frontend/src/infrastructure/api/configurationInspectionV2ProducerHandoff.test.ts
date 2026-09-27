// @vitest-environment jsdom
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getConfigurationInspection } from './configurationInspectionApi';

type Capture = { stem: string; bytes: number; sha256: string; kind: string };
const directory = 'src/infrastructure/api/__fixtures__/configurationInspectionV2Http';
const index = JSON.parse(readFileSync(`${directory}/index.json`, 'utf8')) as { responses: Capture[] };
const generated = [
  ['publish_required_complete-5bcf79c0c445', 'available', 'none', 'complete', 'none', 16, 'uncontrolled', 'af7e873f-6e89-4076-827a-dd1d0fd2d1d8'],
  ['publish_required_complete_controlled-0e2623f596ae', 'available', 'none', 'complete', 'none', 18, 'controlled', 'b39f0968-8e7d-4f64-a1a1-2e9463652627'],
  ['publish_required_partial-0a62072ce366', 'available', 'none', 'partial', 'nonfatal_error', 16, 'uncontrolled', '686ce2b0-4035-439e-be60-757cdc057d24'],
  ['publish_required_partial_controlled-e2aa4e09194b', 'available', 'none', 'partial', 'nonfatal_error', 18, 'controlled', 'c150fa8c-06a7-44bb-bc87-adb38a2e6cb3'],
  ['publish_required_unavailable-8568faf3d85d', 'available', 'none', 'unavailable', 'instrumentation_missing', 0, 'uncontrolled', '23d9aa5d-05b4-4157-b000-50a64b59a03d'],
  ['publish_required_unavailable_controlled-94e729d78eab', 'available', 'none', 'unavailable', 'instrumentation_missing', 0, 'controlled', 'cc7f1c17-ced7-4220-8001-edc7dbd34cac'],
  ['publish_required_bad_capture_complete-cacaaeacf2f5', 'unavailable', 'capture_failed', 'complete', 'none', 16, 'uncontrolled', 'baf4cb43-220b-47f1-ac8b-6efc73cdfcea'],
  ['publish_required_bad_capture_complete_controlled-b5b8278979fe', 'unavailable', 'capture_failed', 'complete', 'none', 18, 'controlled', 'b1ecfbf1-0e4a-452a-920e-2e503c8a28a7'],
  ['publish_required_early_unavailable_complete-d5324353f082', 'unavailable', 'projection_invalid', 'complete', 'none', 16, 'uncontrolled', '356f380d-883a-4fa0-a1a8-1307f32ead5d'],
  ['publish_required_early_unavailable_complete_controlled-5a257484e45c', 'unavailable', 'projection_invalid', 'complete', 'none', 18, 'controlled', '1f8cdb83-4a32-4d9f-bca9-87ee3766a76c'],
] as const;
const refusals = [
  ['mutation-malformed-newest-publish_required_complete-5bcf79c0c445', 'invalid_publication'],
  ['mutation-malformed-newest-publish_required_bad_capture_complete_controlled-b5b8278979fe', 'invalid_publication'],
  ['mutation-mismatched-attempt', 'invalid_publication'],
  ['mutation-scope-changed', 'scope_changed'],
] as const;

function captured(stem: string, kind: string): ArrayBuffer {
  const match = index.responses.find(row => row.stem === stem);
  expect(match?.kind).toBe(kind);
  const bytes = readFileSync(`${directory}/${stem}.http.json`);
  expect(bytes.byteLength).toBe(match?.bytes);
  expect(createHash('sha256').update(bytes).digest('hex')).toBe(match?.sha256);
  const wire = new ArrayBuffer(bytes.byteLength);
  new Uint8Array(wire).set(bytes);
  return wire;
}

function respond(raw: string | ArrayBuffer): Response {
  return new Response(raw, { status: 200, headers: { 'Content-Type': 'application/json' } });
}

describe('actual C++ v2 child through PostgreSQL, Flask and the HTTP client', () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it.each(generated)(
    'preserves generated %s through the bounded client and strict parser',
    async (stem, earlyStatus, earlyReason, consumptionStatus, consumptionReason, nodeCount, mode, captureId) => {
      // Catches a client dropping retained early failures, confusing early/final
      // status, coercing Decimal8, or losing an actual generated node/field.
      const raw = captured(stem, 'generated');
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(respond(raw));
      const result = await getConfigurationInspection('trend', 'BOOK');
      const original = JSON.parse(readFileSync(
        `../algolens-api/tests/fixtures/configuration_inspection_cpp_v2/${stem}.jsonb.txt`, 'utf8'));
      expect(result.api_version).toBe(1);
      expect(result.scope).toEqual({ registry_id: 'trend', portfolio_id: 'BOOK' });
      expect([result.status, result.reason]).toEqual([earlyStatus, earlyReason]);
      expect(result.publication).toEqual(original);
      const publication = result.publication;
      if (!publication || publication.publication_schema_version !== 2) throw new Error('Expected retained v2 publication');
      expect(publication.identity).toMatchObject({
        registry_id: 'trend', registry_revision: 0, engine_strategy_id: 'LIVE_TREND',
        portfolio_id: 'BOOK', run_date: '2026-09-22', producer_version: 'local-test',
        control_mode: mode, capture_id: captureId, publication_id: captureId,
      });
      expect(publication.identity.runtime_attempt_id).toBe(mode === 'controlled' ? captureId : null);
      expect([publication.status, publication.reason]).toEqual([earlyStatus, earlyReason]);
      expect([publication.consumption.status, publication.consumption.reason]).toEqual([
        consumptionStatus, consumptionReason,
      ]);
      expect(publication.consumption.nodes).toHaveLength(nodeCount);
      expect(Object.keys(publication.consumption.coverage)).toHaveLength(8);
      expect(publication.consumption.coverage.control_flow).toEqual(
        consumptionStatus === 'partial' ? { status: 'partial', reason: 'nonfatal_error' }
          : consumptionStatus === 'unavailable' ? { status: 'unavailable', reason: 'instrumentation_missing' }
            : { status: 'complete', reason: 'none' });
      if (earlyStatus === 'unavailable') {
        expect(publication.supplied).toBeNull();
        expect(publication.selected_trend).toBeNull();
        expect(publication.consumption.status).toBe('complete');
        expect(publication.consumption.coverage).toEqual({
          setup: { status: 'complete', reason: 'none' },
          control_flow: { status: 'complete', reason: 'none' },
          market_input: { status: 'complete', reason: 'none' },
          preparation: { status: 'complete', reason: 'none' },
          primary: { status: 'complete', reason: 'none' },
          execution: { status: 'complete', reason: 'none' },
          cost_history: { status: 'complete', reason: 'none' },
          diagnostics: { status: 'complete', reason: 'none' },
        });
      } else {
        expect(publication.supplied?.fields.find(row => row.path === '/initial_capital')?.value).toBe(500000);
        expect(publication.selected_trend?.strategies[0].strategy_id).toBe('TREND');
      }
      if (nodeCount) {
        const diagnostics = publication.consumption.nodes.filter(node => node.consumer === 'risk.diagnostics');
        expect(diagnostics).toHaveLength(1);
        expect(diagnostics[0].reads.filter(row => row.field === 'risk.capital')).toEqual([{
          field: 'risk.capital', value_type: 'fixed_decimal8',
          value: '-92233720368.54775808', origin: 'derived',
        }]);
      }
    },
  );

  it.each(refusals)('keeps actual Flask refusal %s fixed and publication-free', async (stem, reason) => {
    // These bytes came from explicitly mutated SQL fixtures, never the ten
    // generated publications. A malformed newest row cannot fall back.
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(respond(captured(stem, 'synthetic-negative-mutation')));
    const result = await getConfigurationInspection('trend', 'BOOK');
    expect(result.api_version).toBe(1);
    expect(result.scope).toEqual({ registry_id: 'trend', portfolio_id: 'BOOK' });
    expect([result.status, result.reason, result.publication]).toEqual(['unavailable', reason, null]);
  });

  it('continues to accept the existing v1 authenticated HTTP fixture', async () => {
    // Catches a v2-only change accidentally removing the v1 dispatch path.
    const raw = readFileSync('src/infrastructure/api/__fixtures__/configurationInspectionHttp.json', 'utf8');
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(respond(raw));
    const result = await getConfigurationInspection('trend', 'BOOK');
    expect(result.publication?.publication_schema_version).toBe(1);
    expect(result.publication?.consumption).toEqual({ status: 'not_collected' });
  });
});
