// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  aggregatePortfolioTotals,
  sanitizePositionStrategyNames,
  PortfolioApiService,
} from './portfolioApi';

afterEach(() => vi.unstubAllGlobals());

describe('strategy position stream requests', () => {
  const response = (body: unknown) => new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
  });

  it('defaults a detail request to system and carries the proven response stream', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      id: 'trendfollowing', portfolio_id: 'BASE_PORTFOLIO',
      positionStream: 'system', positionStrategyNames: ['MODEL_A'], positions: [],
    }));
    vi.stubGlobal('fetch', fetchMock);

    const detail = await PortfolioApiService.getStrategy('trendfollowing', 'BASE_PORTFOLIO');

    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.pathname).toBe('/portfolio/strategy/trendfollowing');
    expect(url.searchParams.get('portfolio_id')).toBe('BASE_PORTFOLIO');
    expect(url.searchParams.getAll('position_stream')).toEqual(['system']);
    expect(detail.positionStream).toBe('system');
  });

  it('sends an explicit QT detail request without changing its response identity', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      id: 'trendfollowing', portfolio_id: 'BASE_PORTFOLIO',
      positionStream: 'qt', positionStrategyNames: ['QT_A'], positions: [],
    }));
    vi.stubGlobal('fetch', fetchMock);

    const detail = await PortfolioApiService.getStrategy('trendfollowing', 'BASE_PORTFOLIO', 'qt');

    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.searchParams.getAll('position_stream')).toEqual(['qt']);
    expect(detail.positionStream).toBe('qt');
  });

  it('loads dashboard aggregates from the system model explicitly', async () => {
    const urls: URL[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = new URL(String(input));
      urls.push(url);
      if (url.pathname.endsWith('/portfolio/strategies')) {
        return response({ strategies: [{ id: 'trendfollowing', name: 'Trend Following' }] });
      }
      return response({
        id: 'trendfollowing', portfolio_id: 'BASE_PORTFOLIO', positionStream: 'system',
        positionStrategyNames: ['MODEL_A'], positions: [], dataAvailable: true,
        invested: 100, currentValue: 110, historicalData: [],
      });
    }));

    const portfolio = await PortfolioApiService.getPortfolioData();

    expect(urls.filter(url => url.pathname.endsWith('/portfolio/strategy/trendfollowing'))
      .map(url => url.searchParams.getAll('position_stream'))).toEqual([['system']]);
    expect(portfolio.strategies[0].positionStream).toBe('system');
  });
});

describe('exact position transport', () => {
  it('keeps exact companions in a QT detail response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      id: 'trendfollowing', positionStream: 'qt', positionStrategyNames: ['Engine A'],
      positions: [{ symbol: 'ES', shares: 92233720368.12346,
        quantity_exact: '92233720368.12345678', costBasis: 92233720368.12346,
        average_price_exact: '92233720368.12345678' }],
    }))));
    const detail = await PortfolioApiService.getStrategy('trendfollowing', 'MACRO_BOOK', 'qt');
    expect(detail.positions[0].quantity_exact).toBe('92233720368.12345678');
    expect(detail.positions[0].average_price_exact).toBe('92233720368.12345678');
  });

  it('writes exact quantity and price as JSON strings through the actual client', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ risk_check: {
      evaluated: true, passed: true, breaches: [],
    } }), { status: 201 }));
    vi.stubGlobal('fetch', fetchMock);
    await PortfolioApiService.savePosition({
      strategy_id: 'trendfollowing', strategy_name: 'Engine A', portfolio_id: 'MACRO_BOOK',
      symbol: 'ES', quantity: '92233720368.12345678',
      average_price: '92233720368.12345678', reason: 'rebalance',
    });
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body.quantity).toBe('92233720368.12345678');
    expect(body.average_price).toBe('92233720368.12345678');
  });
});

describe('strategy detail position identities', () => {
  it('deduplicates valid identities without changing their opaque text', () => {
    expect(sanitizePositionStrategyNames([
      ' Engine A ',
      ' Engine A ',
      'Engine A',
      'Engine B',
    ])).toEqual([' Engine A ', 'Engine A', 'Engine B']);
  });

  it('fails the whole field closed when any entry is invalid', () => {
    expect(sanitizePositionStrategyNames(['Engine A', null])).toEqual([]);
    expect(sanitizePositionStrategyNames(['Engine A', '   '])).toEqual([]);
    expect(sanitizePositionStrategyNames(['Engine A', 42])).toEqual([]);
  });

  it('fails closed when the response field is absent or not an array', () => {
    expect(sanitizePositionStrategyNames(undefined)).toEqual([]);
    expect(sanitizePositionStrategyNames('Engine A')).toEqual([]);
  });
});

describe('portfolio return aggregation', () => {
  it('withholds return figures when any included starting equity is unknown', () => {
    const totals = aggregatePortfolioTotals([
      { dataAvailable: true, invested: 100_000, currentValue: 110_000 },
      { dataAvailable: true, invested: null, currentValue: 100_000 },
    ]);

    expect(totals).toEqual({
      totalValue: 210_000,
      totalInvested: 100_000,
      totalReturn: null,
      totalReturnPercent: null,
    });
  });

  it('retains numeric return figures when every included basis is known', () => {
    const totals = aggregatePortfolioTotals([
      { dataAvailable: true, invested: 100_000, currentValue: 110_000 },
      { dataAvailable: true, invested: 50_000, currentValue: 55_000 },
      { dataAvailable: false, invested: null, currentValue: 0 },
    ]);

    expect(totals).toEqual({
      totalValue: 165_000,
      totalInvested: 150_000,
      totalReturn: 15_000,
      totalReturnPercent: 10,
    });
  });
});
