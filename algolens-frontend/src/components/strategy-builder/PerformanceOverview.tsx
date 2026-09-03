import type { CombinedMetrics } from '../../domain/portfolio/computeCombinedMetrics';
import { formatMetric, formatThousands } from '../../domain/portfolio/formatMetric';

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
            <div className="text-lg">{formatMetric(metrics.metrics.volatility, 2, { suffix: '%' })}</div>
            <div className={`text-xs mt-1 ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>Ann.</div>
          </div>

          <div>
            <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>SHARPE</div>
            <div className="text-lg">{formatMetric(metrics.metrics.sharpeRatio, 2)}</div>
            <div className={`text-xs mt-1 ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>0% risk-free</div>
          </div>

          <div>
            <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>MAX DD</div>
            <div className="text-lg text-red-500">{formatMetric(metrics.metrics.maxDrawdown, 2, { suffix: '%' })}</div>
            <div className={`text-xs mt-1 ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>Peak</div>
          </div>

          <div>
            <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>WIN RATE</div>
            <div className="text-lg">{formatMetric(metrics.metrics.winRate, 1, { suffix: '%' })}</div>
            <div className={`text-xs mt-1 ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>{metrics.metrics.totalTrades} trades</div>
          </div>
        </div>
      </div>

      {/* Risk Metrics Grid - Bloomberg style */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className={`p-3 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
          }`}>
          <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>SORTINO</div>
          {/* null means there is no downside to divide by. Show that rather than a
              number -- this used to fall back to a hardcoded 0.1 denominator, which
              reported a Sortino of 100.00 for a book that had simply never lost. */}
          <div className="text-base">
            {metrics.advancedMetrics.sortinoRatio === null
              ? '—'
              : metrics.advancedMetrics.sortinoRatio.toFixed(2)}
          </div>
          <div className={`text-xs ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>
            {metrics.advancedMetrics.sortinoRatio === null
              ? 'No measurable downside'
              : 'Downside only'}
          </div>
        </div>

        <div className={`p-3 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
          }`}>
          <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>INFO RATIO</div>
          {/* null means the ratio could not be computed against a real benchmark
              series. Show that rather than a number -- the caption used to read
              "vs SPX" while the figure was derived from a hardcoded constant. */}
          <div className="text-base">
            {metrics.advancedMetrics.informationRatio === null
              ? '—'
              : metrics.advancedMetrics.informationRatio.toFixed(2)}
          </div>
          <div className={`text-xs ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>
            {metrics.advancedMetrics.informationRatio === null
              ? 'Needs a benchmark stream'
              : 'vs system alone'}
          </div>
        </div>

        <div className={`p-3 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
          }`}>
          <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>VAR (95%)</div>
          <div className="text-base text-red-500">{formatThousands(metrics.advancedMetrics.var95)}</div>
          <div className={`text-xs ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>1-day</div>
        </div>
      </div>
    </div>
  );
}
