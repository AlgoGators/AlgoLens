import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTheme } from '../../adapters/react/ThemeContext';
import { useCommandPoll } from '../../adapters/react/useCommandPoll';
import { DeskService } from '../../application/qt/deskService';
import type { PositionBook } from '../../domain/portfolio/bookLabel';
import {
  CUTOFF_RULE,
  approveBlockedReason,
  deskDayStatus,
  deskLock,
  describeCommand,
  editBlockedReason,
  formatCountdown,
  newYorkTime,
  overrideBlockedReason,
  proposalKey,
  publishSourceOf,
  serverClockOffsetMs,
  type ComparisonRow,
  type DayPhase,
  type DayStatus,
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
      {describeCommand(polled.command, polled.phase)}
      <span className="opacity-70"> ({polled.command.requested_by})</span>
      {polled.error && <div className="mt-1 text-red-500">{polled.error}</div>}
      {(polled.phase !== 'normal' || polled.error) && (
        <button type="button" className="ml-2 underline" onClick={polled.refresh}>
          Refresh
        </button>
      )}
    </div>
  );
}

/** Re-read the desk state this often, so the banner sees the engine's 09:30 send and 10:00 fallback. */
const STATE_REFRESH_MS = 60_000;

function bannerTone(phase: DayPhase, dark: boolean): string {
  switch (phase) {
    case 'sent':
    case 'approved':
      return dark ? 'bg-green-950 border-green-800 text-green-200' : 'bg-green-50 border-green-300 text-green-800';
    case 'fallback':
      return dark ? 'bg-red-950 border-red-800 text-red-200' : 'bg-red-50 border-red-300 text-red-800';
    case 'open':
    case 'approving':
      return dark ? 'bg-amber-950 border-amber-800 text-amber-200' : 'bg-amber-50 border-amber-300 text-amber-900';
    default:
      return dark ? 'bg-gray-900 border-gray-700 text-gray-200' : 'bg-gray-50 border-gray-300 text-gray-800';
  }
}

/** The day's cutoff state with a countdown on the server's clock. */
function DayBanner({ status, nowMs, dark }: { status: DayStatus; nowMs: number; dark: boolean }) {
  return (
    <div
      data-testid="desk-day-banner"
      role="status"
      className={`mt-3 rounded border px-3 py-2 text-sm ${bannerTone(status.phase, dark)}`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-medium">{status.title}</span>
        {status.countdownTo !== null && (
          <span className="font-mono tabular-nums" data-testid="desk-countdown">
            {formatCountdown(status.countdownTo - nowMs)} {status.countdownLabel}
          </span>
        )}
      </div>
      <p className="mt-1 opacity-80">{status.detail}</p>
      {status.detail !== CUTOFF_RULE && <p className="mt-1 text-xs opacity-70">{CUTOFF_RULE}</p>}
    </div>
  );
}

function publishedLine(state: DeskState): string {
  const published = state.published;
  if (!published?.published_at) {
    return deskLock(state) === 'published' ? 'approved' : 'not approved';
  }
  const at = new Date(published.published_at).toLocaleString();
  const sent = published.sent_at ? `; e-mailed at ${newYorkTime(published.sent_at)} New York` : '';
  switch (publishSourceOf(published)) {
    case 'fallback':
      return `not approved; the engine published the model's book at ${at}${sent}`;
    case 'desk':
      return `approved by ${published.published_by ?? 'unknown'} at ${at}${sent}`;
    default:
      return `published by ${published.published_by ?? 'the engine'} at ${at}${sent}`;
  }
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
 * watch the engine's answer, request an override, approve the day's book by
 * 09:30 New York (the engine's publish command). The banner and its
 * countdown run on the server's clock (serverTime), never the browser's.
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
  const [reloading, setReloading] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  // serverTime minus the browser clock at the last answer; the countdown adds it.
  const [clockOffset, setClockOffset] = useState(0);
  const [browserNow, setBrowserNow] = useState(() => Date.now());
  // Only the newest state request may land: an older answer (a slow one, or
  // one for the portfolio shown before) is dropped.
  const requestSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++requestSeq.current;
    try {
      const next = await DeskService.state(portfolioId);
      if (seq !== requestSeq.current || next.portfolioId !== portfolioId) return;
      const received = Date.now();
      setClockOffset(serverClockOffsetMs(next.serverTime, received));
      setBrowserNow(received);
      setState(next);
      setError(null);
      setLastSave(prev => (prev && next.latestSave?.id === prev.id ? prev : next.latestSave));
      setLastPublish(prev => (prev && next.publish?.id === prev.id ? prev : next.publish));
    } catch (err) {
      if (seq !== requestSeq.current) return;
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [portfolioId]);

  useEffect(() => {
    setEditing(false);
    setLastRequest(null);
    setActionError(null);
    load();
    return () => {
      requestSeq.current += 1; // drop answers still in flight
    };
  }, [load]);

  // The countdown ticks every second; the state is re-read every minute.
  useEffect(() => {
    const tick = window.setInterval(() => setBrowserNow(Date.now()), 1_000);
    const refresh = window.setInterval(() => load(), STATE_REFRESH_MS);
    return () => {
      window.clearInterval(tick);
      window.clearInterval(refresh);
    };
  }, [load]);

  const serverNow = browserNow + clockOffset;
  const dayStatus = state ? deskDayStatus(state, serverNow) : null;
  // Crossing 09:30 or 10:00 changes the phase: ask the server again then.
  const phase = dayStatus?.phase;
  const lastPhase = useRef<DayPhase | undefined>(undefined);
  useEffect(() => {
    const previous = lastPhase.current;
    lastPhase.current = phase;
    if (previous !== undefined && phase !== previous) load();
  }, [phase, load]);

  // A day that becomes published (or starts publishing), or passes 10:00, takes no more edits.
  const editBlocked = state ? editBlockedReason(state, serverNow) : null;
  useEffect(() => {
    if (editBlocked) setEditing(false);
  }, [editBlocked]);

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

  const approveBlocked = approveBlockedReason(state, serverNow);
  const overrideBlocked = overrideBlockedReason(state, serverNow);
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
            {publishedLine(state)}
          </p>
        </div>
        <div className="flex flex-col items-end">
          <button
            type="button"
            data-testid="approve-button"
            disabled={busy || approveBlocked !== null}
            title={
              approveBlocked ??
              "Freeze the day's qt book. Approved before 09:30 New York it is e-mailed at 09:30; from 09:30 to 10:00, at once."
            }
            onClick={() =>
              act(async () => {
                const result = await DeskService.publish(portfolioId);
                setLastPublish(result.command);
                load();
              })
            }
            className="px-4 py-2 rounded bg-orange-500 text-white hover:bg-orange-600 disabled:opacity-50"
          >
            {deskLock(state) === 'published' && publishSourceOf(state.published) === 'desk' ? 'Approved' : 'Approve'}
          </button>
          {approveBlocked && state.date && (
            <p className={`mt-1 max-w-xs text-right text-xs ${muted}`} data-testid="approve-blocked">
              {approveBlocked}
            </p>
          )}
        </div>
      </div>

      {dayStatus && state.deadlines && <DayBanner status={dayStatus} nowMs={serverNow} dark={dark} />}

      {!state.seeded && (
        <p className={`mt-3 rounded border px-3 py-2 text-sm ${tone({ status: 'refused' } as DeskCommand, dark)}`}>
          The day's model run has not seeded the QT proposal yet. Editing opens once it has.
        </p>
      )}

      <CommandStatus command={lastSave} label="save" onFinal={refreshAll} />
      <CommandStatus command={lastPublish} label="approve" onFinal={load} />
      <CommandStatus command={lastRequest} label="override" onFinal={load} />
      {actionError && <p className="mt-3 text-sm text-red-500">{actionError}</p>}

      {state.seeded && book === 'qt_proposal' && !editing && (
        <button
          type="button"
          data-testid="edit-button"
          className="mt-4 px-4 py-2 rounded border disabled:opacity-50"
          disabled={reloading || editBlocked !== null}
          title={editBlocked ?? (reloading ? 'Reloading the proposal...' : undefined)}
          onClick={() => setEditing(true)}
        >
          {editBlocked && deskLock(state) === 'published' ? 'Closed: no more edits' : 'Edit the proposal'}
        </button>
      )}
      {state.seeded && book !== 'qt_proposal' && (
        <p className={`mt-4 text-sm ${muted}`}>Switch the book to QT proposal to edit it.</p>
      )}
      {editing && book === 'qt_proposal' && (
        <DeskEditForm
          // Keyed on the proposal: a reload that changes it resets the draft.
          key={proposalKey(state.books.qt_proposal)}
          portfolioId={portfolioId}
          proposal={state.books.qt_proposal}
          onCancel={() => setEditing(false)}
          onStale={message => {
            setActionError(message);
            load();
          }}
          onSaved={command => {
            setEditing(false);
            setLastSave(command);
            // Edit stays disabled until the proposal this save wrote is reloaded.
            setReloading(true);
            reloadBook();
            load().finally(() => setReloading(false));
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
            className="mt-1 px-3 py-1 rounded border text-sm disabled:opacity-50"
            disabled={busy || overrideBlocked !== null}
            title={overrideBlocked ?? undefined}
            onClick={() => setOverrideOpen(true)}
          >
            Request override
          </button>
        ) : (
          <div className="mt-2">
            <p className={`text-xs ${muted}`}>
              Asks the VP and the President (by e-mail) to let the proposal trade exactly as asked. The request
              records the proposal as it is now; if the desk changes it afterwards, the request can no longer be
              approved. It must be decided, and the day approved, before 10:00 New York: from then on the model's
              book is sent.
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
                disabled={busy || !overrideReason.trim() || overrideBlocked !== null}
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
