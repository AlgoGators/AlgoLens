import { useCallback, useEffect, useState } from 'react';
import { ArrowRightLeft, Briefcase } from 'lucide-react';

import { useAuth } from '../adapters/react/AuthContext';
import { useTheme } from '../adapters/react/ThemeContext';
import { isInternalRole } from '../domain/identity/user';
import {
  knownPortfolioIds,
  portfolioWeights,
  type PortfolioSummary,
} from '../domain/portfolio/portfolioAssignment';
import { PortfolioApiService } from '../infrastructure/api/portfolioApi';
import { ReassignPortfolioModal } from './ReassignPortfolioModal';

type MoveTarget = { strategyId: string; strategyName: string; portfolioId: string };

/**
 * The strategies grouped by the portfolio that owns them.
 *
 * portfolio_id has always scoped every read in this app, but nothing ever
 * showed it — you could not tell from any screen that two strategies shared a
 * book and a third did not. This is that view, plus the only place the mapping
 * can be changed.
 */
export function PortfolioGrouping() {
  const { theme } = useTheme();
  const { user } = useAuth();
  const [portfolios, setPortfolios] = useState<PortfolioSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [moving, setMoving] = useState<MoveTarget | null>(null);

  const isDark = theme === 'dark';
  // The backend enforces this too (@internal_only); this only avoids offering a
  // control that would come back 403.
  const canReassign = isInternalRole(user?.role);

  const load = useCallback(async () => {
    try {
      setPortfolios(await PortfolioApiService.getPortfolios());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load portfolios');
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/50 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
        {error}
      </div>
    );
  }
  if (!portfolios) {
    return <div className={`text-sm ${isDark ? 'text-gray-500' : 'text-gray-400'}`}>Loading…</div>;
  }

  const weights = new Map(portfolioWeights(portfolios).map(w => [w.portfolio_id, w.percent]));
  const allIds = knownPortfolioIds(portfolios);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className={`text-sm uppercase tracking-wider ${isDark ? 'text-gray-400' : 'text-gray-500'}`}>
          Portfolios
        </h3>
        <span className={`text-xs ${isDark ? 'text-gray-500' : 'text-gray-400'}`}>
          {portfolios.length} {portfolios.length === 1 ? 'portfolio' : 'portfolios'}
        </span>
      </div>

      {portfolios.map(portfolio => (
        <div
          key={portfolio.portfolio_id}
          className={`rounded-lg border overflow-hidden ${isDark ? 'border-gray-800' : 'border-gray-200'}`}
        >
          <div
            className={`flex items-center justify-between px-4 py-3 border-b ${
              isDark ? 'bg-gray-900 border-gray-800' : 'bg-gray-50 border-gray-200'
            }`}
          >
            <div className="flex items-center gap-2">
              <Briefcase className="w-4 h-4" />
              <span className="font-mono text-sm">{portfolio.portfolio_id}</span>
              <span className={`text-xs ${isDark ? 'text-gray-500' : 'text-gray-400'}`}>
                {portfolio.strategy_count}{' '}
                {portfolio.strategy_count === 1 ? 'strategy' : 'strategies'}
              </span>
            </div>
            <div className="text-right">
              <div className="text-sm tabular-nums">
                ${portfolio.total_value.toLocaleString('en-US', { maximumFractionDigits: 0 })}
              </div>
              <div className={`text-xs tabular-nums ${isDark ? 'text-gray-500' : 'text-gray-400'}`}>
                {(weights.get(portfolio.portfolio_id) ?? 0).toFixed(1)}% of fund
              </div>
            </div>
          </div>

          {portfolio.strategies.map(strategy => (
            <div
              key={strategy.id}
              className={`flex items-center justify-between px-4 py-3 border-b last:border-b-0 ${
                isDark ? 'border-gray-800 hover:bg-gray-900' : 'border-gray-100 hover:bg-gray-50'
              }`}
            >
              <div>
                <div className="text-sm">{strategy.name}</div>
                <div className={`text-xs font-mono ${isDark ? 'text-gray-500' : 'text-gray-400'}`}>
                  {strategy.strategy_type}
                  {strategy.lifecycle !== 'live' && (
                    <span className="ml-2 uppercase">· {strategy.lifecycle}</span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-4">
                {/* null means the engine has published nothing for this
                    (strategy, portfolio) pairing yet -- which is exactly what
                    happens right after a move. Showing $0 would read as
                    "worth nothing" instead of "not published yet". */}
                {strategy.current_value === null ? (
                  <span
                    className={`text-xs ${isDark ? 'text-amber-400' : 'text-amber-600'}`}
                    title="The engine has not published results for this strategy in this portfolio yet"
                  >
                    awaiting engine data
                  </span>
                ) : (
                  <span className="text-sm tabular-nums">
                    ${strategy.current_value.toLocaleString('en-US', { maximumFractionDigits: 0 })}
                  </span>
                )}
                {canReassign && (
                  <button
                    aria-label={`Move ${strategy.name} to another portfolio`}
                    onClick={() =>
                      setMoving({
                        strategyId: strategy.id,
                        strategyName: strategy.name,
                        portfolioId: portfolio.portfolio_id,
                      })
                    }
                    className={`inline-flex items-center justify-center rounded-lg p-1.5 ${
                      isDark ? 'hover:bg-gray-800' : 'hover:bg-gray-200'
                    }`}
                  >
                    <ArrowRightLeft className="w-4 h-4" />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      ))}

      {moving && (
        <ReassignPortfolioModal
          strategyId={moving.strategyId}
          strategyName={moving.strategyName}
          currentPortfolioId={moving.portfolioId}
          knownPortfolioIds={allIds}
          theme={theme}
          onClose={() => setMoving(null)}
          onSaved={() => {
            setMoving(null);
            void load();
          }}
        />
      )}
    </div>
  );
}
