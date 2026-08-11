import { describe, it, expect } from 'vitest';
import { filterByPeriod } from './filterByPeriod';

// A series that ends in the past (the regression the fix targets).
const series = [
  { date: '2025-01-01', value: 1 },
  { date: '2025-10-01', value: 2 },
  { date: '2025-10-25', value: 3 }, // last point: 2025-10-25
  { date: '2025-10-31', value: 4 },
];

describe('filterByPeriod', () => {
  it('1W keeps the last 7 days of DATA even when the series ends in the past', () => {
    // Anchored to 2025-10-31; cutoff 2025-10-24 -> keeps 10-25 and 10-31.
    const out = filterByPeriod(series, '1W');
    expect(out.map(p => p.value)).toEqual([3, 4]);
  });

  it('1M keeps the last 30 days of data', () => {
    // cutoff 2025-10-01 -> keeps 10-01, 10-25, 10-31.
    const out = filterByPeriod(series, '1M');
    expect(out.map(p => p.value)).toEqual([2, 3, 4]);
  });

  it('3M keeps points within 90 days of the last point', () => {
    // cutoff 2025-08-02 -> drops 2025-01-01 only.
    const out = filterByPeriod(series, '3M');
    expect(out.map(p => p.value)).toEqual([2, 3, 4]);
  });

  it('ALL returns everything', () => {
    expect(filterByPeriod(series, 'ALL')).toHaveLength(4);
  });

  it('empty input returns empty', () => {
    expect(filterByPeriod([], '1W')).toEqual([]);
  });

  it('cutoff boundary is inclusive', () => {
    const s = [
      { date: '2025-10-18', value: 1 }, // exactly 7 days before last
      { date: '2025-10-25', value: 2 },
    ];
    expect(filterByPeriod(s, '1W').map(p => p.value)).toEqual([1, 2]);
  });
});
