// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PortfolioApiService } from './portfolioApi';
import { ApiError, fetchWithAuth } from './httpClient';

vi.mock('./httpClient', async importOriginal => ({
  ...await importOriginal<typeof import('./httpClient')>(),
  API_BASE_URL: 'http://offline.invalid',
  fetchWithAuth: vi.fn(),
  log: () => {},
}));

const response = (data: unknown) => ({ json: async () => data } as Response);
const summary = {
  id: 'trendfollowing', name: 'Trend Following', dataAvailable: false,
  portfolio_id: 'CONSERVATIVE_PORTFOLIO', books: ['CONSERVATIVE_PORTFOLIO'],
};
const detail = {
  id: summary.id, name: summary.name, description: '', dataAvailable: false,
  resultSource: 'system', resultDate: null, invested: 100000, currentValue: null,
  return: null, returnPercent: null, positions: [{ symbol: 'ES' }],
  positionStrategyNames: ['Engine A'], positionDate: '2026-09-23',
  positionStream: 'system', positionsEditable: false,
  positionEditUnavailableReason: 'Model/system positions are read-only.',
  historicalData: [], historyBreaks: [], bestDay: null, worstDay: null,
  metrics: { sharpeRatio: null, volatility: null }, executions: [],
  finalizedPositions: [], managers: [], lastUpdate: '',
  portfolio_id: summary.portfolio_id, books: summary.books,
};

beforeEach(() => { vi.mocked(fetchWithAuth).mockReset(); });

describe('system-model dashboard reads', () => {
  it('fetches and retains real system positions while disclosing partial totals', async () => {
    const urls: string[] = [];
    vi.mocked(fetchWithAuth).mockImplementation(async url => {
      urls.push(url);
      return response(url.endsWith('/strategies') ? { strategies: [summary] } : detail);
    });

    const portfolio = await PortfolioApiService.getPortfolioData();

    expect(portfolio.strategies[0].positions).toEqual([{ symbol: 'ES' }]);
    expect(portfolio.strategies[0].positionsEditable).toBe(false);
    expect(urls.filter(url => url.includes('/portfolio/strategy/'))).toHaveLength(1);
    expect(urls.some(url => url.includes('position_stream=system'))).toBe(true);
    expect(urls.some(url => url.includes('position_stream=qt'))).toBe(false);
    expect(portfolio.strategies[0].currentValue).toBeNull();
    expect(portfolio.strategiesAwaitingData).toBe(1);
    expect(portfolio.totalValue).toBe(0);
  });

  it('keeps only a real no_data_for_book as an empty placeholder', async () => {
    vi.mocked(fetchWithAuth).mockImplementation(async url => {
      if (url.endsWith('/strategies')) return response({ strategies: [summary] });
      throw new ApiError('not found', 404, 'no_data_for_book');
    });

    const portfolio = await PortfolioApiService.getPortfolioData();

    expect(portfolio.strategies[0].positions).toEqual([]);
    expect(portfolio.strategies[0].currentValue).toBeNull();
    expect(portfolio.strategies[0].portfolio_id).toBe('CONSERVATIVE_PORTFOLIO');
    expect(portfolio.strategies[0].books).toEqual(['CONSERVATIVE_PORTFOLIO']);
    expect(portfolio.strategiesAwaitingData).toBe(1);
  });

  it('does not fall back to QT when the system book has no publication', async () => {
    const urls: string[] = [];
    vi.mocked(fetchWithAuth).mockImplementation(async url => {
      urls.push(url);
      if (url.endsWith('/strategies')) return response({ strategies: [summary] });
      throw new ApiError('not found', 404, 'no_data_for_book');
    });

    const portfolio = await PortfolioApiService.getPortfolioData();

    expect(portfolio.strategies[0].portfolio_id).toBe('CONSERVATIVE_PORTFOLIO');
    expect(portfolio.strategies[0].positionStream).toBeNull();
    expect(portfolio.strategies[0].positions).toEqual([]);
    expect(portfolio.strategies[0].dataAvailable).toBe(false);
    expect(urls.filter(url => url.includes('/portfolio/strategy/'))).toHaveLength(1);
    expect(urls.some(url => url.includes('position_stream=qt'))).toBe(false);
  });

  it('propagates an unrelated detail failure instead of calling it unavailable', async () => {
    vi.mocked(fetchWithAuth).mockImplementation(async url => {
      if (url.endsWith('/strategies')) return response({ strategies: [summary] });
      throw new ApiError('server failed', 500);
    });

    await expect(PortfolioApiService.getPortfolioData()).rejects.toMatchObject({ status: 500 });
  });
});
