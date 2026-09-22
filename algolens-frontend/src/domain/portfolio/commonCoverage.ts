import type { HistoricalDataPoint, HistoryBreak } from './portfolioData';

export interface CoverageExclusion {
  date: string;
  missingSeries: string[];
}

export interface AggregateCoverage {
  partial: boolean;
  excludedDates: CoverageExclusion[];
  firstCommonDate: string | null;
  lastCommonDate: string | null;
  /** Every adjacent common point is adjacent in every source curve. */
  comparableDailyReturns: boolean;
  /** Uninterrupted common stretches. Never calculate a return across segments. */
  segments: HistoricalDataPoint[][];
}

export interface CommonCoverageSeries {
  id: string;
  points: HistoricalDataPoint[];
  historyBreaks?: HistoryBreak[];
}

export interface CommonCoverageResult {
  points: HistoricalDataPoint[];
  coverage: AggregateCoverage;
}

export const EMPTY_COVERAGE: AggregateCoverage = {
  partial: false,
  excludedDates: [],
  firstCommonDate: null,
  lastCommonDate: null,
  comparableDailyReturns: false,
  segments: [],
};

const day = (stamp: string) => String(stamp).slice(0, 10);

function crossesBreak(previous: string, current: string, breaks: HistoryBreak[] | undefined) {
  return (breaks ?? []).some(item => {
    const boundary = day(item.date);
    return boundary > previous && boundary <= current;
  });
}

/**
 * Sum equity only where every named series published a point.
 *
 * The union is retained as explicit exclusion metadata; absence is never
 * converted to zero. Segments split whenever a common pair is not adjacent in
 * every source or crosses a declared history break, so consumers cannot turn
 * an internal publication hole or book move into daily P&L.
 */
export function aggregateCommonCoverage(
  series: CommonCoverageSeries[],
): CommonCoverageResult {
  if (series.length === 0) return { points: [], coverage: { ...EMPTY_COVERAGE } };

  const maps = series.map(item => new Map(
    item.points.map((point, index) => [day(point.date), { value: point.value, index }]),
  ));
  const union = Array.from(new Set(series.flatMap(item => item.points.map(point => day(point.date)))))
    .sort((a, b) => a.localeCompare(b));

  const excludedDates: CoverageExclusion[] = [];
  const points: HistoricalDataPoint[] = [];
  const indexes: number[][] = [];

  for (const date of union) {
    const missingSeries = series
      .filter((_, index) => !maps[index].has(date))
      .map(item => item.id);
    if (missingSeries.length > 0) {
      excludedDates.push({ date, missingSeries });
      continue;
    }
    const entries = maps.map(map => map.get(date)!);
    points.push({ date, value: entries.reduce((sum, entry) => sum + entry.value, 0) });
    indexes.push(entries.map(entry => entry.index));
  }

  const segments: HistoricalDataPoint[][] = [];
  points.forEach((point, pointIndex) => {
    const previous = points[pointIndex - 1];
    const adjacent = pointIndex > 0 && series.every((item, seriesIndex) =>
      indexes[pointIndex][seriesIndex] === indexes[pointIndex - 1][seriesIndex] + 1 &&
      !crossesBreak(previous.date, point.date, item.historyBreaks),
    );
    if (!adjacent) segments.push([]);
    segments[segments.length - 1].push(point);
  });

  return {
    points,
    coverage: {
      partial: excludedDates.length > 0 || segments.length > 1,
      excludedDates,
      firstCommonDate: points[0]?.date ?? null,
      lastCommonDate: points[points.length - 1]?.date ?? null,
      comparableDailyReturns: points.length >= 2 && segments.length === 1,
      segments,
    },
  };
}
