import React, { useEffect, useMemo, useState } from 'react';
import { useTheme } from '../../adapters/react/ThemeContext';
import { DeskApiError, DeskService } from '../../application/qt/deskService';
import {
  validateEdit,
  type BookPosition,
  type DeskCommand,
  type SymbolChoice,
} from '../../domain/qt/desk';

interface DeskEditFormProps {
  portfolioId: string;
  proposal: BookPosition[];
  onSaved: (command: DeskCommand, agent: string) => void;
  onCancel: () => void;
  /** The proposal changed under the draft (409 listing symbols): the panel reloads it. */
  onStale?: (message: string) => void;
}

/**
 * Edit mode on the qt_proposal view (A3): quantities only, whole contracts,
 * 0 = flatten, new symbols from the contract list at their latest close, and
 * a reason. Save writes the proposal and the save row in one transaction,
 * then asks the engine to run its one pass.
 *
 * Each change carries the quantity the form showed (`expected`); the server
 * refuses the save if the proposal moved meanwhile. The parent keys this form
 * on the proposal, so the draft is rebuilt whenever the proposal changes.
 */
export function DeskEditForm({ portfolioId, proposal, onSaved, onCancel, onStale }: DeskEditFormProps) {
  const { theme } = useTheme();
  const dark = theme === 'dark';
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries(proposal.map(p => [p.symbol, String(p.quantity)])),
  );
  const [added, setAdded] = useState<string[]>([]);
  const [reason, setReason] = useState('');
  const [choices, setChoices] = useState<SymbolChoice[] | null>(null);
  const [choiceError, setChoiceError] = useState<string | null>(null);
  const [pick, setPick] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    DeskService.symbols(portfolioId)
      .then(setChoices)
      .catch(err => setChoiceError(err instanceof Error ? err.message : String(err)));
  }, [portfolioId]);

  const held = useMemo(() => new Set(proposal.map(p => p.symbol)), [proposal]);
  const pickable = (choices ?? []).filter(c => !held.has(c.symbol) && !added.includes(c.symbol));
  const priceOf = (symbol: string) => choices?.find(c => c.symbol === symbol);
  const validation = validateEdit(proposal, draft, added, reason);

  const input = `w-24 px-2 py-1 rounded border text-right ${
    dark ? 'bg-gray-900 border-gray-700 text-white' : 'bg-white border-gray-300 text-gray-900'
  }`;
  const muted = dark ? 'text-gray-400' : 'text-gray-500';

  const save = async () => {
    setTouched(true);
    if (!validation.ok) return;
    setSaving(true);
    setSaveError(null);
    try {
      const result = await DeskService.save(portfolioId, validation.changes, reason.trim());
      onSaved(result.command, result.agent);
    } catch (err) {
      if (err instanceof DeskApiError && err.status === 409 && err.changed.length > 0 && onStale) {
        onStale(
          `Not saved: ${err.changed.join(', ')} changed since you loaded the proposal. ` +
            'The form now shows the current proposal; edit again.',
        );
        return;
      }
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const row = (symbol: string, current: number | null, isNew: boolean) => {
    const choice = isNew ? priceOf(symbol) : undefined;
    return (
      <tr key={symbol} className={dark ? 'border-t border-gray-800' : 'border-t border-gray-200'}>
        <td className="py-2 pr-4">
          {symbol}
          {isNew && choice && (
            <span className={`ml-2 text-xs ${muted}`}>
              new, at {choice.price} ({choice.price_date?.slice(0, 10) ?? 'latest'})
            </span>
          )}
        </td>
        <td className={`py-2 pr-4 text-right ${muted}`}>{current ?? '-'}</td>
        <td className="py-2 pr-4 text-right">
          <input
            aria-label={`Quantity for ${symbol}`}
            inputMode="numeric"
            className={input}
            value={draft[symbol] ?? ''}
            onChange={e => setDraft(d => ({ ...d, [symbol]: e.target.value }))}
            disabled={saving}
          />
          {touched && validation.fieldErrors[symbol] && (
            <div className="text-xs text-red-500 mt-1">{validation.fieldErrors[symbol]}</div>
          )}
        </td>
        <td className="py-2 text-right">
          {isNew ? (
            <button
              type="button"
              className="text-xs text-red-500 hover:underline"
              onClick={() => {
                setAdded(a => a.filter(s => s !== symbol));
                setDraft(d => {
                  const { [symbol]: _drop, ...rest } = d;
                  return rest;
                });
              }}
            >
              remove
            </button>
          ) : (
            <button
              type="button"
              className={`text-xs hover:underline ${muted}`}
              onClick={() => setDraft(d => ({ ...d, [symbol]: '0' }))}
              disabled={saving}
            >
              flatten
            </button>
          )}
        </td>
      </tr>
    );
  };

  return (
    <div data-testid="desk-edit-form" className="mt-4">
      <table className="w-full text-sm">
        <thead>
          <tr className={muted}>
            <th className="text-left py-1 pr-4 font-normal">Symbol</th>
            <th className="text-right py-1 pr-4 font-normal">Proposal now</th>
            <th className="text-right py-1 pr-4 font-normal">New quantity (contracts)</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {proposal.map(p => row(p.symbol, p.quantity, false))}
          {added.map(symbol => row(symbol, null, true))}
        </tbody>
      </table>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <select
          aria-label="Add a symbol"
          className={`px-2 py-1 rounded border text-sm max-w-full ${
            dark ? 'bg-gray-900 border-gray-700 text-white' : 'bg-white border-gray-300'
          }`}
          value={pick}
          onChange={e => setPick(e.target.value)}
          disabled={saving || !choices}
        >
          <option value="">
            {choices ? 'Add a symbol...' : choiceError ? 'Symbol list unavailable' : 'Loading symbols...'}
          </option>
          {pickable.map(c => (
            <option key={c.symbol} value={c.symbol}>
              {c.symbol} - {c.name} - last {c.price}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="px-3 py-1 rounded border text-sm"
          disabled={!pick || saving}
          onClick={() => {
            setAdded(a => [...a, pick]);
            setDraft(d => ({ ...d, [pick]: '' }));
            setPick('');
          }}
        >
          Add
        </button>
        <span className={`text-xs ${muted}`}>The price is the latest close; it is never typed.</span>
      </div>

      <label className="block mt-4 text-sm">
        Reason <span className="text-red-500">*</span>
        <textarea
          aria-label="Reason"
          className={`mt-1 w-full px-3 py-2 rounded border ${
            dark ? 'bg-gray-900 border-gray-700 text-white' : 'bg-white border-gray-300'
          }`}
          rows={2}
          value={reason}
          onChange={e => setReason(e.target.value)}
          disabled={saving}
          placeholder="Why the desk is changing the book"
        />
      </label>

      {touched && validation.formErrors.length > 0 && (
        <ul className="mt-2 text-sm text-red-500">
          {validation.formErrors.map(e => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {saveError && <p className="mt-2 text-sm text-red-500">Save failed: {saveError}</p>}

      <div className="mt-4 flex gap-2">
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="px-4 py-2 rounded bg-orange-500 text-white hover:bg-orange-600 disabled:opacity-50"
        >
          {saving ? 'Saving...' : `Save ${validation.changes.length || ''} change${validation.changes.length === 1 ? '' : 's'}`}
        </button>
        <button type="button" onClick={onCancel} disabled={saving} className="px-4 py-2 rounded border">
          Cancel
        </button>
      </div>
    </div>
  );
}
