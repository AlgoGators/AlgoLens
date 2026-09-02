import { describe, it, expect } from 'vitest';
import { computeCombinedMetrics } from './computeCombinedMetrics';
import type { Strategy, StrategyMetrics, Position, FinalizedPosition } from './portfolioData';

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

  it('does not fabricate a correlation matrix (unavailable without per-symbol history)', () => {
    const a = strategy({
      id: 'a',
      currentValue: 100000,
      positions: [pos('ES', 40000), pos('NQ', 35000), pos('CL', 25000)],
    });
    const out = computeCombinedMetrics([a], ['a']);
    // Correlation needs per-symbol price history the API doesn't expose (issue #56),
    // so it's returned empty rather than as random values...
    expect(out.advancedMetrics.correlationMatrix).toEqual([]);
    // ...but the real top holdings it would describe are still populated.
    expect(out.advancedMetrics.topHoldings.map(h => h.symbol)).toEqual(['ES', 'NQ', 'CL']);
  });

  it('builds combined performance and daily PnL from the real equity curves', () => {
    const a = strategy({
      id: 'a',
      currentValue: 100000,
      historicalData: [
        { date: '2026-01-01', value: 100000 },
        { date: '2026-01-02', value: 110000 },
        { date: '2026-01-03', value: 105000 },
      ],
    });
    const b = strategy({
      id: 'b',
      currentValue: 100000,
      historicalData: [
        { date: '2026-01-01', value: 100000 },
        { date: '2026-01-02', value: 100000 },
        { date: '2026-01-03', value: 130000 },
      ],
    });
    const out = computeCombinedMetrics([a, b], ['a', 'b']);

    // Combined equity by date is 200k -> 210k -> 235k; performance is % from the base.
    expect(out.historicalPerformance.map(p => p.date)).toEqual([
      '2026-01-01', '2026-01-02', '2026-01-03',
    ]);
    expect(out.historicalPerformance[0].return).toBeCloseTo(0, 6);
    expect(out.historicalPerformance[1].return).toBeCloseTo(5, 6);    // 210/200 - 1
    expect(out.historicalPerformance[2].return).toBeCloseTo(17.5, 6); // 235/200 - 1

    // Daily PnL is the day-over-day dollar change of that combined curve.
    expect(out.dailyPnL.map(p => p.pnl)).toEqual([0, 10000, 25000]);
  });
});

describe('information ratio', () => {
  // The yardstick is the `benchmark` stream -- what the algorithm would have
  // compounded to with no human edits -- not an index. That is the only benchmark
  // series the platform actually has, and it is the comparison AlphaAttribution
  // already treats as the answer to "did the desk add value".

  function withStreams(
    id: string,
    book: [string, number][],
    benchmark?: [string, number][],
  ) {
    return strategy({
      id,
      historicalData: book.map(([date, value]) => ({ date, value })),
      ...(benchmark
        ? { equityByStream: { benchmark: benchmark.map(([date, value]) => ({ date, value })) } }
        : {}),
    });
  }

  it('is unavailable when no strategy carries a benchmark stream', () => {
    // The pre-migration state. Reporting a number here would mean inventing one.
    const a = withStreams('a', [['2026-01-01', 100], ['2026-01-02', 102]]);
    const out = computeCombinedMetrics([a], ['a']);
    expect(out.advancedMetrics.informationRatio).toBeNull();
  });

  it('is unavailable when the two curves overlap on fewer than three dates', () => {
    // Two shared dates yield a single active return, which has no dispersion.
    const a = withStreams(
      'a',
      [['2026-01-01', 100], ['2026-01-02', 102]],
      [['2026-01-01', 100], ['2026-01-02', 101]],
    );
    const out = computeCombinedMetrics([a], ['a']);
    expect(out.advancedMetrics.informationRatio).toBeNull();
  });

  it('is unavailable when the book has never diverged from the benchmark', () => {
    // This is production today: nothing writes edits into qt, so the two curves
    // are identical and tracking error is zero. Dividing by it would produce
    // Infinity; reporting 0.00 would read as "the desk added nothing".
    const curve: [string, number][] = [
      ['2026-01-01', 100], ['2026-01-02', 102], ['2026-01-03', 102], ['2026-01-04', 106.08],
    ];
    const a = withStreams('a', curve, curve);
    const out = computeCombinedMetrics([a], ['a']);
    expect(out.advancedMetrics.informationRatio).toBeNull();
  });

  it('measures active return against the benchmark stream, annualised', () => {
    // Book returns   +2%, 0%, +4%
    // Benchmark      +1%, +1%, +1%
    // Active          +1%, -1%, +3%  -> mean 1%, population sd 1.63299%
    // IR = 0.01 * sqrt(252) / 0.0163299 = 9.7211
    const a = withStreams(
      'a',
      [['2026-01-01', 100], ['2026-01-02', 102], ['2026-01-03', 102], ['2026-01-04', 106.08]],
      [['2026-01-01', 100], ['2026-01-02', 101], ['2026-01-03', 102.01], ['2026-01-04', 103.0301]],
    );
    const out = computeCombinedMetrics([a], ['a']);
    expect(out.advancedMetrics.informationRatio).toBeCloseTo(9.7211, 3);
  });

  it('goes negative when the book trails the benchmark', () => {
    const a = withStreams(
      'a',
      [['2026-01-01', 100], ['2026-01-02', 101], ['2026-01-03', 102.01], ['2026-01-04', 103.0301]],
      [['2026-01-01', 100], ['2026-01-02', 102], ['2026-01-03', 102], ['2026-01-04', 106.08]],
    );
    const out = computeCombinedMetrics([a], ['a']);
    expect(out.advancedMetrics.informationRatio).toBeCloseTo(-9.7211, 3);
  });

  it('sums benchmark curves across strategies the same way the book is summed', () => {
    // Two strategies, each half the size. Summed, they reproduce the single-strategy
    // case above exactly, so the ratio must come out identical.
    const a = withStreams(
      'a',
      [['2026-01-01', 50], ['2026-01-02', 51], ['2026-01-03', 51], ['2026-01-04', 53.04]],
      [['2026-01-01', 50], ['2026-01-02', 50.5], ['2026-01-03', 51.005], ['2026-01-04', 51.51505]],
    );
    const b = withStreams(
      'b',
      [['2026-01-01', 50], ['2026-01-02', 51], ['2026-01-03', 51], ['2026-01-04', 53.04]],
      [['2026-01-01', 50], ['2026-01-02', 50.5], ['2026-01-03', 51.005], ['2026-01-04', 51.51505]],
    );
    const out = computeCombinedMetrics([a, b], ['a', 'b']);
    expect(out.advancedMetrics.informationRatio).toBeCloseTo(9.7211, 3);
  });

  it('ignores dates the benchmark does not cover', () => {
    // A trailing book date with no benchmark point must not be read as a day the
    // benchmark returned zero -- that would invent an active return.
    const a = withStreams(
      'a',
      [
        ['2026-01-01', 100], ['2026-01-02', 102], ['2026-01-03', 102],
        ['2026-01-04', 106.08], ['2026-01-05', 200],
      ],
      [['2026-01-01', 100], ['2026-01-02', 101], ['2026-01-03', 102.01], ['2026-01-04', 103.0301]],
    );
    const out = computeCombinedMetrics([a], ['a']);
    expect(out.advancedMetrics.informationRatio).toBeCloseTo(9.7211, 3);
  });

  it('is unavailable when only some of the selected strategies have a benchmark', () => {
    // Summing a partial benchmark against a full book would understate the benchmark
    // and overstate the desk -- a wrong number, not a missing one.
    const a = withStreams(
      'a',
      [['2026-01-01', 50], ['2026-01-02', 51], ['2026-01-03', 51], ['2026-01-04', 53.04]],
      [['2026-01-01', 50], ['2026-01-02', 50.5], ['2026-01-03', 51.005], ['2026-01-04', 51.51505]],
    );
    const b = withStreams(
      'b',
      [['2026-01-01', 50], ['2026-01-02', 51], ['2026-01-03', 51], ['2026-01-04', 53.04]],
    );
    const out = computeCombinedMetrics([a, b], ['a', 'b']);
    expect(out.advancedMetrics.informationRatio).toBeNull();
  });

  it('is unavailable rather than zero when nothing is selected', () => {
    const out = computeCombinedMetrics([strategy({ id: 'a' })], []);
    expect(out.advancedMetrics.informationRatio).toBeNull();
  });
});

describe('sortino ratio', () => {
  // Downside deviation is target semi-deviation with a minimum acceptable return of
  // zero: root-mean-square of the negative daily returns over EVERY period, not just
  // the losing ones, annualised by sqrt(252). Returns are percentages, matching
  // annualizedReturn, so the ratio is dimensionless.

  function book(id: string, curve: [string, number][], annualizedReturn: number) {
    return strategy({
      id,
      historicalData: curve.map(([date, value]) => ({ date, value })),
      metrics: metrics({ annualizedReturn }),
    });
  }

  it('measures each day against the previous day, not against the first day', () => {
    // 100 -> 110 -> 99 is +10% then -10%.
    // Downside = sqrt(10^2 / 2) * sqrt(252) = 7.0710678 * 15.8745079 = 112.24972
    // Sortino  = 10 / 112.24972 = 0.089087
    //
    // Reading the differences of cumulative-return-from-base instead would call the
    // second day -11 rather than -10, because it divides by the opening equity rather
    // than by yesterday's.
    const a = book('a', [['2026-01-01', 100], ['2026-01-02', 110], ['2026-01-03', 99]], 10);
    const out = computeCombinedMetrics([a], ['a']);
    expect(out.advancedMetrics.sortinoRatio).toBeCloseTo(0.089087, 5);
  });

  it('divides by every period, not only the losing ones', () => {
    // +10%, -10%, +10%. One losing day out of three.
    // Downside = sqrt(10^2 / 3) * sqrt(252) = 5.7735027 * 15.8745079 = 91.651514
    // Sortino  = 10 / 91.651514 = 0.109109
    //
    // Dividing by the count of losing days instead would give 158.745, understating
    // the ratio by a factor that grows as the portfolio wins more often -- the exact
    // opposite of what the number is supposed to reward.
    const a = book(
      'a',
      [['2026-01-01', 100], ['2026-01-02', 110], ['2026-01-03', 99], ['2026-01-04', 108.9]],
      10,
    );
    const out = computeCombinedMetrics([a], ['a']);
    expect(out.advancedMetrics.sortinoRatio).toBeCloseTo(0.109109, 5);
  });

  it('is unavailable when the book has never had a down day', () => {
    // There is no downside to divide by. The old fallback substituted 0.1, which
    // turned a 10% annualised return into a Sortino of 100.00 on screen.
    const a = book('a', [['2026-01-01', 100], ['2026-01-02', 110], ['2026-01-03', 120]], 10);
    const out = computeCombinedMetrics([a], ['a']);
    expect(out.advancedMetrics.sortinoRatio).toBeNull();
  });

  it('is unavailable when there are not two points to take a return between', () => {
    const a = book('a', [['2026-01-01', 100]], 10);
    const out = computeCombinedMetrics([a], ['a']);
    expect(out.advancedMetrics.sortinoRatio).toBeNull();
  });

  it('is unavailable when the curve touches zero', () => {
    // A return off a zero base is undefined; the ratio must not be built on it.
    const a = book('a', [['2026-01-01', 0], ['2026-01-02', 100], ['2026-01-03', 90]], 10);
    const out = computeCombinedMetrics([a], ['a']);
    expect(out.advancedMetrics.sortinoRatio).toBeNull();
  });

  it('goes negative when the book lost money over the period', () => {
    const a = book('a', [['2026-01-01', 100], ['2026-01-02', 110], ['2026-01-03', 99]], -10);
    const out = computeCombinedMetrics([a], ['a']);
    expect(out.advancedMetrics.sortinoRatio).toBeCloseTo(-0.089087, 5);
  });

  it('sums the strategies before taking returns, not after', () => {
    // Two halves of the single-strategy case above must reproduce it exactly.
    const a = book('a', [['2026-01-01', 50], ['2026-01-02', 55], ['2026-01-03', 49.5]], 10);
    const b = book('b', [['2026-01-01', 50], ['2026-01-02', 55], ['2026-01-03', 49.5]], 10);
    const out = computeCombinedMetrics([a, b], ['a', 'b']);
    expect(out.advancedMetrics.sortinoRatio).toBeCloseTo(0.089087, 5);
  });

  it('is unavailable rather than zero when nothing is selected', () => {
    const out = computeCombinedMetrics([strategy({ id: 'a' })], []);
    expect(out.advancedMetrics.sortinoRatio).toBeNull();
  });
});
