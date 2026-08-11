import React from 'react';
import { ChevronRight, TrendingUp, TrendingDown, BarChart3 } from 'lucide-react';
import type { Strategy } from '@/models';
import { useTheme } from '../adapters/react/ThemeContext';

interface StrategyListProps {
  strategies: Strategy[];
  onSelectStrategy: (id: string) => void;
}

export function StrategyList({ strategies, onSelectStrategy }: StrategyListProps) {
  const { theme } = useTheme();
  
  return (
    <div className="grid grid-cols-1 md:grid-cols-1 gap-4">
      {strategies.map((strategy) => {
        const isPositive = strategy.return >= 0;
        
        return (
          <button
            key={strategy.id}
            onClick={() => onSelectStrategy(strategy.id)}
            className={`p-5 md:p-6 rounded-xl border transition-all text-left group ${
              theme === 'dark' 
                ? 'bg-gray-900 border-gray-800 hover:border-orange-500 hover:bg-gray-800' 
                : 'bg-gray-50 border-gray-200 hover:border-orange-500 hover:bg-white hover:shadow-lg'
            }`}
          >
            {/* Header Section */}
            <div className="flex items-start justify-between mb-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-2">
                  <div className={`p-2 rounded-lg ${
                    theme === 'dark' ? 'bg-gray-800' : 'bg-white'
                  }`}>
                    <BarChart3 className="w-5 h-5 text-orange-500" />
                  </div>
                  <h3 className="text-lg">{strategy.name}</h3>
                </div>
                <p className={`text-sm mb-2 ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-600'
                }`}>
                  {strategy.description}
                </p>
                <div className={`text-sm flex items-center gap-3 ${
                  theme === 'dark' ? 'text-gray-500' : 'text-gray-500'
                }`}>
                  <span>Managed by {strategy.managers.join(' & ')}</span>
                  <span>•</span>
                  <span>{strategy.positions.length} Holdings</span>
                </div>
              </div>
              
              <ChevronRight className={`w-5 h-5 flex-shrink-0 ml-3 transition-transform group-hover:translate-x-1 ${
                theme === 'dark' ? 'text-gray-600' : 'text-gray-400'
              }`} />
            </div>

            {/* Performance Section */}
            <div className={`pt-4 border-t ${
              theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
            }`}>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {/* Current Value */}
                <div>
                  <div className={`text-xs mb-1 uppercase tracking-wider ${
                    theme === 'dark' ? 'text-gray-500' : 'text-gray-500'
                  }`}>
                    Current Value
                  </div>
                  <div className="text-lg">
                    ${strategy.currentValue.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                  </div>
                </div>

                {/* Total Return */}
                <div>
                  <div className={`text-xs mb-1 uppercase tracking-wider ${
                    theme === 'dark' ? 'text-gray-500' : 'text-gray-500'
                  }`}>
                    Total Return
                  </div>
                  <div className={`text-lg flex items-center gap-1 ${
                    isPositive ? 'text-orange-500' : 'text-red-500'
                  }`}>
                    {isPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                    {isPositive ? '+' : ''}{strategy.returnPercent.toFixed(2)}%
                  </div>
                </div>

                {/* Sharpe Ratio */}
                <div>
                  <div className={`text-xs mb-1 uppercase tracking-wider ${
                    theme === 'dark' ? 'text-gray-500' : 'text-gray-500'
                  }`}>
                    Sharpe Ratio
                  </div>
                  <div className="text-lg">
                    {strategy.metrics.sharpeRatio.toFixed(2)}
                  </div>
                </div>

                {/* Volatility */}
                <div>
                  <div className={`text-xs mb-1 uppercase tracking-wider ${
                    theme === 'dark' ? 'text-gray-500' : 'text-gray-500'
                  }`}>
                    Volatility
                  </div>
                  <div className="text-lg">
                    {strategy.metrics.volatility.toFixed(1)}%
                  </div>
                </div>
              </div>

              {/* Mini Performance Bar */}
              <div className="mt-4">
                <div className={`h-2 rounded-full overflow-hidden ${
                  theme === 'dark' ? 'bg-gray-800' : 'bg-gray-200'
                }`}>
                  <div 
                    className={`h-full transition-all ${
                      isPositive ? 'bg-orange-500' : 'bg-red-500'
                    }`}
                    style={{ 
                      width: `${Math.min(Math.abs(strategy.returnPercent) * 2, 100)}%` 
                    }}
                  ></div>
                </div>
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
