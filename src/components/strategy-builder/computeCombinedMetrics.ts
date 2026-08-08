import type { Strategy, StrategyMetrics } from '../../data/portfolioData';

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
  sortinoRatio: number;
  informationRatio: number;
  hhi: number;
  correlationMatrix: number[][];
  topHoldings: AllocationSlice[];
  var95: number;
}

export interface CombinedMetrics {
  totalInvested: number;
  totalValue: number;
  totalReturn: number;
  returnPercent: number;
  metrics: StrategyMetrics;
  symbolPnL: SymbolPnL[];
  dailyPnL: { date: string; pnl: number }[];
  strategies: Strategy[];
  assetAllocation: AllocationSlice[];
  strategyAllocation: StrategySlice[];
  historicalPerformance: { date: string; return: number }[];
  advancedMetrics: AdvancedMetrics;
}

function zeroMetrics(): StrategyMetrics {
  return {
    volatility: 0, sharpeRatio: 0, maxDrawdown: 0, winRate: 0, totalTrades: 0,
    avgWin: 0, avgLoss: 0, profitFactor: 0, dailyReturn: 0, cumulativeReturn: 0, annualizedReturn: 0,
    grossLeverage: 0, netLeverage: 0, portfolioLeverage: 0, marginPosted: 0,
    equityToMarginRatio: 0, marginCushion: 0, totalNotional: 0, unrealizedPnL: 0,
    realizedPnL: 0, totalCommissions: 0, netPnL: 0, cashAvailable: 0, currentPortfolioValue: 0
  };
}

function emptyCombined(): CombinedMetrics {
  const today = new Date();
  const zeroHistorical = Array.from({ length: 91 }, (_, i) => {
    const date = new Date(today);
    date.setDate(date.getDate() - (90 - i));
    return { date: date.toISOString().split('T')[0], return: 0 };
  });

  const zeroDaily = Array.from({ length: 31 }, (_, i) => {
    const date = new Date(today);
    date.setDate(date.getDate() - (30 - i));
    return { date: date.toISOString().split('T')[0], pnl: 0 };
  });

  return {
    totalInvested: 0,
    totalValue: 0,
    totalReturn: 0,
    returnPercent: 0,
    metrics: zeroMetrics(),
    symbolPnL: [],
    dailyPnL: zeroDaily,
    strategies: [],
    assetAllocation: [],
    strategyAllocation: [],
    historicalPerformance: zeroHistorical,
    advancedMetrics: {
      sortinoRatio: 0, informationRatio: 0, hhi: 0, correlationMatrix: [],
      topHoldings: [], var95: 0
    }
  };
}

/**
 * Combine the selected strategies into the aggregate view model: totals, asset and
 * strategy allocations, weighted metrics, and advanced risk stats.
 *
 * NOTE: some series (historicalPerformance, dailyPnL, and the correlation matrix)
 * are simulated with Math.random() -- this preserves the original component's
 * behaviour exactly. It is intentionally kept non-deterministic here; the caller
 * memoizes on the selection so the values are stable per selection.
 */
export function computeCombinedMetrics(
  strategies: Strategy[],
  selectedStrategyIds: string[]
): CombinedMetrics {
  const selected = strategies.filter(s => selectedStrategyIds.includes(s.id));

  if (selected.length === 0) {
    return emptyCombined();
  }

  const totalInvested = selected.reduce((sum, s) => sum + s.invested, 0);
  const totalValue = selected.reduce((sum, s) => sum + s.currentValue, 0);
  const totalReturn = totalValue - totalInvested;
  const returnPercent = (totalReturn / totalInvested) * 100;

  // Combine all positions for asset allocation
  const assetValues: { [key: string]: number } = {};
  selected.forEach(strategy => {
    strategy.positions.forEach(pos => {
      assetValues[pos.symbol] = (assetValues[pos.symbol] || 0) + pos.currentValue;
    });
  });

  // Convert to array and sort by value
  const assetAllocation = Object.entries(assetValues)
    .map(([symbol, value]) => ({
      symbol,
      value,
      percentage: (value / totalValue) * 100
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
      percentage: (othersTotal / totalValue) * 100
    });
  }

  // Strategy allocation for pie chart
  const strategyAllocation = selected.map(s => ({
    name: s.name,
    value: s.currentValue,
    percentage: (s.currentValue / totalValue) * 100
  }));

  // Historical performance data (combined)
  const historicalPerformance: { date: string; return: number }[] = [];
  const today = new Date();
  let cumulativeReturn = 0;
  for (let i = 90; i >= 0; i--) {
    const date = new Date(today);
    date.setDate(date.getDate() - i);
    cumulativeReturn += (Math.random() - 0.45) * 0.5; // Trend upward
    historicalPerformance.push({
      date: date.toISOString().split('T')[0],
      return: cumulativeReturn
    });
  }

  // Combine all finalized positions for PnL by symbol
  const symbolPnL: { [key: string]: number } = {};
  selected.forEach(strategy => {
    strategy.finalizedPositions.forEach(pos => {
      symbolPnL[pos.symbol] = (symbolPnL[pos.symbol] || 0) + pos.realizedPnL;
    });
  });

  // Sort by PnL
  const sortedSymbols = Object.entries(symbolPnL)
    .sort((a, b) => a[1] - b[1])
    .map(([symbol, pnl]) => ({ symbol, pnl }));

  // Generate daily PnL data (simulated)
  const dailyPnL = [];
  for (let i = 30; i >= 0; i--) {
    const date = new Date(today);
    date.setDate(date.getDate() - i);
    const variance = Math.random() - 0.5;
    const basePnl = returnPercent > 0 ? 200 : -200;
    dailyPnL.push({
      date: date.toISOString().split('T')[0],
      pnl: basePnl + variance * 800
    });
  }

  // Weighted average metrics - MUST BE CALCULATED FIRST
  const weightedMetrics: StrategyMetrics = {
    volatility: 0,
    sharpeRatio: 0,
    maxDrawdown: 0,
    winRate: 0,
    totalTrades: 0,
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

  let totalWeight = 0;
  selected.forEach(s => {
    const weight = s.currentValue / totalValue;
    totalWeight += weight;

    weightedMetrics.volatility += s.metrics.volatility * weight;
    weightedMetrics.sharpeRatio += s.metrics.sharpeRatio * weight;
    weightedMetrics.maxDrawdown = Math.max(weightedMetrics.maxDrawdown, s.metrics.maxDrawdown);
    weightedMetrics.winRate += s.metrics.winRate * weight;
    weightedMetrics.totalTrades += s.metrics.totalTrades;
    weightedMetrics.avgWin += s.metrics.avgWin * weight;
    weightedMetrics.avgLoss += s.metrics.avgLoss * weight;
    weightedMetrics.profitFactor += s.metrics.profitFactor * weight;
    weightedMetrics.dailyReturn += s.metrics.dailyReturn * weight;
    weightedMetrics.annualizedReturn += s.metrics.annualizedReturn * weight;
    weightedMetrics.grossLeverage += s.metrics.grossLeverage * weight;
    weightedMetrics.netLeverage += s.metrics.netLeverage * weight;
    weightedMetrics.portfolioLeverage += s.metrics.portfolioLeverage * weight;
    weightedMetrics.marginPosted += s.metrics.marginPosted;
    weightedMetrics.totalNotional += s.metrics.totalNotional;
    weightedMetrics.unrealizedPnL += s.metrics.unrealizedPnL;
    weightedMetrics.realizedPnL += s.metrics.realizedPnL;
    weightedMetrics.totalCommissions += s.metrics.totalCommissions;
    weightedMetrics.netPnL += s.metrics.netPnL;
    weightedMetrics.cashAvailable += s.metrics.cashAvailable;
  });

  weightedMetrics.equityToMarginRatio = weightedMetrics.marginPosted > 0
    ? totalValue / weightedMetrics.marginPosted
    : 0;
  weightedMetrics.marginCushion = weightedMetrics.marginPosted > 0
    ? ((totalValue - weightedMetrics.marginPosted) / totalValue) * 100
    : 0;

  // Calculate advanced risk metrics (NOW weightedMetrics is available)
  // Sortino Ratio (only penalizes downward volatility)
  const dailyReturns = historicalPerformance.map((_, i) =>
    i > 0 ? historicalPerformance[i].return - historicalPerformance[i - 1].return : 0
  );
  const negativeReturns = dailyReturns.filter(r => r < 0);
  const downsideDeviation = negativeReturns.length > 0
    ? Math.sqrt(negativeReturns.reduce((sum, r) => sum + r * r, 0) / negativeReturns.length) * Math.sqrt(252)
    : 0.1;
  const sortinoRatio = downsideDeviation > 0
    ? (weightedMetrics.annualizedReturn / downsideDeviation)
    : 0;

  // Information Ratio (excess return vs benchmark)
  const benchmarkReturn = 12.5; // S&P 500 average
  const excessReturn = weightedMetrics.annualizedReturn - benchmarkReturn;
  const trackingError = weightedMetrics.volatility * 0.7; // Simulated
  const informationRatio = trackingError > 0 ? excessReturn / trackingError : 0;

  // Herfindahl-Hirschman Index (concentration risk)
  const hhi = assetAllocation.reduce((sum, asset) =>
    sum + Math.pow(asset.percentage, 2), 0
  );

  // Correlation Matrix (top 5 holdings)
  const topHoldings = assetAllocation.slice(0, 5);
  const correlationMatrix = topHoldings.map(asset1 =>
    topHoldings.map(asset2 => {
      if (asset1.symbol === asset2.symbol) return 1;
      // Simulate correlations (in real app, calculate from historical prices)
      return 0.3 + Math.random() * 0.5;
    })
  );

  // Value at Risk (95% confidence, 1-day)
  const portfolioStdDev = (weightedMetrics.volatility / 100) * totalValue / Math.sqrt(252);
  const var95 = totalValue - (totalValue - 1.645 * portfolioStdDev);

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
    strategyAllocation,
    historicalPerformance,
    advancedMetrics: {
      sortinoRatio,
      informationRatio,
      hhi,
      correlationMatrix,
      topHoldings,
      var95
    }
  };
}
