import React, { useState } from 'react';
import { ArrowLeft, TrendingUp, TrendingDown } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts';
import type { Strategy } from '../data/portfolioData';
import { useTheme } from '../contexts/ThemeContext';
import { FinancialAnalysis } from './FinancialAnalysis';
import { PositionBreakdown } from './PositionBreakdown';
import { TradingActivity } from './TradingActivity';

interface StrategyDetailProps {
  strategy: Strategy;
  onBack: () => void;
}

export function StrategyDetail({ strategy, onBack }: StrategyDetailProps) {
  const [selectedPeriod, setSelectedPeriod] = useState('1M');
  const [selectedTab, setSelectedTab] = useState<'positions' | 'analysis' | 'activity'>('positions');
  const { theme } = useTheme();
  const isPositive = strategy.return >= 0;
  const periods = ['1D', '1W', '1M', '3M', '1Y', 'ALL'];

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
        <div className={`flex items-center gap-2 text-lg ${isPositive ? 'text-orange-500' : 'text-red-500'}`}>
          {isPositive ? <TrendingUp className="w-5 h-5" /> : <TrendingDown className="w-5 h-5" />}
          <span>
            ${Math.abs(strategy.return).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ({isPositive ? '+' : ''}{strategy.returnPercent.toFixed(2)}%) Today
          </span>
        </div>
      </div>

      <div className="mb-4">
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={strategy.historicalData}>
            <defs>
              <linearGradient id="stratLineGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={isPositive ? "#f97316" : "#ef4444"} stopOpacity={theme === 'dark' ? 0.2 : 0.1} />
                <stop offset="100%" stopColor={isPositive ? "#f97316" : "#ef4444"} stopOpacity={0} />
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
              type="monotone"
              dataKey="value"
              stroke={isPositive ? "#f97316" : "#ef4444"}
              strokeWidth={2}
              dot={false}
              fill="url(#stratLineGradient)"
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