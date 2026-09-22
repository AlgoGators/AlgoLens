// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from 'vitest';

const http = vi.hoisted(() => ({
  fetchWithAuth: vi.fn(),
  postWithAuth: vi.fn(),
}));

vi.mock('./httpClient', () => ({
  API_BASE_URL: 'http://api.test',
  fetchWithAuth: http.fetchWithAuth,
  postWithAuth: http.postWithAuth,
  putWithAuth: vi.fn(),
  deleteWithAuth: vi.fn(),
  log: vi.fn(),
}));

import { PortfolioApiService } from './portfolioApi';

beforeEach(() => {
  http.fetchWithAuth.mockReset();
  http.postWithAuth.mockReset();
});

describe('lifecycle API', () => {
  it('reads lifecycle history from the lifecycle-blind endpoint', async () => {
    const history = [{
      id: 2, strategy_id: 'retired/trend', before_state: 'live',
      after_state: 'retired', reason: 'review', user_id: '7',
      created_at: '2026-09-22T12:00:00Z',
    }];
    http.fetchWithAuth.mockResolvedValue({ json: async () => ({ history }) });

    await expect(PortfolioApiService.getLifecycleHistory('retired/trend')).resolves.toEqual(history);
    expect(http.fetchWithAuth).toHaveBeenCalledWith(
      'http://api.test/portfolio/strategies/retired%2Ftrend/lifecycle/history',
    );
  });

  it('turns stable closure codes into safe user messages', async () => {
    http.postWithAuth.mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ error: 'open_positions' }),
    });

    const result = await PortfolioApiService.changeIncubation(
      'trend', 'retire', { reason: 'review' },
    );

    expect(result).toEqual({
      outcome: 'rejected',
      message: 'Close every effective position in every book before changing this lifecycle.',
    });
  });

  it('does not display an unknown server or SQL error', async () => {
    http.postWithAuth.mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ error: 'relation trading.positions password=secret' }),
    });

    const result = await PortfolioApiService.changeIncubation(
      'trend', 'retire', { reason: 'review' },
    );

    expect(result).toEqual({
      outcome: 'rejected',
      message: 'The lifecycle change was rejected. Refresh and try again.',
    });
  });
});
