import { describe, expect, it } from 'vitest';

import { aggregateCommonCoverage } from './commonCoverage';

const series = (id: string, points: Array<[string, number]>) => ({
  id,
  points: points.map(([date, value]) => ({ date, value })),
});

describe('aggregate common coverage', () => {
  it('uses only dates covered by every series and reports exclusions', () => {
    const result = aggregateCommonCoverage([
      series('A', [['2026-09-19', 100_000], ['2026-09-20', 100_000], ['2026-09-21', 100_000]]),
      series('B', [['2026-09-20', 100_000], ['2026-09-21', 100_000]]),
    ]);

    expect(result.points).toEqual([
      { date: '2026-09-20', value: 200_000 },
      { date: '2026-09-21', value: 200_000 },
    ]);
    expect(result.coverage.partial).toBe(true);
    expect(result.coverage.excludedDates).toEqual([
      { date: '2026-09-19', missingSeries: ['B'] },
    ]);
    expect(result.coverage.comparableDailyReturns).toBe(true);
  });

  it('splits around an internal hole instead of bridging it as daily P&L', () => {
    const result = aggregateCommonCoverage([
      series('A', [['2026-09-19', 100], ['2026-09-20', 110], ['2026-09-21', 120]]),
      series('B', [['2026-09-19', 100], ['2026-09-21', 100]]),
    ]);

    expect(result.coverage.segments).toEqual([
      [{ date: '2026-09-19', value: 200 }],
      [{ date: '2026-09-21', value: 220 }],
    ]);
    expect(result.coverage.comparableDailyReturns).toBe(false);
  });
});
