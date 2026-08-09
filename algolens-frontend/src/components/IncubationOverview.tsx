import React, { useMemo } from 'react';
import { Clock, FlaskConical, TrendingUp } from 'lucide-react';
import type { IncubatingStrategy } from '../domain/portfolio/incubationData';
import {
  calculateIncubationProgress,
  calculateDaysRemaining,
  formatMockCapital,
  isNearEndOfWindow,
  isWindowComplete,
} from '../domain/portfolio/incubationUtils';
import { useTheme } from '../adapters/react/ThemeContext';

interface IncubationOverviewProps {
  strategies: IncubatingStrategy[];
}

export function IncubationOverview({ strategies }: IncubationOverviewProps) {
  const { theme } = useTheme();

  const summary = useMemo(() => {
    const totalMockCapital = strategies.reduce(
      (sum, strategy) => sum + (strategy.mock_capital || 0),
      0
    );
    const averageProgress =
      strategies.length > 0
        ? strategies.reduce(
            (sum, strategy) =>
              sum +
              calculateIncubationProgress(
                strategy.days_elapsed,
                strategy.window_days
              ),
            0
          ) / strategies.length
        : 0;
    const completed = strategies.filter(strategy =>
      isWindowComplete(strategy.days_elapsed, strategy.window_days)
    ).length;
    const nearEnd = strategies.filter(
      strategy =>
        isNearEndOfWindow(strategy.days_elapsed, strategy.window_days) &&
        !isWindowComplete(strategy.days_elapsed, strategy.window_days)
    ).length;

    return { totalMockCapital, averageProgress, completed, nearEnd };
  }, [strategies]);

  return (
    <div className="mb-8">
      <div className="mb-4">
        <h2
          className={`text-sm uppercase tracking-wider mb-2 ${
            theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}
        >
          Mock Capital Incubation
        </h2>
      </div>

      <div className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <FlaskConical className="w-8 h-8 text-orange-500" />
          <div className="text-4xl md:text-5xl">
            {formatMockCapital(summary.totalMockCapital)}
          </div>
        </div>
        <div
          className={`flex flex-wrap items-center gap-x-4 gap-y-2 text-lg ${
            theme === 'dark' ? 'text-gray-300' : 'text-gray-700'
          }`}
        >
          <span>{strategies.length} incubating strategies</span>
          <span className="hidden sm:inline">•</span>
          <span className="flex items-center gap-2 text-orange-500">
            <TrendingUp className="w-5 h-5" />
            {Math.round(summary.averageProgress)}% average progress
          </span>
        </div>
      </div>

      <div
        className={`grid grid-cols-1 md:grid-cols-3 gap-4 mb-8 border-y py-4 ${
          theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
        }`}
      >
        <div>
          <div
            className={`text-xs mb-1 uppercase tracking-wider ${
              theme === 'dark' ? 'text-gray-500' : 'text-gray-500'
            }`}
          >
            Window Complete
          </div>
          <div className="text-2xl">{summary.completed}</div>
        </div>
        <div>
          <div
            className={`text-xs mb-1 uppercase tracking-wider ${
              theme === 'dark' ? 'text-gray-500' : 'text-gray-500'
            }`}
          >
            Ending Soon
          </div>
          <div className="text-2xl">{summary.nearEnd}</div>
        </div>
        <div>
          <div
            className={`text-xs mb-1 uppercase tracking-wider ${
              theme === 'dark' ? 'text-gray-500' : 'text-gray-500'
            }`}
          >
            Observation Window
          </div>
          <div className="text-2xl">120 days</div>
        </div>
      </div>

      {strategies.length > 0 && (
        <div className="space-y-3 mb-8">
          {strategies.map(strategy => {
            const progress = calculateIncubationProgress(
              strategy.days_elapsed,
              strategy.window_days
            );
            const daysRemaining = calculateDaysRemaining(
              strategy.days_elapsed,
              strategy.window_days
            );

            return (
              <div key={strategy.id}>
                <div className="flex items-center justify-between gap-3 mb-2">
                  <div className="min-w-0">
                    <div className="truncate">{strategy.name}</div>
                    <div
                      className={`text-sm flex items-center gap-1 ${
                        theme === 'dark' ? 'text-gray-500' : 'text-gray-500'
                      }`}
                    >
                      <Clock className="w-4 h-4" />
                      {strategy.days_elapsed}d elapsed, {daysRemaining}d remaining
                    </div>
                  </div>
                  <div className="text-sm text-orange-500">
                    {Math.round(progress)}%
                  </div>
                </div>
                <div
                  className={`h-2 rounded-full overflow-hidden ${
                    theme === 'dark' ? 'bg-gray-800' : 'bg-gray-200'
                  }`}
                >
                  <div
                    className="h-full bg-orange-500 transition-all"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl">Incubating Strategies</h2>
      </div>
    </div>
  );
}
