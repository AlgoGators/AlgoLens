import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, History } from 'lucide-react';

import { useTheme } from '../adapters/react/ThemeContext';
import { PortfolioApiService, type PositionOverride } from '../infrastructure/api/portfolioApi';

interface OverrideHistoryProps {
  strategyId: string;
}

function quantityOf(state: Record<string, unknown> | null | undefined): string {
  if (!state || state.quantity === undefined || state.quantity === null) return '—';
  return String(state.quantity);
}

/**
 * Every manual edit made to this strategy's book.
 *
 * `trading.position_overrides` has been written on every edit since the write
 * path landed, and `GET /portfolio/overrides/<id>` has returned it — but
 * nothing displayed it, so the only way to see what the desk had changed was to
 * query the database. An audit trail nobody can read is not doing its job.
 *
 * Overrides that went through a stated risk breach are called out: "which edits
 * were made over a warning" is the question this table exists to answer.
 */
export function OverrideHistory({ strategyId }: OverrideHistoryProps) {
  const { theme } = useTheme();
  const [overrides, setOverrides] = useState<PositionOverride[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isDark = theme === 'dark';

  const load = useCallback(async () => {
    try {
      setOverrides(await PortfolioApiService.getPositionOverrides(strategyId));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the override history');
    }
  }, [strategyId]);

  useEffect(() => { void load(); }, [load]);

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/50 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
        {error}
      </div>
    );
  }
  if (!overrides) {
    return <div className={`text-sm ${isDark ? 'text-gray-500' : 'text-gray-400'}`}>Loading…</div>;
  }

  const overRiskCount = overrides.filter(o => o.overrode_risk).length;

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h3
          className={`flex items-center gap-2 text-sm uppercase tracking-wider ${
            isDark ? 'text-gray-400' : 'text-gray-500'
          }`}
        >
          <History className="w-4 h-4" />
          Manual edits
        </h3>
        {overRiskCount > 0 && (
          <span className={`text-xs ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>
            {overRiskCount} made over a risk warning
          </span>
        )}
      </div>

      {overrides.length === 0 ? (
        <div
          className={`rounded-lg border px-4 py-8 text-center text-sm ${
            isDark ? 'border-gray-800 text-gray-500' : 'border-gray-200 text-gray-400'
          }`}
        >
          No manual edits recorded for this strategy.
        </div>
      ) : (
        <div className={`rounded-lg border overflow-hidden ${isDark ? 'border-gray-800' : 'border-gray-200'}`}>
          <div
            className={`grid grid-cols-6 gap-4 p-4 text-sm border-b ${
              isDark
                ? 'bg-gray-900 border-gray-800 text-gray-400'
                : 'bg-gray-50 border-gray-200 text-gray-500'
            }`}
          >
            <div>When</div>
            <div>Symbol</div>
            <div className="text-right">Change</div>
            <div>Who</div>
            <div>Risk</div>
            <div>Reason</div>
          </div>

          {overrides.map((override, index) => (
            <div
              key={override.id}
              className={`grid grid-cols-6 gap-4 p-4 text-sm ${
                index !== overrides.length - 1
                  ? isDark
                    ? 'border-b border-gray-800'
                    : 'border-b border-gray-200'
                  : ''
              }`}
            >
              <div className={isDark ? 'text-gray-400' : 'text-gray-500'}>
                {new Date(override.created_at).toLocaleString('en-US', {
                  month: 'short',
                  day: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </div>
              <div className="font-mono">{override.symbol}</div>
              <div className="text-right font-mono tabular-nums">
                {quantityOf(override.before_state)} → {quantityOf(override.after_state)}
              </div>
              <div className={isDark ? 'text-gray-400' : 'text-gray-500'}>
                {override.user_id}{' '}
                <span className={`text-xs ${isDark ? 'text-gray-600' : 'text-gray-400'}`}>
                  via {override.source_app}
                </span>
              </div>
              <div>
                {/* Three states, not two. "not checked" is what an unreachable
                    risk envelope records, and it must never read as a pass. */}
                {override.overrode_risk ? (
                  <span className={`flex items-center gap-1 ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>
                    <AlertTriangle className="w-3.5 h-3.5" />
                    overridden
                  </span>
                ) : override.risk_check_result?.evaluated === false ? (
                  <span className={isDark ? 'text-gray-500' : 'text-gray-400'}>not checked</span>
                ) : (
                  <span className={isDark ? 'text-gray-400' : 'text-gray-500'}>passed</span>
                )}
              </div>
              <div className={isDark ? 'text-gray-300' : 'text-gray-700'}>{override.reason}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
