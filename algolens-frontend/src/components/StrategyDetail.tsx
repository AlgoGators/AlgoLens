import React, { useState, useMemo } from 'react';
import { ArrowLeft, TrendingUp, TrendingDown } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts';
import type { Strategy } from '../domain/portfolio/portfolioData';
import { useTheme } from '../adapters/react/ThemeContext';
import { FinancialAnalysis } from './FinancialAnalysis';
import { PositionBreakdown } from './PositionBreakdown';
import { TradingActivity } from './TradingActivity';
import { AlphaAttribution } from './AlphaAttribution';

interface StrategyDetailProps {
  strategy: Strategy;
  onBack: () => void;
}

export function StrategyDetail({ strategy, onBack }: StrategyDetailProps) {
  const [selectedPeriod, setSelectedPeriod] = useState('1M');
  const [selectedTab, setSelectedTab] = useState<'positions' | 'analysis' | 'activity'>('positions');
  const { theme } = useTheme();
  const isPositive = strategy.return >= 0;
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
        return strategy.historicalData;
    }

    const cutoffDate = new Date(now);
    cutoffDate.setDate(cutoffDate.getDate() - daysToShow);

    return strategy.historicalData.filter(point => {
      const pointDate = new Date(point.date);
      return pointDate >= cutoffDate;
    });
  }, [selectedPeriod, strategy.historicalData]);

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
    <div>
      <button
        onClick={onBack}
        className={`flex items-center gap-2 mb-6 px-4 py-2 rounded-lg transition-colors ${theme === 'dark'
          ? 'text-gray-300 hover:text-white hover:bg-gray-900'
          : 'text-gray-700 hover:text-black hover:bg-gray-100'
          }`}
      >
        <ArrowLeft className="w-5 h-5" />
        <span>Back to Strategies</span>
      </button>

      <div className="mb-6">
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <h1 className="text-2xl md:text-3xl mb-1">{strategy.name}</h1>
            <p className={theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}>
              {strategy.description}
            </p>
            <div className={`text-sm mt-2 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Managed by {strategy.managers.join(' & ')} • {strategy.lastUpdate}
            </div>
          </div>
        </div>
      </div>

      <div className="mb-6">
        <div className="text-3xl md:text-4xl mb-2">
          ${strategy.currentValue.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
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
              <linearGradient id="stratLineGradient" x1="0" y1="0" x2="0" y2="1">
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
              domain={['dataMin - 500', 'dataMax + 500']}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: theme === 'dark' ? '#1f2937' : '#fff',
                border: theme === 'dark' ? '1px solid #374151' : '1px solid #e5e7eb',
                borderRadius: '8px',
                boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)',
                color: theme === 'dark' ? '#fff' : '#000'
              }}
              formatter={(value: number) => [`$${value.toLocaleString('en-US', { minimumFractionDigits: 2 })}`, 'Value']}
              labelFormatter={(label) => new Date(label).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
            />
            <Line
              type="linear"
              dataKey="value"
              stroke={periodReturn.value >= 0 ? "#f97316" : "#ef4444"}
              strokeWidth={2}
              dot={false}
              fill="url(#stratLineGradient)"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Is QT's judgement adding value? Renders an explanation instead of a
          chart until both streams exist. */}
      <div className="mb-8">
        <AlphaAttribution equityByStream={strategy.equityByStream} theme={theme} />
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

      {/* Tab Navigation */}
      <div className={`flex items-center justify-between mb-6 border-b ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
        }`}>
        <div className="flex items-center gap-4">
          <button
            onClick={() => setSelectedTab('positions')}
            className={`pb-3 px-1 transition-colors relative ${selectedTab === 'positions'
              ? 'text-orange-500'
              : theme === 'dark'
                ? 'text-gray-400 hover:text-white'
                : 'text-gray-500 hover:text-gray-900'
              }`}
          >
            Positions
            {selectedTab === 'positions' && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-orange-500" />
            )}
          </button>
          <button
            onClick={() => setSelectedTab('analysis')}
            className={`pb-3 px-1 transition-colors relative ${selectedTab === 'analysis'
              ? 'text-orange-500'
              : theme === 'dark'
                ? 'text-gray-400 hover:text-white'
                : 'text-gray-500 hover:text-gray-900'
              }`}
          >
            Financial Analysis
            {selectedTab === 'analysis' && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-orange-500" />
            )}
          </button>
          <button
            onClick={() => setSelectedTab('activity')}
            className={`pb-3 px-1 transition-colors relative ${selectedTab === 'activity'
              ? 'text-orange-500'
              : theme === 'dark'
                ? 'text-gray-400 hover:text-white'
                : 'text-gray-500 hover:text-gray-900'
              }`}
          >
            Trading Activity
            {selectedTab === 'activity' && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-orange-500" />
            )}
          </button>
        </div>

        <button
          onClick={onBack}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${theme === 'dark'
              ? 'text-gray-300 hover:text-white hover:bg-gray-900'
              : 'text-gray-700 hover:text-black hover:bg-gray-100'
            }`}
        >
          <ArrowLeft className="w-5 h-5" />
          <span>Back to Strategies</span>
        </button>
      </div>

      {/* Tab Content */}
      {selectedTab === 'positions' && (
        <PositionBreakdown positions={strategy.positions} />
      )}

      {selectedTab === 'analysis' && (
        <FinancialAnalysis metrics={strategy.metrics} />
      )}

      {selectedTab === 'activity' && (
        <TradingActivity
          executions={strategy.executions}
          finalizedPositions={strategy.finalizedPositions}
        />
      )}
    </div>
  );
}