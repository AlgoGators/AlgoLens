export interface PeriodReturn {
  /** Dollars gained or lost across the window. */
  value: number;
  /** The same, as a percentage of the window's opening value. */
  percent: number;
}

/**
 * The return of an equity series over the window it covers.
 *
 * Null when there is nothing to measure: fewer than two points in the window,
 * or an opening value of zero, off which a percentage return is undefined.
 *
 * The three views that each carried a copy of this returned
 * `{ value: 0, percent: 0 }` in exactly those cases, and rendered it -- so a
 * period with no data on record read as "$0.00 (+0.00%) 1M", a flat month,
 * rather than as a month nothing is known about. Callers now render an em
 * dash instead.
 */
export function periodReturn(
  series: { value: number }[],
): PeriodReturn | null {
  if (series.length < 2) return null;
  const startValue = series[0].value;
  if (startValue <= 0) return null;
  const value = series[series.length - 1].value - startValue;
  return { value, percent: (value / startValue) * 100 };
}
