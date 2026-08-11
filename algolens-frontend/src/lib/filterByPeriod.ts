// Time-range filtering for chart series.
//
// The historical/equity-curve series ends in the PAST (the latest point can be
// months before today). Anchoring the window to `new Date()` therefore excluded
// every point for 1W/1M/3M and the charts rendered empty. The window is instead
// anchored to the LAST data point: 1W = the last 7 days *of data*, etc.

export type Period = '1W' | '1M' | '3M' | '1Y' | 'ALL';

const PERIOD_DAYS: Record<Exclude<Period, 'ALL'>, number> = {
  '1W': 7,
  '1M': 30,
  '3M': 90,
  '1Y': 365,
};

/**
 * Keep the points within `period` of the most recent point in `series`.
 * `series` is assumed sorted ascending by date (the last element is newest).
 * `ALL` (or empty input) returns the series unchanged. The cutoff is inclusive.
 */
export function filterByPeriod<T extends { date: string }>(
  series: T[],
  period: Period
): T[] {
  if (period === 'ALL' || series.length === 0) return series;

  const lastDate = new Date(series[series.length - 1].date);
  const cutoff = new Date(lastDate);
  cutoff.setDate(cutoff.getDate() - PERIOD_DAYS[period]);

  return series.filter(point => new Date(point.date) >= cutoff);
}
