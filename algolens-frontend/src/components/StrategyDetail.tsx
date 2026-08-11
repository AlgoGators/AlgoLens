import { useState, useMemo } from 'react';
import { ArrowLeft, TrendingUp, TrendingDown } from 'lucide-react';
import type { Strategy } from '@/models';
import { filterByPeriod, type Period } from '@/lib/filterByPeriod';
import { PeriodSelector } from './PeriodSelector';
import { StrategyTabs, type StrategyTab } from './strategy/StrategyTabs';
import { StrategyChart } from './strategy/StrategyChart';
import { useTheme } from '../adapters/react/ThemeContext';
import { FinancialAnalysis } from './FinancialAnalysis';
import { PositionBreakdown } from './PositionBreakdown';
import { TradingActivity } from './TradingActivity';

interface StrategyDetailProps {
  strategy: Strategy;
  onBack: () => void;
}

const PERIODS: Period[] = ['1W', '1M', '3M', '1Y', 'ALL'];

function computePeriodReturn(series: { value: number }[]) {
  if (series.length < 2) return { value: 0, percent: 0 };
  const startValue = series[0].value;
  const endValue = series[series.length - 1].value;
  const returnValue = endValue - startValue;
  const returnPercent = startValue > 0 ? (returnValue / startValue) * 100 : 0;
  return { value: returnValue, percent: returnPercent };
}

function TabContent({ tab, strategy }: { tab: StrategyTab; strategy: Strategy }) {
  if (tab === 'analysis') return <FinancialAnalysis metrics={strategy.metrics} />;
  if (tab === 'activity') {
    return (
      <TradingActivity
        executions={strategy.executions}
        finalizedPositions={strategy.finalizedPositions}
      />
    );
  }
  return <PositionBreakdown positions={strategy.positions} />;
}

export function StrategyDetail({ strategy, onBack }: StrategyDetailProps) {
  const [selectedPeriod, setSelectedPeriod] = useState<Period>('1M');
  const [selectedTab, setSelectedTab] = useState<StrategyTab>('positions');
  const { theme } = useTheme();

  const filteredData = useMemo(
    () => filterByPeriod(strategy.historicalData, selectedPeriod),
    [selectedPeriod, strategy.historicalData]
  );
  const periodReturn = useMemo(() => computePeriodReturn(filteredData), [filteredData]);
  const periodLabel = selectedPeriod === 'ALL' ? 'All Time' : selectedPeriod;
  const positive = periodReturn.value >= 0;
  const currentValue = strategy.currentValue.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const returnDollars = Math.abs(periodReturn.value).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

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
        <span>Back to Strategies</span>
      </button>

      <div className="mb-6">
        <h1 className="text-2xl md:text-3xl mb-1">{strategy.name}</h1>
        <p className={theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}>{strategy.description}</p>
        <div className={`text-sm mt-2 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}`}>
          Managed by {strategy.managers.join(' & ')} • {strategy.lastUpdate}
        </div>
      </div>

      <div className="mb-6">
        <div className="text-3xl md:text-4xl mb-2">${currentValue}</div>
        <div className={`flex items-center gap-2 text-lg ${positive ? 'text-orange-500' : 'text-red-500'}`}>
          {positive ? <TrendingUp className="w-5 h-5" /> : <TrendingDown className="w-5 h-5" />}
          <span>
            ${returnDollars} ({periodReturn.percent >= 0 ? '+' : ''}
            {periodReturn.percent.toFixed(2)}%) {periodLabel}
          </span>
        </div>
      </div>

      <StrategyChart data={filteredData} positive={positive} />


      <PeriodSelector periods={PERIODS} selected={selectedPeriod} onSelect={setSelectedPeriod} />

      <StrategyTabs selected={selectedTab} onSelect={setSelectedTab} onBack={onBack} />

      <TabContent tab={selectedTab} strategy={strategy} />
    </div>
  );
}
