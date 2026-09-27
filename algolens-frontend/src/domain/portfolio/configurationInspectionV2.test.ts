import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { InspectionProtocolError, parseConfigurationInspection, UnsupportedNumericRepresentationError } from './configurationInspection';

// Hand-specified synthetic fixtures; these are not C++ or PostgreSQL captures.
const earlyFixture = JSON.parse(readFileSync(new URL(
  '../../../../algolens-api/tests/fixtures/configuration_inspection_v1.json', import.meta.url), 'utf8'));
const cases = JSON.parse(readFileSync(new URL('../../../../contracts/consumption-v2-cases.json', import.meta.url), 'utf8'));

const publication = (consumption: unknown) => ({
  ...structuredClone(earlyFixture), publication_schema_version: 2, consumption,
});
const response = (child: unknown) => JSON.stringify({
  api_version: 1, scope: { registry_id: 'trend', portfolio_id: 'BOOK' },
  read_at: '2026-09-22T15:02:00Z', status: 'available', reason: 'none',
  publication: publication(child),
});
const envelope = (pub: Record<string, unknown>) => JSON.stringify({
  api_version: 1, scope: { registry_id: 'trend', portfolio_id: 'BOOK' },
  read_at: '2026-09-22T15:02:00Z', status: pub.status, reason: pub.reason,
  publication: pub,
});
const invalid = (raw: string) => {
  try {
    parseConfigurationInspection(raw, 'trend', 'BOOK');
    throw new Error('Malformed publication was accepted');
  } catch (error) {
    expect(error).toBeInstanceOf(InspectionProtocolError);
    expect((error as Error).message).toBe('Published configuration response is unavailable.');
  }
};
type TestChild = { nodes: Array<{ reads: Array<{ field: string; value: unknown }> }> };
const changed = (child: unknown, field: string, value: unknown) => {
  const copy = structuredClone(child) as TestChild;
  const read = copy.nodes.flatMap(node => node.reads).find(row => row.field === field);
  expect(read).toBeDefined();
  read!.value = value;
  return copy;
};
const rawNumber = (child: unknown, field: string, original: number, token: string) => {
  const copy = changed(child, field, original);
  const raw = response(copy);
  const needle = `"field":"${field}","value_type":"number","value":${original}`;
  expect(raw).toContain(needle);
  return raw.replace(needle, `"field":"${field}","value_type":"number","value":${token}`);
};

describe('configuration inspection v2 envelope (synthetic)', () => {
  it('admits and preserves a complete observed consumption child', () => {
    const child = cases.accepted.ordinary;
    const parsed = parseConfigurationInspection(response(child), 'trend', 'BOOK');
    expect(parsed.publication?.publication_schema_version).toBe(2);
    expect(parsed.publication?.consumption).toEqual(child);
    expect(parsed.publication?.supplied).toEqual(earlyFixture.supplied);
    expect(parsed.publication?.selected_trend).toEqual(earlyFixture.selected_trend);
  });

  it.each(Object.entries(cases.accepted).flatMap(([name, child]) =>
    (['controlled', 'uncontrolled'] as const).flatMap(mode =>
      (['available', 'unavailable'] as const).map(early => ({ name, child, mode, early })),
    ),
  ))('preserves accepted $name, $mode capture, and $early early status', ({ child, mode, early }) => {
    const pub = publication(child);
    pub.identity.control_mode = mode;
    pub.identity.runtime_attempt_id = mode === 'controlled' ? pub.identity.publication_id : null;
    if (early === 'unavailable') {
      pub.status = 'unavailable'; pub.reason = 'capture_failed';
      pub.supplied = null; pub.selected_trend = null;
    }
    const raw = envelope(pub);
    const before = JSON.stringify(pub);
    const parsed = parseConfigurationInspection(raw, 'trend', 'BOOK');
    expect(parsed).toEqual(JSON.parse(raw));
    expect(parsed.publication?.consumption).toEqual(child);
    expect(parsed.publication?.status).toBe(early);
    expect(JSON.stringify(pub)).toBe(before);
    expect(parseConfigurationInspection(raw, 'trend', 'BOOK')).toEqual(parsed);
  });

  for (const testCase of cases.rejected as Array<{
    name: string;
    base: string; path?: string; value?: unknown; append_to?: string; item?: unknown;
  }>) it(`rejects shared malformed child ${testCase.name} through a full response`, () => {
    const child = structuredClone(cases.accepted[testCase.base]);
    const path = (testCase.path ?? testCase.append_to)!.split('.');
    let target = child;
    for (const step of path.slice(0, -1)) target = target[step];
    if (testCase.append_to) target[path.at(-1)!].push(testCase.item);
    else target[path.at(-1)!] = testCase.value;
    invalid(response(child));
  });

  it('rejects cross-version contamination, version 3, profile changes, and bad root/child shapes', () => {
    const oldWithNew = structuredClone(earlyFixture);
    oldWithNew.consumption = structuredClone(cases.accepted.ordinary);
    invalid(envelope(oldWithNew));
    invalid(response({ status: 'not_collected' }));
    const v3 = publication(cases.accepted.ordinary);
    v3.publication_schema_version = 3;
    invalid(envelope(v3));
    const badProfile = publication(cases.accepted.ordinary);
    badProfile.profile = 'other';
    invalid(envelope(badProfile));
    const badRoot = JSON.parse(response(cases.accepted.ordinary));
    badRoot.extra = true;
    invalid(JSON.stringify(badRoot));
    invalid(response(null));
  });

  it('rejects duplicate raw keys at the child root and nested reads, including escaped spelling', () => {
    const raw = response(cases.accepted.ordinary);
    expect(raw).toContain('"consumption":{"version":2');
    invalid(raw.replace('"consumption":{"version":2',
      '"consumption":{"version":2,"\\u0076ersion":2'));
    const needle = '"value":0.5,"origin":"configured_strategy_leaf"';
    expect(raw).toContain(needle);
    invalid(raw.replace(needle, '"value":0.5,"\\u0076alue":0.5,"origin":"configured_strategy_leaf"'));
    invalid(raw.replace('"publication":', '"publication":null,"\\u0070ublication":'));
  });

  it('keeps scope, identity, date, time, and early validation independent of valid consumption', () => {
    const pub = publication(cases.accepted.ordinary);
    invalid(envelope(pub).replace('"portfolio_id":"BOOK"', '"portfolio_id":"OTHER"'));
    for (const mutate of [
      (row: Record<string, any>) => { row.identity.capture_id = 'bad'; },
      (row: Record<string, any>) => { row.identity.run_date = '2026-02-30'; },
      (row: Record<string, any>) => { row.captured_at = '2026-09-22T15:03:00Z'; },
      (row: Record<string, any>) => { row.publication_recorded_at = '2026-09-22T14:59:00Z'; },
      (row: Record<string, any>) => { row.identity.runtime_attempt_id = null; },
      (row: Record<string, any>) => { row.supplied.fields.pop(); },
      (row: Record<string, any>) => { row.selected_trend.schema_version = 2; },
    ]) {
      const bad = publication(cases.accepted.ordinary);
      mutate(bad);
      invalid(envelope(bad));
    }
  });

  it('admits finite signed ordinary child numbers above the safe integer range', () => {
    for (const token of ['9007199254740992', '-9007199254740992']) {
      const raw = rawNumber(cases.accepted.rich, 'cost.impact.min_adv', 100, token);
      const parsed = parseConfigurationInspection(raw, 'trend', 'BOOK');
      const consumption = parsed.publication?.publication_schema_version === 2
        ? parsed.publication.consumption : undefined;
      const read = consumption?.nodes.flatMap(node => node.reads)
        .find(row => row.field === 'cost.impact.min_adv');
      expect(read?.value).toBe(Number(token));
    }
    const pair = response(cases.accepted.rich).replace('"value":[[1,-0.5]]',
      '"value":[[1,9007199254740992]]');
    expect(pair).not.toBe(response(cases.accepted.rich));
    expect(() => parseConfigurationInspection(pair, 'trend', 'BOOK')).not.toThrow();
  });

  it('rejects unsafe integers in v2 child integer/dimension and unchanged early contexts', () => {
    invalid(response(changed(cases.accepted.ordinary, 'cost.impact_history.adv_lookback_days',
      9007199254740992)));
    invalid(response(changed(cases.accepted.ordinary, 'runner.market_input.historical_days',
      9007199254740992)));
    const badNode = response(cases.accepted.ordinary).replace('"id":0,"parent":null',
      '"id":9007199254740992,"parent":null');
    expect(badNode).not.toBe(response(cases.accepted.ordinary));
    invalid(badNode);
    const early = publication(cases.accepted.ordinary);
    early.selected_trend.strategies[0].factory_resolved.max_history_size = 9007199254740992;
    expect(() => parseConfigurationInspection(envelope(early), 'trend', 'BOOK'))
      .toThrow(UnsupportedNumericRepresentationError);
    const root = response(cases.accepted.ordinary).replace('"api_version":1',
      '"api_version":9007199254740992');
    expect(() => parseConfigurationInspection(root, 'trend', 'BOOK'))
      .toThrow(UnsupportedNumericRepresentationError);
    const malformed = structuredClone(cases.accepted.rich);
    malformed.extra = true;
    invalid(rawNumber(malformed, 'cost.impact.min_adv', 100, '9007199254740992'));
  });

  it('retains the v1 raw unsafe-integer refusal when publication is null', () => {
    const raw = JSON.stringify({
      api_version: 1, scope: { registry_id: 'trend', portfolio_id: 'BOOK' },
      read_at: '2026-09-22T15:02:00Z', status: 'unavailable',
      reason: 'not_published', publication: null,
    }).replace('"api_version":1', '"api_version":9007199254740992');
    expect(() => parseConfigurationInspection(raw, 'trend', 'BOOK'))
      .toThrow(UnsupportedNumericRepresentationError);
  });

  it('accepts integral float spellings in v2 child fields and preserves v1 spelling rules', () => {
    let raw = response(cases.accepted.ordinary);
    raw = raw.replace('"id":0,"parent":null', '"id":0.0,"parent":null');
    raw = raw.replace('"field":"runner.market_input.historical_days","value_type":"int32","value":30',
      '"field":"runner.market_input.historical_days","value_type":"int32","value":30.0');
    raw = raw.replace('"field":"cost.impact_history.adv_lookback_days","value_type":"uint53","value":20',
      '"field":"cost.impact_history.adv_lookback_days","value_type":"uint53","value":20e0');
    expect(() => parseConfigurationInspection(raw, 'trend', 'BOOK')).not.toThrow();
    const pair = response(cases.accepted.rich).replace('"value":[[1,-0.5]]',
      '"value":[[1.0,-0.5]]');
    expect(pair).not.toBe(response(cases.accepted.rich));
    expect(() => parseConfigurationInspection(pair, 'trend', 'BOOK')).not.toThrow();
    invalid(envelope(earlyFixture).replace('"publication_schema_version":1',
      '"publication_schema_version":1.0'));
  });

  it('rejects nonfinite, string, boolean, and out-of-range numeric substitutions', () => {
    for (const token of ['1e999', '"100"', 'true']) {
      invalid(rawNumber(cases.accepted.rich, 'cost.impact.min_adv', 100, token));
    }
    invalid(response(changed(cases.accepted.ordinary, 'runner.market_input.historical_days', 2147483648)));
    invalid(response(changed(cases.accepted.ordinary, 'cost.impact_history.adv_lookback_days', -1)));
  });

  it('preserves exact Decimal endpoints and rejects adjacent scaled units', () => {
    const rich = cases.accepted.rich;
    const result = parseConfigurationInspection(response(rich), 'trend', 'BOOK');
    const consumption = result.publication?.publication_schema_version === 2
      ? result.publication.consumption : undefined;
    const decimals = consumption?.nodes.flatMap(node => node.reads)
      .filter(row => row.value_type === 'fixed_decimal8').map(row => row.value);
    expect(decimals).toContain('92233720368.54775807');
    expect(decimals).toContain('-92233720368.54775808');
    invalid(response(changed(rich, 'strategy.base_risk.risk_max_leverage', '92233720368.54775808')));
    invalid(response(changed(rich, 'portfolio.optimization.total_capital', '-92233720368.54775809')));
  });

  it('caps the exact received v2 publication span, including escaped member spelling', () => {
    const pubText = JSON.stringify(publication(cases.accepted.ordinary));
    const cap = 2 * 1024 * 1024;
    const base = new TextEncoder().encode(pubText).byteLength;
    const wrap = (text: string) => envelope(publication(cases.accepted.ordinary))
      .replace(/"publication":\{.*\}$/, `"\\u0070ublication":${text}}`);
    const at = pubText.replace('{', `{${' '.repeat(cap - base)}`);
    expect(new TextEncoder().encode(at).byteLength).toBe(cap);
    expect(() => parseConfigurationInspection(wrap(at), 'trend', 'BOOK')).not.toThrow();
    const over = pubText.replace('{', `{${' '.repeat(cap - base + 1)}`);
    invalid(wrap(over));
  });

  it('rejects a compact combined publication above 2 MiB although the received span fits', () => {
    const pub = publication(cases.accepted.ordinary);
    const row = pub.supplied.fields.find((field: { path: string }) => field.path === '/strategy_defaults/fdm');
    row.value = [];
    const cap = 2 * 1024 * 1024;
    const base = new TextEncoder().encode(JSON.stringify(pub)).byteLength;
    row.value = [[1, 1000000]];
    const first = new TextEncoder().encode(JSON.stringify(pub)).byteLength - base;
    row.value = [[1, 1000000], [1, 1000000]];
    const perAdditionalPair = new TextEncoder().encode(JSON.stringify(pub)).byteLength - base - first;
    const count = 1 + Math.ceil((cap + 1 - base - first) / perAdditionalPair);
    row.value = Array.from({ length: count }, () => [1, 1000000]);
    const compact = envelope(pub);
    const raw = compact.replaceAll('[1,1000000]', '[1,1e6]');
    const span = raw.slice(raw.indexOf('"publication":') + '"publication":'.length, -1);
    const earlyOnly = structuredClone(pub);
    earlyOnly.publication_schema_version = 1;
    earlyOnly.consumption = { status: 'not_collected' };
    expect(new TextEncoder().encode(span).byteLength).toBeLessThanOrEqual(cap);
    expect(new TextEncoder().encode(JSON.stringify(pub)).byteLength).toBeGreaterThan(cap);
    expect(new TextEncoder().encode(JSON.stringify(earlyOnly)).byteLength).toBeLessThan(cap);
    expect(new TextEncoder().encode(JSON.stringify(pub.consumption)).byteLength).toBeLessThan(cap);
    expect(() => parseConfigurationInspection(envelope(earlyOnly), 'trend', 'BOOK')).not.toThrow();
    invalid(raw);
  });
});
