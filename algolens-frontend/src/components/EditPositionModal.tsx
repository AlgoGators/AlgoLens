import { useEffect, useReducer, useRef, useState } from 'react';
import { AlertTriangle, X } from 'lucide-react';

import { buildDiff, canSubmit, initialState, isValidAveragePrice, normalizeDecimal8Input, positionValueEvidence, reduce, type ExistingPositionValue } from '../domain/portfolio/positionEdit';
import { PortfolioApiService } from '../infrastructure/api/portfolioApi';
import { useDialogLifecycle } from './useDialogLifecycle';

interface EditPositionModalProps {
  strategyId: string;
  /** Engine-owned identity; strategy type alone is not a unique write target. */
  strategyName: string;
  /** The book being edited. Sent explicitly so the write cannot land elsewhere. */
  portfolioId?: string;
  /** null when adding a new position, in which case the symbol is editable. */
  symbol: string | null;
  existing: ExistingPositionValue | null;
  theme: string;
  onClose: () => void;
  onSaved: () => void;
}

/**
 * Edit or create one position in the qt stream.
 *
 * The critical interaction: when the backend answers with a risk breach it
 * returns 409 and we dispatch {type:'breach'} and STOP. The user must click
 * again to acknowledge. Never resubmit automatically -- an auto-retry would
 * pass every visual review and quietly disable the gate.
 *
 * Ported from AlgoLens PR #32.
 */
export function EditPositionModal({
  strategyId,
  strategyName,
  portfolioId,
  symbol,
  existing,
  theme,
  onClose,
  onSaved,
}: EditPositionModalProps) {
  const [state, dispatch] = useReducer(reduce, undefined, initialState);
  const inFlight = useRef(false);

  // If the user closes the modal mid-flight the request still completes; without
  // this guard its resolution would dispatch into an unmounted component.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const [symbolInput, setSymbolInput] = useState(symbol ?? '');
  const existingEvidence = existing ? positionValueEvidence(existing) : null;
  const invalidEvidence = existingEvidence?.valid === false;
  const [quantity, setQuantity] = useState(existingEvidence?.quantity ?? '');
  const [avgPrice, setAvgPrice] = useState(
    existingEvidence?.averagePrice ?? '',
  );
  const [reason, setReason] = useState('');
  // Only used when the server answered "which book?". A strategy in one book
  // never reaches that state, and a caller that names the book never does.
  const [bookChoice, setBookChoice] = useState('');

  // Captured at RENDER time, deliberately. On the first click the phase is
  // 'idle' so this is false; on the resubmit the previous render left it
  // 'needs_acknowledgement' so it is true. Reading state.phase inside the async
  // handler instead would always see 'submitting' (the dispatch above already
  // ran), so acknowledge_risk would always be false and the gate would never
  // let an acknowledged breach through.
  const acknowledging = state.phase === 'needs_acknowledgement';

  const isDark = theme === 'dark';
  const addingPosition = symbol === null;
  const priceMissing = avgPrice.trim() === '';
  const priceIsValid = isValidAveragePrice(avgPrice) && (!addingPosition || !priceMissing);
  let diff: ReturnType<typeof buildDiff> = [];
  if (!invalidEvidence && canSubmit(reason, quantity) && priceIsValid) {
    try {
      diff = buildDiff(existing, {
        quantity: normalizeDecimal8Input(quantity),
        average_price: priceMissing ? null : normalizeDecimal8Input(avgPrice),
      });
    } catch { /* Invalid legacy evidence cannot be sent as a changed value. */ }
  }
  const submitting = state.phase === 'submitting';
  const dialogRef = useDialogLifecycle(onClose, submitting);

  function onFieldChange(setter: (value: string) => void) {
    return (value: string) => {
      if (inFlight.current) return;
      setter(value);
      // Any edit invalidates a verdict computed from the old values.
      dispatch({ type: 'edited' });
    };
  }

  async function handleSubmit() {
    if (inFlight.current || invalidEvidence || !canSubmit(reason, quantity) || !priceIsValid || diff.length === 0) return;
    inFlight.current = true;
    dispatch({ type: 'submit' });
    try {
      const result = await PortfolioApiService.savePosition({
        strategy_id: strategyId,
        strategy_name: strategyName,
        // Existing rows carry the engine's exact key; the API normalizes new symbols.
        symbol: symbol === null ? symbolInput.trim() : symbol,
        quantity: normalizeDecimal8Input(quantity),
        average_price: priceMissing ? null : normalizeDecimal8Input(avgPrice),
        reason: reason.trim(),
        acknowledge_risk: acknowledging,
        portfolio_id: portfolioId ?? (bookChoice || undefined),
      });
      if (!mounted.current) return;

      if (result.outcome === 'needs_acknowledgement') {
        dispatch({ type: 'breach', risk_check: result.risk_check });
        return;
      }
      if (result.outcome === 'needs_book') {
        setBookChoice(result.books[0] ?? '');
        dispatch({ type: 'ambiguous', books: result.books });
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
        message: error instanceof Error ? error.message : 'Could not save the position',
      });
    } finally {
      inFlight.current = false;
    }
  }

  const choosingBook = state.phase === 'needs_book' || (submitting && state.books.length > 0);
  const disabled =
    submitting ||
    invalidEvidence ||
    !canSubmit(reason, quantity) ||
    !priceIsValid ||
    diff.length === 0 ||
    symbolInput.trim() === '' ||
    (choosingBook && bookChoice === '');
  const inputClass = `w-full px-3 py-2 rounded-lg border text-sm ${
    isDark
      ? 'bg-gray-900 border-gray-700 text-white placeholder-gray-500'
      : 'bg-white border-gray-300 text-black placeholder-gray-400'
  }`;
  const labelClass = `block text-xs font-medium mb-1 ${isDark ? 'text-gray-400' : 'text-gray-500'}`;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="position-editor-title"
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
            <h2 id="position-editor-title" className="text-lg font-semibold">
              {symbol ? `Adjust ${symbol}` : 'Add position'}
            </h2>
            <p className={`text-sm ${isDark ? 'text-gray-400' : 'text-gray-500'}`}>
              {portfolioId ? (
                <>
                  Writes <span className="font-mono">{portfolioId}</span> and records an
                  audit entry
                </>
              ) : (
                'Writes the traded book and records an audit entry'
              )}
            </p>
          </div>
          <button
            onClick={onClose}
            disabled={submitting}
            aria-label="Close"
            className={`rounded-lg p-2 ${isDark ? 'hover:bg-gray-800' : 'hover:bg-gray-100'}`}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-6 py-5 space-y-4">
          {invalidEvidence && (
            <p role="alert" className="text-sm text-red-600 dark:text-red-400">
              Invalid position evidence. Refresh before editing this position.
            </p>
          )}
          <div>
            <label className={labelClass} htmlFor="position-symbol">Symbol</label>
            <input
              id="position-symbol"
              className={inputClass}
              value={symbolInput}
              disabled={symbol !== null || submitting}
              onChange={e => onFieldChange(setSymbolInput)(e.target.value)}
              placeholder="ES"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={labelClass} htmlFor="position-quantity">Quantity</label>
              <input
                id="position-quantity"
                className={inputClass}
                value={quantity}
                disabled={submitting}
                aria-describedby="position-quantity-help"
                onChange={e => onFieldChange(setQuantity)(e.target.value)}
                placeholder="0 closes the position"
              />
              <p
                id="position-quantity-help"
                className={`mt-1 text-xs ${isDark ? 'text-gray-400' : 'text-gray-600'}`}
              >
                Equities may use fractional shares (up to 8 decimal places). Futures require whole contracts. The server verifies the instrument type when saving.
              </p>
            </div>
            <div>
              <label className={labelClass} htmlFor="position-price">
                Average price{' '}
                <span className="font-normal">
                  {addingPosition ? '(required for new positions)' : '(optional — blank keeps current)'}
                </span>
              </label>
              <input
                id="position-price"
                className={inputClass}
                value={avgPrice}
                disabled={submitting}
                aria-invalid={!priceIsValid}
                onChange={e => onFieldChange(setAvgPrice)(e.target.value)}
                placeholder={addingPosition ? 'Required' : 'Leave blank to keep current'}
              />
              {!priceIsValid && (
                <p role="alert" className="mt-1 text-xs text-red-600 dark:text-red-400">
                  {addingPosition && priceMissing
                    ? 'A new position needs an average price.'
                    : 'Average price must be a finite, non-negative number.'}
                </p>
              )}
            </div>
          </div>

          <div>
            <label className={labelClass} htmlFor="position-reason">Reason (required)</label>
            <textarea
              id="position-reason"
              className={`${inputClass} min-h-[72px]`}
              value={reason}
              disabled={submitting}
              onChange={e => onFieldChange(setReason)(e.target.value)}
              placeholder="Why is this position being changed?"
            />
          </div>

          {diff.length > 0 && (
            <div
              className={`rounded-lg border px-4 py-3 text-sm ${
                isDark ? 'border-gray-800 bg-gray-900' : 'border-gray-200 bg-gray-50'
              }`}
            >
              {diff.map(line => (
                <div key={line.field} className="flex justify-between">
                  <span className={isDark ? 'text-gray-400' : 'text-gray-500'}>{line.field}</span>
                  <span className="font-mono">{line.from} → {line.to}</span>
                </div>
              ))}
            </div>
          )}

          {state.phase === 'needs_acknowledgement' && (
            <div className="rounded-lg border border-amber-500/50 bg-amber-500/10 px-4 py-3">
              <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400">
                <AlertTriangle className="w-4 h-4" />
                <span className="text-sm font-medium">
                  This breaches a published risk limit
                </span>
              </div>
              <ul className="mt-2 space-y-1 text-sm">
                {state.breaches.map(breach => (
                  <li key={breach.limit}>{breach.message}</li>
                ))}
              </ul>
              <p className={`mt-2 text-xs ${isDark ? 'text-gray-400' : 'text-gray-600'}`}>
                Saving again records this as a deliberate override against your name.
              </p>
            </div>
          )}

          {choosingBook && (
            <div
              className={`rounded-lg border px-4 py-3 text-sm ${
                isDark ? 'border-gray-800 bg-gray-900' : 'border-gray-200 bg-gray-50'
              }`}
            >
              <p className="mb-2">
                This strategy trades in {state.books.length} books, each with its own
                positions and limits. Which one is this edit for?
              </p>
              <select
                aria-label="Book"
                className={inputClass}
                value={bookChoice}
                disabled={submitting}
                onChange={e => {
                  if (!inFlight.current) setBookChoice(e.target.value);
                }}
              >
                {state.books.map(book => (
                  <option key={book} value={book}>{book}</option>
                ))}
              </select>
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
            disabled={submitting}
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
            {submitting
              ? 'Saving…'
              : acknowledging
                ? 'Override and save'
                : choosingBook
                  ? `Save to ${bookChoice || '…'}`
                  : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
