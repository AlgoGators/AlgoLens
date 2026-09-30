// @vitest-environment jsdom
//
// A book is shared by several strategies but has one MODEL owner per day. The
// rows of the other strategies are saved QT rows and are shown as locked
// holdings. On a strategy page whose own rows are ALL locked while another
// strategy's rows are editable, the window used to give no reason. With
// `focusStrategyName` the guide now says whose quantities can be changed.
// Presentation only: it never changes which row is editable.

import { render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import fixtures from '../../../contracts/qt-workflow-v1.json';
import { decodeQtDraft, decodeQtProposal, type QtSelectionRow } from '../domain/portfolio/qtPreview';
import { QtRecovery } from '../infrastructure/api/qtRecovery';
import { QtProposalWorkspace } from './QtProposalWorkspace';

const api = vi.hoisted(() => ({ getProposal: vi.fn(), getDraft: vi.fn(), saveDraft: vi.fn(),
  createPreview: vi.fn(), confirmPreview: vi.fn(), approveOverride: vi.fn(), getDecision: vi.fn(), getBookDecision: vi.fn() }));
vi.mock('../infrastructure/api/qtPreviewApi', async importOriginal => ({
  ...await importOriginal<typeof import('../infrastructure/api/qtPreviewApi')>(), QtPreviewApi: api,
}));

const props = { actorId: '101', bookId: 'synthetic-book-A', sourceDay: '2026-09-25' };
const NOTE = 'cannot be changed in this window';

function row(strategy: string, symbol: string, editable: boolean, origin: QtSelectionRow['origin']) {
  return { key: { portfolio_id: props.bookId, strategy_id: `id-${strategy}-${symbol}`, strategy_name: strategy,
    date: props.sourceDay, symbol, portfolio_type: editable ? 'qt_proposal' : 'qt' },
  quantity_exact: '3', basis_status: 'preserved_source', average_price_exact: '100', asset_type: 'EQUITY',
  editable, origin };
}
/**
 * rows: [strategy, symbol, editable]. The MODEL seed holds the editable rows of the
 * owner; the other strategies' saved QT rows arrive as locked (immutable) context.
 */
function serve(rows: Array<[string, string, boolean]>) {
  const seed = rows.filter(([, , e]) => e).map(([s, sym]) => row(s, sym, true, 'verified_model_seed'));
  const locked = rows.filter(([, , e]) => !e).map(([s, sym]) => row(s, sym, false, 'immutable'));
  const chosen = rows.map(([s, sym, e]) => row(s, sym, e, e ? 'qt_draft' : 'immutable'));
  api.getProposal.mockResolvedValue(decodeQtProposal({ ...structuredClone(fixtures.proposal_ready),
    seed_rows: seed, saved_qt_rows: locked }));
  api.getDraft.mockResolvedValue(decodeQtDraft({ ...structuredClone(fixtures.draft_saved), selection_rows: chosen }));
}
const note = () => screen.queryByRole('note');
const guide = () => screen.getByRole('region', { name: 'How QT position changes work' });
async function ready() {
  await screen.findByRole('region', { name: 'How QT position changes work' });
  await waitFor(() => expect(api.getDraft).toHaveBeenCalled());
  await screen.findByRole('table', { name: 'QT component quantities' });
}

beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear();
  QtRecovery.activateActor(sessionStorage, props.actorId);
  api.getBookDecision.mockResolvedValue({ schema_version: 'qt-workflow/v1', book_id: props.bookId,
    source_day: props.sourceDay, decision: null, preview: null });
});
afterEach(() => { sessionStorage.clear(); });

describe('the note for a strategy whose rows are all locked', () => {
  it('names the two editable owners and the locked strategy (the Carry case)', async () => {
    serve([['Carry', '6E', false], ['Carry', 'ZN', false], ['Trend Following', 'ES', true], ['Mean Reversion', 'NQ', true]]);
    render(<QtProposalWorkspace {...props} embedded focusStrategyName="Carry" onPublished={vi.fn()} />);
    await ready();
    await waitFor(() => expect(note()).toBeTruthy());
    expect(note()!.textContent).toBe("Carry cannot be changed in this window: this book's QT desk feed comes from " +
      "Trend Following and Mean Reversion, so Carry's positions are shown as locked holdings. " +
      "You can change Trend Following and Mean Reversion's quantities here.");
    expect(guide().contains(note())).toBe(true);
    expect(note()!.textContent).toContain(NOTE);
  });

  it('uses the singular owner text when one strategy owns every editable row', async () => {
    serve([['Carry', '6E', false], ['Trend Following', 'ES', true], ['Trend Following', 'NQ', true]]);
    render(<QtProposalWorkspace {...props} embedded focusStrategyName="Carry" onPublished={vi.fn()} />);
    await ready();
    await waitFor(() => expect(note()).toBeTruthy());
    expect(note()!.textContent).toBe("Carry cannot be changed in this window: this book's QT desk feed comes from " +
      "Trend Following, so Carry's positions are shown as locked holdings. You can change Trend Following's quantities here.");
  });

  it('matches the strategy name without regard to case, spaces or underscores', async () => {
    serve([['CARRY_TREND', 'ZN', false], ['TREND_FOLLOWING', 'ES', true]]);
    render(<QtProposalWorkspace {...props} embedded focusStrategyName="Carry Trend" onPublished={vi.fn()} />);
    await ready();
    await waitFor(() => expect(note()).toBeTruthy());
    expect(note()!.textContent).toContain('Carry Trend cannot be changed in this window');
    expect(note()!.textContent).toContain('comes from TREND_FOLLOWING,');
  });

  it('does not change which boxes are editable', async () => {
    serve([['Carry', '6E', false], ['Trend Following', 'ES', true]]);
    render(<QtProposalWorkspace {...props} embedded focusStrategyName="Carry" onPublished={vi.fn()} />);
    await ready();
    const table = within(screen.getByRole('table', { name: 'QT component quantities' }));
    const carry = table.getByRole('textbox', { name: /^Chosen quantity for Carry / }) as HTMLInputElement;
    const trend = table.getByRole('textbox', { name: /^Chosen quantity for Trend Following / }) as HTMLInputElement;
    expect(carry.disabled).toBe(true);
    expect(trend.disabled).toBe(false);
  });
});

describe('the note is absent everywhere else', () => {
  it('when the focus strategy has editable rows', async () => {
    serve([['Trend Following', 'ES', true], ['Carry', '6E', false]]);
    render(<QtProposalWorkspace {...props} embedded focusStrategyName="Trend Following" onPublished={vi.fn()} />);
    await ready();
    expect(note()).toBeNull();
  });

  it('when only some of the focus strategy rows are locked', async () => {
    serve([['Carry', '6E', true], ['Carry', 'ZN', false], ['Trend Following', 'ES', true]]);
    render(<QtProposalWorkspace {...props} embedded focusStrategyName="Carry" onPublished={vi.fn()} />);
    await ready();
    expect(note()).toBeNull();
  });

  it('when the workspace has no rows for the focus strategy', async () => {
    serve([['Trend Following', 'ES', true], ['Mean Reversion', 'NQ', false]]);
    render(<QtProposalWorkspace {...props} embedded focusStrategyName="Carry" onPublished={vi.fn()} />);
    await ready();
    expect(note()).toBeNull();
  });

  it('when nothing in the book is editable', async () => {
    serve([['Carry', '6E', false], ['Trend Following', 'ES', false]]);
    render(<QtProposalWorkspace {...props} embedded focusStrategyName="Carry" onPublished={vi.fn()} />);
    await ready();
    expect(note()).toBeNull();
  });

  it('when no focus strategy is given', async () => {
    serve([['Carry', '6E', false], ['Trend Following', 'ES', true]]);
    render(<QtProposalWorkspace {...props} embedded onPublished={vi.fn()} />);
    await ready();
    expect(note()).toBeNull();
  });

  it('when the whole choice is locked by an existing decision (the guide already explains the lock)', async () => {
    serve([['Carry', '6E', false], ['Trend Following', 'ES', true]]);
    const decided = { schema_version: 'qt-workflow/v1', book_id: props.bookId, source_day: props.sourceDay,
      decision: structuredClone(fixtures.decision_pending), preview: structuredClone(fixtures.preview_clean) };
    api.getBookDecision.mockResolvedValue(decided);
    render(<QtProposalWorkspace {...props} embedded focusStrategyName="Carry" onPublished={vi.fn()} />);
    await screen.findByRole('region', { name: 'Immutable QT decision review' });
    await waitFor(() => expect(within(guide()).getByText(/A decision already exists for this source day/)).toBeTruthy());
    expect(note()).toBeNull();
  });
});
