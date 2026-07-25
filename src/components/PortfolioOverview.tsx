import React, { useState, useMemo } from 'react';
import { TrendingUp, TrendingDown } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts';
import type { PortfolioData } from '../data/portfolioData';
import { useTheme } from '../contexts/ThemeContext';
import { PERIOD_OPTIONS, filterByPeriod } from '../lib/period';
import { formatCurrency } from '../lib/currency';

interface PortfolioOverviewProps {
  data: PortfolioData;
  onBuilderClick: () => void;
}

export function PortfolioOverview({ data, onBuilderClick }: PortfolioOverviewProps) {
  const [selectedPeriod, setSelectedPeriod] = useState('1M');
  const { theme } = useTheme();
  const isPositive = data.totalReturn >= 0;

  const periods = PERIOD_OPTIONS;

  // Filter data based on selected period
  const filteredData = useMemo(
    () => filterByPeriod(data.historicalData, selectedPeriod),
    [selectedPeriod, data.historicalData]
  );

  // Calculate period-specific return
  const periodReturn = useMemo(() => {
    if (filteredData.length < 2) return { value: 0, percent: 0 };
    const startValue = filteredData[0].value;
    const endValue = filteredData[filteredData.length - 1].value;
    const returnValue = endValue - startValue;
    const returnPercent = startValue > 0 ? (returnValue / startValue) * 100 : 0;
    return { value: returnValue, percent: returnPercent };
  }, [filteredData]);

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
          {formatCurrency(data.totalValue, { maximumFractionDigits: 2 })}
        </div>
        <div className={`flex items-center gap-2 text-lg ${periodReturn.value >= 0 ? 'text-orange-500' : 'text-red-500'}`}>
          {periodReturn.value >= 0 ? <TrendingUp className="w-5 h-5" /> : <TrendingDown className="w-5 h-5" />}
          <span>
            {formatCurrency(Math.abs(periodReturn.value), { maximumFractionDigits: 2 })} ({periodReturn.percent >= 0 ? '+' : ''}{periodReturn.percent.toFixed(2)}%) {periodLabel}
          </span>
        </div>
      </div>

      <div className="mb-4">
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={filteredData}>
            <defs>
              <linearGradient id="lineGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={periodReturn.value >= 0 ? "#f97316" : "#ef4444"} stopOpacity={theme === 'dark' ? 0.2 : 0.1} />
                <stop offset="100%" stopColor={periodReturn.value >= 0 ? "#f97316" : "#ef4444"} stopOpacity={0} />
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
              formatter={(value: number) => [formatCurrency(value), 'Fund Value']}
              labelFormatter={(label) => new Date(label).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
            />
            <Line
              type="linear"
              dataKey="value"
              stroke={periodReturn.value >= 0 ? "#f97316" : "#ef4444"}
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