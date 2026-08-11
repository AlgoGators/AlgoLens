import React, { useState, useMemo } from 'react';
import { TrendingUp, TrendingDown, Beaker } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts';
import type { PortfolioData } from '@/models';
import { filterByPeriod, type Period } from '@/lib/filterByPeriod';
import { PeriodSelector } from './PeriodSelector';
import { useTheme } from '../adapters/react/ThemeContext';

interface PortfolioOverviewProps {
  data: PortfolioData;
  onBuilderClick: () => void;
}

export function PortfolioOverview({ data, onBuilderClick }: PortfolioOverviewProps) {
  const [selectedPeriod, setSelectedPeriod] = useState<Period>('1M');
  const { theme } = useTheme();
  const isPositive = data.totalReturn >= 0;

  const periods: Period[] = ['1W', '1M', '3M', '1Y', 'ALL'];

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
          ${data.totalValue.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </div>
        <div className={`flex items-center gap-2 text-lg ${periodReturn.value >= 0 ? 'text-orange-500' : 'text-red-500'}`}>
          {periodReturn.value >= 0 ? <TrendingUp className="w-5 h-5" /> : <TrendingDown className="w-5 h-5" />}
          <span>
            ${Math.abs(periodReturn.value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ({periodReturn.percent >= 0 ? '+' : ''}{periodReturn.percent.toFixed(2)}%) {periodLabel}
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
              formatter={(value: number) => [`$${value.toLocaleString('en-US', { minimumFractionDigits: 2 })}`, 'Fund Value']}
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

      <PeriodSelector periods={periods} selected={selectedPeriod} onSelect={setSelectedPeriod} />

      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl">Investment Strategies</h2>
      </div>
    </div>
  );
}
