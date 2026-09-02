import { useEffect, useReducer, useRef, useState } from 'react';
import { AlertTriangle, X } from 'lucide-react';

import {
  canSubmit,
  initialState,
  normalizePortfolioId,
  reduce,
} from '../domain/portfolio/portfolioAssignment';
import { PortfolioApiService } from '../infrastructure/api/portfolioApi';

interface ReassignPortfolioModalProps {
  strategyId: string;
  strategyName: string;
  currentPortfolioId: string;
  /** Portfolios already in use, offered as suggestions. A new one can be typed. */
  knownPortfolioIds: string[];
  theme: string;
  onClose: () => void;
  onSaved: () => void;
}

/**
 * Move one strategy to another portfolio.
 *
 * The critical interaction, identical to EditPositionModal: when the backend
 * answers with the consequences it returns 409, we dispatch and STOP. The user
 * must click again to acknowledge. Never resubmit automatically — an auto-retry
 * would pass every visual review and quietly remove the only thing standing
 * between a mis-click and two portfolios with discontinuous history.
 */
export function ReassignPortfolioModal({
  strategyId,
  strategyName,
  currentPortfolioId,
  knownPortfolioIds,
  theme,
  onClose,
  onSaved,
}: ReassignPortfolioModalProps) {
  const [state, dispatch] = useReducer(reduce, undefined, initialState);

  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);

  const [target, setTarget] = useState('');
  const [reason, setReason] = useState('');

  // Captured at RENDER time, deliberately — same reason as EditPositionModal.
  // On the first click the phase is 'idle' so this is false; on the resubmit the
  // previous render left it 'needs_acknowledgement' so it is true. Reading
  // state.phase inside the async handler would always see 'submitting'.
  const acknowledging = state.phase === 'needs_acknowledgement';

  const isDark = theme === 'dark';
  const submitting = state.phase === 'submitting';
  const disabled = submitting || !canSubmit(target, currentPortfolioId, reason);

  function onFieldChange(setter: (value: string) => void) {
    return (value: string) => {
      setter(value);
      // Changing the target invalidates a verdict computed for the old one.
      dispatch({ type: 'edited' });
    };
  }

  async function handleSubmit() {
    dispatch({ type: 'submit' });
    try {
      const result = await PortfolioApiService.reassignPortfolio({
        strategy_id: strategyId,
        portfolio_id: normalizePortfolioId(target),
        reason: reason.trim(),
        acknowledge: acknowledging,
      });
      if (!mounted.current) return;

      if (result.outcome === 'needs_acknowledgement') {
        dispatch({ type: 'consequences', check: result.assignment_check });
        return;
      }
      if (result.outcome === 'rejected') {
        dispatch({ type: 'rejected', message: result.message });
        return;
      }
      dispatch({ type: 'succeeded' });
      onSaved();
    } catch (error) {
      if (!mounted.current) return;
      dispatch({
        type: 'rejected',
        message: error instanceof Error ? error.message : 'Could not reassign the strategy',
      });
    }
  }

  const inputClass = `w-full px-3 py-2 rounded-lg border text-sm ${
    isDark
      ? 'bg-gray-900 border-gray-700 text-white placeholder-gray-500'
      : 'bg-white border-gray-300 text-black placeholder-gray-400'
  }`;
  const labelClass = `block text-xs font-medium mb-1 ${isDark ? 'text-gray-400' : 'text-gray-500'}`;
  const others = knownPortfolioIds.filter(id => id !== currentPortfolioId);

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 p-4">
      <div
        className={`w-full max-w-lg rounded-xl border shadow-xl ${
          isDark ? 'bg-black border-gray-800 text-white' : 'bg-white border-gray-200 text-black'
        }`}
      >
        <div
          className={`flex items-center justify-between border-b px-6 py-4 ${
            isDark ? 'border-gray-800' : 'border-gray-200'
          }`}
        >
          <div>
            <h2 className="text-lg font-semibold">Move {strategyName}</h2>
            <p className={`text-sm ${isDark ? 'text-gray-400' : 'text-gray-500'}`}>
              Currently in <span className="font-mono">{currentPortfolioId}</span>
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className={`rounded-lg p-2 ${isDark ? 'hover:bg-gray-800' : 'hover:bg-gray-100'}`}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-6 py-5 space-y-4">
          <div>
            <label className={labelClass} htmlFor="target-portfolio">Move to</label>
            <input
              id="target-portfolio"
              className={inputClass}
              value={target}
              list="known-portfolios"
              onChange={e => onFieldChange(setTarget)(e.target.value)}
              placeholder="Pick one, or type a new portfolio name"
            />
            <datalist id="known-portfolios">
              {others.map(id => <option key={id} value={id} />)}
            </datalist>
            {others.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {others.map(id => (
                  <button
                    key={id}
                    onClick={() => onFieldChange(setTarget)(id)}
                    className={`rounded-full px-2.5 py-1 text-xs font-mono ${
                      isDark ? 'bg-gray-800 hover:bg-gray-700' : 'bg-gray-100 hover:bg-gray-200'
                    }`}
                  >
                    {id}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div>
            <label className={labelClass} htmlFor="assign-reason">Reason (required)</label>
            <textarea
              id="assign-reason"
              className={`${inputClass} min-h-[72px]`}
              value={reason}
              onChange={e => onFieldChange(setReason)(e.target.value)}
              placeholder="Why is this strategy moving?"
            />
          </div>

          {state.phase === 'needs_acknowledgement' && (
            <div className="rounded-lg border border-amber-500/50 bg-amber-500/10 px-4 py-3">
              <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400">
                <AlertTriangle className="w-4 h-4" />
                <span className="text-sm font-medium">This breaks history continuity</span>
              </div>
              <ul className="mt-2 space-y-1.5 text-sm">
                {state.consequences.map(c => <li key={c.code}>{c.message}</li>)}
              </ul>
              <p className={`mt-2 text-xs ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
                Moving again records this as a deliberate change against your name.
              </p>
            </div>
          )}

          {state.phase === 'error' && state.message && (
            <div className="rounded-lg border border-red-500/50 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
              {state.message}
            </div>
          )}
        </div>

        <div
          className={`flex justify-end gap-3 border-t px-6 py-4 ${
            isDark ? 'border-gray-800' : 'border-gray-200'
          }`}
        >
          <button
            onClick={onClose}
            className={`rounded-lg px-4 py-2 text-sm ${
              isDark ? 'bg-gray-800 hover:bg-gray-700' : 'bg-gray-100 hover:bg-gray-200'
            }`}
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={disabled}
            className={`rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-40 ${
              acknowledging ? 'bg-amber-600 hover:bg-amber-500' : 'bg-blue-600 hover:bg-blue-500'
            }`}
          >
            {submitting ? 'Moving…' : acknowledging ? 'Move anyway' : 'Move'}
          </button>
        </div>
      </div>
    </div>
  );
}
