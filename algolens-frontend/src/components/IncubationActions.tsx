import { useState } from 'react';
import { AlertTriangle, ArrowUpCircle, XCircle } from 'lucide-react';

import { PortfolioApiService } from '../infrastructure/api/portfolioApi';

interface IncubationActionsProps {
  strategyId: string;
  strategyName: string;
  daysElapsed: number;
  windowDays: number;
  theme: string;
  onChanged: () => void;
}

type Pending = 'promote' | 'retire' | null;

/**
 * Promote a trial to live capital, or retire it.
 *
 * Both transitions existed on the API from the start with nothing calling them,
 * so the trial workflow could only be driven with curl. Both take a reason and
 * are recorded in trading.strategy_lifecycle_log.
 *
 * Promoting before the observation window closes is allowed but called out.
 * The window exists so a decision is made on a full sample; cutting it short is
 * a judgement someone can make, but not one they should make without noticing.
 */
export function IncubationActions({
  strategyId,
  strategyName,
  daysElapsed,
  windowDays,
  theme,
  onChanged,
}: IncubationActionsProps) {
  const [pending, setPending] = useState<Pending>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isDark = theme === 'dark';
  const windowComplete = daysElapsed >= windowDays;
  const remaining = Math.max(0, windowDays - daysElapsed);

  async function submit() {
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      const result = await PortfolioApiService.changeIncubation(strategyId, pending, {
        reason: reason.trim(),
      });
      if (result.outcome === 'rejected') {
        setError(result.message);
        return;
      }
      setPending(null);
      setReason('');
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  const buttonBase = 'inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm';

  if (!pending) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={() => { setPending('promote'); setError(null); }}
          className={`${buttonBase} bg-blue-600 text-white hover:bg-blue-500`}
        >
          <ArrowUpCircle className="w-4 h-4" />
          Promote to live
        </button>
        <button
          onClick={() => { setPending('retire'); setError(null); }}
          className={`${buttonBase} ${
            isDark ? 'bg-gray-800 hover:bg-gray-700' : 'bg-gray-100 hover:bg-gray-200'
          }`}
        >
          <XCircle className="w-4 h-4" />
          Retire
        </button>
        {error && (
          <span className="text-sm text-red-600 dark:text-red-400">{error}</span>
        )}
      </div>
    );
  }

  return (
    <div
      className={`rounded-lg border p-4 ${
        isDark ? 'border-gray-800 bg-gray-900' : 'border-gray-200 bg-gray-50'
      }`}
    >
      <div className="mb-2 text-sm font-medium">
        {pending === 'promote'
          ? `Promote ${strategyName} to live capital`
          : `Retire ${strategyName}`}
      </div>

      {pending === 'promote' && !windowComplete && (
        <div className="mb-3 flex items-start gap-2 rounded-lg border border-amber-500/50 bg-amber-500/10 px-3 py-2">
          <AlertTriangle className="mt-0.5 w-4 h-4 shrink-0 text-amber-600 dark:text-amber-400" />
          <span className="text-sm">
            The observation window has {remaining} of {windowDays} days left. Promoting now
            decides on a partial sample.
          </span>
        </div>
      )}

      <label
        className={`block text-xs font-medium mb-1 ${isDark ? 'text-gray-400' : 'text-gray-500'}`}
        htmlFor="incubation-reason"
      >
        Reason (required)
      </label>
      <textarea
        id="incubation-reason"
        value={reason}
        onChange={e => setReason(e.target.value)}
        placeholder={
          pending === 'promote'
            ? 'What in the trial justifies live capital?'
            : 'Why is this trial being stopped?'
        }
        className={`w-full min-h-[64px] rounded-lg border px-3 py-2 text-sm ${
          isDark
            ? 'bg-gray-950 border-gray-700 text-white placeholder-gray-500'
            : 'bg-white border-gray-300 text-black placeholder-gray-400'
        }`}
      />

      {error && (
        <div className="mt-2 rounded-lg border border-red-500/50 bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-400">
          {error}
        </div>
      )}

      <div className="mt-3 flex justify-end gap-2">
        <button
          onClick={() => { setPending(null); setReason(''); setError(null); }}
          className={`${buttonBase} ${
            isDark ? 'bg-gray-800 hover:bg-gray-700' : 'bg-gray-200 hover:bg-gray-300'
          }`}
        >
          Cancel
        </button>
        <button
          onClick={submit}
          disabled={busy || reason.trim() === ''}
          className={`${buttonBase} text-white disabled:opacity-40 ${
            pending === 'promote'
              ? 'bg-blue-600 hover:bg-blue-500'
              : 'bg-red-600 hover:bg-red-500'
          }`}
        >
          {busy ? 'Saving…' : pending === 'promote' ? 'Promote' : 'Retire'}
        </button>
      </div>
    </div>
  );
}
