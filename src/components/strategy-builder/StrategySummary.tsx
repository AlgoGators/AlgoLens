import type { CombinedMetrics } from '../../domain/portfolio/computeCombinedMetrics';

interface StrategySummaryProps {
  metrics: CombinedMetrics;
  theme: string;
}

export function StrategySummary({ metrics, theme }: StrategySummaryProps) {
  return (
    <div>
      <h3 className={`text-sm uppercase tracking-wider mb-4 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
        }`}>
        Strategy Summary
      </h3>
      <div className={`border rounded-lg overflow-hidden ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
        }`}>
        {metrics.strategies.map((strategy, index) => {
          const weight = (strategy.currentValue / metrics.totalValue) * 100;
          const strategyReturn = strategy.return >= 0;
          return (
            <div
              key={strategy.id}
              className={`p-4 ${theme === 'dark' ? 'bg-gray-900' : 'bg-white'
                } ${index !== metrics.strategies.length - 1
                  ? theme === 'dark' ? 'border-b border-gray-800' : 'border-b border-gray-200'
                  : ''
                }`}
            >
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h4 className="mb-1">{strategy.name}</h4>
                  <div className="flex items-center gap-3 text-sm">
                    <span className={theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}>
                      {weight.toFixed(1)}% of portfolio
                    </span>
                    <span className={strategyReturn ? 'text-orange-500' : 'text-red-500'}>
                      {strategyReturn ? '+' : ''}{strategy.returnPercent.toFixed(2)}%
                    </span>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-lg">
                    ${strategy.currentValue.toLocaleString('en-US', { minimumFractionDigits: 0 })}
                  </div>
                </div>
              </div>
              <div className={`w-full rounded-full h-2 ${theme === 'dark' ? 'bg-gray-800' : 'bg-gray-200'
                }`}>
                <div
                  className="bg-orange-500 h-2 rounded-full transition-all"
                  style={{ width: `${weight}%` }}
                ></div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
