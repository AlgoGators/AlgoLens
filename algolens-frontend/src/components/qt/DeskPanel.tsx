import React, { useCallback, useEffect, useState } from 'react';
import { useTheme } from '../../adapters/react/ThemeContext';
import { useCommandPoll } from '../../adapters/react/useCommandPoll';
import { DeskService } from '../../application/qt/deskService';
import type { PositionBook } from '../../domain/portfolio/bookLabel';
import {
  describeCommand,
  publishBlockedReason,
  type ComparisonRow,
  type DeskCommand,
  type DeskState,
} from '../../domain/qt/desk';
import { DeskEditForm } from './DeskEditForm';
import { SettingsEditor } from './SettingsEditor';

interface DeskPanelProps {
  portfolioId: string;
  book: PositionBook;
  /** Re-read the portfolio's book (the positions under the panel). */
  reloadBook: () => void;
}

function tone(command: DeskCommand | null, dark: boolean): string {
  switch (command?.status) {
    case 'refused':
    case 'failed':
      return dark ? 'bg-red-950 border-red-800 text-red-200' : 'bg-red-50 border-red-300 text-red-800';
    case 'done':
      return dark ? 'bg-green-950 border-green-800 text-green-200' : 'bg-green-50 border-green-300 text-green-800';
    default:
      return dark ? 'bg-gray-900 border-gray-700 text-gray-200' : 'bg-gray-50 border-gray-300 text-gray-800';
  }
}

function CommandStatus({ command, label, onFinal }: {
  command: DeskCommand | null;
  label: string;
  onFinal: () => void;
}) {
  const { theme } = useTheme();
  const polled = useCommandPoll(command, onFinal);
  if (!polled.command) return null;
  return (
    <div
      data-testid={`status-${label}`}
      role="status"
      className={`mt-3 rounded border px-3 py-2 text-sm ${tone(polled.command, theme === 'dark')}`}
    >
      <span className="font-medium">#{polled.command.id}</span>{' '}
      {describeCommand(polled.command, polled.timedOut)}
      <span className="opacity-70"> ({polled.command.requested_by})</span>
    </div>
  );
}

function AskedVsGiven({ rows, dark }: { rows: ComparisonRow[]; dark: boolean }) {
  if (rows.length === 0) return null;
  const muted = dark ? 'text-gray-400' : 'text-gray-500';
  return (
    <div className="mt-4 overflow-x-auto">
      <h4 className={`text-xs uppercase tracking-wider mb-2 ${muted}`}>Asked (QT proposal) vs given (QT)</h4>
      <table className="w-full text-sm" data-testid="asked-vs-given">
        <thead>
          <tr className={muted}>
            <th className="text-left font-normal py-1 pr-4">Symbol</th>
            <th className="text-right font-normal py-1 pr-4">Asked</th>
            <th className="text-right font-normal py-1 pr-4">Given</th>
            <th className="text-left font-normal py-1">Moved by</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr
              key={r.symbol}
              className={`${dark ? 'border-t border-gray-800' : 'border-t border-gray-200'} ${
                r.differs ? (dark ? 'text-amber-300' : 'text-amber-700') : ''
              }`}
            >
              <td className="py-1 pr-4">{r.symbol}</td>
              <td className="py-1 pr-4 text-right">{r.asked ?? '-'}</td>
              <td className="py-1 pr-4 text-right">{r.given ?? '-'}</td>
              <td className="py-1">{r.moved_by ?? (r.differs ? '(not recorded)' : '')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The QT desk panel on a desk-editable portfolio (A3-A6): edit the proposal,
 * watch the engine's answer, request an override, publish the day's book.
 */
export function DeskPanel({ portfolioId, book, reloadBook }: DeskPanelProps) {
  const { theme } = useTheme();
  const dark = theme === 'dark';
  const [state, setState] = useState<DeskState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [lastSave, setLastSave] = useState<DeskCommand | null>(null);
  const [lastPublish, setLastPublish] = useState<DeskCommand | null>(null);
  const [lastRequest, setLastRequest] = useState<DeskCommand | null>(null);
  const [overrideReason, setOverrideReason] = useState('');
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const load = useCallback(async () => {
    try {
      const next = await DeskService.state(portfolioId);
      setState(next);
      setError(null);
      setLastSave(prev => (prev && next.latestSave?.id === prev.id ? prev : next.latestSave));
      setLastPublish(prev => (prev && next.publish?.id === prev.id ? prev : next.publish));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [portfolioId]);

  useEffect(() => {
    setEditing(false);
    load();
  }, [load]);

  const refreshAll = useCallback(() => {
    load();
    reloadBook();
  }, [load, reloadBook]);

  const box = `mb-8 rounded-lg border p-4 ${dark ? 'border-orange-900 bg-gray-950' : 'border-orange-200 bg-orange-50/30'}`;
  const muted = dark ? 'text-gray-400' : 'text-gray-500';

  if (error) {
    return (
      <section className={box} data-testid="desk-panel">
        <p className="text-sm text-red-500">QT desk unavailable: {error}</p>
      </section>
    );
  }
  if (!state) {
    return (
      <section className={box} data-testid="desk-panel">
        <p className={`text-sm ${muted}`}>Loading the QT desk...</p>
      </section>
    );
  }

  const publishBlocked = publishBlockedReason(state);
  const act = async (fn: () => Promise<void>) => {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={box} data-testid="desk-panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg">QT desk</h3>
          <p className={`text-sm ${muted}`}>
            Book date {state.date ?? 'none yet'}
            {' - '}
            {state.published?.published_at
              ? `published by ${state.published.published_by ?? 'unknown'} at ${new Date(state.published.published_at).toLocaleString()}`
              : 'not published'}
          </p>
        </div>
        <button
          type="button"
          data-testid="publish-button"
          disabled={busy || publishBlocked !== null}
          title={publishBlocked ?? 'Finalise the qt book, send the daily e-mail and CSV'}
          onClick={() =>
            act(async () => {
              const result = await DeskService.publish(portfolioId);
              setLastPublish(result.command);
              load();
            })
          }
          className="px-4 py-2 rounded bg-orange-500 text-white hover:bg-orange-600 disabled:opacity-50"
        >
          {publishBlocked === 'Published' ? 'Published' : 'Publish'}
        </button>
      </div>

      {!state.seeded && (
        <p className={`mt-3 rounded border px-3 py-2 text-sm ${tone({ status: 'refused' } as DeskCommand, dark)}`}>
          The day's model run has not seeded the QT proposal yet. Editing opens once it has.
        </p>
      )}

      <CommandStatus command={lastSave} label="save" onFinal={refreshAll} />
      <CommandStatus command={lastPublish} label="publish" onFinal={load} />
      <CommandStatus command={lastRequest} label="override" onFinal={load} />
      {actionError && <p className="mt-3 text-sm text-red-500">{actionError}</p>}

      {state.seeded && book === 'qt_proposal' && !editing && (
        <button
          type="button"
          data-testid="edit-button"
          className="mt-4 px-4 py-2 rounded border"
          onClick={() => setEditing(true)}
        >
          Edit the proposal
        </button>
      )}
      {state.seeded && book !== 'qt_proposal' && (
        <p className={`mt-4 text-sm ${muted}`}>Switch the book to QT proposal to edit it.</p>
      )}
      {editing && book === 'qt_proposal' && (
        <DeskEditForm
          portfolioId={portfolioId}
          proposal={state.books.qt_proposal}
          onCancel={() => setEditing(false)}
          onSaved={command => {
            setEditing(false);
            setLastSave(command);
            refreshAll();
          }}
        />
      )}

      <AskedVsGiven rows={state.comparison} dark={dark} />

      <div className="mt-6">
        <h4 className={`text-xs uppercase tracking-wider mb-2 ${muted}`}>Override</h4>
        {state.overrideRequests.map(r => (
          <p key={r.id} className="text-sm mb-1">
            #{r.id} by {r.requested_by}: {r.status}
            {r.message ? ` (${r.message})` : ''}
            {' - '}
            {r.decision
              ? `${(r.decision.payload as { approved?: boolean }).approved ? 'APPROVED' : 'REJECTED'} by the ${r.decision.approver_role} (${r.decision.requested_by}), ${r.decision.status}${r.decision.message ? `: ${r.decision.message}` : ''}`
              : 'awaiting the VP or the President'}
          </p>
        ))}
        {!overrideOpen ? (
          <button
            type="button"
            className="mt-1 px-3 py-1 rounded border text-sm"
            disabled={!state.seeded || busy}
            onClick={() => setOverrideOpen(true)}
          >
            Request override
          </button>
        ) : (
          <div className="mt-2">
            <p className={`text-xs ${muted}`}>
              Asks the VP and the President (by e-mail) to let the proposal trade exactly as asked.
            </p>
            <textarea
              aria-label="Override reason"
              className={`mt-1 w-full px-3 py-2 rounded border ${dark ? 'bg-gray-900 border-gray-700' : 'bg-white border-gray-300'}`}
              rows={2}
              value={overrideReason}
              onChange={e => setOverrideReason(e.target.value)}
              placeholder="Why the desk's book should trade as asked"
            />
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                className="px-3 py-1 rounded bg-orange-500 text-white disabled:opacity-50"
                disabled={busy || !overrideReason.trim()}
                onClick={() =>
                  act(async () => {
                    const result = await DeskService.requestOverride(portfolioId, overrideReason.trim());
                    setLastRequest(result.command);
                    setOverrideReason('');
                    setOverrideOpen(false);
                    load();
                  })
                }
              >
                Send request
              </button>
              <button type="button" className="px-3 py-1 rounded border" onClick={() => setOverrideOpen(false)}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="mt-6">
        <button
          type="button"
          className={`text-xs uppercase tracking-wider ${muted} hover:underline`}
          onClick={() => setShowSettings(v => !v)}
          aria-expanded={showSettings}
        >
          {showSettings ? 'Hide' : 'Show'} desk settings
        </button>
        {showSettings && (
          <div className="mt-3">
            <SettingsEditor portfolioId={portfolioId} />
          </div>
        )}
      </div>
    </section>
  );
}
