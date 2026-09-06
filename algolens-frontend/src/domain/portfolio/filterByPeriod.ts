/**
 * The 1W/1M/3M/1Y window on a series of daily bars.
 *
 * The window is anchored to the NEWEST BAR IN THE SERIES, not to today's clock.
 * Anchoring on `now` looks right while the engine is publishing daily and goes
 * quietly wrong the moment it is not: a series whose last bar is three days old
 * returns four bars under a button labelled "1W", and a series that stopped a
 * month ago returns nothing at all, which the charts draw as empty or flat
 * rather than as a series that ended. A retired or paused strategy hits that
 * every time it is opened.
 *
 * Boundary: inclusive, and by calendar day. A daily bar is stamped at the start
 * of its day, so a cutoff carrying a clock time falls just after the oldest bar
 * in the window and drops it -- "1M" then measures 29 days and reports 2.06%
 * where the full month was 2.69%. Both ends are reduced to UTC midnight so the
 * comparison cannot depend on the reader's timezone.
 */

export type Period = '1W' | '1M' | '3M' | '1Y' | 'ALL';

/** Days back from the anchor. 'ALL' is deliberately absent: it has no window. */
const PERIOD_DAYS: Record<string, number> = {
  '1W': 7,
  '1M': 30,
  '3M': 90,
  '1Y': 365,
};

const MS_PER_DAY = 86_400_000;

/**
 * UTC midnight of a stamp's calendar day, from either `YYYY-MM-DD` or a full
 * ISO stamp. `NaN` for anything else.
 */
function dayStart(date: string): number {
  return Date.parse(date.slice(0, 10));
}

/**
 * The points falling in `period`, or every point for 'ALL' and for any period
 * this does not recognise. A point whose date cannot be read is kept rather
 * than dropped: a window is for narrowing a series, not for discarding data
 * nothing else has complained about.
 */
export function filterByPeriod<T extends { date: string }>(
  points: readonly T[],
  period: string
): T[] {
  const days = PERIOD_DAYS[period];
  if (days === undefined || points.length === 0) return [...points];

  let newest = Number.NEGATIVE_INFINITY;
  for (const point of points) {
    const day = dayStart(point.date);
    if (!Number.isNaN(day) && day > newest) newest = day;
  }
  // Nothing in the series carries a readable date; there is no anchor to
  // measure from, so narrowing it would be guesswork.
  if (newest === Number.NEGATIVE_INFINITY) return [...points];

  const cutoff = newest - days * MS_PER_DAY;
  return points.filter(point => {
    const day = dayStart(point.date);
    return Number.isNaN(day) || day >= cutoff;
  });
}
