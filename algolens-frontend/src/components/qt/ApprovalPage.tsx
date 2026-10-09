import React, { useEffect, useState } from 'react';
import { useTheme } from '../../adapters/react/ThemeContext';
import { useCommandPoll } from '../../adapters/react/useCommandPoll';
import { DeskService, type ApprovalPage as ApprovalData } from '../../application/qt/deskService';
import {
  approvalTokenFrom,
  describeCommand,
  formatCountdown,
  serverClockOffsetMs,
  type DeskCommand,
  type DeskDeadlines,
} from '../../domain/qt/desk';

/**
 * The request day's deadline: the desk approves by 09:30 New York; from 10:00
 * the model's book is sent and the request can no longer be decided. Counts
 * down on the server's clock.
 */
function Deadline({ date, deadlines, nowMs }: { date: string; deadlines: DeskDeadlines; nowMs: number }) {
  const approveBy = Date.parse(deadlines.approveBy);
  const fallbackAt = Date.parse(deadlines.fallbackAt);
  let text: string;
  if (nowMs < approveBy) {
    text = `The desk must approve the ${date} book by 09:30 New York (${formatCountdown(approveBy - nowMs)} left). Decide before then so the desk can approve the book you decide.`;
  } else if (nowMs < fallbackAt) {
    text = `09:30 New York has passed. The ${date} book can still be approved until 10:00 (${formatCountdown(fallbackAt - nowMs)} left); from then the model's book is sent and this request can no longer be decided.`;
  } else {
    text = `Closed: from 10:00 New York on ${date} the model's book is sent, so this request can no longer be decided.`;
  }
  return (
    <p data-testid="approval-deadline" className="mt-3 rounded border border-amber-400 px-3 py-2 text-sm">
      {text}
    </p>
  );
}

/**
 * /qt/approve?token=... (A5). The engine e-mails this link to the VP and the
 * President. The page shows the book the request snapshotted (C1): exactly
 * what an approval trades. Below it, the model book (system) next to the
 * desk's current proposal and the current qt book; either approver decides.
 * Once the desk changes the proposal the snapshot no longer matches and the
 * request can only be rejected (the server and the engine refuse an approval).
 * AlgoLens never sees the token's plain value outside this request: the API
 * hashes it to find the override request.
 */
export function ApprovalPage({ onDone }: { onDone: () => void }) {
  const { theme } = useTheme();
  const dark = theme === 'dark';
  const token = approvalTokenFrom(window.location.search);
  const [page, setPage] = useState<ApprovalData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [decision, setDecision] = useState<DeskCommand | null>(null);
  const polled = useCommandPoll(decision);
  const [clockOffset, setClockOffset] = useState(0);
  const [browserNow, setBrowserNow] = useState(() => Date.now());

  useEffect(() => {
    const tick = window.setInterval(() => setBrowserNow(Date.now()), 1_000);
    return () => window.clearInterval(tick);
  }, []);

  const load = () => {
    if (!token) {
      setError('This link has no approval token.');
      return;
    }
    DeskService.approval(token)
      .then(data => {
        const received = Date.now();
        setClockOffset(serverClockOffsetMs(data.serverTime, received));
        setBrowserNow(received);
        setPage(data);
        if (data.decision) setDecision(data.decision);
      })
      .catch(err => setError(err instanceof Error ? err.message : String(err)));
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [token]);

  const decide = async (approved: boolean) => {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      const result = await DeskService.decide(token, approved, reason);
      setDecision(result.command);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const muted = dark ? 'text-gray-400' : 'text-gray-500';
  const viewer = page?.viewer;
  const serverNow = browserNow + clockOffset;
  const closed = Boolean(page?.deadlines && serverNow >= Date.parse(page.deadlines.fallbackAt));
  const canDecide =
    viewer &&
    viewer.approver_role &&
    !viewer.is_requester &&
    !page?.decision &&
    !decision &&
    !page?.published &&
    !closed;
  const canApprove = Boolean(page?.snapshot && page.snapshotMatches);

  return (
    <div className={`min-h-screen ${dark ? 'bg-black text-white' : 'bg-white text-black'}`}>
      <div className="max-w-3xl mx-auto px-4 py-8">
        <button type="button" onClick={onDone} className={`text-sm mb-6 ${muted} hover:underline`}>
          Back to AlgoLens
        </button>
        <h1 className="text-2xl mb-2">QT override approval</h1>
        {error && <p className="mt-4 rounded border border-red-400 px-3 py-2 text-red-500">{error}</p>}
        {!page && !error && <p className={muted}>Loading the request...</p>}
        {page && (
          <>
            <p className="mt-2">
              <span className="font-medium">{page.request.portfolio_id}</span>, book date {page.request.date}
            </p>
            <p className={`mt-1 text-sm ${muted}`}>
              Requested by {page.request.requested_by} at {new Date(page.request.created_at).toLocaleString()}
              {page.request.token_expires_at &&
                `; link valid until ${new Date(page.request.token_expires_at).toLocaleString()}`}
            </p>
            <blockquote className={`mt-3 border-l-4 pl-3 ${dark ? 'border-orange-700' : 'border-orange-300'}`}>
              {page.request.reason}
            </blockquote>
            {page.deadlines && !page.published && (
              <Deadline date={page.request.date} deadlines={page.deadlines} nowMs={serverNow} />
            )}

            <h2 className="text-lg mt-6">The book an approval trades</h2>
            <p className={`text-xs ${muted}`}>
              The desk's proposal as it stood when the request was made. Approving books exactly this.
            </p>
            {page.snapshot ? (
              <table className="w-full text-sm mt-2" data-testid="approval-snapshot">
                <thead>
                  <tr className={muted}>
                    <th className="text-left font-normal py-1 pr-4">Sleeve</th>
                    <th className="text-left font-normal py-1 pr-4">Symbol</th>
                    <th className="text-right font-normal py-1">Contracts</th>
                  </tr>
                </thead>
                <tbody>
                  {page.snapshot.map(r => (
                    <tr
                      key={`${r.strategy_name}|${r.symbol}`}
                      className={dark ? 'border-t border-gray-800' : 'border-t border-gray-200'}
                    >
                      <td className="py-1 pr-4">{r.strategy_name}</td>
                      <td className="py-1 pr-4">{r.symbol}</td>
                      <td className="py-1 text-right">{r.quantity}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="mt-2 text-sm text-red-500">
                This request was made before requests recorded their book; it cannot be approved. Ask the desk for a new
                request.
              </p>
            )}
            {page.snapshot && !page.snapshotMatches && (
              <p className="mt-3 rounded border border-red-400 px-3 py-2 text-sm text-red-500" role="alert">
                The desk has changed the proposal since this request, so it can no longer be approved. Reject it, or ask
                the desk for a new request.
              </p>
            )}
            {page.published && (
              <p className={`mt-3 text-sm ${muted}`}>
                The {page.request.date} book was{' '}
                {page.published.publish_source === 'fallback' ||
                (page.published.published_by ?? '').startsWith('system:fallback')
                  ? "not approved by 10:00 New York, so the engine sent the model's book"
                  : `approved${page.published.published_by ? ` by ${page.published.published_by}` : ''}`}
                ; this request can no longer be decided.
              </p>
            )}

            <h2 className="text-lg mt-6">The books now</h2>
            <table className="w-full text-sm mt-2" data-testid="approval-books">
              <thead>
                <tr className={muted}>
                  <th className="text-left font-normal py-1 pr-4">Symbol</th>
                  <th className="text-right font-normal py-1 pr-4">Model (system)</th>
                  <th className="text-right font-normal py-1 pr-4">Desk proposal now</th>
                  <th className="text-right font-normal py-1 pr-4">Current QT</th>
                  <th className="text-left font-normal py-1">Moved by</th>
                </tr>
              </thead>
              <tbody>
                {page.table.map(r => (
                  <tr key={r.symbol} className={dark ? 'border-t border-gray-800' : 'border-t border-gray-200'}>
                    <td className="py-1 pr-4">{r.symbol}</td>
                    <td className="py-1 pr-4 text-right">{r.model ?? '-'}</td>
                    <td className={`py-1 pr-4 text-right ${r.asked !== r.model ? 'font-semibold' : ''}`}>{r.asked ?? '-'}</td>
                    <td className="py-1 pr-4 text-right">{r.given ?? '-'}</td>
                    <td className="py-1">{r.moved_by ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {polled.command && (
              <p role="status" className="mt-6 rounded border px-3 py-2 text-sm">
                {(polled.command.payload as { approved?: boolean }).approved ? 'Approved' : 'Rejected'} by the{' '}
                {polled.command.approver_role} ({polled.command.requested_by}).{' '}
                {describeCommand(polled.command, polled.phase)}
                {polled.error && <span className="block text-red-500">{polled.error}</span>}
                {(polled.phase !== 'normal' || polled.error) && (
                  <button type="button" className="ml-2 underline" onClick={polled.refresh}>
                    Refresh
                  </button>
                )}
              </p>
            )}

            {viewer && !viewer.approver_role && (
              <p className={`mt-6 text-sm ${muted}`}>
                You are signed in as {viewer.email}, who is not the VP or the President, so you can view this request but
                not decide it.
              </p>
            )}
            {viewer?.is_requester && viewer.approver_role && (
              <p className={`mt-6 text-sm ${muted}`}>You made this request, so the other approver must decide it.</p>
            )}

            {canDecide && (
              <div className="mt-6">
                <label className="block text-sm">
                  Note (optional)
                  <textarea
                    aria-label="Decision note"
                    className={`mt-1 w-full px-3 py-2 rounded border ${dark ? 'bg-gray-900 border-gray-700' : 'bg-white border-gray-300'}`}
                    rows={2}
                    value={reason}
                    onChange={e => setReason(e.target.value)}
                  />
                </label>
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    disabled={busy || !canApprove}
                    title={canApprove ? undefined : 'The proposal changed since the request; it can only be rejected'}
                    onClick={() => decide(true)}
                    className="px-4 py-2 rounded bg-green-600 text-white disabled:opacity-50"
                  >
                    Approve as {viewer?.approver_role === 'vp' ? 'VP' : 'President'}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => decide(false)}
                    className="px-4 py-2 rounded bg-red-600 text-white disabled:opacity-50"
                  >
                    Reject
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
