import { useState, useReducer } from 'react'
import { X } from 'lucide-react'
import { useTheme } from '../contexts/ThemeContext'
import { PortfolioApiService, RiskBreachError } from '../services/portfolioApi'
import { initialState, reduce, canSubmit, buildDiff } from '../lib/positionEdit'

interface EditPositionModalProps {
  strategyId: string
  symbol: string | null
  existing: { quantity: number; average_price: number | null } | null
  onClose: () => void
  onSaved: () => void
}

/**
 * Modal for editing or creating a trading position.
 *
 * When symbol is null, the user is adding a new position and can edit the symbol.
 * Otherwise symbol is read-only and existing contains the current state.
 *
 * The critical interaction: if the backend rejects with a risk breach (409 + risk_check),
 * we dispatch {type:'breach'} and stop. The user must click again to override.
 * Never resubmit automatically inside the catch block — that would defeat the gate.
 */
export function EditPositionModal({
  strategyId, symbol, existing, onClose, onSaved,
}: EditPositionModalProps) {
  const { theme } = useTheme()

  // The reducer manages phase transitions: idle -> submitting -> needs_acknowledgement/error/done
  const [state, dispatch] = useReducer(reduce, undefined, initialState)

  // Form fields, each dispatching {type:'edited'} to clear stale breaches
  const [symbolInput, setSymbolInput] = useState(symbol ?? '')
  const [quantity, setQuantity] = useState(existing ? String(existing.quantity) : '')
  const [avgPrice, setAvgPrice] = useState(
    existing?.average_price != null ? String(existing.average_price) : '',
  )
  const [reason, setReason] = useState('')

  // True when we're waiting for the user to acknowledge a breach and resubmit
  const acknowledging = state.phase === 'needs_acknowledgement'

  async function handleSubmit() {
    dispatch({ type: 'submit' })
    try {
      await PortfolioApiService.createPosition({
        strategy_id: strategyId,
        symbol: symbolInput.trim().toUpperCase(),
        quantity: Number(quantity),
        average_price: avgPrice.trim() === '' ? null : Number(avgPrice),
        reason: reason.trim(),
        // Only true on a resubmit the user explicitly asked for (second click).
        acknowledge_risk: acknowledging,
      })
      // The backend accepted. Transition to done; only then call onSaved.
      dispatch({ type: 'succeeded' })
      onSaved()
      onClose()
    } catch (err) {
      if (err instanceof RiskBreachError) {
        // The breach is overridable. Dispatch the breach and STOP.
        // The user must click the button again to acknowledge and retry.
        dispatch({ type: 'breach', risk_check: err.risk_check })
        return
      }
      // Non-overridable error. Show it but don't allow retry.
      dispatch({
        type: 'rejected',
        message: err instanceof Error ? err.message : String(err),
      })
    }
  }

  // Compute the diff: what will change if we submit
  const after = {
    quantity: Number(quantity),
    average_price: avgPrice.trim() === '' ? null : Number(avgPrice),
  }
  const diff = buildDiff(existing, after)

  // Primary button is disabled if we can't submit (form invalid or already submitting)
  const canProceed = canSubmit(reason, quantity) && state.phase !== 'submitting'

  return (
    <div className="fixed inset-0 z-[100] overflow-hidden">
      <div className={`h-full overflow-y-auto ${theme === 'dark' ? 'bg-black text-white' : 'bg-white text-black'}`}>
        {/* Sticky header with close button */}
        <div className={`sticky top-0 z-10 border-b ${theme === 'dark' ? 'bg-black border-gray-800' : 'bg-white border-gray-200'}`}>
          <div className="max-w-2xl mx-auto px-6 py-4 flex items-center justify-between">
            <div>
              <h2 className="text-xl font-semibold">
                {existing ? `Edit ${symbol}` : 'Add Position'}
              </h2>
              <p className={`text-sm ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}`}>
                {existing ? 'Update position details' : 'Create a new position in this strategy'}
              </p>
            </div>
            <button
              onClick={onClose}
              className={`p-2 rounded-lg transition-colors ${theme === 'dark'
                ? 'hover:bg-gray-800 text-gray-400'
                : 'hover:bg-gray-100 text-gray-600'
              }`}
              aria-label="Close"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Modal content */}
        <div className="max-w-2xl mx-auto px-6 py-6">
          {/* Risk breach banner: red, lists every breach message */}
          {state.breaches.length > 0 && (
            <div className={`mb-6 p-4 rounded-lg border ${theme === 'dark'
              ? 'bg-red-950 border-red-900 text-red-100'
              : 'bg-red-50 border-red-200 text-red-900'
            }`}>
              <div className="font-semibold mb-2">Risk Limit Breached</div>
              <ul className="space-y-1">
                {state.breaches.map((breach, i) => (
                  <li key={i} className="text-sm">{breach.message}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Non-breach error: no override button */}
          {state.phase === 'error' && state.message && (
            <div className={`mb-6 p-4 rounded-lg border ${theme === 'dark'
              ? 'bg-red-950 border-red-900 text-red-100'
              : 'bg-red-50 border-red-200 text-red-900'
            }`}>
              <div className="text-sm font-semibold">{state.message}</div>
            </div>
          )}

          {/* Form: symbol (read-only if editing), quantity, avg price, reason */}
          <form className="space-y-6" onSubmit={(e) => { e.preventDefault(); handleSubmit() }}>
            {/* Symbol field */}
            <div>
              <label className={`block text-sm font-medium mb-2 ${theme === 'dark' ? 'text-gray-300' : 'text-gray-700'}`}>
                Symbol
              </label>
              {symbol !== null ? (
                // Editing: symbol is read-only
                <div className={`p-3 rounded-lg border ${theme === 'dark'
                  ? 'bg-gray-900 border-gray-800 text-gray-300'
                  : 'bg-gray-50 border-gray-200 text-gray-600'
                }`}>
                  {symbol}
                </div>
              ) : (
                // Adding new: symbol is editable
                <input
                  type="text"
                  value={symbolInput}
                  onChange={(e) => {
                    setSymbolInput(e.target.value)
                    dispatch({ type: 'edited' })
                  }}
                  placeholder="e.g., AAPL"
                  className={`w-full px-3 py-2 rounded-lg border transition-colors ${theme === 'dark'
                    ? 'bg-gray-900 border-gray-800 text-white placeholder-gray-500 focus:border-orange-500 focus:ring-1 focus:ring-orange-500'
                    : 'bg-white border-gray-200 text-black placeholder-gray-400 focus:border-orange-500 focus:ring-1 focus:ring-orange-500'
                  }`}
                />
              )}
            </div>

            {/* Quantity field */}
            <div>
              <label className={`block text-sm font-medium mb-2 ${theme === 'dark' ? 'text-gray-300' : 'text-gray-700'}`}>
                Quantity
              </label>
              <input
                type="number"
                step="0.01"
                value={quantity}
                onChange={(e) => {
                  setQuantity(e.target.value)
                  dispatch({ type: 'edited' })
                }}
                placeholder="e.g., 100"
                className={`w-full px-3 py-2 rounded-lg border transition-colors ${theme === 'dark'
                  ? 'bg-gray-900 border-gray-800 text-white placeholder-gray-500 focus:border-orange-500 focus:ring-1 focus:ring-orange-500'
                  : 'bg-white border-gray-200 text-black placeholder-gray-400 focus:border-orange-500 focus:ring-1 focus:ring-orange-500'
                }`}
              />
            </div>

            {/* Average price field (optional) */}
            <div>
              <label className={`block text-sm font-medium mb-2 ${theme === 'dark' ? 'text-gray-300' : 'text-gray-700'}`}>
                Average Price <span className={theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}>(optional)</span>
              </label>
              <input
                type="number"
                step="0.01"
                value={avgPrice}
                onChange={(e) => {
                  setAvgPrice(e.target.value)
                  dispatch({ type: 'edited' })
                }}
                placeholder="e.g., 150.25"
                className={`w-full px-3 py-2 rounded-lg border transition-colors ${theme === 'dark'
                  ? 'bg-gray-900 border-gray-800 text-white placeholder-gray-500 focus:border-orange-500 focus:ring-1 focus:ring-orange-500'
                  : 'bg-white border-gray-200 text-black placeholder-gray-400 focus:border-orange-500 focus:ring-1 focus:ring-orange-500'
                }`}
              />
            </div>

            {/* Reason field (required, multiline) */}
            <div>
              <label className={`block text-sm font-medium mb-2 ${theme === 'dark' ? 'text-gray-300' : 'text-gray-700'}`}>
                Reason
              </label>
              <textarea
                value={reason}
                onChange={(e) => {
                  setReason(e.target.value)
                  dispatch({ type: 'edited' })
                }}
                placeholder="Why are you making this change?"
                rows={3}
                className={`w-full px-3 py-2 rounded-lg border transition-colors resize-none ${theme === 'dark'
                  ? 'bg-gray-900 border-gray-800 text-white placeholder-gray-500 focus:border-orange-500 focus:ring-1 focus:ring-orange-500'
                  : 'bg-white border-gray-200 text-black placeholder-gray-400 focus:border-orange-500 focus:ring-1 focus:ring-orange-500'
                }`}
              />
            </div>

            {/* Diff preview: what will change */}
            {diff.length > 0 && (
              <div className={`p-4 rounded-lg border ${theme === 'dark'
                ? 'bg-gray-900 border-gray-800'
                : 'bg-gray-50 border-gray-200'
              }`}>
                <div className={`text-sm font-semibold mb-3 ${theme === 'dark' ? 'text-gray-300' : 'text-gray-700'}`}>
                  Preview
                </div>
                <div className="space-y-2">
                  {diff.map((line, i) => (
                    <div key={i} className={`text-sm flex items-center gap-2 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-600'}`}>
                      <span className="font-medium">{line.field}:</span>
                      <span>{line.from}</span>
                      <span className={theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}>→</span>
                      <span className={theme === 'dark' ? 'text-orange-400' : 'text-orange-600'}>{line.to}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Buttons: cancel and primary (submit or override & save) */}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={onClose}
                className={`flex-1 px-4 py-3 rounded-lg font-medium transition-colors ${theme === 'dark'
                  ? 'bg-gray-800 hover:bg-gray-700 text-gray-300'
                  : 'bg-gray-100 hover:bg-gray-200 text-gray-700'
                }`}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!canProceed}
                className={`flex-1 px-4 py-3 rounded-lg font-medium transition-colors ${
                  canProceed
                    ? theme === 'dark'
                      ? 'bg-orange-600 hover:bg-orange-500 text-white cursor-pointer'
                      : 'bg-orange-500 hover:bg-orange-600 text-white cursor-pointer'
                    : theme === 'dark'
                      ? 'bg-gray-800 text-gray-600 cursor-not-allowed'
                      : 'bg-gray-100 text-gray-400 cursor-not-allowed'
                }`}
              >
                {state.phase === 'submitting' ? 'Saving...' : (acknowledging ? 'Override and save' : 'Save')}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
