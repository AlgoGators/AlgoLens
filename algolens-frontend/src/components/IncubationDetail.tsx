import { useMemo, useState } from 'react';
import { TrendingDown, TrendingUp } from 'lucide-react';
import type { IncubatingStrategy, IncubationPerformance } from '@/models';
import {
  calculateDaysRemaining,
  calculateIncubationProgress,
  formatEquity,
} from '@/lib/incubationUtils';
import { filterByPeriod, type Period } from '@/lib/filterByPeriod';
import { PeriodSelector } from './PeriodSelector';
import { IncubationDetailHeader } from './incubation/IncubationDetailHeader';
import { IncubationChart } from './incubation/IncubationChart';
import { IncubationStats } from './incubation/IncubationStats';
import { IncubationPositionsTable } from './incubation/IncubationPositionsTable';
import { useTheme } from '../adapters/react/ThemeContext';

interface IncubationDetailProps {
  strategy: IncubatingStrategy;
  performance: IncubationPerformance | null;
  isLoading: boolean;
  error: string | null;
  onBack: () => void;
}

const PERIODS: Period[] = ['1W', '1M', '3M', 'ALL'];

function computePeriodReturn(series: { value: number }[]) {
  if (series.length < 2) return { value: 0, percent: 0 };
  const startValue = series[0].value;
  const endValue = series[series.length - 1].value;
  const returnValue = endValue - startValue;
  const returnPercent = startValue > 0 ? (returnValue / startValue) * 100 : 0;
  return { value: returnValue, percent: returnPercent };
}

function LoadingState() {
  const { theme } = useTheme();
  return (
    <div className="flex items-center justify-center min-h-[320px]">
      <div className="text-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500 mx-auto mb-4"></div>
        <p className={theme === 'dark' ? 'text-gray-400' : 'text-gray-600'}>
          Loading incubation performance...
        </p>
      </div>
    </div>
  );
}

function ErrorState({ error }: { error: string }) {
  return (
    <div className="flex items-center justify-center min-h-[320px]">
      <div className="text-center max-w-lg">
        <div className="mb-4 p-4 bg-red-100 dark:bg-red-900/30 rounded-lg">
          <p className="text-red-600 dark:text-red-400 text-sm font-mono break-words text-left">
            {error}
          </p>
        </div>
      </div>
    </div>
  );
}

function ReturnLine({
  currentEquity,
  periodReturn,
  periodLabel,
}: {
  currentEquity: number;
  periodReturn: { value: number; percent: number };
  periodLabel: string;
}) {
  const positive = periodReturn.value >= 0;
  const dollars = Math.abs(periodReturn.value).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return (
    <div className="mb-6">
      <div className="text-3xl md:text-4xl mb-2">{formatEquity(currentEquity)}</div>
      <div className={`flex items-center gap-2 text-lg ${positive ? 'text-orange-500' : 'text-red-500'}`}>
        {positive ? <TrendingUp className="w-5 h-5" /> : <TrendingDown className="w-5 h-5" />}
        <span>
          ${dollars} ({periodReturn.percent >= 0 ? '+' : ''}
          {periodReturn.percent.toFixed(2)}%) {periodLabel}
        </span>
      </div>
    </div>
  );
}

export function IncubationDetail({
  strategy,
  performance,
  isLoading,
  error,
  onBack,
}: IncubationDetailProps) {
  const [selectedPeriod, setSelectedPeriod] = useState<Period>('1M');

  const historicalData = useMemo(
    () =>
      (performance?.equity_curve || [])
        .filter(point => point.equity !== null)
        .map(point => ({ date: point.date, value: point.equity || 0 })),
    [performance]
  );

  const filteredData = useMemo(
    () => filterByPeriod(historicalData, selectedPeriod),
    [historicalData, selectedPeriod]
  );

  const periodReturn = useMemo(() => computePeriodReturn(filteredData), [filteredData]);

  const currentEquity =
    historicalData.length > 0
      ? historicalData[historicalData.length - 1].value
      : strategy.mock_capital || 0;
  const progress = calculateIncubationProgress(strategy.days_elapsed, strategy.window_days);
  const daysRemaining = calculateDaysRemaining(strategy.days_elapsed, strategy.window_days);
  const periodLabel = selectedPeriod === 'ALL' ? 'All Time' : selectedPeriod;

  return (
    <div>
      <IncubationDetailHeader strategy={strategy} onBack={onBack} />

      {isLoading && <LoadingState />}
      {!isLoading && error && <ErrorState error={error} />}
      {!isLoading && !error && (
        <>
          <ReturnLine
            currentEquity={currentEquity}
            periodReturn={periodReturn}
            periodLabel={periodLabel}
          />
          <IncubationChart data={filteredData} positive={periodReturn.value >= 0} />
          <PeriodSelector periods={PERIODS} selected={selectedPeriod} onSelect={setSelectedPeriod} />
          <IncubationStats
            progress={progress}
            daysRemaining={daysRemaining}
            positionsCount={performance?.positions.length || 0}
          />
          <IncubationPositionsTable positions={performance?.positions || []} />
        </>
      )}
    </div>
  );
}
