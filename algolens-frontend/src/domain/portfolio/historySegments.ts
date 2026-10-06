/**
 * Where a strategy's equity curve stops describing the same portfolio.
 *
 * A strategy that moves between books keeps producing one continuous curve,
 * but the money behind it changed. Drawn as a single line it invites the one
 * reading that is wrong: that the whole line is one thing, measurable end to
 * end.
 *
 * Decision (2026-09-06): the line breaks at the move, the break is labelled
 * with the two books, and no window figure spans it. This mirrors
 * `algolens/domain/portfolio/history_segments.py`, which decides WHERE the
 * breaks are; this file only decides how they are drawn.
 */

export interface HistoryBreak {
  /** YYYY-MM-DD. The first day of the new book's history. */
  date: string;
  fromPortfolioId: string;
  toPortfolioId: string;
  reason: string;
}

interface Dated {
  date: string;
}

/** The calendar day of a stamp, as a sortable number. NaN if unreadable. */
function dayStart(date: string): number {
  return Date.parse(String(date).slice(0, 10));
}

/**
 * `points` grouped into segments, one per uninterrupted stretch of book. A
 * point dated on or after a break opens the next segment: the move takes
 * effect that day, so that day's equity is the new book's first, not the old
 * book's last.
 *
 * Always returns at least one segment.
 */
export function splitAtBreaks<T extends Dated>(
  points: readonly T[],
  breaks: readonly HistoryBreak[] | undefined
): T[][] {
  const boundaries = (breaks ?? [])
    .map(b => dayStart(b.date))
    .filter(d => !Number.isNaN(d))
    .sort((a, b) => a - b);

  const segments: T[][] = Array.from({ length: boundaries.length + 1 }, () => []);
  for (const point of points ?? []) {
    const day = dayStart(point.date);
    let index = 0;
    if (!Number.isNaN(day)) {
      while (index < boundaries.length && day >= boundaries[index]) index += 1;
    }
    segments[index].push(point);
  }
  return segments;
}

/**
 * The most recent unbroken stretch -- what a window return may be measured
 * over. A return spanning a book change is a return on two different
 * portfolios added together, which is not a number about anything.
 */
export function latestSegment<T extends Dated>(
  points: readonly T[],
  breaks: readonly HistoryBreak[] | undefined
): T[] {
  const segments = splitAtBreaks(points, breaks);
  for (let i = segments.length - 1; i >= 0; i -= 1) {
    if (segments[i].length > 0) return segments[i];
  }
  return [];
}

/**
 * The points a chart should plot: the same series with a null-valued spacer
 * between segments, which is how recharts is told to lift the pen. Charts
 * must not set `connectNulls`, or the spacer is drawn straight over.
 */
export function withBreakGaps<T extends Dated & { value: number | null }>(
  points: readonly T[],
  breaks: readonly HistoryBreak[] | undefined
): (T | { date: string; value: null })[] {
  const segments = splitAtBreaks(points, breaks).filter(s => s.length > 0);
  if (segments.length < 2) return [...points];

  const plotted: (T | { date: string; value: null })[] = [];
  segments.forEach((segment, index) => {
    // The spacer carries the day before the segment opens, so it sits in the
    // gap rather than on top of the first real point of the new book.
    if (index > 0) {
      const opensAt = dayStart(segment[0].date);
      const spacerDay = Number.isNaN(opensAt)
        ? segment[0].date
        : new Date(opensAt - 86_400_000).toISOString().slice(0, 10);
      plotted.push({ date: spacerDay, value: null });
    }
    plotted.push(...segment);
  });
  return plotted;
}

/** The breaks that fall inside a window, so only visible ones are labelled. */
export function breaksWithin<T extends Dated>(
  points: readonly T[],
  breaks: readonly HistoryBreak[] | undefined
): HistoryBreak[] {
  if (!breaks?.length || !points?.length) return [];
  const days = points.map(p => dayStart(p.date)).filter(d => !Number.isNaN(d));
  if (!days.length) return [];
  const first = Math.min(...days);
  const last = Math.max(...days);
  return breaks.filter(b => {
    const day = dayStart(b.date);
    return !Number.isNaN(day) && day > first && day <= last;
  });
}
