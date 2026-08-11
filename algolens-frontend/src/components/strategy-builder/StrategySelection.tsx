import type { Strategy } from '@/models';

interface StrategySelectionProps {
  strategies: Strategy[];
  selectedStrategies: string[];
  onToggle: (id: string) => void;
  theme: string;
}

export function StrategySelection({ strategies, selectedStrategies, onToggle, theme }: StrategySelectionProps) {
  return (
    <div className={`mb-4 p-4 border rounded ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
      }`}>
      <div className="flex items-center justify-between mb-3">
        <h3 className={`text-xs uppercase tracking-wider ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
          Strategy Selection
        </h3>
        <span className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
          }`}>
          {selectedStrategies.length} of {strategies.length} selected
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {strategies.map(strategy => {
          const isSelected = selectedStrategies.includes(strategy.id);
          const isPositive = strategy.return >= 0;

          return (
            <button
              key={strategy.id}
              onClick={() => onToggle(strategy.id)}
              className={`p-3 border text-left transition-all ${isSelected
                ? theme === 'dark'
                  ? 'border-orange-500 bg-gray-800 text-white'
                  : 'border-orange-500 bg-orange-50 text-black'
                : theme === 'dark'
                  ? 'border-gray-800 hover:border-gray-700 bg-gray-900'
                  : 'border-gray-200 hover:border-gray-300 bg-white'
                }`}
            >
              <div className="flex items-start justify-between mb-2">
                <div className="flex-1">
                  <h4 className="text-sm mb-0.5">{strategy.name}</h4>
                  <p className={`text-xs ${isSelected
                    ? 'text-gray-500'
                    : theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
                    }`}>
                    {strategy.positions.length} positions
                  </p>
                </div>

                <div className={`w-4 h-4 rounded-full border flex items-center justify-center flex-shrink-0 ${isSelected
                  ? 'border-orange-500 bg-orange-500'
                  : theme === 'dark' ? 'border-gray-600' : 'border-gray-300'
                  }`}>
                  {isSelected && (
                    <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2 text-xs">
                <div>
                  <div className={isSelected ? 'text-gray-500' : theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}>VAL</div>
                  <div>${(strategy.currentValue / 1000).toFixed(0)}k</div>
                </div>
                <div>
                  <div className={isSelected ? 'text-gray-500' : theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}>RET</div>
                  <div className={isPositive ? 'text-orange-500' : 'text-red-500'}>
                    {isPositive ? '+' : ''}{strategy.returnPercent.toFixed(1)}%
                  </div>
                </div>
                <div>
                  <div className={isSelected ? 'text-gray-500' : theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}>SR</div>
                  <div>{strategy.metrics.sharpeRatio.toFixed(2)}</div>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
