import type { QtDecision, QtPhase } from '../../domain/portfolio/qtPreview';
import { qtStyles, useQtDark, type QtTone } from './qtStyles';

export function QtDecisionStatus({ decision, phase, verifiedContext, approvalAllowed = verifiedContext, onRefresh, onApprove, busy }: {
  decision: QtDecision | null; phase: QtPhase; onRefresh: () => void;
  onApprove: () => void; busy: boolean; verifiedContext: boolean; approvalAllowed?: boolean;
}) {
  const dark = useQtDark();
  const ui = qtStyles(dark);
  if (!decision) return null;
  const status = !verifiedContext ? 'Recovered decision: source day unverified' :
    phase === 'pending_override' ? 'Waiting for two approvals' :
    phase === 'processed' && decision.report_ready ? 'Report ready' :
      phase === 'report_blocked' ? 'Report projection unavailable' :
        decision.receipt?.status === 'failed' ? 'Desk processing failed' : 'Desk processing';
  const statusTone: QtTone = !verifiedContext ? 'warning' : phase === 'pending_override' ? 'warning' :
    phase === 'processed' && decision.report_ready ? 'success' :
      phase === 'report_blocked' || decision.receipt?.status === 'failed' ? 'danger' : 'info';
  // The pill follows the card when the card is amber or red, so a green pill never sits inside a warning.
  const badgeTone: QtTone = statusTone === 'warning' || statusTone === 'danger' ? statusTone :
    decision.status === 'confirmed_decision' ? 'success' : 'warning';
  const dot = (filled: boolean) => filled ? (dark ? 'bg-emerald-400 border-emerald-400' : 'bg-emerald-600 border-emerald-600') :
    (dark ? 'border-gray-500' : 'border-gray-400');
  return <section aria-label="QT decision status" aria-live="polite" className={`space-y-3 rounded-lg border p-4 ${ui.tone[statusTone]}`}>
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-base font-semibold">{status}</h3>
      <span className="flex items-center gap-2">
        <span className={ui.badge(badgeTone)}>
          {decision.status === 'confirmed_decision' ? 'Confirmed decision' : 'Pending override'}
        </span>
        <span aria-hidden="true" className="flex items-center gap-1">
          {Array.from({ length: decision.required_approvals }, (_, index) =>
            <span key={index} className={`h-2.5 w-2.5 rounded-full border ${dot(index < decision.approvals_count)}`} />)}
        </span>
      </span>
    </div>
    <p className="text-sm">Decision <span className="font-mono break-all">{decision.decision_id}</span>. {decision.approvals_count} of {decision.required_approvals} approvals recorded by the server.</p>
    {decision.approvals.map(approval => <p key={approval.person_id} className="text-sm">
      {approval.display_label} approved at {approval.approved_at}.
    </p>)}
    {decision.report_blocked_reasons.length > 0 && <p className="text-sm">Report status: {decision.report_blocked_reasons.join(', ')}.</p>}
    <div className={ui.buttonRow}>
      {verifiedContext && approvalAllowed && decision.can_approve && decision.status === 'pending_override' &&
        <button type="button" className={ui.btnWarning} disabled={busy} onClick={onApprove}>Approve override</button>}
      <button type="button" className={ui.btnSecondary} disabled={busy} onClick={onRefresh}>Refresh decision status</button>
    </div>
  </section>;
}
