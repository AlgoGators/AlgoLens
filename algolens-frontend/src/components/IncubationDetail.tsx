import React, { useMemo, useState } from 'react';
import { ArrowLeft, Clock, TrendingDown, TrendingUp } from 'lucide-react';
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type {
  IncubatingStrategy,
  IncubationPerformance,
} from '../domain/portfolio/incubationData';
import {
  calculateDaysRemaining,
  calculateIncubationProgress,
  formatEquity,
  formatIncubationDate,
  formatMockCapital,
} from '../domain/portfolio/incubationUtils';
import { useTheme } from '../adapters/react/ThemeContext';

interface IncubationDetailProps {
  strategy: IncubatingStrategy;
  performance: IncubationPerformance | null;
  isLoading: boolean;
  error: string | null;
  onBack: () => void;
}

export function IncubationDetail({
  strategy,
  performance,
  isLoading,
  error,
  onBack,
}: IncubationDetailProps) {
  const [selectedPeriod, setSelectedPeriod] = useState('1M');
  const { theme } = useTheme();
  const periods = ['1W', '1M', '3M', 'ALL'];

  const historicalData = useMemo(
    () =>
      (performance?.equity_curve || [])
        .filter(point => point.equity !== null)
        .map(point => ({ date: point.date, value: point.equity || 0 })),
    [performance]
  );

  const filteredData = useMemo(() => {
    if (selectedPeriod === 'ALL') return historicalData;

    const daysToShow =
      selectedPeriod === '1W' ? 7 : selectedPeriod === '1M' ? 30 : 90;
    const cutoffDate = new Date();
    cutoffDate.setDate(cutoffDate.getDate() - daysToShow);

    return historicalData.filter(point => new Date(point.date) >= cutoffDate);
  }, [historicalData, selectedPeriod]);

  const periodReturn = useMemo(() => {
    if (filteredData.length < 2) return { value: 0, percent: 0 };
    const startValue = filteredData[0].value;
    const endValue = filteredData[filteredData.length - 1].value;
    const returnValue = endValue - startValue;
    const returnPercent = startValue > 0 ? (returnValue / startValue) * 100 : 0;
    return { value: returnValue, percent: returnPercent };
  }, [filteredData]);

  const currentEquity =
    historicalData.length > 0
      ? historicalData[historicalData.length - 1].value
      : strategy.mock_capital || 0;
  const progress = calculateIncubationProgress(
    strategy.days_elapsed,
    strategy.window_days
  );
  const daysRemaining = calculateDaysRemaining(
    strategy.days_elapsed,
    strategy.window_days
  );
  const periodLabel = selectedPeriod === 'ALL' ? 'All Time' : selectedPeriod;

  return (
    <div>
      <button
        onClick={onBack}
        className={`flex items-center gap-2 mb-6 px-4 py-2 rounded-lg transition-colors ${
          theme === 'dark'
            ? 'text-gray-300 hover:text-white hover:bg-gray-900'
            : 'text-gray-700 hover:text-black hover:bg-gray-100'
        }`}
      >
        <ArrowLeft className="w-5 h-5" />
        <span>Back to Incubation</span>
      </button>

      <div className="mb-6">
        <h1 className="text-2xl md:text-3xl mb-1">{strategy.name}</h1>
        <p className={theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}>
          {strategy.description || strategy.id}
        </p>
        <div
          className={`text-sm mt-2 flex flex-wrap items-center gap-3 ${
            theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}
        >
          <span>{formatMockCapital(strategy.mock_capital)} mock capital</span>
          <span>•</span>
          <span>Started {formatIncubationDate(strategy.incubation_started_at)}</span>
          <span>•</span>
          <span className="flex items-center gap-1">
            <Clock className="w-4 h-4" />
            {strategy.days_elapsed}d / {strategy.window_days}d
          </span>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center min-h-[320px]">
          <div className="text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500 mx-auto mb-4"></div>
            <p className={theme === 'dark' ? 'text-gray-400' : 'text-gray-600'}>
              Loading incubation performance...
            </p>
          </div>
        </div>
      ) : error ? (
        <div className="flex items-center justify-center min-h-[320px]">
          <div className="text-center max-w-lg">
            <div className="mb-4 p-4 bg-red-100 dark:bg-red-900/30 rounded-lg">
              <p className="text-red-600 dark:text-red-400 text-sm font-mono break-words text-left">
                {error}
              </p>
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="mb-6">
            <div className="text-3xl md:text-4xl mb-2">
              {formatEquity(currentEquity)}
            </div>
            <div
              className={`flex items-center gap-2 text-lg ${
                periodReturn.value >= 0 ? 'text-orange-500' : 'text-red-500'
              }`}
            >
              {periodReturn.value >= 0 ? (
                <TrendingUp className="w-5 h-5" />
              ) : (
                <TrendingDown className="w-5 h-5" />
              )}
              <span>
                ${Math.abs(periodReturn.value).toLocaleString('en-US', {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}{' '}
                ({periodReturn.percent >= 0 ? '+' : ''}
                {periodReturn.percent.toFixed(2)}%) {periodLabel}
              </span>
            </div>
          </div>

          <div className="mb-4">
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={filteredData}>
                <XAxis dataKey="date" hide />
                <YAxis hide domain={['dataMin - 500', 'dataMax + 500']} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: theme === 'dark' ? '#1f2937' : '#fff',
                    border:
                      theme === 'dark'
                        ? '1px solid #374151'
                        : '1px solid #e5e7eb',
                    borderRadius: '8px',
                    boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)',
                    color: theme === 'dark' ? '#fff' : '#000',
                  }}
                  formatter={(value: number) => [
                    `$${value.toLocaleString('en-US', {
                      minimumFractionDigits: 2,
                    })}`,
                    'Mock Equity',
                  ]}
                  labelFormatter={label =>
                    new Date(label).toLocaleDateString('en-US', {
                      month: 'short',
                      day: 'numeric',
                      year: 'numeric',
                    })
                  }
                />
                <Line
                  type="linear"
                  dataKey="value"
                  stroke={periodReturn.value >= 0 ? '#f97316' : '#ef4444'}
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div
            className={`flex items-center justify-between mb-8 border-b ${
              theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
            }`}
          >
            {periods.map(period => (
              <button
                key={period}
                onClick={() => setSelectedPeriod(period)}
                className={`px-3 py-3 text-sm transition-colors relative ${
                  selectedPeriod === period
                    ? 'text-orange-500'
                    : theme === 'dark'
                      ? 'text-gray-400 hover:text-white'
                      : 'text-gray-500 hover:text-gray-900'
                }`}
              >
                {period}
                {selectedPeriod === period && (
                  <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-orange-500" />
                )}
              </button>
            ))}
          </div>

          <div
            className={`grid grid-cols-1 md:grid-cols-3 gap-4 mb-8 border-y py-4 ${
              theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
            }`}
          >
            <div>
              <div
                className={`text-xs mb-1 uppercase tracking-wider ${
                  theme === 'dark' ? 'text-gray-500' : 'text-gray-500'
                }`}
              >
                Progress
              </div>
              <div className="text-2xl">{Math.round(progress)}%</div>
            </div>
            <div>
              <div
                className={`text-xs mb-1 uppercase tracking-wider ${
                  theme === 'dark' ? 'text-gray-500' : 'text-gray-500'
                }`}
              >
                Remaining
              </div>
              <div className="text-2xl">{daysRemaining}d</div>
            </div>
            <div>
              <div
                className={`text-xs mb-1 uppercase tracking-wider ${
                  theme === 'dark' ? 'text-gray-500' : 'text-gray-500'
                }`}
              >
                Positions
              </div>
              <div className="text-2xl">{performance?.positions.length || 0}</div>
            </div>
          </div>

          <div>
            <h3
              className={`text-sm uppercase tracking-wider mb-4 ${
                theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}
            >
              Incubation Positions
            </h3>
            <div
              className={`border rounded-lg overflow-x-auto ${
                theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
              }`}
            >
              <div
                className={`grid grid-cols-4 gap-4 p-4 text-sm min-w-[640px] border-b ${
                  theme === 'dark'
                    ? 'bg-gray-900 border-gray-800 text-gray-400'
                    : 'bg-gray-50 border-gray-200 text-gray-500'
                }`}
              >
                <div>Date</div>
                <div>Symbol</div>
                <div className="text-right">Quantity</div>
                <div className="text-right">Entry Price</div>
              </div>
              {(performance?.positions || []).map((position, index) => (
                <div
                  key={`${position.date}-${position.symbol}-${index}`}
                  className={`grid grid-cols-4 gap-4 p-4 min-w-[640px] ${
                    theme === 'dark' ? 'hover:bg-gray-900' : 'hover:bg-gray-50'
                  } ${
                    index !== (performance?.positions.length || 0) - 1
                      ? theme === 'dark'
                        ? 'border-b border-gray-800'
                        : 'border-b border-gray-200'
                      : ''
                  }`}
                >
                  <div>{formatIncubationDate(position.date)}</div>
                  <div>{position.symbol}</div>
                  <div className="text-right">{position.quantity ?? 0}</div>
                  <div className="text-right">
                    {position.entry_price === null
                      ? 'N/A'
                      : `$${position.entry_price.toLocaleString('en-US', {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })}`}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
