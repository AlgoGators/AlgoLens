import type { QtDecision, QtPhase } from '../../domain/portfolio/qtPreview';

export function QtDecisionStatus({ decision, phase, verifiedContext, approvalAllowed = verifiedContext, onRefresh, onApprove, busy }: {
  decision: QtDecision | null; phase: QtPhase; onRefresh: () => void;
  onApprove: () => void; busy: boolean; verifiedContext: boolean; approvalAllowed?: boolean;
}) {
  if (!decision) return null;
  const status = !verifiedContext ? 'Recovered decision: source day unverified' :
    phase === 'pending_override' ? 'Waiting for two approvals' :
    phase === 'processed' && decision.report_ready ? 'Report ready' :
      phase === 'report_blocked' ? 'Report projection unavailable' :
        decision.receipt?.status === 'failed' ? 'Desk processing failed' : 'Desk processing';
  return <section aria-label="QT decision status" aria-live="polite">
    <h3>{status}</h3>
    <p>Decision {decision.decision_id}. {decision.approvals_count} of {decision.required_approvals} approvals recorded by the server.</p>
    {decision.approvals.map(approval => <p key={approval.person_id}>
      {approval.display_label} approved at {approval.approved_at}.
    </p>)}
    {decision.report_blocked_reasons.length > 0 && <p>Report status: {decision.report_blocked_reasons.join(', ')}.</p>}
    {verifiedContext && approvalAllowed && decision.can_approve && decision.status === 'pending_override' &&
      <button type="button" disabled={busy} onClick={onApprove}>Approve override</button>}
    <button type="button" disabled={busy} onClick={onRefresh}>Refresh decision status</button>
  </section>;
}
