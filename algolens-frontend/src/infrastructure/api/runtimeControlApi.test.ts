import { afterEach, expect, it, vi } from 'vitest';
import { RuntimeControlApi } from './runtimeControlApi';

const http = vi.hoisted(() => ({ fetchWithAuth: vi.fn(), postWithAuth: vi.fn() }));
vi.mock('./httpClient', () => ({ API_BASE_URL: 'http://synthetic.invalid', ...http }));
afterEach(() => Object.values(http).forEach(fn => fn.mockReset()));

it('encodes exact scope and never infers enabled approval from missing status fields', async () => {
  http.fetchWithAuth.mockResolvedValue(new Response(JSON.stringify({ enabled: true }), { status: 200 }));
  await expect(RuntimeControlApi.status('strategy/id', 'BOOK X')).rejects.toThrow('Invalid runtime status');
  expect(http.fetchWithAuth).toHaveBeenCalledWith('http://synthetic.invalid/portfolio/strategies/strategy%2Fid/runtime?portfolio_id=BOOK%20X');
});

it('writes a request without a configuration or authoritative approval payload', async () => {
  http.postWithAuth.mockResolvedValue(new Response(JSON.stringify({ intent: { id: 12 } }), { status: 201 }));
  expect(await RuntimeControlApi.request('trend', { action: 'run', portfolio_id: 'BOOK', reason: 'Review' })).toEqual({ outcome: 'saved' });
  expect(http.postWithAuth).toHaveBeenCalledWith('http://synthetic.invalid/portfolio/strategies/trend/runtime/requests',
    { action: 'run', portfolio_id: 'BOOK', reason: 'Review' });
});

it('does not display arbitrary backend failure detail', async () => {
  http.postWithAuth.mockResolvedValue(new Response(JSON.stringify({ code: 'unexpected', error: 'private database detail' }), { status: 409 }));
  const result = await RuntimeControlApi.approve('trend', 12, 'Review');
  expect(result).toEqual({ outcome: 'rejected', message: 'The request was refused. Refresh status before retrying.' });
});

it('treats a server failure or malformed success as uncertain without retrying', async () => {
  for (const status of [200, 503]) {
    http.postWithAuth.mockResolvedValueOnce(new Response('{}', { status }));
    await expect(RuntimeControlApi.approve('trend', 12, 'Review')).rejects.toThrow('Uncertain runtime mutation');
  }
  expect(http.postWithAuth).toHaveBeenCalledTimes(2);
});
