// @vitest-environment jsdom
//
// The small "Confirmed decision" / "Pending override" pill inside the decision
// card. When the card itself is amber (waiting, or the source day is
// unverified) or red (report blocked / processing failed), a green pill inside
// it contradicted the card. The pill now follows the card in those two cases and
// is otherwise unchanged (green when confirmed, amber when pending).

import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import fixtures from '../../../../contracts/qt-workflow-v1.json';
import { decodeQtDecision, type QtPhase } from '../../domain/portfolio/qtPreview';
import { QtDecisionStatus } from './QtDecisionStatus';
import { qtStyles } from './qtStyles';

afterEach(cleanup);
const ui = qtStyles(false);
const processed = () => decodeQtDecision(structuredClone(fixtures.decision_processed));
const pending = () => ({ ...decodeQtDecision(structuredClone(fixtures.decision_pending)), status: 'pending_override' as const });

function pill(decision: ReturnType<typeof processed>, phase: QtPhase, verifiedContext: boolean) {
  render(<QtDecisionStatus decision={decision} phase={phase} verifiedContext={verifiedContext}
    onRefresh={vi.fn()} onApprove={vi.fn()} busy={false} />);
  const region = screen.getByRole('region', { name: 'QT decision status' });
  const badge = screen.getByText(/^(Confirmed decision|Pending override)$/);
  return { region, badge };
}

describe('decision pill tone', () => {
  it('is green on a green card (confirmed, processed, report ready)', () => {
    const { region, badge } = pill(processed(), 'processed', true);
    expect(region.className).toContain(ui.tone.success);
    expect(badge.className).toContain(ui.tone.success);
  });
  it('is amber, not green, when the card is amber because the source day is unverified', () => {
    const { region, badge } = pill(processed(), 'processed', false);
    expect(region.className).toContain(ui.tone.warning);
    expect(badge.className).toContain(ui.tone.warning);
    expect(badge.className).not.toContain(ui.tone.success);
  });
  it('is red, not green, when the card is red because the report is blocked', () => {
    const { region, badge } = pill(processed(), 'report_blocked', true);
    expect(region.className).toContain(ui.tone.danger);
    expect(badge.className).toContain(ui.tone.danger);
    expect(badge.className).not.toContain(ui.tone.success);
  });
  it('stays amber while an override is pending', () => {
    const { region, badge } = pill(pending(), 'pending_override', true);
    expect(region.className).toContain(ui.tone.warning);
    expect(badge.className).toContain(ui.tone.warning);
  });
});
