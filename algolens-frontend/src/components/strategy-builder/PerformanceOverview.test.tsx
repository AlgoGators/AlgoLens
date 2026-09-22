// @vitest-environment jsdom

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { CombinedMetrics } from '../../domain/portfolio/computeCombinedMetrics';
import { PerformanceOverview } from './PerformanceOverview';

const coverageGapMetrics: CombinedMetrics = {
  totalValue: 200,
  totalInvested: 200,
  totalReturn: 0,
  returnPercent: 0,
  metrics: {
    volatility: null,
    sharpeRatio: null,
    sortinoRatio: null,
    downsideDeviation: null,
    maxDrawdown: null,
    winRate: null,
    executionsToday: null,
    avgWin: null,
    avgLoss: null,
    profitFactor: null,
    dailyReturn: null,
    cumulativeReturn: null,
    annualizedReturn: null,
    grossLeverage: null,
    netLeverage: null,
    portfolioLeverage: null,
    marginPosted: null,
    equityToMarginRatio: null,
    marginCushion: null,
    totalNotional: null,
    unrealizedPnL: null,
    realizedPnL: null,
    totalCommissions: null,
    netPnL: null,
    cashAvailable: null,
    currentPortfolioValue: 200,
  },
  symbolPnL: [],
  dailyPnL: [],
  strategies: [],
  assetAllocation: [],
  holdings: [],
  strategyAllocation: [],
  historicalPerformance: [],
  coverage: {
    partial: true,
    excludedDates: [{ date: '2026-09-20', missingSeries: ['strategy-b'] }],
    firstCommonDate: '2026-09-19',
    lastCommonDate: '2026-09-21',
    comparableDailyReturns: false,
    segments: [],
  },
  advancedMetrics: {
    sortinoRatio: null,
    informationRatio: null,
    hhi: 0,
    correlationMatrix: [],
    correlationObservations: 0,
    topHoldings: [],
    var95: null,
  },
};

describe('PerformanceOverview unavailable metric copy', () => {
  it('does not invent causes for risk metrics withheld by a common-coverage gap', () => {
    render(<PerformanceOverview metrics={coverageGapMetrics} theme="light" />);

    expect(screen.getAllByText('Unavailable')).toHaveLength(2);
    expect(screen.getByText(/limited to dates shared by every selected strategy/i)).toBeTruthy();
    expect(screen.queryByText('No measurable downside')).toBeNull();
    expect(screen.queryByText('Needs a benchmark stream')).toBeNull();
  });
});
