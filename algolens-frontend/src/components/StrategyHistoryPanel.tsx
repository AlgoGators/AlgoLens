import { useEffect, useState } from 'react';
import { ChevronDown, ChevronUp, History } from 'lucide-react';

import {
  PortfolioApiService,
  type AssignmentRecord,
  type LifecycleRecord,
} from '../infrastructure/api/portfolioApi';

interface StrategyHistoryPanelProps {
  strategyId: string;
  strategyName: string;
  theme: string;
  refreshToken?: number;
}

export function StrategyHistoryPanel({
  strategyId,
  strategyName,
  theme,
  refreshToken = 0,
}: StrategyHistoryPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const [lifecycle, setLifecycle] = useState<LifecycleRecord[]>([]);
  const [assignments, setAssignments] = useState<AssignmentRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isDark = theme === 'dark';

  useEffect(() => {
    if (!expanded) return;
    let current = true;
    setLoading(true);
    setError(null);
    void Promise.all([
        PortfolioApiService.getLifecycleHistory(strategyId),
        PortfolioApiService.getAssignmentHistory(strategyId),
      ])
      .then(([lifecycleRows, assignmentRows]) => {
        if (!current) return;
        setLifecycle(lifecycleRows);
        setAssignments(assignmentRows);
      })
      .catch(() => {
        if (current) setError('History could not be loaded. Refresh and try again.');
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => { current = false; };
  }, [expanded, strategyId, refreshToken]);

  return (
    <div className="w-full">
      <button
        aria-label={`${expanded ? 'Hide' : 'Show'} history for ${strategyName}`}
        aria-expanded={expanded}
        onClick={() => setExpanded(value => !value)}
        className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs ${
          isDark ? 'hover:bg-gray-800' : 'hover:bg-gray-200'
        }`}
      >
        <History className="w-3.5 h-3.5" />
        History
        {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
      </button>
      {expanded && (
        <div className={`mt-2 rounded-lg border p-3 ${
          isDark ? 'border-gray-700 bg-gray-950' : 'border-gray-200 bg-white'
        }`}>
          {loading && <div className="text-xs">Loading history…</div>}
          {error && <div role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</div>}
          {!loading && !error && (
            <div className="overflow-x-auto">
              <div className="grid min-w-[560px] gap-5 md:grid-cols-2">
                <section aria-labelledby={`lifecycle-history-${strategyId}`}>
                  <h3 id={`lifecycle-history-${strategyId}`} className="text-xs font-semibold uppercase tracking-wide">
                    Lifecycle history
                  </h3>
                  {lifecycle.length === 0 ? (
                    <p className="mt-2 text-xs">No lifecycle changes recorded.</p>
                  ) : lifecycle.map(row => (
                    <div key={row.id} className="mt-2 border-t pt-2 text-xs first:border-t-0">
                      <div className="font-medium">{row.before_state} → {row.after_state}</div>
                      <div>{row.reason}</div>
                      <time dateTime={row.created_at}>{new Date(row.created_at).toLocaleString()}</time>
                    </div>
                  ))}
                </section>
                <section aria-labelledby={`membership-history-${strategyId}`}>
                  <h3 id={`membership-history-${strategyId}`} className="text-xs font-semibold uppercase tracking-wide">
                    Membership history
                  </h3>
                  {assignments.length === 0 ? (
                    <p className="mt-2 text-xs">No membership changes recorded.</p>
                  ) : assignments.map(row => (
                    <div key={row.id} className="mt-2 border-t pt-2 text-xs first:border-t-0">
                      <div className="font-medium">
                        {row.from_portfolio_id ?? '—'} → {row.to_portfolio_id ?? '—'}
                      </div>
                      <div>{row.reason || 'No reason recorded'}</div>
                      <time dateTime={row.created_at}>{new Date(row.created_at).toLocaleString()}</time>
                    </div>
                  ))}
                </section>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
