import React, { useEffect, useState } from 'react';
import { useTheme } from '../../adapters/react/ThemeContext';
import { useCommandPoll } from '../../adapters/react/useCommandPoll';
import { DeskService, type ApprovalPage as ApprovalData } from '../../application/qt/deskService';
import { approvalTokenFrom, describeCommand, type DeskCommand } from '../../domain/qt/desk';

/**
 * /qt/approve?token=... (A5). The engine e-mails this link to the VP and the
 * President. The page shows the model book (system) next to the desk's
 * request (qt_proposal) and the current qt book; either approver decides.
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

  const load = () => {
    if (!token) {
      setError('This link has no approval token.');
      return;
    }
    DeskService.approval(token)
      .then(data => {
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
  const canDecide = viewer && viewer.approver_role && !viewer.is_requester && !page?.decision && !decision;

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

            <table className="w-full text-sm mt-6" data-testid="approval-books">
              <thead>
                <tr className={muted}>
                  <th className="text-left font-normal py-1 pr-4">Symbol</th>
                  <th className="text-right font-normal py-1 pr-4">Model (system)</th>
                  <th className="text-right font-normal py-1 pr-4">Desk request (QT proposal)</th>
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
                {describeCommand(polled.command, polled.timedOut)}
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
                    disabled={busy}
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
