import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { InspectionProtocolError, parseConfigurationInspection, UnsupportedNumericRepresentationError } from './configurationInspection';

const fixture = readFileSync(new URL('../../../../algolens-api/tests/fixtures/configuration_inspection_v1.json', import.meta.url), 'utf8');
const response = (publication: unknown) => JSON.stringify({
  api_version: 1, scope: { registry_id: 'trend', portfolio_id: 'BOOK' },
  read_at: '2026-09-22T15:02:00Z', status: 'available', reason: 'none', publication,
});
const rawResponse = (publicationText: string) => response(null).replace('"publication":null', `"publication":${publicationText}`);

describe('configuration inspection protocol', () => {
  it('accepts the complete hand-specified v1 catalog and distinct selected stages', () => {
    const result = parseConfigurationInspection(response(JSON.parse(fixture)), 'trend', 'BOOK');
    expect(result.publication?.supplied?.fields).toHaveLength(57);
    expect(result.publication?.selected_trend?.strategies[0].factory_resolved.vol_lookback_long).toBe(60);
    expect(result.publication?.selected_trend?.strategies[0].constructor_normalized.vol_lookback_long).toBe(64);
  });

  it('rejects missing and extra catalog rows, scope mismatch and unsupported versions', () => {
    const publication = JSON.parse(fixture);
    publication.supplied.fields.pop();
    expect(() => parseConfigurationInspection(response(publication), 'trend', 'BOOK')).toThrow();
    publication.supplied.fields.push({ path: '/private', value: 'secret' });
    expect(() => parseConfigurationInspection(response(publication), 'trend', 'BOOK')).toThrow();
    expect(() => parseConfigurationInspection(response(JSON.parse(fixture)), 'trend', 'OTHER')).toThrow();
    publication.publication_schema_version = 2;
    expect(() => parseConfigurationInspection(response(publication), 'trend', 'BOOK')).toThrow();
  });

  it('rejects a non-string catalog descriptor even when join would coerce it to expected text', () => {
    const publication = JSON.parse(fixture);
    const row = publication.supplied.fields.find((field: { path: string }) => field.path === '/initial_capital');
    row.classification = ['source_supported_config_input'];
    expect(() => parseConfigurationInspection(response(publication), 'trend', 'BOOK'))
      .toThrow(InspectionProtocolError);
  });

  it.each(['9007199254740991', '9007199254740992', '9007199254740993', '18446744073709551615'])(
    'never rounds raw max_history_size token %s', value => {
      const raw = response(JSON.parse(fixture)).replace('"max_history_size":500', `"max_history_size":${value}`);
      if (value === '9007199254740991') {
        expect(parseConfigurationInspection(raw, 'trend', 'BOOK').publication?.selected_trend?.strategies[0].factory_resolved.max_history_size).toBe(Number(value));
      } else {
        expect(() => parseConfigurationInspection(raw, 'trend', 'BOOK')).toThrow(UnsupportedNumericRepresentationError);
      }
    },
  );

  it.each([
    ['max_history_size', '"max_history_size":500', '"max_history_size":9007199254740991.1'],
    ['root version', '"api_version":1', '"api_version":1.0'],
    ['publication version', '"publication_schema_version":1', '"publication_schema_version":1e0'],
    ['registry revision', '"registry_revision":1', '"registry_revision":1.0'],
    ['projection version', '"projection_version":1', '"projection_version":1e0'],
    ['selected stage version', '"schema_version":1', '"schema_version":1.0'],
    ['integer pair member', '"value":[[1,1]', '"value":[[1.0,1]'],
  ])('refuses a fractional or exponent lexical token in integer-typed %s', (_name, before, after) => {
    const raw = response(JSON.parse(fixture));
    expect(raw).toContain(before);
    expect(() => parseConfigurationInspection(raw.replace(before, after), 'trend', 'BOOK'))
      .toThrow(InspectionProtocolError);
  });

  it('applies integer spelling to supplied scalar inputs as well as selected stage pairs', () => {
    const raw = response(JSON.parse(fixture));
    const scalar = raw.replace(/("path":"\/backtest\/lookback_years"[^}]*"value":)2(?=[,}])/, (_all, prefix: string) => `${prefix}2.0`);
    const pair = raw.replace('"ema_windows":[[8,32]', '"ema_windows":[[8e0,32]');
    expect(scalar).not.toBe(raw);
    expect(pair).not.toBe(raw);
    expect(() => parseConfigurationInspection(scalar, 'trend', 'BOOK')).toThrow(InspectionProtocolError);
    expect(() => parseConfigurationInspection(pair, 'trend', 'BOOK')).toThrow(InspectionProtocolError);
  });

  it('bounds exact received publication whitespace at 2 MiB, including escaped keys and strings', () => {
    const child = fixture.trim().replace('"producer_version":"synthetic.test-1"',
      '"producer_version":"synthetic\\u002etest-1"');
    const baseBytes = new TextEncoder().encode(child).byteLength;
    expect(baseBytes).toBeLessThan(2 * 1024 * 1024);
    const padded = (bytes: number) => child.replace('{', `{${' '.repeat(bytes - baseBytes)}`);
    const atLimit = rawResponse(padded(2 * 1024 * 1024))
      .replace('"publication":', '"\\u0070ublication":');
    expect(parseConfigurationInspection(atLimit, 'trend', 'BOOK').publication?.identity.producer_version)
      .toBe('synthetic.test-1');
    expect(() => parseConfigurationInspection(rawResponse(padded(2 * 1024 * 1024 + 1)), 'trend', 'BOOK'))
      .toThrow(InspectionProtocolError);
    expect(parseConfigurationInspection(response(null).replace('"status":"available","reason":"none"',
      '"status":"unavailable","reason":"not_published"'), 'trend', 'BOOK').publication).toBeNull();
  });

  it.each(['2026-02-30T12:00:00Z', '2026-04-31T12:00:00Z', '2026-13-01T12:00:00Z',
    '2026-09-22T24:00:00Z', '0000-01-01T12:00:00Z'])(
    'rejects impossible UTC calendar time %s instead of normalizing it', bad => {
      const publication = JSON.parse(fixture);
      publication.captured_at = bad;
      expect(() => parseConfigurationInspection(response(publication), 'trend', 'BOOK'))
        .toThrow(InspectionProtocolError);
    },
  );

  it('accepts leap day and preserves microsecond text but rejects reversed sub-millisecond order', () => {
    const publication = JSON.parse(fixture);
    publication.identity.run_date = '2024-02-29';
    publication.captured_at = '2024-02-29T12:00:00.123456Z';
    publication.publication_recorded_at = '2024-02-29T12:00:00.123457Z';
    const parsed = parseConfigurationInspection(response(publication), 'trend', 'BOOK');
    expect(parsed.publication?.captured_at).toBe('2024-02-29T12:00:00.123456Z');
    publication.captured_at = '2024-02-29T12:00:00.123458Z';
    expect(() => parseConfigurationInspection(response(publication), 'trend', 'BOOK'))
      .toThrow(InspectionProtocolError);
  });

  it('requires coherent unavailable results with no value stages', () => {
    const result = parseConfigurationInspection(JSON.stringify({
      api_version: 1, scope: { registry_id: 'trend', portfolio_id: 'BOOK' },
      read_at: '2026-09-22T15:02:00Z', status: 'unavailable',
      reason: 'legacy_publication', publication: null,
    }), 'trend', 'BOOK');
    expect(result.publication).toBeNull();
    expect(result.reason).toBe('legacy_publication');
  });

  it.each(['projection_invalid', 'selected_stage_unavailable', 'capture_failed'])(
    'requires a bound publication for producer reason %s', reason => {
      const nullBody = response(null).replace('"status":"available","reason":"none"',
        `"status":"unavailable","reason":"${reason}"`);
      expect(() => parseConfigurationInspection(nullBody, 'trend', 'BOOK'))
        .toThrow(InspectionProtocolError);
      const publication = { ...JSON.parse(fixture), status: 'unavailable', reason,
        supplied: null, selected_trend: null };
      const boundBody = response(publication).replace('"status":"available","reason":"none"',
        `"status":"unavailable","reason":"${reason}"`);
      expect(parseConfigurationInspection(boundBody, 'trend', 'BOOK').publication?.reason).toBe(reason);
    },
  );

  it('rejects duplicate keys before JSON materialization, including nested fields', () => {
    const raw = response(JSON.parse(fixture));
    expect(() => parseConfigurationInspection(raw.replace('"api_version":1', '"api_version":1,"api_version":1'), 'trend', 'BOOK')).toThrow();
    expect(() => parseConfigurationInspection(raw.replace('"scope":"exact"', '"scope":"exact","scope":"exact"'), 'trend', 'BOOK')).toThrow();
    expect(() => parseConfigurationInspection(raw.replace('"api_version":1',
      '"api_version":1,"\\u0061pi_version":1'), 'trend', 'BOOK')).toThrow(InspectionProtocolError);
  });

  it('rejects literal non-ASCII text outside the closed v1 identifier catalog', () => {
    const raw = response(JSON.parse(fixture)).replace('"producer_version":"synthetic.test-1"',
      '"producer_version":"café"');
    expect(() => parseConfigurationInspection(raw, 'trend', 'BOOK')).toThrow(InspectionProtocolError);
  });

  it('rejects a publication child beyond 2 MiB even inside an allowed outer response', () => {
    const publication = JSON.parse(fixture);
    publication.supplied.fields.find((field: { path: string }) => field.path === '/strategy_defaults/fdm').value =
      Array.from({ length: 360000 }, () => [1, 1]);
    expect(() => parseConfigurationInspection(response(publication), 'trend', 'BOOK')).toThrow();
  });

  it('accepts canonical UUIDs permitted by the API validator without inventing version bits', () => {
    const publication = JSON.parse(fixture);
    const canonical = '00000000-0000-0000-0000-000000000000';
    publication.identity.capture_id = canonical;
    publication.identity.publication_id = canonical;
    publication.identity.runtime_attempt_id = canonical;
    expect(parseConfigurationInspection(response(publication), 'trend', 'BOOK').publication?.identity.capture_id).toBe(canonical);
  });
});
