import type { HeldCorrelations, Strategy, StrategyMetrics } from './portfolioData';

// Shapes of the derived data the StrategyBuilder view renders. Extracted verbatim
// from the old inline useMemo so the computation can live (and be tested) apart
// from the ~760 lines of JSX it used to be buried in.

export interface AllocationSlice {
  symbol: string;
  value: number;
  percentage: number;
}

export interface StrategySlice {
  name: string;
  value: number;
  percentage: number;
}

export interface SymbolPnL {
  symbol: string;
  pnl: number;
}

export interface AdvancedMetrics {
  /** null when it cannot be computed honestly -- see sortinoRatioFromCurve. */
  sortinoRatio: number | null;
  /** null when it cannot be computed honestly -- see informationRatioVsBenchmark. */
  informationRatio: number | null;
  hhi: number;
  /**
   * Correlations between the top holdings, in the order `topHoldings` lists
   * them. A cell is null where the pair could not be measured. Empty when the
   * API supplied nothing -- which the panel reports as unavailable rather than
   * drawing an empty grid.
   */
  correlationMatrix: (number | null)[][];
  /** Overlapping returns behind the thinnest pair in the matrix. */
  correlationObservations: number;
  topHoldings: AllocationSlice[];
  /** Null when combined volatility is unknown. */
  var95: number | null;
}

export interface CombinedMetrics {
  totalInvested: number;
  totalValue: number;
  /** Null when any selected strategy has no starting equity on record. */
  totalReturn: number | null;
  /** Null for the same reason. */
  returnPercent: number | null;
  metrics: StrategyMetrics;
  symbolPnL: SymbolPnL[];
  dailyPnL: { date: string; pnl: number }[];
  strategies: Strategy[];
  /**
   * For the pie chart: sub-3% slices collapsed into one "Others" row. Do not
   * count these -- "Others" is not an instrument.
   */
  assetAllocation: AllocationSlice[];
  /** Every instrument, ungrouped. This is what a holdings count means. */
  holdings: AllocationSlice[];
  strategyAllocation: StrategySlice[];
  historicalPerformance: { date: string; return: number }[];
  advancedMetrics: AdvancedMetrics;
}

/**
 * Every metric of an empty selection is unknown, not zero. "0.00x leverage"
 * and "$0 margin posted" are claims about a book; there is no book here.
 * executionsToday is a count, and a count of nothing really is nothing.
 */
function zeroMetrics(): StrategyMetrics {
  return {
    volatility: null, sharpeRatio: null, sortinoRatio: null, downsideDeviation: null,
    maxDrawdown: null, winRate: null, executionsToday: 0,
    avgWin: null, avgLoss: null, profitFactor: null, dailyReturn: null,
    cumulativeReturn: null, annualizedReturn: null,
    grossLeverage: null, netLeverage: null, portfolioLeverage: null, marginPosted: null,
    equityToMarginRatio: null, marginCushion: null, totalNotional: null, unrealizedPnL: null,
    realizedPnL: null, totalCommissions: null, netPnL: null, cashAvailable: null,
    currentPortfolioValue: null
  };
}

/**
 * The view model for "nothing is selected".
 *
 * This used to generate 91 dates ending today, each with a return of exactly
 * 0%, and 31 more with a P&L of exactly $0. Recharts drew them: a flat line
 * across three months, and a row of empty bars, both stamped with real dates.
 * Nothing in any table said any of it. An empty selection has no series, so
 * there is no series here and the charts render their own empty state.
 */
function emptyCombined(): CombinedMetrics {
  return {
    totalInvested: 0,
    totalValue: 0,
    totalReturn: null,
    returnPercent: null,
    metrics: zeroMetrics(),
    symbolPnL: [],
    dailyPnL: [],
    strategies: [],
    assetAllocation: [],
    holdings: [],
    strategyAllocation: [],
    historicalPerformance: [],
    advancedMetrics: {
      sortinoRatio: null, informationRatio: null, hhi: 0, correlationMatrix: [],
      topHoldings: [], var95: null, correlationObservations: 0
    }
  };
}

/**
 * Period-over-period returns of an equity curve, as percentages.
 *
 * Returns null if any point is non-positive, because a return off a zero or negative
 * base is undefined and everything downstream of it would be noise.
 */
function periodReturns(curve: { value: number }[]): number[] | null {
  if (curve.length < 2) return null;
  const returns: number[] = [];
  for (let i = 1; i < curve.length; i++) {
    const prev = curve[i - 1].value;
    if (prev <= 0) return null;
    returns.push(((curve[i].value - prev) / prev) * 100);
  }
  return returns;
}

/**
 * Sortino ratio: annualised return over downside deviation.
 *
 * Downside deviation is the target semi-deviation with a minimum acceptable return of
 * zero -- the root-mean-square of the negative returns taken over EVERY period, not
 * only the losing ones, annualised by sqrt(252). Dividing by the count of losing days
 * instead (as this did) inflates the denominator as the portfolio wins more often,
 * which understates the ratio exactly where it should reward.
 *
 * Returns are percentages so they share units with annualizedReturn, leaving the
 * ratio dimensionless.
 *
 * Returns null rather than a number when there is no downside to divide by. That case
 * used to substitute a hardcoded 0.1, which turned a 10% annualised return into a
 * Sortino of 100.00 on screen for any book that simply had not had a losing day yet.
 * An undefined ratio is undefined; it is not an outstanding one.
 */
/**
 * Volatility, max drawdown and win rate of one equity curve.
 *
 * Volatility is the standard deviation of daily percentage returns annualised
 * by sqrt(252), which is the convention the engine's own volatility figure
 * uses. Everything is null rather than zero when the curve is too short to
 * say anything.
 */
function curveStatistics(curve: { value: number }[]): {
  volatility: number | null;
  maxDrawdown: number | null;
  winRate: number | null;
} {
  const returns = periodReturns(curve);
  if (!returns || returns.length === 0) {
    return { volatility: null, maxDrawdown: null, winRate: null };
  }
  const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
  const variance = returns.reduce((a, r) => a + (r - mean) ** 2, 0) / returns.length;
  const volatility = Math.sqrt(variance) * Math.sqrt(252);

  let peak = curve[0].value;
  let maxDrawdown = 0;
  for (const point of curve) {
    if (point.value > peak) peak = point.value;
    if (peak > 0) maxDrawdown = Math.max(maxDrawdown, ((peak - point.value) / peak) * 100);
  }

  const upDays = returns.filter(r => r > 0).length;
  return { volatility, maxDrawdown, winRate: (upDays / returns.length) * 100 };
}

export function sortinoRatioFromCurve(
  bookCurve: { date: string; value: number }[],
  annualizedReturn: number
): number | null {
  const returns = periodReturns(bookCurve);
  if (returns === null) return null;

  const downside = returns.reduce(
    (sum, r) => sum + (r < 0 ? r * r : 0),
    0
  );
  if (downside === 0) return null;

  const downsideDeviation = Math.sqrt(downside / returns.length) * Math.sqrt(252);
  return annualizedReturn / downsideDeviation;
}

/**
 * Information ratio: mean active return over its own standard deviation, annualised.
 *
 * The yardstick is the `benchmark` stream -- what the algorithm would have compounded
 * to with no human edits. That is the only benchmark series the platform actually
 * produces, and it is the comparison AlphaAttribution already treats as the answer to
 * "did the desk add value". `system` is deliberately not the yardstick: position
 * buffering anchors each day's target on yesterday's actual position, so `system`
 * drifts along with the desk's own past decisions.
 *
 * Returns null rather than a number whenever it cannot be computed honestly. There are
 * four such cases, and each of them used to produce a plausible-looking figure:
 *
 *   - a selected strategy carries no benchmark stream (the pre-migration state, and
 *     the reason this must not silently sum a partial benchmark against a full book)
 *   - fewer than three dates overlap, so there is no dispersion to divide by
 *   - tracking error is zero. This is production today: nothing writes edits into
 *     `qt`, so the two curves are identical. Reporting 0.00 would read as "the desk
 *     added nothing" when the truth is "the desk has not acted yet"
 *   - a curve touches zero, which would make a return undefined
 *
 * Same convention as the downside deviation above: population standard deviation, and
 * sqrt(252) to annualise.
 */
export function informationRatioVsBenchmark(
  bookCurve: { date: string; value: number }[],
  selected: Strategy[]
): number | null {
  const streams = selected.map(s => s.equityByStream?.benchmark);
  if (streams.some(stream => !stream || stream.length === 0)) return null;

  const benchmarkByDate = new Map<string, number>();
  streams.forEach(stream => {
    stream!.forEach(pt => {
      benchmarkByDate.set(pt.date, (benchmarkByDate.get(pt.date) || 0) + pt.value);
    });
  });

  // Only dates present in both curves. A book date the benchmark does not cover is
  // not a day on which the benchmark returned zero.
  const paired = bookCurve.filter(pt => benchmarkByDate.has(pt.date));

  // n points give n-1 returns, and dispersion needs at least two of those.
  if (paired.length < 3) return null;

  const bookReturns = periodReturns(paired);
  const benchReturns = periodReturns(
    paired.map(pt => ({ value: benchmarkByDate.get(pt.date)! }))
  );
  if (bookReturns === null || benchReturns === null) return null;

  const active = bookReturns.map((r, i) => r - benchReturns[i]);

  const mean = active.reduce((sum, r) => sum + r, 0) / active.length;
  const variance =
    active.reduce((sum, r) => sum + (r - mean) * (r - mean), 0) / active.length;
  const trackingError = Math.sqrt(variance);
  // Not just an exact zero. When the two curves differ by a near-constant drift
  // the dispersion is floating-point dust, and dividing by it produced an
  // information ratio of 37,874 -- a number with the shape of a measurement and
  // none of the meaning. Anything under a basis point of daily tracking error
  // is treated as no tracking error at all.
  if (!Number.isFinite(trackingError) || trackingError < 1e-4) return null;

  return (mean * Math.sqrt(252)) / trackingError;
}

/**
 * Combine the selected strategies into the aggregate view model: totals, asset and
 * strategy allocations, weighted metrics, and advanced risk stats.
 *
 * historicalPerformance and dailyPnL are derived from the selected strategies' REAL
 * equity curves (Strategy.historicalData) -- summed by date, then expressed as a
 * cumulative % return and day-over-day dollar change respectively. The correlation
 * matrix is left empty: a real one needs per-symbol price history the API does not
 * expose yet (see issue #56). This function is deterministic given its inputs.
 */
export function computeCombinedMetrics(
  strategies: Strategy[],
  selectedStrategyIds: string[],
  correlations?: HeldCorrelations | null,
): CombinedMetrics {
  // A strategy with dataAvailable === false carries placeholder zeros, not
  // measurements. It must not reach the maths: a zero-value strategy would show
  // up as a 0% allocation slice and a $0 line in the summary, both of which read
  // as real. The selection UI shows it as awaiting data instead.
  const selected = strategies.filter(
    s => selectedStrategyIds.includes(s.id) && s.dataAvailable !== false,
  );

  if (selected.length === 0) {
    return emptyCombined();
  }

  // A strategy with no starting equity on record makes the SELECTION's return
  // unknown, not smaller. Skipping it from the invested total while its value
  // stayed in the value total reported its entire market value as profit --
  // the comment here said it was "left out", and arithmetically it was left
  // in at zero.
  const anyBasisUnknown = selected.some(s => s.invested == null);
  const totalInvested = selected.reduce((sum, s) => sum + (s.invested ?? 0), 0);
  const totalValue = selected.reduce((sum, s) => sum + s.currentValue, 0);
  const totalReturn = anyBasisUnknown ? null : totalValue - totalInvested;
  // A selection whose invested or current value sums to zero has no meaningful
  // share to report. 0, not NaN or Infinity, which would otherwise render.
  const share = (part: number, whole: number) => (whole > 0 ? (part / whole) * 100 : 0);
  const returnPercent =
    totalReturn === null || totalInvested <= 0 ? null : share(totalReturn, totalInvested);

  // Combine all positions for asset allocation
  const assetValues: { [key: string]: number } = {};
  selected.forEach(strategy => {
    strategy.positions.forEach(pos => {
      // A position whose exposure could not be computed contributes nothing to
      // the allocation rather than a zero that would shrink every other slice.
      if (pos.currentValue == null) return;
      assetValues[pos.symbol] = (assetValues[pos.symbol] || 0) + pos.currentValue;
    });
  });

  // Convert to array and sort by value
  // Share of total EXPOSURE, not of portfolio equity. These values are
  // notional -- quantity x price x contract size -- and a futures book carries
  // many times its equity in exposure, so dividing by equity produced weights
  // like 407% in a column headed WEIGHT that is meant to sum to 100.
  const totalExposure = Object.values(assetValues).reduce((sum, v) => sum + v, 0);
  const assetAllocation = Object.entries(assetValues)
    .map(([symbol, value]) => ({
      symbol,
      value,
      percentage: share(value, totalExposure)
    }))
    .sort((a, b) => b.value - a.value);

  // Group smaller positions (less than 3%) into "Others"
  const threshold = 3;
  const mainAssets = assetAllocation.filter(a => a.percentage >= threshold);
  const otherAssets = assetAllocation.filter(a => a.percentage < threshold);
  const othersTotal = otherAssets.reduce((sum, a) => sum + a.value, 0);

  const pieData = [...mainAssets];
  if (othersTotal > 0) {
    pieData.push({
      symbol: 'Others',
      value: othersTotal,
      percentage: share(othersTotal, totalExposure)
    });
  }

  // Strategy allocation for pie chart
  const strategyAllocation = selected.map(s => ({
    name: s.name,
    value: s.currentValue,
    percentage: share(s.currentValue, totalValue)
  }));

  // Combined equity curve: sum each selected strategy's REAL historical equity by
  // date, then express it as cumulative % return from the first (earliest) point.
  // Reads the actual per-strategy equity curves instead of simulating a series.
  const equityByDate = new Map<string, number>();
  selected.forEach(s => {
    s.historicalData.forEach(pt => {
      equityByDate.set(pt.date, (equityByDate.get(pt.date) || 0) + pt.value);
    });
  });
  const combinedCurve = Array.from(equityByDate.entries())
    .map(([date, value]) => ({ date, value }))
    .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());

  const baseEquity = combinedCurve.length > 0 ? combinedCurve[0].value : 0;
  const historicalPerformance = combinedCurve.map(pt => ({
    date: pt.date,
    return: baseEquity > 0 ? ((pt.value - baseEquity) / baseEquity) * 100 : 0
  }));

  // Combine all finalized positions for PnL by symbol
  const symbolPnL: { [key: string]: number } = {};
  selected.forEach(strategy => {
    strategy.finalizedPositions.forEach(pos => {
      // A lot whose realised P&L the engine has not published contributes
      // nothing rather than turning the whole bar into NaN.
      if (pos.realizedPnL == null) return;
      symbolPnL[pos.symbol] = (symbolPnL[pos.symbol] || 0) + pos.realizedPnL;
    });
  });

  // Sort by PnL
  const sortedSymbols = Object.entries(symbolPnL)
    .sort((a, b) => a[1] - b[1])
    .map(([symbol, pnl]) => ({ symbol, pnl }));

  // Daily PnL: day-over-day change in the combined equity curve (real dollars),
  // most recent 31 days. Derived from the same real curve, not simulated.
  const dailyPnL = combinedCurve
    .map((pt, i) => ({
      date: pt.date,
      pnl: i === 0 ? 0 : pt.value - combinedCurve[i - 1].value
    }))
    .slice(-31);

  // Weighted average metrics - MUST BE CALCULATED FIRST
  const weightedMetrics: StrategyMetrics = {
    volatility: 0,
    sharpeRatio: 0,
    sortinoRatio: null,
    downsideDeviation: null,
    maxDrawdown: 0,
    winRate: 0,
    executionsToday: 0,
    avgWin: 0,
    avgLoss: 0,
    profitFactor: 0,
    dailyReturn: 0,
    cumulativeReturn: returnPercent,
    annualizedReturn: 0,
    grossLeverage: 0,
    netLeverage: 0,
    portfolioLeverage: 0,
    marginPosted: 0,
    equityToMarginRatio: 0,
    marginCushion: 0,
    totalNotional: 0,
    unrealizedPnL: 0,
    realizedPnL: 0,
    totalCommissions: 0,
    netPnL: 0,
    cashAvailable: 0,
    currentPortfolioValue: totalValue
  };

  // Value-weighted averages over the strategies that actually report each
  // metric. A strategy whose engine row has NULL for a figure is left out of
  // that figure's average rather than dragged in as zero; if no strategy
  // reports it, the combined figure is unknown too.
  const weightOf = (s: Strategy) => (totalValue > 0 ? (s.currentValue ?? 0) / totalValue : 0);
  const weighted = (pick: (m: StrategyMetrics) => number | null): number | null => {
    let sum = 0;
    let weightSum = 0;
    for (const s of selected) {
      const v = pick(s.metrics);
      if (v === null || v === undefined) continue;
      const w = weightOf(s);
      sum += v * w;
      weightSum += w;
    }
    return weightSum > 0 ? sum / weightSum : null;
  };
  const summed = (pick: (m: StrategyMetrics) => number | null): number | null => {
    let any = false;
    let sum = 0;
    for (const s of selected) {
      const v = pick(s.metrics);
      if (v === null || v === undefined) continue;
      any = true;
      sum += v;
    }
    return any ? sum : null;
  };

  // Volatility, Sharpe, drawdown and win rate of a COMBINED book are
  // properties of the combined equity curve, not averages of the parts: two
  // offsetting strategies have lower volatility together than either alone,
  // and a weighted average of Sharpe ratios is not the Sharpe ratio of the
  // sum. These were value-weighted averages, presented with the same labels
  // as the real thing. They are now read off the combined curve, the same
  // way Sortino and the information ratio already were.
  const curveStats = curveStatistics(combinedCurve);
  weightedMetrics.volatility = curveStats.volatility;
  weightedMetrics.maxDrawdown = curveStats.maxDrawdown;
  weightedMetrics.winRate = curveStats.winRate;
  weightedMetrics.executionsToday = selected.reduce(
    (n, s) => n + (s.metrics.executionsToday ?? 0), 0);
  weightedMetrics.avgWin = weighted(m => m.avgWin);
  weightedMetrics.avgLoss = weighted(m => m.avgLoss);
  weightedMetrics.profitFactor = weighted(m => m.profitFactor);
  weightedMetrics.dailyReturn = weighted(m => m.dailyReturn);
  weightedMetrics.annualizedReturn = weighted(m => m.annualizedReturn);
  // Same 0% risk-free convention as the per-strategy figure from the API.
  weightedMetrics.sharpeRatio =
    weightedMetrics.annualizedReturn !== null &&
    curveStats.volatility !== null &&
    curveStats.volatility > 0
      ? weightedMetrics.annualizedReturn / curveStats.volatility
      : null;
  weightedMetrics.grossLeverage = weighted(m => m.grossLeverage);
  weightedMetrics.netLeverage = weighted(m => m.netLeverage);
  weightedMetrics.portfolioLeverage = weighted(m => m.portfolioLeverage);
  weightedMetrics.marginPosted = summed(m => m.marginPosted);
  weightedMetrics.totalNotional = summed(m => m.totalNotional);
  weightedMetrics.unrealizedPnL = summed(m => m.unrealizedPnL);
  weightedMetrics.realizedPnL = summed(m => m.realizedPnL);
  weightedMetrics.totalCommissions = summed(m => m.totalCommissions);
  weightedMetrics.netPnL = summed(m => m.netPnL);
  weightedMetrics.cashAvailable = summed(m => m.cashAvailable);

  const marginPosted = weightedMetrics.marginPosted;
  weightedMetrics.equityToMarginRatio =
    marginPosted !== null && marginPosted > 0 ? totalValue / marginPosted : null;
  weightedMetrics.marginCushion =
    marginPosted !== null && marginPosted > 0 && totalValue > 0
      ? ((totalValue - marginPosted) / totalValue) * 100
      : null;

  // Calculate advanced risk metrics (NOW weightedMetrics is available)
  const sortinoRatio =
    weightedMetrics.annualizedReturn === null
      ? null
      : sortinoRatioFromCurve(combinedCurve, weightedMetrics.annualizedReturn);

  // Information Ratio: active return against the benchmark stream, annualised.
  const informationRatio = informationRatioVsBenchmark(combinedCurve, selected);

  // Herfindahl-Hirschman Index (concentration risk)
  const hhi = assetAllocation.reduce((sum, asset) =>
    sum + Math.pow(asset.percentage, 2), 0
  );

  // Correlation matrix for the top 5 holdings, sliced out of the fund-wide
  // matrix the API computes from futures_data.ohlcv_1d.
  //
  // This used to be hardcoded empty, and the panel explained the gap as
  // "the API does not expose per-symbol price history". It always did: that is
  // the table every market price on the site already comes from. Nothing read
  // it. Before that it was filled with Math.random, which is how a panel of
  // invented numbers ended up shipping in the first place.
  const topHoldings = assetAllocation.slice(0, 5);
  const correlationIndex = new Map(
    (correlations?.symbols ?? []).map((symbol, i) => [symbol, i]),
  );
  // Only build the grid if every holding on it is one the API measured. A
  // matrix with a missing row is a matrix whose labels no longer line up with
  // its cells, which is worse than no matrix.
  const covered = topHoldings.every(h => correlationIndex.has(h.symbol));
  const correlationMatrix: (number | null)[][] =
    covered && topHoldings.length > 0
      ? topHoldings.map(row =>
          topHoldings.map(
            column =>
              correlations!.matrix[correlationIndex.get(row.symbol)!]?.[
                correlationIndex.get(column.symbol)!
              ] ?? null,
          ),
        )
      : [];

  // Value at Risk (95% confidence, 1-day)
  const var95 =
    weightedMetrics.volatility === null
      ? null
      : 1.645 * ((weightedMetrics.volatility / 100) * totalValue) / Math.sqrt(252);

  return {
    totalInvested,
    totalValue,
    totalReturn,
    returnPercent,
    metrics: weightedMetrics,
    symbolPnL: sortedSymbols,
    dailyPnL,
    strategies: selected,
    assetAllocation: pieData,
    holdings: assetAllocation,
    strategyAllocation,
    historicalPerformance,
    advancedMetrics: {
      sortinoRatio,
      informationRatio,
      hhi,
      correlationMatrix,
      correlationObservations: correlationMatrix.length > 0
        ? correlations?.observations ?? 0
        : 0,
      topHoldings,
      var95
    }
  };
}
