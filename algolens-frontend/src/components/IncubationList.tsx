import React from 'react';
import {
  ChevronRight,
  Clock,
  DollarSign,
  FlaskConical,
  Sprout,
} from 'lucide-react';
import type { IncubatingStrategy } from '@/models';
import {
  calculateDaysRemaining,
  calculateIncubationProgress,
  formatIncubationDate,
  formatMockCapital,
  isNearEndOfWindow,
  isWindowComplete,
} from '@/lib/incubationUtils';
import { useTheme } from '../adapters/react/ThemeContext';

interface IncubationListProps {
  strategies: IncubatingStrategy[];
  onSelectStrategy: (id: string) => void;
}

export function IncubationList({
  strategies,
  onSelectStrategy,
}: IncubationListProps) {
  const { theme } = useTheme();

  if (strategies.length === 0) {
    return (
      <div className="text-center py-12 px-6">
        <FlaskConical
          className={`w-12 h-12 mx-auto mb-4 ${
            theme === 'dark' ? 'text-gray-600' : 'text-gray-300'
          }`}
        />
        <h3
          className={`text-lg mb-2 ${
            theme === 'dark' ? 'text-gray-300' : 'text-gray-700'
          }`}
        >
          No Incubating Strategies
        </h3>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-1 gap-4">
      {strategies.map(strategy => {
        const progress = calculateIncubationProgress(
          strategy.days_elapsed,
          strategy.window_days
        );
        const daysRemaining = calculateDaysRemaining(
          strategy.days_elapsed,
          strategy.window_days
        );
        const isComplete = isWindowComplete(
          strategy.days_elapsed,
          strategy.window_days
        );
        const isNearEnd =
          isNearEndOfWindow(strategy.days_elapsed, strategy.window_days) &&
          !isComplete;

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
            <div className="flex items-start justify-between mb-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-2">
                  <div
                    className={`p-2 rounded-lg ${
                      theme === 'dark' ? 'bg-gray-800' : 'bg-white'
                    }`}
                  >
                    <Sprout className="w-5 h-5 text-orange-500" />
                  </div>
                  <h3 className="text-lg">{strategy.name}</h3>
                </div>
                <p
                  className={`text-sm mb-2 ${
                    theme === 'dark' ? 'text-gray-400' : 'text-gray-600'
                  }`}
                >
                  {strategy.description || strategy.id}
                </p>
                <div
                  className={`text-sm flex flex-wrap items-center gap-3 ${
                    theme === 'dark' ? 'text-gray-500' : 'text-gray-500'
                  }`}
                >
                  <span>Started {formatIncubationDate(strategy.incubation_started_at)}</span>
                  <span>•</span>
                  <span>{strategy.portfolio_id}</span>
                </div>
              </div>

              <ChevronRight
                className={`w-5 h-5 flex-shrink-0 ml-3 transition-transform group-hover:translate-x-1 ${
                  theme === 'dark' ? 'text-gray-600' : 'text-gray-400'
                }`}
              />
            </div>

            <div
              className={`pt-4 border-t ${
                theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
              }`}
            >
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div>
                  <div
                    className={`text-xs mb-1 uppercase tracking-wider ${
                      theme === 'dark' ? 'text-gray-500' : 'text-gray-500'
                    }`}
                  >
                    Mock Capital
                  </div>
                  <div className="text-lg flex items-center gap-1">
                    <DollarSign className="w-4 h-4 text-orange-500" />
                    {formatMockCapital(strategy.mock_capital).replace('$', '')}
                  </div>
                </div>

                <div>
                  <div
                    className={`text-xs mb-1 uppercase tracking-wider ${
                      theme === 'dark' ? 'text-gray-500' : 'text-gray-500'
                    }`}
                  >
                    Elapsed
                  </div>
                  <div className="text-lg flex items-center gap-1">
                    <Clock className="w-4 h-4 text-orange-500" />
                    {strategy.days_elapsed}d
                  </div>
                </div>

                <div>
                  <div
                    className={`text-xs mb-1 uppercase tracking-wider ${
                      theme === 'dark' ? 'text-gray-500' : 'text-gray-500'
                    }`}
                  >
                    Remaining
                  </div>
                  <div className="text-lg">{daysRemaining}d</div>
                </div>

                <div>
                  <div
                    className={`text-xs mb-1 uppercase tracking-wider ${
                      theme === 'dark' ? 'text-gray-500' : 'text-gray-500'
                    }`}
                  >
                    Status
                  </div>
                  <div
                    className={`text-lg ${
                      isComplete
                        ? 'text-emerald-500'
                        : isNearEnd
                          ? 'text-amber-500'
                          : 'text-orange-500'
                    }`}
                  >
                    {isComplete
                      ? 'Complete'
                      : isNearEnd
                        ? 'Ending Soon'
                        : `${Math.round(progress)}%`}
                  </div>
                </div>
              </div>

              <div className="mt-4">
                <div
                  className={`h-2 rounded-full overflow-hidden ${
                    theme === 'dark' ? 'bg-gray-800' : 'bg-gray-200'
                  }`}
                >
                  <div
                    className={`h-full transition-all ${
                      isComplete
                        ? 'bg-emerald-500'
                        : isNearEnd
                          ? 'bg-amber-500'
                          : 'bg-orange-500'
                    }`}
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
