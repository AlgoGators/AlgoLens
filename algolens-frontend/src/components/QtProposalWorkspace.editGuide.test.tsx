// @vitest-environment jsdom
//
// The edit guide inside the QT proposal workspace, the lock that goes with it,
// and the embedded mode used inside the QT edit dialog (the dialog, not the
// workspace, now scrolls and focuses when "Edit positions" is pressed).
//
// The lock had a hole: the quantity boxes were locked only by a decision this
// browser session created itself. A decision the server already holds for the
// day is shown in the immutable review below, and the boxes above it stayed
// editable and looked live while it was still in flight. They now lock while it
// is pending two approvals or still being processed, and the guide says a
// decision already exists. Once it has finished (processed or failed) a new
// choice may start, so they stay open; those cases are in QtProposalWorkspace.test.tsx.

import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import fixtures from '../../../contracts/qt-workflow-v1.json';
import { decodeQtDecision, decodeQtDraft, decodeQtPreview, decodeQtProposal } from '../domain/portfolio/qtPreview';
import { QtRecovery } from '../infrastructure/api/qtRecovery';
import { QtProposalWorkspace } from './QtProposalWorkspace';

const api = vi.hoisted(() => ({ getProposal: vi.fn(), getDraft: vi.fn(), saveDraft: vi.fn(),
  createPreview: vi.fn(), confirmPreview: vi.fn(), approveOverride: vi.fn(), getDecision: vi.fn(), getBookDecision: vi.fn() }));
vi.mock('../infrastructure/api/qtPreviewApi', async importOriginal => ({
  ...await importOriginal<typeof import('../infrastructure/api/qtPreviewApi')>(), QtPreviewApi: api,
}));

const proposal = () => decodeQtProposal(structuredClone(fixtures.proposal_ready));
const draft = () => decodeQtDraft(structuredClone(fixtures.draft_saved));
const clean = () => decodeQtPreview(structuredClone(fixtures.preview_clean));
const breach = () => decodeQtPreview(structuredClone(fixtures.preview_breach));
const props = { actorId: '101', bookId: 'synthetic-book-A', sourceDay: '2026-09-25' };
const envelope = (decision: unknown, preview: unknown) => ({ schema_version: 'qt-workflow/v1', book_id: props.bookId,
  source_day: props.sourceDay, decision, preview });
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(yes => { resolve = yes; }); return { promise, resolve }; }

const guide = () => screen.getByRole('region', { name: 'How QT position changes work' });
const currentStep = () => within(guide()).queryAllByRole('listitem').filter(item => item.getAttribute('aria-current') === 'step')
  .map(item => item.textContent ?? '');
const editorInputs = () => within(screen.getByRole('table', { name: 'QT component quantities' })).getAllByRole('textbox') as HTMLInputElement[];
const workspace = () => screen.getByRole('region', { name: 'QT proposal workspace' });

beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear();
  QtRecovery.activateActor(sessionStorage, props.actorId);
  api.getProposal.mockResolvedValue(proposal()); api.getDraft.mockResolvedValue(draft());
  api.getBookDecision.mockResolvedValue(envelope(null, null));
});
afterEach(() => { sessionStorage.clear(); });

describe('the edit guide in the workspace', () => {
  it('sits above the quantity boxes and starts at Evaluate for a saved draft, comparing with MODEL', async () => {
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await screen.findAllByRole('textbox');
    const region = guide();
    expect(region).toBeTruthy();
    // The saved draft is 5 and 1; MODEL is 4 and 2, so both boxes differ.
    expect(within(region).getByRole('status').textContent).toBe('2 of 2 editable components differ from the MODEL recommendation.');
    expect(currentStep()).toHaveLength(1);
    expect(currentStep()[0]).toContain('3. Evaluate');
    const table = screen.getByRole('table', { name: 'QT component quantities' });
    expect(region.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('is not shown before the source has loaded', async () => {
    const waiting = deferred<ReturnType<typeof proposal>>(); api.getProposal.mockReturnValue(waiting.promise);
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    expect(screen.queryByRole('region', { name: 'How QT position changes work' })).toBeNull();
    await act(async () => waiting.resolve(proposal()));
    await screen.findByRole('region', { name: 'How QT position changes work' });
  });

  it('goes back to Save draft and recounts as soon as a quantity is edited', async () => {
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await screen.findAllByRole('textbox');
    const [alpha] = editorInputs();
    fireEvent.change(alpha, { target: { value: '4' } });
    // alpha now equals MODEL (4); beta is still 1 against MODEL 2.
    await waitFor(() => expect(within(guide()).getByRole('status').textContent)
      .toBe('1 of 2 editable components differ from the MODEL recommendation.'));
    expect(currentStep()[0]).toContain('2. Save draft');
    expect(within(guide()).getByText(/^✓ 1\. Change quantity/)).toBeTruthy();
  });

  it('moves to Confirm once the choice has been evaluated', async () => {
    api.createPreview.mockResolvedValue(clean());
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await screen.findByRole('button', { name: 'Confirm these quantities' });
    expect(currentStep()[0]).toContain('4. Confirm');
  });
});

describe('a decision the server already holds locks the boxes', () => {
  it('locks them and says so for a pending override found on load', async () => {
    const scoped = proposal(); scoped.action_grants.can_approve = true; api.getProposal.mockResolvedValue(scoped);
    api.getBookDecision.mockResolvedValue(envelope(decodeQtDecision({ ...fixtures.confirm_pending, can_approve: true }), breach()));
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await screen.findByRole('region', { name: 'Immutable QT decision review' });
    await waitFor(() => expect(editorInputs().every(input => input.disabled)).toBe(true));
    expect(within(guide()).getByText(/A decision already exists for this source day/)).toBeTruthy();
    expect(within(guide()).queryByText(/Change quantity/)).toBeNull();
    expect(screen.getByRole('button', { name: 'Approve override' })).toBeTruthy();
  });

  it('locks them and says so for a confirmed decision still being processed, found on load', async () => {
    api.getBookDecision.mockResolvedValue(envelope(decodeQtDecision(structuredClone(fixtures.decision_pending)), clean()));
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await screen.findByRole('region', { name: 'Immutable QT decision review' });
    await waitFor(() => expect(editorInputs().every(input => input.disabled)).toBe(true));
    expect(within(guide()).getByText(/A decision already exists for this source day/)).toBeTruthy();
  });

  it('leaves them editable, and the guide at Evaluate, when the server holds no decision', async () => {
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await screen.findAllByRole('textbox');
    await waitFor(() => expect(api.getBookDecision).toHaveBeenCalled());
    expect(editorInputs().every(input => !input.disabled)).toBe(true);
    expect(within(guide()).queryByText(/A decision already exists/)).toBeNull();
  });

  it('still locks the boxes for a decision this session confirmed itself', async () => {
    api.createPreview.mockResolvedValue(clean());
    api.confirmPreview.mockResolvedValue(decodeQtDecision(structuredClone(fixtures.decision_processed)));
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm these quantities' }));
    await screen.findByText('Report ready');
    expect(editorInputs().every(input => input.disabled)).toBe(true);
    expect(within(guide()).getByText(/A decision already exists for this source day/)).toBeTruthy();
  });

  it('does not lock a verified empty selection, which may start a new choice after a processed one', async () => {
    const marker = { schema_version: 'qt-empty-owner-choice/v2', model_publication_id: fixtures.proposal_ready.seed_publication_id,
      owner_document_digest: 'a'.repeat(64), configured_owner_names: ['EQUITY_MEAN_REVERSION'] };
    api.getProposal.mockResolvedValue(decodeQtProposal({ ...structuredClone(fixtures.proposal_ready),
      schema_version: 'qt-workflow/v2', seed_rows: [], saved_qt_rows: [], empty_owner: marker }));
    api.getDraft.mockResolvedValue(decodeQtDraft({ ...structuredClone(fixtures.draft_saved),
      schema_version: 'qt-workflow/v2', selection_rows: [], empty_owner: marker }));
    api.getBookDecision.mockResolvedValue(envelope(decodeQtDecision(structuredClone(fixtures.decision_processed)), clean()));
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await screen.findByRole('region', { name: 'Immutable QT decision review' });
    expect(within(guide()).queryByText(/A decision already exists/)).toBeNull();
    expect(within(guide()).getByRole('status').textContent).toBe('There are no editable components in this book.');
  });
});

describe('embedded in the QT edit dialog', () => {
  // The dialog supplies the border, radius, padding and background; the workspace keeps only its own spacing.
  it('draws its own panel chrome by default', async () => {
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await screen.findAllByRole('textbox');
    for (const token of ['rounded-xl', 'border', 'p-4', 'sm:p-6', 'bg-white']) expect(workspace().classList.contains(token)).toBe(true);
  });

  it('drops the border, rounding, padding and background when embedded, and keeps its vertical spacing', async () => {
    render(<QtProposalWorkspace {...props} embedded onPublished={vi.fn()} />);
    await screen.findAllByRole('textbox');
    const classes = Array.from(workspace().classList);
    for (const token of ['rounded-xl', 'border', 'p-4', 'sm:p-6', 'bg-white', 'bg-gray-950', 'border-gray-200', 'border-gray-800']) {
      expect(classes).not.toContain(token);
    }
    expect(classes).toContain('space-y-6');
  });

  it('keeps everything else exactly as it is: heading, source day, guide, table, id and tabindex', async () => {
    render(<QtProposalWorkspace {...props} embedded onPublished={vi.fn()} />);
    await screen.findAllByRole('textbox');
    expect(screen.getByRole('heading', { name: 'QT proposal for synthetic-book-A' })).toBeTruthy();
    expect(screen.getByText('Source day 2026-09-25')).toBeTruthy();
    expect(guide()).toBeTruthy();
    expect(screen.getByRole('table', { name: 'QT component quantities' })).toBeTruthy();
    expect(workspace().id).toBe('qt-proposal-workspace');
    expect(workspace().getAttribute('tabindex')).toBe('-1');
  });

  it('no longer moves focus or scrolls by itself: that is the dialog job now', async () => {
    const scroll = vi.fn(); Element.prototype.scrollIntoView = scroll;
    render(<QtProposalWorkspace {...props} embedded onPublished={vi.fn()} />);
    const [alpha] = await screen.findAllByRole('textbox');
    await waitFor(() => expect(alpha).toHaveProperty('disabled', false));
    expect(scroll).not.toHaveBeenCalled();
    expect(document.activeElement).not.toBe(alpha);
    expect(document.activeElement).not.toBe(workspace());
  });

  it('has no focusRequest prop any more (type-level check, run by npm run typecheck)', () => {
    // @ts-expect-error focusRequest was removed when the workspace moved into the dialog
    const stale = <QtProposalWorkspace {...props} focusRequest={1} onPublished={vi.fn()} />;
    expect(stale).toBeTruthy();
  });

  it('does not save, evaluate or confirm anything just by being shown', async () => {
    render(<QtProposalWorkspace {...props} embedded onPublished={vi.fn()} />);
    await screen.findAllByRole('textbox');
    expect(api.saveDraft).not.toHaveBeenCalled();
    expect(api.createPreview).not.toHaveBeenCalled();
    expect(api.confirmPreview).not.toHaveBeenCalled();
    expect(api.approveOverride).not.toHaveBeenCalled();
  });
});

describe('the section itself', () => {
  it('can be linked to and focused', async () => {
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await screen.findAllByRole('textbox');
    expect(workspace().id).toBe('qt-proposal-workspace');
    expect(workspace().getAttribute('tabindex')).toBe('-1');
  });
});
