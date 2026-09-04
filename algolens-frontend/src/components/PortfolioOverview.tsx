import React, { useState, useMemo } from 'react';
import { periodReturn } from '../domain/portfolio/periodReturn';
import { TrendingUp, TrendingDown, Beaker } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts';
import type { PortfolioData } from '../domain/portfolio/portfolioData';
import { useTheme } from '../adapters/react/ThemeContext';
import { PortfolioGrouping } from './PortfolioGrouping';

interface PortfolioOverviewProps {
  data: PortfolioData;
  onBuilderClick: () => void;
}

export function PortfolioOverview({ data, onBuilderClick }: PortfolioOverviewProps) {
  const [selectedPeriod, setSelectedPeriod] = useState('1M');
  const { theme } = useTheme();
  const isPositive = data.totalReturn >= 0;

  const periods = ['1W', '1M', '3M', '1Y', 'ALL'];

  // Filter data based on selected period
  const filteredData = useMemo(() => {
    const now = new Date();
    let daysToShow: number;

    switch (selectedPeriod) {
      case '1W':
        daysToShow = 7;
        break;
      case '1M':
        daysToShow = 30;
        break;
      case '3M':
        daysToShow = 90;
        break;
      case '1Y':
        daysToShow = 365;
        break;
      case 'ALL':
      default:
        return data.historicalData;
    }

    const cutoffDate = new Date(now);
    // Midnight, not "this time of day 30 days ago". A daily bar is stamped at
    // the start of its day, so a cutoff carrying the current clock time fell
    // just after the oldest bar in the window and dropped it: "1M" measured 29
    // days and reported 2.06% where the full month was 2.69%. Every period on
    // every chart was short by one bar.
    cutoffDate.setDate(cutoffDate.getDate() - daysToShow);
    cutoffDate.setHours(0, 0, 0, 0);

    return data.historicalData.filter(point => {
      const pointDate = new Date(point.date);
      return pointDate >= cutoffDate;
    });
  }, [selectedPeriod, data.historicalData]);

  // Calculate period-specific return
  const windowReturn = useMemo(() => {
    return periodReturn(filteredData);
  }, [filteredData]);
  // The window's direction, for chart colours. An unknown window is
  // drawn in the neutral-positive colour rather than not drawn at all.
  const gaining = (windowReturn?.value ?? 0) >= 0;

  const periodLabel = selectedPeriod === 'ALL' ? 'All Time' : selectedPeriod;

  return (
    <div className="mb-8">
      <div className="mb-4">
        <h2 className={`text-sm uppercase tracking-wider mb-2 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
          Fund Performance
        </h2>
      </div>

      <div className="mb-6">
        <div className="text-4xl md:text-5xl mb-2">
          ${data.totalValue.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </div>
        {/* A total that quietly omits a strategy is worse than one that admits
            it is partial. This is the state right after a strategy changes book,
            before the engine has published for the new pairing. */}
        {(data.strategiesAwaitingData ?? 0) > 0 && (
          <div className={`mb-2 text-sm ${theme === 'dark' ? 'text-amber-400' : 'text-amber-600'}`}>
            Excludes {data.strategiesAwaitingData}{' '}
            {data.strategiesAwaitingData === 1 ? 'strategy' : 'strategies'} the engine has not
            published results for yet.
          </div>
        )}
        {/* Null means the window holds fewer than two points, so there is no
            return to state. This used to state "$0.00 (+0.00%)" -- a flat
            period, rather than a period nothing is known about. */}
        {windowReturn === null ? (
          <div className={`text-lg ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
            &mdash; no data for {periodLabel}
          </div>
        ) : (
          <div className={`flex items-center gap-2 text-lg ${gaining ? 'text-orange-500' : 'text-red-500'}`}>
            {gaining ? <TrendingUp className="w-5 h-5" /> : <TrendingDown className="w-5 h-5" />}
            <span>
              ${Math.abs(windowReturn.value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ({windowReturn.percent >= 0 ? '+' : ''}{windowReturn.percent.toFixed(2)}%) {periodLabel}
            </span>
          </div>
        )}
      </div>

      {/* Directly under the fund total, above the chart: the fund splits into
          portfolios, which contain strategies. Below the chart this sat at the
          fold and was invisible on a normal window. */}
      <div className="mb-8">
        <PortfolioGrouping />
      </div>

      <div className="mb-4">
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={filteredData}>
            <defs>
              <linearGradient id="lineGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={gaining ? "#f97316" : "#ef4444"} stopOpacity={theme === 'dark' ? 0.2 : 0.1} />
                <stop offset="100%" stopColor={gaining ? "#f97316" : "#ef4444"} stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="date"
              hide
            />
            <YAxis
              hide
              domain={['dataMin - 1000', 'dataMax + 1000']}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: theme === 'dark' ? '#1f2937' : '#fff',
                border: theme === 'dark' ? '1px solid #374151' : '1px solid #e5e7eb',
                borderRadius: '8px',
                boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)',
                color: theme === 'dark' ? '#fff' : '#000',
                fontSize: '14px',
                fontWeight: '600',
                padding: '12px'
              }}
              formatter={(value: number) => [`$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, 'Fund Value']}
              labelFormatter={(label) => new Date(label).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
            />
            <Line
              type="linear"
              dataKey="value"
              stroke={gaining ? "#f97316" : "#ef4444"}
              strokeWidth={2}
              dot={false}
              fill="url(#lineGradient)"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className={`flex items-center justify-between mb-8 border-b ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
        }`}>
        {periods.map((period) => (
          <button
            key={period}
            onClick={() => setSelectedPeriod(period)}
            className={`px-3 py-3 text-sm transition-colors relative ${selectedPeriod === period
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

      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl">Investment Strategies</h2>
      </div>
    </div>
  );
}