import { describe, expect, it } from 'vitest';
import { countsInFundTotal, fundTotals } from './fundTotals';
import type { Strategy } from './portfolioData';

function strategy(id: string, invested: number, currentValue: number, inFundTotal?: boolean): Strategy {
  return {
    id,
    name: id,
    description: '',
    invested,
    currentValue,
    return: currentValue - invested,
    returnPercent: 0,
    positions: [],
    historicalData: [
      { date: '2026-10-12', value: invested },
      { date: '2026-10-13', value: currentValue },
    ],
    bestDay: 0,
    worstDay: 0,
    metrics: {} as Strategy['metrics'],
    executions: [],
    finalizedPositions: [],
    managers: [],
    lastUpdate: '2026-10-13',
    inFundTotal,
  };
}

describe('fundTotals', () => {
  const trend = strategy('trendfollowing', 500_000, 520_000, true);
  const desk = strategy('qt_conservative', 500_000, 490_000, false);
  const model = strategy('qt_conservative_model', 500_000, 510_000, false);

  it('adds up only the strategies that count (not the QT desk book or its model twin)', () => {
    const totals = fundTotals([trend, desk, model]);
    expect(totals.totalInvested).toBe(500_000);
    expect(totals.totalValue).toBe(520_000);
    expect(totals.totalReturn).toBe(20_000);
    expect(totals.totalReturnPercent).toBeCloseTo(4);
    expect(totals.historicalData).toEqual([
      { date: '2026-10-12', value: 500_000 },
      { date: '2026-10-13', value: 520_000 },
    ]);
  });

  it('counts a strategy without the flag (an older API)', () => {
    expect(countsInFundTotal(strategy('legacy', 1, 1))).toBe(true);
    expect(fundTotals([trend, strategy('legacy', 100_000, 100_000)]).totalValue).toBe(620_000);
  });

  it('is zero with nothing to count', () => {
    expect(fundTotals([desk, model])).toEqual({
      totalValue: 0,
      totalInvested: 0,
      totalReturn: 0,
      totalReturnPercent: 0,
      historicalData: [],
    });
  });
});
