import { describe, expect, it } from 'vitest';

import { filterByPeriod } from './filterByPeriod';

/** A daily series of `count` bars ending on `last` (YYYY-MM-DD). */
function series(last: string, count: number): { date: string; value: number }[] {
  const end = Date.parse(last);
  return Array.from({ length: count }, (_, i) => {
    const day = new Date(end - (count - 1 - i) * 86_400_000);
    return { date: day.toISOString().slice(0, 10), value: i };
  });
}

describe('the window is measured from the data, not from the clock', () => {
  it('returns the last week of a series that ended a year ago', () => {
    // The regression this exists for. Against wall-clock `now` every point is
    // older than the cutoff, the filter returns nothing, and the chart draws an
    // empty panel for a strategy that has a perfectly good year of history.
    const points = series('2025-06-30', 400);
    const week = filterByPeriod(points, '1W');

    expect(week.length).toBeGreaterThan(0);
    expect(week[week.length - 1].date).toBe('2025-06-30');
    expect(week[0].date).toBe('2025-06-23');
  });

  it('gives the same answer whether or not the series reaches today', () => {
    const ended = filterByPeriod(series('2025-06-30', 400), '1M');
    const current = filterByPeriod(series('2026-09-06', 400), '1M');

    expect(ended.length).toBe(current.length);
  });
});

describe('the boundary is inclusive and by calendar day', () => {
  it('keeps the bar stamped exactly one month back', () => {
    // 30 days back plus the anchor itself. Excluding the oldest bar is what
    // made "1M" measure 29 days and under-report the month's return.
    expect(filterByPeriod(series('2026-09-06', 400), '1M')).toHaveLength(31);
  });

  it('drops the bar one day beyond the window', () => {
    const window = filterByPeriod(series('2026-09-06', 400), '1W');

    expect(window[0].date).toBe('2026-08-30');
    expect(window.map(p => p.date)).not.toContain('2026-08-29');
  });

  it('reads a full ISO stamp as its calendar day', () => {
    const points = [
      { date: '2026-08-29T23:59:59Z', value: 0 },
      { date: '2026-08-30T00:00:00Z', value: 1 },
      { date: '2026-09-06T13:45:00Z', value: 2 },
    ];

    expect(filterByPeriod(points, '1W').map(p => p.value)).toEqual([1, 2]);
  });
});

describe('what it declines to narrow', () => {
  it('returns everything for ALL', () => {
    const points = series('2026-09-06', 400);
    expect(filterByPeriod(points, 'ALL')).toHaveLength(400);
  });

  it('returns everything for a period it does not know', () => {
    const points = series('2026-09-06', 400);
    expect(filterByPeriod(points, '5Y')).toHaveLength(400);
  });

  it('handles an empty series', () => {
    expect(filterByPeriod([], '1W')).toEqual([]);
  });

  it('keeps a point whose date cannot be read rather than dropping it', () => {
    const points = [
      { date: 'not a date', value: 0 },
      ...series('2026-09-06', 3),
    ];

    expect(filterByPeriod(points, '1W')).toHaveLength(4);
  });

  it('does not narrow a series in which no date can be read', () => {
    const points = [{ date: 'x', value: 0 }, { date: 'y', value: 1 }];
    expect(filterByPeriod(points, '1W')).toHaveLength(2);
  });

  it('does not mutate or alias the series it was given', () => {
    const points = series('2026-09-06', 3);
    const all = filterByPeriod(points, 'ALL');

    expect(all).not.toBe(points);
    expect(points).toHaveLength(3);
  });
});
