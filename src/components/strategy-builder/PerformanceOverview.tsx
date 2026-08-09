import type { CombinedMetrics } from '../../domain/portfolio/computeCombinedMetrics';

interface PerformanceOverviewProps {
  metrics: CombinedMetrics;
  theme: string;
}

export function PerformanceOverview({ metrics, theme }: PerformanceOverviewProps) {
  const isPositive = metrics.totalReturn >= 0;

  return (
    <div className="mb-4">
      {/* Main Performance Bar */}
      <div className={`p-4 border mb-3 ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
        }`}>
        <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
          <div className="md:col-span-2">
            <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
              }`}>
              PORTFOLIO VALUE
            </div>
            <div className="text-2xl">${(metrics.totalValue / 1000).toFixed(1)}k</div>
            <div className={`flex items-center gap-1 text-sm mt-1 ${isPositive ? 'text-orange-500' : 'text-red-500'
              }`}>
              {isPositive ? '▲' : '▼'}
              <span>{isPositive ? '+' : ''}{metrics.returnPercent.toFixed(2)}%</span>
              <span className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
                (${Math.abs(metrics.totalReturn / 1000).toFixed(1)}k)
              </span>
            </div>
          </div>

          <div>
            <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>VOLATILITY</div>
            <div className="text-lg">{metrics.metrics.volatility.toFixed(2)}%</div>
            <div className={`text-xs mt-1 ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>Ann.</div>
          </div>

          <div>
            <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>SHARPE</div>
            <div className="text-lg">{metrics.metrics.sharpeRatio.toFixed(2)}</div>
            <div className={`text-xs mt-1 ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>Ratio</div>
          </div>

          <div>
            <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>MAX DD</div>
            <div className="text-lg text-red-500">{metrics.metrics.maxDrawdown.toFixed(2)}%</div>
            <div className={`text-xs mt-1 ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>Peak</div>
          </div>

          <div>
            <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>WIN RATE</div>
            <div className="text-lg">{metrics.metrics.winRate.toFixed(1)}%</div>
            <div className={`text-xs mt-1 ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>{metrics.metrics.totalTrades} trades</div>
          </div>
        </div>
      </div>

      {/* Risk Metrics Grid - Bloomberg style */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className={`p-3 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
          }`}>
          <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>SORTINO</div>
          <div className="text-base">{metrics.advancedMetrics.sortinoRatio.toFixed(2)}</div>
          <div className={`text-xs ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>Downside only</div>
        </div>

        <div className={`p-3 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
          }`}>
          <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>INFO RATIO</div>
          <div className="text-base">{metrics.advancedMetrics.informationRatio.toFixed(2)}</div>
          <div className={`text-xs ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>vs SPX</div>
        </div>

        <div className={`p-3 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
          }`}>
          <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>VAR (95%)</div>
          <div className="text-base text-red-500">${(metrics.advancedMetrics.var95 / 1000).toFixed(1)}k</div>
          <div className={`text-xs ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>1-day</div>
        </div>
      </div>
    </div>
  );
}
