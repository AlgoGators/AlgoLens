import type { HistoricalDataPoint, Strategy } from './portfolioData';

/**
 * Whether a strategy's book counts in the fund's total. The API decides
 * (`inFundTotal`): the QT desk book and its model twin are paper books until
 * they send positions, so they are listed but not added up. An older API
 * that does not send the flag counts every strategy.
 */
export function countsInFundTotal(strategy: Strategy): boolean {
  return strategy.inFundTotal !== false;
}

export interface FundTotals {
  totalValue: number;
  totalInvested: number;
  totalReturn: number;
  totalReturnPercent: number;
  historicalData: HistoricalDataPoint[];
}

/** The fund's value, return and equity curve over the strategies that count. */
export function fundTotals(strategies: Strategy[]): FundTotals {
  const counted = strategies.filter(countsInFundTotal);
  const totalInvested = counted.reduce((sum, s) => sum + s.invested, 0);
  const totalValue = counted.reduce((sum, s) => sum + s.currentValue, 0);
  const totalReturn = totalValue - totalInvested;
  const totalReturnPercent = totalInvested > 0 ? (totalReturn / totalInvested) * 100 : 0;
  return {
    totalValue,
    totalInvested,
    totalReturn,
    totalReturnPercent,
    historicalData: aggregateHistoricalData(counted),
  };
}

/** The sum of the strategies' equity curves, by date. */
export function aggregateHistoricalData(strategies: Strategy[]): HistoricalDataPoint[] {
  const dateMap = new Map<string, number>();
  strategies.forEach(strategy => {
    strategy.historicalData.forEach(point => {
      dateMap.set(point.date, (dateMap.get(point.date) || 0) + point.value);
    });
  });
  return Array.from(dateMap.entries())
    .map(([date, value]) => ({ date, value }))
    .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());
}
