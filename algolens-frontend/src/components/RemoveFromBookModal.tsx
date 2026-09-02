import { useEffect, useReducer, useRef, useState } from 'react';
import { AlertTriangle, X } from 'lucide-react';

import { initialState, reduce } from '../domain/portfolio/portfolioAssignment';
import { PortfolioApiService } from '../infrastructure/api/portfolioApi';

interface RemoveFromBookModalProps {
  strategyId: string;
  strategyName: string;
  portfolioId: string;
  theme: string;
  onClose: () => void;
  onRemoved: () => void;
}

/**
 * Take a strategy out of one book.
 *
 * This is the destructive half of membership. Adding a strategy to another book
 * takes nothing away from the books it is already in, so it happens inline with
 * no ceremony. Removing makes that book's history discontinuous, so it gets the
 * same acknowledge-once treatment as a risk breach: the server answers 409 with
 * the consequences, we stop, and the user must act again.
 *
 * Never resubmit automatically.
 */
export function RemoveFromBookModal({
  strategyId,
  strategyName,
  portfolioId,
  theme,
  onClose,
  onRemoved,
}: RemoveFromBookModalProps) {
  const [state, dispatch] = useReducer(reduce, undefined, initialState);
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);

  const [reason, setReason] = useState('');

  // Captured at RENDER time — see EditPositionModal for why reading state.phase
  // inside the async handler would always see 'submitting'.
  const acknowledging = state.phase === 'needs_acknowledgement';

  const isDark = theme === 'dark';
  const submitting = state.phase === 'submitting';
  const disabled = submitting || reason.trim().length === 0;

  async function handleSubmit() {
    dispatch({ type: 'submit' });
    try {
      const result = await PortfolioApiService.removeStrategyFromBook({
        portfolio_id: portfolioId,
        strategy_id: strategyId,
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
      onRemoved();
    } catch (error) {
      if (!mounted.current) return;
      dispatch({
        type: 'rejected',
        message: error instanceof Error ? error.message : 'Could not remove the strategy',
      });
    }
  }

  const inputClass = `w-full px-3 py-2 rounded-lg border text-sm ${
    isDark
      ? 'bg-gray-900 border-gray-700 text-white placeholder-gray-500'
      : 'bg-white border-gray-300 text-black placeholder-gray-400'
  }`;

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
            <h2 className="text-lg font-semibold">Remove {strategyName}</h2>
            <p className={`text-sm ${isDark ? 'text-gray-400' : 'text-gray-500'}`}>
              from <span className="font-mono">{portfolioId}</span>
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
          <p className={`text-sm ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
            The strategy keeps every other book it belongs to. It cannot be removed from its
            last one.
          </p>

          <div>
            <label
              className={`block text-xs font-medium mb-1 ${isDark ? 'text-gray-400' : 'text-gray-500'}`}
              htmlFor="remove-reason"
            >
              Reason (required)
            </label>
            <textarea
              id="remove-reason"
              className={`${inputClass} min-h-[72px]`}
              value={reason}
              onChange={e => { setReason(e.target.value); dispatch({ type: 'edited' }); }}
              placeholder="Why is this strategy leaving this book?"
            />
          </div>

          {state.phase === 'needs_acknowledgement' && (
            <div className="rounded-lg border border-amber-500/50 bg-amber-500/10 px-4 py-3">
              <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400">
                <AlertTriangle className="w-4 h-4" />
                <span className="text-sm font-medium">This breaks the book's history</span>
              </div>
              <ul className="mt-2 space-y-1.5 text-sm">
                {state.consequences.map(c => <li key={c.code}>{c.message}</li>)}
              </ul>
              <p className={`mt-2 text-xs ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
                Removing again records this as a deliberate change against your name.
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
              acknowledging ? 'bg-amber-600 hover:bg-amber-500' : 'bg-red-600 hover:bg-red-500'
            }`}
          >
            {submitting ? 'Removing…' : acknowledging ? 'Remove anyway' : 'Remove'}
          </button>
        </div>
      </div>
    </div>
  );
}
