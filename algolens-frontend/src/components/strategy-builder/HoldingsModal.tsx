import { X } from 'lucide-react';
import type { CombinedMetrics } from '../../domain/portfolio/computeCombinedMetrics';
import { COLORS } from './chartTheme';

interface HoldingsModalProps {
  metrics: CombinedMetrics;
  theme: string;
  onClose: () => void;
}

export function HoldingsModal({ metrics, theme, onClose }: HoldingsModalProps) {
  return (
    <div className="fixed inset-0 z-[100] overflow-hidden">
      <div className={`h-full overflow-y-auto ${theme === 'dark' ? 'bg-black text-white' : 'bg-white text-black'}`}>
        {/* Modal Header */}
        <div className={`sticky top-0 z-10 border-b ${theme === 'dark' ? 'bg-black border-gray-800' : 'bg-white border-gray-200'}`}>
          <div className="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
            <div>
              <h2 className="text-xl font-semibold">All Holdings</h2>
              <p className={`text-sm ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}`}>
                {metrics.assetAllocation.length} total positions
              </p>
            </div>
            <button
              onClick={onClose}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${theme === 'dark' ? 'bg-gray-800 hover:bg-gray-700 text-white' : 'bg-gray-100 hover:bg-gray-200 text-black'}`}
            >
              <X className="w-5 h-5" />
              <span className="text-sm font-medium">Close</span>
            </button>
          </div>
        </div>

        {/* Modal Content */}
        <div className="max-w-4xl mx-auto px-6 py-6">
          <div className={`border rounded-lg overflow-hidden ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'}`}>
            {/* Table Header */}
            <div className={`grid grid-cols-12 gap-4 p-4 text-sm font-medium border-b ${theme === 'dark' ? 'bg-gray-900 border-gray-800 text-gray-400' : 'bg-gray-50 border-gray-200 text-gray-500'}`}>
              <div className="col-span-1 text-center">#</div>
              <div className="col-span-5">SYMBOL</div>
              <div className="col-span-3 text-right">VALUE</div>
              <div className="col-span-3 text-right">WEIGHT</div>
            </div>

            {/* Holdings List */}
            {metrics.assetAllocation.map((asset, index) => (
              <div
                key={asset.symbol}
                className={`grid grid-cols-12 gap-4 p-4 border-b transition-colors ${theme === 'dark' ? 'border-gray-800 hover:bg-gray-900' : 'border-gray-100 hover:bg-gray-50'}`}
              >
                <div className={`col-span-1 text-center ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>{index + 1}</div>
                <div className="col-span-5 flex items-center gap-3">
                  <div
                    className="w-3 h-3 rounded-full flex-shrink-0"
                    style={{ backgroundColor: COLORS[index % COLORS.length] }}
                  ></div>
                  <span className="font-medium">{asset.symbol}</span>
                </div>
                <div className="col-span-3 text-right tabular-nums font-medium">
                  ${asset.value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
                <div className="col-span-3 text-right tabular-nums text-orange-500 font-medium">
                  {asset.percentage.toFixed(2)}%
                </div>
              </div>
            ))}

            {/* Summary Footer */}
            <div className={`grid grid-cols-12 gap-4 p-4 font-semibold ${theme === 'dark' ? 'bg-gray-900 text-white' : 'bg-gray-50 text-black'}`}>
              <div className="col-span-1"></div>
              <div className="col-span-5">Total ({metrics.assetAllocation.length} holdings)</div>
              <div className="col-span-3 text-right tabular-nums">
                ${metrics.totalValue.toLocaleString('en-US', { minimumFractionDigits: 2 })}
              </div>
              <div className="col-span-3 text-right text-orange-500">100.00%</div>
            </div>
          </div>

          {/* Back Button */}
          <div className="mt-6 flex justify-center">
            <button
              onClick={onClose}
              className={`px-6 py-3 rounded-lg font-medium transition-colors ${theme === 'dark' ? 'bg-orange-500 hover:bg-orange-600 text-white' : 'bg-orange-500 hover:bg-orange-600 text-white'}`}
            >
              Back to Strategy Builder
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
