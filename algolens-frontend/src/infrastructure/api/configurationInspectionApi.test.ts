// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getConfigurationInspection, InspectionReadError } from './configurationInspectionApi';
import { SessionExpiredError } from './httpClient';
import { UnsupportedNumericRepresentationError } from '../../domain/portfolio/configurationInspection';

const fixture = readFileSync('../algolens-api/tests/fixtures/configuration_inspection_v1.json', 'utf8');
const authenticatedHttpBody = readFileSync('src/infrastructure/api/__fixtures__/configurationInspectionHttp.json', 'utf8');
const body = () => JSON.stringify({
  api_version: 1, scope: { registry_id: 'trend', portfolio_id: 'BOOK' },
  read_at: '2026-09-22T15:02:00Z', status: 'available', reason: 'none',
  publication: JSON.parse(fixture),
});
const json = (value = body(), status = 200) => new Response(value, {
  status, headers: { 'Content-Type': 'application/json' },
});

describe('private configuration inspection read', () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it('accepts the exact authenticated C++ to SQL to API HTTP response', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(authenticatedHttpBody));
    const result = await getConfigurationInspection('trend', 'BOOK');
    expect(result.status).toBe('available');
    expect(result.publication?.identity.producer_version).toBe('local-test');
    expect(result.publication?.identity.capture_id).toBe('68536f43-aae0-4486-867a-99bffd3b7c31');
    expect(result.publication?.supplied?.fields).toHaveLength(57);
    expect(result.publication?.selected_trend?.strategies[0].strategy_id).toBe('TREND');
  });

  it('encodes both scope parts, forwards abort and never retries', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json());
    const signal = new AbortController().signal;
    const result = await getConfigurationInspection('trend', 'BOOK', signal);
    expect(result.publication?.identity.portfolio_id).toBe('BOOK');
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      expect.stringMatching(/\/portfolio\/strategies\/trend\/configuration\?portfolio_id=BOOK$/),
      { method: 'GET', credentials: 'include', cache: 'no-store',
        headers: { Accept: 'application/json', 'Cache-Control': 'no-store' }, signal },
    );
  });

  it('URI-encodes scope text without dropping the explicitly requested book', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json('synthetic', 404));
    await expect(getConfigurationInspection('trend/name', 'BOOK WITH SPACE')).rejects.toBeInstanceOf(InspectionReadError);
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/trend%2Fname\/configuration\?portfolio_id=BOOK%20WITH%20SPACE$/);
  });

  it.each([403, 404, 503])('uses a fixed error on HTTP %i without exposing a response body', async status => {
    const secret = 'PRIVATE-SENTINEL';
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(secret, status));
    const log = vi.spyOn(console, 'error').mockImplementation(() => {});
    await expect(getConfigurationInspection('trend', 'BOOK')).rejects.toBeInstanceOf(InspectionReadError);
    expect(log.mock.calls.join(' ')).not.toContain(secret);
  });

  it.each([401, 422])('preserves shared session expiry on %i', async status => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json('secret', status));
    await expect(getConfigurationInspection('trend', 'BOOK')).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it('rejects HTML, invalid JSON, mismatched scope and oversized content with fixed errors', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    fetchMock.mockResolvedValueOnce(new Response('<secret/>', { headers: { 'Content-Type': 'text/html' } }));
    await expect(getConfigurationInspection('trend', 'BOOK')).rejects.toBeInstanceOf(InspectionReadError);
    fetchMock.mockResolvedValueOnce(json('{'));
    await expect(getConfigurationInspection('trend', 'BOOK')).rejects.toBeInstanceOf(InspectionReadError);
    fetchMock.mockResolvedValueOnce(json(body().replace('"portfolio_id":"BOOK"', '"portfolio_id":"OTHER"')));
    await expect(getConfigurationInspection('trend', 'BOOK')).rejects.toBeInstanceOf(InspectionReadError);
    fetchMock.mockResolvedValueOnce(json(' '.repeat(3 * 1024 * 1024 + 1)));
    await expect(getConfigurationInspection('trend', 'BOOK')).rejects.toBeInstanceOf(InspectionReadError);
  });

  it('stops a streaming body before materializing beyond the limit', async () => {
    const chunk = new Uint8Array(1024 * 1024);
    let delivered = 0;
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) { delivered++; controller.enqueue(chunk); },
    });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(stream, {
      headers: { 'Content-Type': 'application/json' },
    }));
    await expect(getConfigurationInspection('trend', 'BOOK')).rejects.toBeInstanceOf(InspectionReadError);
    expect(delivered).toBeLessThan(8);
  });

  it('preserves the fixed unsupported-numeric refusal for a valid uint64 beyond JS precision', async () => {
    const raw = body().replace('"max_history_size":500', '"max_history_size":18446744073709551615');
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(raw));
    await expect(getConfigurationInspection('trend', 'BOOK')).rejects.toBeInstanceOf(UnsupportedNumericRepresentationError);
  });
});
