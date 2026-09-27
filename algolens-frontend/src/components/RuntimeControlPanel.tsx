import { useEffect, useId, useRef, useState } from 'react';
import { useTheme } from '../adapters/react/ThemeContext';
import { RuntimeControlApi, type RuntimeStatus } from '../infrastructure/api/runtimeControlApi';

type Props = { strategyId: string; portfolioId: string; strategyName: string; refreshKey?: string | number };
const uncertainMessage = 'The outcome is uncertain. Refresh status before retrying; no automatic retry was made.';

export function RuntimeControlPanel(props: Props) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const panelId = useId();
  return <section className="mt-2 min-w-0 text-sm">
    <button type="button" aria-expanded={open} aria-controls={panelId} disabled={pending}
      aria-label={`Next-run status for ${props.strategyName} in ${props.portfolioId}`}
      className="rounded border px-3 py-2 disabled:opacity-50" onClick={() => setOpen(value => !value)}>
      Next-run status
    </button>
    {open && <RuntimeDetails key={`${props.strategyId}:${props.portfolioId}`}
      {...props} panelId={panelId} onPending={setPending} />}
  </section>;
}

function RuntimeDetails({ strategyId, portfolioId, refreshKey, panelId, onPending }: Props & {
  panelId: string; onPending: (pending: boolean) => void;
}) {
  const { theme } = useTheme();
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [approvalReason, setApprovalReason] = useState('');
  const [action, setAction] = useState<'run' | 'stop'>('run');
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const busy = useRef(false);
  const alive = useRef(true);
  const lastRequestedRefresh = useRef(-1);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; onPending(false); };
  }, [onPending]);
  useEffect(() => {
    // A sibling lifecycle refresh must not replace this mutation state. Wait
    // for the mutation's own response/manual refresh instead of racing a read.
    if (busy.current) return;
    let current = true;
    const requestedRefresh = refresh !== lastRequestedRefresh.current;
    lastRequestedRefresh.current = refresh;
    setLoading(true);
    RuntimeControlApi.status(strategyId, portfolioId).then(result => {
      if (!current) return;
      setStatus(result);
      setError(previous => previous === uncertainMessage && !requestedRefresh ? previous : null);
      if (requestedRefresh) setUncertain(false);
    }).catch(() => {
      if (current) { setStatus(null); setError('Runtime status is unavailable. No engine state can be confirmed.'); }
    }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [strategyId, portfolioId, refreshKey, refresh]);

  async function mutate(approve: boolean) {
    if (busy.current || !status || loading || uncertain) return;
    busy.current = true; setPending(true); onPending(true); setError(null); setNotice(null);
    try {
      const result = approve && status.intent
        ? await RuntimeControlApi.approve(strategyId, status.intent.id, approvalReason.trim())
        : await RuntimeControlApi.request(strategyId, { action, portfolio_id: portfolioId, reason: reason.trim() });
      if (!alive.current) return;
      if (result.outcome === 'rejected') { setError(result.message); return; }
      setReason(''); setApprovalReason('');
      setNotice(approve ? 'Approval recorded. Await the next engine acknowledgement.' : 'Request recorded; execution approval is still required.');
      setRefresh(value => value + 1);
    } catch {
      if (alive.current) { setError(uncertainMessage); setUncertain(true); }
    } finally {
      busy.current = false;
      if (alive.current) { setPending(false); onPending(false); }
    }
  }
  const ready = Boolean(status?.enabled && status.scope_supported && !loading && !pending && !uncertain);
  const lifecycleAllowed = action === 'run' ? status?.registry_lifecycle === 'live' : status?.registry_lifecycle === 'retired';
  const intent = status?.intent;
  const attempt = status?.latest_attempt;
  const input = `w-full min-w-0 rounded border p-2 ${theme === 'dark' ? 'bg-gray-900 border-gray-600 text-white' : 'bg-white border-gray-300 text-black'}`;
  const intentLabel = intent?.stale ? 'stale — submit a new request'
    : intent?.status === 'pending' ? 'pending approval'
    : intent?.status === 'approved' ? 'approved; awaiting matching engine acknowledgement' : intent?.status;
  return <div id={panelId} className="mt-2 min-w-0 space-y-3 overflow-x-auto rounded border p-3" aria-busy={loading || pending}>
    <p>These controls apply only to a future scheduled run. They do not start a process, move capital, close positions or send email.</p>
    <p>Lifecycle or membership changes can block the next publication until an eligible administrator approves the revised scope.</p>
    <p>The API setting does not prove the engine is enabled. Only a recorded engine acknowledgement confirms an outcome.</p>
    {loading && <p role="status">Loading runtime status…</p>}
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {status && <>
      {!status.enabled && <p>Next-run control is disabled. Existing history remains visible.</p>}
      {status.enabled && !status.scope_supported && <p>This scope has no available reviewed runtime configuration. Requests and approvals are unavailable.</p>}
      {intent ? <div className="space-y-1 break-words">
        <p>Request #{intent.id}: {intentLabel}</p>
        <p>Requested action: {intent.action}; book: {intent.portfolio_id}; engine scope: {intent.engine_strategy_id}</p>
        <p>Reason: {intent.request_reason}</p>
        <p>Configured capital: {intent.financial_summary.initial_capital.toLocaleString('en-US')}</p>
        <ul className="list-inside list-disc">{intent.financial_summary.allocations.map(row =>
          <li key={row.strategy}>{row.strategy}: {Number((row.allocation * 100).toFixed(6))}%</li>)}</ul>
      </div> : <p>No runtime request has been recorded.</p>}
      {status.approved_intent && status.approved_intent.id !== intent?.id &&
        <p>Earlier approved request #{status.approved_intent.id}{status.approved_intent.stale ? ' is stale.' : ' remains approved until superseded.'}</p>}
      {attempt ? <div className="break-words">
        <p>Engine attempt for request #{attempt.intent_id}: {attempt.status}{attempt.outcome ? ` (${attempt.outcome})` : ''}</p>
        <p>Run date: {attempt.run_date}; producer: {attempt.producer_version || 'unknown'}</p>
        {attempt.status === 'running' && <p>Completion is not confirmed. An interrupted attempt can remain in this state.</p>}
        {attempt.failure_code && <p>Failure category: {attempt.failure_code}</p>}
      </div> : <p>No engine acknowledgement has been recorded.</p>}
      {status.enabled && status.scope_supported && <form className="space-y-2" onSubmit={event => { event.preventDefault(); if (ready && lifecycleAllowed && reason.trim()) void mutate(false); }}>
        <label className="block">Requested action
          <select className={input} value={action} disabled={pending} onChange={event => setAction(event.target.value as 'run' | 'stop')}>
            <option value="run">Run the complete configured scope</option>
            <option value="stop">Stop future runs of a retired scope</option>
          </select>
        </label>
        {!lifecycleAllowed && <p>Run requires a live strategy. Stop requires retirement after all effective positions are closed.</p>}
        <label className="block">Reason for runtime request
          <textarea className={input} maxLength={2000} value={reason} disabled={pending} onChange={event => setReason(event.target.value)} />
        </label>
        <button className="rounded border px-3 py-2 disabled:opacity-50" disabled={!ready || !lifecycleAllowed || !reason.trim()} type="submit">Submit runtime request</button>
      </form>}
      {status.approval_eligible && intent?.status === 'pending' && !intent.stale && status.scope_supported && <form className="space-y-2" onSubmit={event => { event.preventDefault(); if (ready && approvalReason.trim()) void mutate(true); }}>
        <p>Review the exact capital and allocations above before approving this request.</p>
        <label className="block">Reason for execution approval
          <textarea className={input} maxLength={2000} value={approvalReason} disabled={pending} onChange={event => setApprovalReason(event.target.value)} />
        </label>
        <button className="rounded border px-3 py-2 disabled:opacity-50" disabled={!ready || !approvalReason.trim()} type="submit">Approve request #{intent.id}</button>
      </form>}
    </>}
    <button type="button" className="rounded border px-3 py-2 disabled:opacity-50" disabled={pending || loading} onClick={() => setRefresh(value => value + 1)}>Refresh status</button>
  </div>;
}
