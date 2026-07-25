import type { HistoricalDataPoint } from '../data/portfolioData';

export const PERIOD_OPTIONS = ['1W', '1M', '3M', '1Y', 'ALL'] as const;
export type Period = typeof PERIOD_OPTIONS[number];

const PERIOD_DAYS: Record<Exclude<Period, 'ALL'>, number> = {
  '1W': 7,
  '1M': 30,
  '3M': 90,
  '1Y': 365,
};

export function filterByPeriod(
  data: HistoricalDataPoint[],
  period: string
): HistoricalDataPoint[] {
  if (period === 'ALL' || !(period in PERIOD_DAYS)) {
    return data;
  }

  const daysToShow = PERIOD_DAYS[period as Exclude<Period, 'ALL'>];
  const cutoffDate = new Date();
  cutoffDate.setDate(cutoffDate.getDate() - daysToShow);

  return data.filter(point => new Date(point.date) >= cutoffDate);
}
