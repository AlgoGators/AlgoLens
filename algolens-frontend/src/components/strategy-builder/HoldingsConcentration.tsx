import type { CombinedMetrics } from '@/models';
import { COLORS } from './chartTheme';

interface HoldingsConcentrationProps {
  metrics: CombinedMetrics;
  theme: string;
  onShowAll: () => void;
}

export function HoldingsConcentration({ metrics, theme, onShowAll }: HoldingsConcentrationProps) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-4">
      {/* Top Holdings Table */}
      <div className={`p-4 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
        }`}>
        <div className="flex items-center justify-between mb-3">
          <h3 className={`text-xs uppercase tracking-wider ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
            }`}>
            Top Holdings
          </h3>
          <button
            onClick={onShowAll}
            className={`text-xs ${theme === 'dark' ? 'text-orange-500 hover:text-orange-400' : 'text-orange-600 hover:text-orange-700'
              }`}
          >
            Show All
          </button>
        </div>

        <div className="space-y-0">
          <div className={`grid grid-cols-12 gap-2 pb-2 border-b text-xs ${theme === 'dark' ? 'border-gray-800 text-gray-500' : 'border-gray-200 text-gray-400'
            }`}>
            <div className="col-span-5">SYMBOL</div>
            <div className="col-span-4 text-right">VALUE</div>
            <div className="col-span-3 text-right">WEIGHT</div>
          </div>

          {metrics.assetAllocation.slice(0, 6).map((asset, index) => (
            <div
              key={asset.symbol}
              className={`grid grid-cols-12 gap-2 py-2 border-b text-sm ${theme === 'dark' ? 'border-gray-900' : 'border-gray-100'
                }`}
            >
              <div className="col-span-5 flex items-center gap-2">
                <div
                  className="w-2 h-2 rounded-full flex-shrink-0"
                  style={{ backgroundColor: COLORS[index % COLORS.length] }}
                ></div>
                <span className="truncate">{asset.symbol}</span>
              </div>
              <div className="col-span-4 text-right tabular-nums">
                ${(asset.value / 1000).toFixed(1)}k
              </div>
              <div className="col-span-3 text-right tabular-nums text-orange-500">
                {asset.percentage.toFixed(1)}%
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Concentration & Diversification */}
      <div className={`p-4 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
        }`}>
        <h3 className={`text-xs uppercase tracking-wider mb-3 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
          Concentration Risk
        </h3>

        <div className="space-y-4">
          {/* HHI Score */}
          <div>
            <div className="flex items-baseline justify-between mb-2">
              <span className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
                HHI INDEX
              </span>
              <span className="text-2xl tabular-nums">
                {metrics.advancedMetrics.hhi.toFixed(0)}
              </span>
            </div>
            <div className={`w-full h-2 rounded-full ${theme === 'dark' ? 'bg-gray-900' : 'bg-gray-200'
              }`}>
              <div
                className={`h-2 rounded-full ${metrics.advancedMetrics.hhi < 1500
                  ? 'bg-green-500'
                  : metrics.advancedMetrics.hhi < 2500
                    ? 'bg-orange-500'
                    : 'bg-red-500'
                  }`}
                style={{ width: `${Math.min((metrics.advancedMetrics.hhi / 4000) * 100, 100)}%` }}
              ></div>
            </div>
            <div className={`text-xs mt-1 ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'
              }`}>
              {metrics.advancedMetrics.hhi < 1500
                ? 'Well diversified'
                : metrics.advancedMetrics.hhi < 2500
                  ? 'Moderate concentration'
                  : 'High concentration'}
            </div>
          </div>

          {/* Quick Stats */}
          <div className="grid grid-cols-2 gap-3">
            <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
              }`}>
              <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
                HOLDINGS
              </div>
              <div className="text-xl tabular-nums">
                {metrics.assetAllocation.length}
              </div>
            </div>
            <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
              }`}>
              <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
                TOP 3 WT
              </div>
              <div className="text-xl tabular-nums text-orange-500">
                {metrics.assetAllocation.slice(0, 3).reduce((sum, a) => sum + a.percentage, 0).toFixed(0)}%
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
