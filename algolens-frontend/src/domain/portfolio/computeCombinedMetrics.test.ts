import { describe, it, expect } from 'vitest';
import { computeCombinedMetrics } from './computeCombinedMetrics';
import type { Strategy, StrategyMetrics, Position, FinalizedPosition } from './portfolioData';

// Minimal builders so tests stay readable. Only the fields the computation reads
// need realistic values; everything else is zeroed.

function metrics(overrides: Partial<StrategyMetrics> = {}): StrategyMetrics {
  return {
    volatility: 0, sharpeRatio: 0, sortinoRatio: 0, downsideDeviation: 0,
    maxDrawdown: 0, winRate: 0, executionsToday: 0,
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
  it('invents no series at all when nothing is selected', () => {
    // This used to generate 91 dated points at exactly 0% and 31 at exactly
    // $0, and recharts drew them: a flat three-month line and a row of empty
    // bars, every point stamped with a real date and none of it in any table.
    const s = strategy({ id: 'a' });
    const out = computeCombinedMetrics([s], []);
    expect(out.totalValue).toBe(0);
    expect(out.totalInvested).toBe(0);
    expect(out.strategies).toEqual([]);
    expect(out.assetAllocation).toEqual([]);
    expect(out.holdings).toEqual([]);
    expect(out.historicalPerformance).toEqual([]);
    expect(out.dailyPnL).toEqual([]);
  });

  it('reports an empty selection\u2019s metrics as unknown, not as zero', () => {
    const out = computeCombinedMetrics([strategy({ id: 'a' })], []);
    expect(out.metrics.volatility).toBeNull();
    expect(out.metrics.grossLeverage).toBeNull();
    expect(out.metrics.marginPosted).toBeNull();
    expect(out.returnPercent).toBeNull();
  });

  it('reports the return as unknown when any selected basis is unknown', () => {
    // The invested total skipped a strategy with no starting equity while the
    // value total kept it, so its entire market value was reported as profit.
    const known = strategy({ id: 'known', invested: 100000, currentValue: 110000 });
    const unknown = strategy({ id: 'unknown', invested: null, currentValue: 250000 });

    const both = computeCombinedMetrics([known, unknown], ['known', 'unknown']);
    expect(both.totalValue).toBe(360000);
    expect(both.totalReturn).toBeNull();
    expect(both.returnPercent).toBeNull();

    // With a basis for everything selected, it measures normally.
    const one = computeCombinedMetrics([known, unknown], ['known']);
    expect(one.totalReturn).toBe(10000);
    expect(one.returnPercent).toBeCloseTo(10, 6);
  });

  it('counts instruments, not pie slices, as holdings', () => {
    // assetAllocation collapses everything under 3% into one "Others" row for
    // the chart. The holdings table, the holdings count and the top-3 weight
    // all read it, so "Others" was listed as an instrument and counted as one.
    const s = strategy({
      id: 'a',
      currentValue: 100000,
      positions: [
        pos('ES', 500000), pos('NQ', 400000),
        pos('CL', 10000), pos('GC', 9000), pos('ZN', 8000),
      ],
    });
    const out = computeCombinedMetrics([s], ['a']);

    expect(out.assetAllocation.map(a => a.symbol)).toContain('Others');
    expect(out.holdings.map(a => a.symbol)).not.toContain('Others');
    expect(out.holdings).toHaveLength(5);
    expect(out.holdings.map(a => a.symbol)).toEqual(['ES', 'NQ', 'CL', 'GC', 'ZN']);
  });

  it('leaves a lot with no realised P&L out of the per-symbol totals', () => {
    // realizedPnL is nullable on the wire, and summing a null produced NaN,
    // which recharts renders as a bar of no height with no warning.
    const s = strategy({
      id: 'a',
      finalizedPositions: [
        fin('ES', 1200),
        { symbol: 'ZB', quantity: 8, entryPrice: 119.5, exitPrice: null, realizedPnL: null },
      ],
    });
    const out = computeCombinedMetrics([s], ['a']);
    expect(out.symbolPnL.every(x => Number.isFinite(x.pnl))).toBe(true);
    expect(out.symbolPnL.map(x => x.symbol)).toEqual(['ES']);
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

  it('reports an unknown return, not NaN or Infinity, when nothing is invested', () => {
    const s = strategy({
      id: 'fresh',
      invested: 0,
      currentValue: 0,
      positions: [pos('ES', 0)],
    });
    const out = computeCombinedMetrics([s], ['fresh']);

    expect(out.returnPercent).toBeNull();
    expect(out.assetAllocation.every(a => Number.isFinite(a.percentage))).toBe(true);
    expect(out.strategyAllocation.every(a => Number.isFinite(a.percentage))).toBe(true);
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

  it('derives volatility and drawdown from the combined curve, not from a weighted average', () => {
    // Two curves that move in opposite directions. Averaging their individual
    // volatilities would report plenty of risk; the combined book is flat.
    const up = [100, 110, 100, 110, 100].map((v, i) => ({ date: `d${i}`, value: v }));
    const down = [100, 90, 100, 90, 100].map((v, i) => ({ date: `d${i}`, value: v }));
    const a = strategy({ id: 'a', currentValue: 100000, historicalData: up, metrics: metrics({ volatility: 40, maxDrawdown: 9 }) });
    const b = strategy({ id: 'b', currentValue: 100000, historicalData: down, metrics: metrics({ volatility: 40, maxDrawdown: 10 }) });
    const out = computeCombinedMetrics([a, b], ['a', 'b']);
    expect(out.metrics.volatility).toBeCloseTo(0, 6);
    expect(out.metrics.maxDrawdown).toBeCloseTo(0, 6);
  });

  it('reports combined volatility as unknown when the curve is too short to say', () => {
    const a = strategy({ id: 'a', currentValue: 100000, historicalData: [], metrics: metrics({ volatility: 8 }) });
    const out = computeCombinedMetrics([a], ['a']);
    expect(out.metrics.volatility).toBeNull();
    expect(out.metrics.sharpeRatio).toBeNull();
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

describe('placeholder strategies', () => {
  it('excludes a strategy the engine has not published from every aggregate', () => {
    // Its zeros are shape-fillers. Letting it in would produce a 0% allocation
    // slice and a $0 summary line that both read as measurements.
    const priced = strategy({
      id: 'a',
      currentValue: 100000,
      invested: 100000,
      positions: [pos('ES', 100000)],
    });
    const placeholder = strategy({ id: 'b', dataAvailable: false, currentValue: 0, invested: 0 });
    const out = computeCombinedMetrics([priced, placeholder], ['a', 'b']);
    expect(out.strategies.map(s => s.id)).toEqual(['a']);
    expect(out.strategyAllocation.map(s => s.name)).toEqual(['a']);
    expect(out.totalValue).toBe(100000);
  });
});
