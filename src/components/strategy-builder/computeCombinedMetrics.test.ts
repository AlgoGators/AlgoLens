import { describe, it, expect } from 'vitest';
import { computeCombinedMetrics } from './computeCombinedMetrics';
import type { Strategy, StrategyMetrics, Position, FinalizedPosition } from '../../data/portfolioData';

// Minimal builders so tests stay readable. Only the fields the computation reads
// need realistic values; everything else is zeroed.

function metrics(overrides: Partial<StrategyMetrics> = {}): StrategyMetrics {
  return {
    volatility: 0, sharpeRatio: 0, maxDrawdown: 0, winRate: 0, totalTrades: 0,
    avgWin: 0, avgLoss: 0, profitFactor: 0, dailyReturn: 0, cumulativeReturn: 0, annualizedReturn: 0,
    grossLeverage: 0, netLeverage: 0, portfolioLeverage: 0, marginPosted: 0,
    equityToMarginRatio: 0, marginCushion: 0, totalNotional: 0, unrealizedPnL: 0,
    realizedPnL: 0, totalCommissions: 0, netPnL: 0, cashAvailable: 0, currentPortfolioValue: 0,
    ...overrides,
  };
}

function pos(symbol: string, currentValue: number): Position {
  return { symbol, name: symbol, shares: 1, costBasis: currentValue, currentValue };
}

function fin(symbol: string, realizedPnL: number): FinalizedPosition {
  return { symbol, quantity: 1, entryPrice: 0, exitPrice: 0, realizedPnL };
}

function strategy(over: Partial<Strategy> & { id: string }): Strategy {
  return {
    name: over.id,
    description: '',
    invested: 100000,
    currentValue: 100000,
    return: 0,
    returnPercent: 0,
    positions: [],
    historicalData: [],
    bestDay: 0,
    worstDay: 0,
    metrics: metrics(),
    executions: [],
    finalizedPositions: [],
    managers: [],
    lastUpdate: '',
    ...over,
  };
}

describe('computeCombinedMetrics', () => {
  it('returns a zeroed model when nothing is selected', () => {
    const s = strategy({ id: 'a' });
    const out = computeCombinedMetrics([s], []);
    expect(out.totalValue).toBe(0);
    expect(out.totalInvested).toBe(0);
    expect(out.strategies).toEqual([]);
    expect(out.assetAllocation).toEqual([]);
    // The empty branch still supplies placeholder series for the charts.
    expect(out.historicalPerformance).toHaveLength(91);
    expect(out.dailyPnL).toHaveLength(31);
  });

  it('sums invested/value/return across the selected strategies', () => {
    const a = strategy({ id: 'a', invested: 100000, currentValue: 120000 });
    const b = strategy({ id: 'b', invested: 100000, currentValue: 90000 });
    const out = computeCombinedMetrics([a, b], ['a', 'b']);
    expect(out.totalInvested).toBe(200000);
    expect(out.totalValue).toBe(210000);
    expect(out.totalReturn).toBe(10000);
    expect(out.returnPercent).toBeCloseTo(5, 6); // 10000 / 200000
  });

  it('only aggregates the selected subset', () => {
    const a = strategy({ id: 'a', currentValue: 100000 });
    const b = strategy({ id: 'b', currentValue: 999999 });
    const out = computeCombinedMetrics([a, b], ['a']);
    expect(out.totalValue).toBe(100000);
    expect(out.strategies.map(s => s.id)).toEqual(['a']);
  });

  it('aggregates positions into asset allocation with percentages, sorted desc', () => {
    const a = strategy({
      id: 'a',
      currentValue: 100000,
      positions: [pos('ES', 60000), pos('NQ', 40000)],
    });
    const out = computeCombinedMetrics([a], ['a']);
    const symbols = out.assetAllocation.map(x => x.symbol);
    expect(symbols).toEqual(['ES', 'NQ']); // sorted by value desc
    const es = out.assetAllocation.find(x => x.symbol === 'ES')!;
    expect(es.percentage).toBeCloseTo(60, 6); // 60000 / 100000
  });

  it('rolls positions under 3% into an "Others" slice', () => {
    const a = strategy({
      id: 'a',
      currentValue: 100000,
      positions: [pos('BIG', 98000), pos('TINY1', 1000), pos('TINY2', 1000)],
    });
    const out = computeCombinedMetrics([a], ['a']);
    const others = out.assetAllocation.find(x => x.symbol === 'Others');
    expect(others).toBeTruthy();
    expect(others!.value).toBe(2000);
  });

  it('value-weights volatility and takes the max drawdown', () => {
    // 25% weight on vol=8, 75% weight on vol=4  ->  0.25*8 + 0.75*4 = 5
    const a = strategy({ id: 'a', currentValue: 50000, metrics: metrics({ volatility: 8, maxDrawdown: 30 }) });
    const b = strategy({ id: 'b', currentValue: 150000, metrics: metrics({ volatility: 4, maxDrawdown: 10 }) });
    const out = computeCombinedMetrics([a, b], ['a', 'b']);
    expect(out.metrics.volatility).toBeCloseTo(5, 6);
    expect(out.metrics.maxDrawdown).toBe(30); // max, not weighted
  });

  it('sums realized PnL per symbol across strategies', () => {
    const a = strategy({ id: 'a', currentValue: 100000, finalizedPositions: [fin('ES', 500)] });
    const b = strategy({ id: 'b', currentValue: 100000, finalizedPositions: [fin('ES', 300), fin('NQ', -200)] });
    const out = computeCombinedMetrics([a, b], ['a', 'b']);
    const es = out.symbolPnL.find(x => x.symbol === 'ES')!;
    expect(es.pnl).toBe(800);
  });

  it('builds a correlation matrix with a unit diagonal', () => {
    const a = strategy({
      id: 'a',
      currentValue: 100000,
      positions: [pos('ES', 40000), pos('NQ', 35000), pos('CL', 25000)],
    });
    const out = computeCombinedMetrics([a], ['a']);
    const m = out.advancedMetrics.correlationMatrix;
    expect(m).toHaveLength(3);
    for (let i = 0; i < m.length; i++) {
      expect(m[i][i]).toBe(1);
    }
  });
});
