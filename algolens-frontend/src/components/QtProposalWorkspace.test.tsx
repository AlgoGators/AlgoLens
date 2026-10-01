// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import fixtures from '../../../contracts/qt-workflow-v1.json';
import { decodeQtDecision, decodeQtDraft, decodeQtPreview, decodeQtProposal } from '../domain/portfolio/qtPreview';
import { QtRecovery } from '../infrastructure/api/qtRecovery';
import { QtMutationUncertainError, QtApiError } from '../infrastructure/api/qtPreviewApi';
import { QtProposalWorkspace } from './QtProposalWorkspace';
import { QtSelectionTable } from './qt-proposal/QtSelectionTable';

const api = vi.hoisted(() => ({ getProposal: vi.fn(), getDraft: vi.fn(), saveDraft: vi.fn(),
  createPreview: vi.fn(), confirmPreview: vi.fn(), approveOverride: vi.fn(), getDecision: vi.fn(), getBookDecision: vi.fn() }));
vi.mock('../infrastructure/api/qtPreviewApi', async importOriginal => ({
  ...await importOriginal<typeof import('../infrastructure/api/qtPreviewApi')>(), QtPreviewApi: api,
}));
const proposal = () => decodeQtProposal(structuredClone(fixtures.proposal_ready));
const draft = () => decodeQtDraft(structuredClone(fixtures.draft_saved));
const clean = () => decodeQtPreview(structuredClone(fixtures.preview_clean));
const breach = () => decodeQtPreview(structuredClone(fixtures.preview_breach));
const pending = () => decodeQtDecision(structuredClone(fixtures.decision_pending));
const processed = () => decodeQtDecision(structuredClone(fixtures.decision_processed));
const props = { actorId: '101', actorLabel: 'John Riley (john@example.com)', bookId: 'synthetic-book-A', sourceDay: '2026-09-25' };
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(yes => { resolve = yes; }); return { promise, resolve }; }
function storedIntents(): Array<Record<string, unknown>> {
  return Object.keys(sessionStorage).map(key => JSON.parse(sessionStorage.getItem(key)!));
}

beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear();
  QtRecovery.activateActor(sessionStorage, props.actorId);
  api.getProposal.mockResolvedValue(proposal()); api.getDraft.mockResolvedValue(draft());
  api.getBookDecision.mockResolvedValue({ schema_version: 'qt-workflow/v1', book_id: props.bookId,
    source_day: props.sourceDay, decision: null, preview: null });
});
afterEach(() => { sessionStorage.clear(); });

describe('QT proposal workspace', () => {
  it.each(['read_set_digest', 'selected_book_digest', 'preview_id', 'decision_id'] as const)(
    'keeps the original local approval key when acknowledged %s evidence mismatches', async field => {
      const scoped = proposal(); scoped.action_grants.can_approve = true; api.getProposal.mockResolvedValue(scoped);
      const local = decodeQtDecision({ ...fixtures.confirm_pending, can_approve: true });
      const acknowledged = decodeQtDecision({ ...local, can_approve: false, approvals_count: 1,
        approvals: [{ person_id: 'eric_shwartz', display_label: 'Eric Shwartz', user_id: '101',
          approved_at: '2026-09-25T16:00:00Z' }] });
      const wrong = { ...acknowledged, [field]: field.endsWith('digest') ? 'e'.repeat(64) :
        '90000000-0000-4000-8000-000000000099' };
      api.createPreview.mockResolvedValue(breach()); api.confirmPreview.mockResolvedValue(local);
      api.approveOverride.mockResolvedValueOnce(wrong).mockResolvedValue(acknowledged);
      render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
      const user = userEvent.setup();
      await user.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
      await user.click(await screen.findByRole('button', { name: 'Confirm and request two approvals' }));
      await user.click(await screen.findByRole('button', { name: 'Approve override' }));
      await screen.findByText(/outcome is uncertain/);
      const original = QtRecovery.loadApproval(sessionStorage, '101', props.bookId)!;
      expect(original?.request_id).toBe(local.request_id);
      expect(original?.decision_id).toBeUndefined();
      expect(screen.queryByRole('button', { name: 'Approve override' })).toBeNull();
      expect(screen.queryByRole('region', { name: 'Immutable QT decision review' })).toBeNull();
      await user.click(screen.getByRole('button', { name: 'Retry approval' }));
      await waitFor(() => expect(QtRecovery.loadApproval(sessionStorage, '101', props.bookId)).toBeNull());
      expect(api.approveOverride).toHaveBeenCalledTimes(2);
      expect(api.approveOverride.mock.calls[1]).toEqual([local.request_id,
        { action: 'approve', idempotency_key: original.idempotency_key }]);
      expect(await screen.findByText(/Eric Shwartz approved/)).toBeTruthy();
    });

  it.each(['missing', 'unavailable', 'not_required', 'grant_missing', 'decision_denied'] as const)(
    'withdraws discovered approval authority when %s capability/grant evidence is missing', async mode => {
      const scoped = proposal(); scoped.action_grants.can_approve = true;
      if (mode === 'missing') api.getProposal.mockRejectedValue(new Error('synthetic absent proposal'));
      else {
        if (mode === 'unavailable') { scoped.capability.available = false; scoped.workflow_state = 'workflow_unavailable';
          scoped.action_grants.can_save_draft = false; scoped.action_grants.can_confirm = false; }
        if (mode === 'not_required') scoped.capability.required = false;
        if (mode === 'grant_missing') scoped.action_grants.can_approve = false;
        api.getProposal.mockResolvedValue(scoped);
      }
      api.getBookDecision.mockResolvedValue({ schema_version: 'qt-workflow/v1', book_id: props.bookId,
        source_day: props.sourceDay, decision: decodeQtDecision({ ...fixtures.confirm_pending,
          can_approve: mode !== 'decision_denied' }), preview: breach() });
      render(<QtProposalWorkspace {...props} actorId="202" onPublished={vi.fn()} />);
      const review = await screen.findByRole('region', { name: 'Immutable QT decision review' });
      expect(within(review).queryByRole('button', { name: 'Approve override' })).toBeNull();
      expect(api.approveOverride).not.toHaveBeenCalled();
    });

  it('rejects an old actor discovery after an A to B to A epoch even though actor/book/day match again', async () => {
    const old = deferred<any>(); api.getBookDecision.mockReturnValueOnce(old.promise);
    const view = render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await waitFor(() => expect(api.getBookDecision).toHaveBeenCalledTimes(1));
    view.rerender(<QtProposalWorkspace {...props} actorId="202" onPublished={vi.fn()} />);
    await waitFor(() => expect(api.getBookDecision).toHaveBeenCalledTimes(2));
    view.rerender(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await waitFor(() => expect(api.getBookDecision).toHaveBeenCalledTimes(3));
    await act(async () => old.resolve({ schema_version: 'qt-workflow/v1', book_id: props.bookId,
      source_day: props.sourceDay, decision: decodeQtDecision({ ...fixtures.confirm_pending, can_approve: true }), preview: breach() }));
    expect(screen.queryByRole('region', { name: 'Immutable QT decision review' })).toBeNull();
    expect(api.approveOverride).not.toHaveBeenCalled();
  });

  it('does not restore older approval authority from out-of-order explicit discovery refreshes', async () => {
    const old = deferred<any>();
    const envelope = { schema_version: 'qt-workflow/v1', book_id: props.bookId, source_day: props.sourceDay,
      decision: decodeQtDecision({ ...fixtures.confirm_pending, can_approve: true }), preview: breach() };
    const scoped = proposal(); scoped.action_grants.can_approve = true; api.getProposal.mockResolvedValue(scoped);
    api.getBookDecision.mockResolvedValueOnce(envelope).mockReturnValueOnce(old.promise)
      .mockResolvedValue({ ...envelope, decision: { ...envelope.decision, can_approve: false } });
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await screen.findByRole('button', { name: 'Approve override' });
    const refresh = screen.getByRole('button', { name: 'Refresh discovered decision' });
    await userEvent.setup().click(refresh);
    expect(screen.queryByRole('button', { name: 'Approve override' })).toBeNull();
    await userEvent.setup().click(refresh);
    await waitFor(() => expect(api.getBookDecision).toHaveBeenCalledTimes(3));
    await screen.findByRole('region', { name: 'Immutable QT decision review' });
    await act(async () => old.resolve(envelope));
    expect(screen.queryByRole('button', { name: 'Approve override' })).toBeNull();
  });

  it('renders a complete saved QT selection once, preserving its stream and owner identity', () => {
    const selected = draft().selection_rows.map(row => ({ ...row, key: { ...row.key, portfolio_type: 'qt' },
      origin: 'verified_qt_decision' as const }));
    render(<QtSelectionTable sourceRows={proposal().seed_rows} chosenRows={selected} selection={{}}
      locked={false} onEdit={vi.fn()} />);
    expect(screen.getAllByRole('textbox')).toHaveLength(2);
    expect(screen.getAllByRole('textbox').map(input => (input as HTMLInputElement).value)).toEqual(['5', '1']);
    expect(screen.getByRole('textbox', { name: /synthetic-alpha.* qt$/ })).toBeTruthy();
  });

  it('retries the original uncertain request when discovery shows a newer request in the same book', async () => {
    const original = { actor_id: '101', book_id: props.bookId, request_id: fixtures.confirm_pending.request_id!,
      idempotency_key: '22222222-2222-4222-8222-222222222222' };
    QtRecovery.stageApproval(sessionStorage, original);
    const newer = decodeQtDecision({ ...fixtures.confirm_pending, can_approve: true,
      request_id: '50000000-0000-4000-8000-000000000099', decision_id: '40000000-0000-4000-8000-000000000099' });
    const scoped = proposal(); scoped.action_grants.can_approve = true; api.getProposal.mockResolvedValue(scoped);
    api.getBookDecision.mockResolvedValue({ schema_version: 'qt-workflow/v1', book_id: props.bookId,
      source_day: props.sourceDay, decision: newer, preview: breach() });
    api.approveOverride.mockResolvedValue(decodeQtDecision({ ...fixtures.confirm_pending, can_approve: false,
      approvals_count: 1, approvals: [{ person_id: 'eric_shwartz', display_label: 'Eric Shwartz', user_id: '101',
        approved_at: '2026-09-25T16:00:00Z' }] }));
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await screen.findByRole('region', { name: 'Immutable QT decision review' });
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Retry approval' }));
    await waitFor(() => expect(QtRecovery.loadApproval(sessionStorage, '101', props.bookId)).toBeNull());
    expect(api.approveOverride).toHaveBeenCalledExactlyOnceWith(original.request_id,
      { action: 'approve', idempotency_key: original.idempotency_key });
    expect(screen.queryByText(/outcome is uncertain/)).toBeNull();
  });

  it('does not let delayed discovered approval settlement delete the new actor pending intent', async () => {
    const late = deferred<any>(); api.approveOverride.mockReturnValue(late.promise);
    const scoped = proposal(); scoped.action_grants.can_approve = true; api.getProposal.mockResolvedValue(scoped);
    const review = decodeQtDecision({ ...fixtures.confirm_pending, can_approve: true });
    api.getBookDecision.mockResolvedValue({ schema_version: 'qt-workflow/v1', book_id: props.bookId,
      source_day: props.sourceDay, decision: review, preview: breach() });
    const view = render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Approve override' }));
    view.rerender(<QtProposalWorkspace {...props} actorId="202" onPublished={vi.fn()} />);
    await waitFor(() => expect(api.getBookDecision).toHaveBeenCalledTimes(2));
    const active = { actor_id: '202', book_id: props.bookId, request_id: review.request_id!,
      idempotency_key: '33333333-3333-4333-8333-333333333333' };
    QtRecovery.stageApproval(sessionStorage, active);
    await act(async () => late.resolve(decodeQtDecision({ ...review, can_approve: false, approvals_count: 1,
      approvals: [{ person_id: 'eric_shwartz', display_label: 'Eric Shwartz', user_id: '101',
        approved_at: '2026-09-25T16:00:00Z' }] })));
    expect(QtRecovery.loadApproval(sessionStorage, '202', props.bookId)).toEqual(active);
    expect(QtRecovery.loadApproval(sessionStorage, '101', props.bookId)).toBeNull();
    expect(screen.queryByText(/Eric Shwartz approved/)).toBeNull();
  });

  it('keeps mismatched discovered approval uncertain, locks actual editor inputs and explicitly retries the same key', async () => {
    const scoped = proposal(); scoped.action_grants.can_approve = true; api.getProposal.mockResolvedValue(scoped);
    const review = decodeQtDecision({ ...fixtures.confirm_pending, can_approve: true });
    api.getBookDecision.mockResolvedValue({ schema_version: 'qt-workflow/v1', book_id: props.bookId,
      source_day: props.sourceDay, decision: review, preview: breach() });
    const acknowledged = decodeQtDecision({ ...review, can_approve: false, approvals_count: 1,
      approvals: [{ person_id: 'eric_shwartz', display_label: 'Eric Shwartz', user_id: '101',
        approved_at: '2026-09-25T16:00:00Z' }] });
    api.approveOverride.mockResolvedValueOnce({ ...acknowledged, read_set_digest: 'e'.repeat(64) }).mockResolvedValue(acknowledged);
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Approve override' }));
    await screen.findByText(/outcome is uncertain/);
    const original = QtRecovery.loadApproval(sessionStorage, '101', props.bookId)!;
    expect(original.decision_id).toBeUndefined();
    const editor = screen.getByRole('table', { name: 'QT component quantities' });
    expect(within(editor).getAllByRole('textbox').every(input => (input as HTMLInputElement).disabled)).toBe(true);
    expect(screen.queryByRole('button', { name: 'Approve override' })).toBeNull();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Retry approval' }));
    await waitFor(() => expect(QtRecovery.loadApproval(sessionStorage, '101', props.bookId)).toBeNull());
    expect(api.approveOverride.mock.calls[1][1].idempotency_key).toBe(original.idempotency_key);
    expect(await screen.findByText(/Eric Shwartz approved/)).toBeTruthy();
  });

  it('lets a new distinct approver discover and approve immutable 5/1 evidence without actor-local confirmation', async () => {
    const scoped = proposal(); scoped.action_grants.can_save_draft = false;
    scoped.action_grants.can_confirm = false; scoped.action_grants.can_approve = true;
    api.getProposal.mockResolvedValue(scoped);
    const review = decodeQtDecision({ ...fixtures.confirm_pending, can_approve: true, approvals_count: 1,
      approvals: [{ person_id: 'eric_shwartz', display_label: 'Eric Shwartz', user_id: '101',
        approved_at: '2026-09-25T16:00:00Z' }] });
    api.getBookDecision.mockResolvedValue({ schema_version: 'qt-workflow/v1', book_id: props.bookId,
      source_day: props.sourceDay, decision: review, preview: breach() });
    api.approveOverride.mockResolvedValue(decodeQtDecision({ ...review, status: 'confirmed_decision', can_approve: false,
      approvals_count: 2, approvals: [...review.approvals, { person_id: 'john_riley', display_label: 'John Riley',
        user_id: '202', approved_at: '2026-09-25T16:01:00Z' }], receipt: null }));
    const onPublished = vi.fn();
    render(<QtProposalWorkspace {...props} actorId="202" onPublished={onPublished} />);
    const reviewed = await screen.findByRole('region', { name: 'Immutable QT decision review' });
    const quantities = within(reviewed).getByRole('table', { name: 'Reviewed QT decision quantities' });
    expect(within(quantities).getAllByRole('textbox').map(input => (input as HTMLInputElement).value)).toEqual(['5', '1']);
    expect(within(quantities).getAllByRole('textbox').every(input => (input as HTMLInputElement).disabled)).toBe(true);
    expect(within(reviewed).getByText(/Stage: evaluated; known breach/)).toBeTruthy();
    expect(within(reviewed).getByText(/Stage: evaluated; estimated selected-book cost/)).toBeTruthy();
    expect(api.confirmPreview).not.toHaveBeenCalled();
    expect(sessionStorage.length).toBe(0);
    await userEvent.setup().click(within(reviewed).getByRole('button', { name: 'Approve override' }));
    expect(api.approveOverride).toHaveBeenCalledExactlyOnceWith(review.request_id,
      expect.objectContaining({ action: 'approve', idempotency_key: expect.any(String) }));
    expect(await within(reviewed).findByText(/2 of 2 approvals/)).toBeTruthy();
    expect(onPublished).not.toHaveBeenCalled();
    expect(screen.queryByText('Report ready')).toBeNull();
  });

  it('preserves new editing choices when delayed discovery supplies an older immutable decision', async () => {
    const discovery = deferred<any>(); api.getBookDecision.mockReturnValue(discovery.promise);
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    const choice = await screen.findByRole('textbox', { name: /Chosen quantity for synthetic-alpha/ });
    fireEvent.change(choice, { target: { value: '2.5' } });
    await act(async () => discovery.resolve({ schema_version: 'qt-workflow/v1', book_id: props.bookId,
      source_day: props.sourceDay, decision: decodeQtDecision(fixtures.confirm_pending), preview: breach() }));
    const reviewed = await screen.findByRole('region', { name: 'Immutable QT decision review' });
    expect((choice as HTMLInputElement).value).toBe('2.5');
    expect((within(reviewed).getAllByRole('textbox')[0] as HTMLInputElement).value).toBe('5');
    expect(api.createPreview).not.toHaveBeenCalled(); expect(api.confirmPreview).not.toHaveBeenCalled();
  });

  it('discovers review even when the approver draft read fails, but requires both scoped approval grants', async () => {
    const scoped = proposal(); scoped.action_grants.can_approve = false;
    api.getProposal.mockResolvedValue(scoped); api.getDraft.mockRejectedValue(new Error('synthetic unavailable draft'));
    api.getBookDecision.mockResolvedValue({ schema_version: 'qt-workflow/v1', book_id: props.bookId,
      source_day: props.sourceDay, decision: decodeQtDecision({ ...fixtures.confirm_pending, can_approve: true }), preview: breach() });
    render(<QtProposalWorkspace {...props} actorId="202" onPublished={vi.fn()} />);
    const reviewed = await screen.findByRole('region', { name: 'Immutable QT decision review' });
    expect(within(reviewed).queryByRole('button', { name: 'Approve override' })).toBeNull();
    expect(api.approveOverride).not.toHaveBeenCalled();
  });

  it('rejects stale actor discovery and withdraws approval authority during failed explicit status refresh', async () => {
    const old = deferred<any>();
    const scoped = proposal(); scoped.action_grants.can_approve = true; api.getProposal.mockResolvedValue(scoped);
    api.getBookDecision.mockReturnValueOnce(old.promise).mockResolvedValue({ schema_version: 'qt-workflow/v1',
      book_id: props.bookId, source_day: props.sourceDay,
      decision: decodeQtDecision({ ...fixtures.confirm_pending, can_approve: false }), preview: breach() });
    const view = render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await waitFor(() => expect(api.getBookDecision).toHaveBeenCalledTimes(1));
    view.rerender(<QtProposalWorkspace {...props} actorId="202" onPublished={vi.fn()} />);
    await screen.findByRole('region', { name: 'Immutable QT decision review' });
    await act(async () => old.resolve({ schema_version: 'qt-workflow/v1', book_id: props.bookId,
      source_day: props.sourceDay, decision: decodeQtDecision({ ...fixtures.confirm_pending, can_approve: true }), preview: breach() }));
    expect(screen.queryByRole('button', { name: 'Approve override' })).toBeNull();
    api.getBookDecision.mockRejectedValue(new Error('synthetic failed status read'));
    await userEvent.setup().click(screen.getByRole('button', { name: 'Refresh discovered decision' }));
    expect(screen.queryByRole('button', { name: 'Approve override' })).toBeNull();
    expect(await screen.findByText(/Decision review unavailable/)).toBeTruthy();
    expect(api.approveOverride).not.toHaveBeenCalled();
  });

  it('labels MODEL, previous verified QT, new draft and immutable holdings without inventing a missing MODEL zero', () => {
    const sourceRows = proposal().seed_rows;
    const chosenRows = draft().selection_rows;
    const previous = structuredClone(chosenRows[0]); previous.key.portfolio_type = 'qt';
    previous.origin = 'verified_qt_decision' as any; previous.quantity_exact = '2.5';
    const holding = structuredClone(chosenRows[1]); holding.key.strategy_id = 'immutable-owner';
    holding.key.strategy_name = 'synthetic-holding'; holding.origin = 'immutable'; holding.editable = false;
    chosenRows.push(holding);
    render(<QtSelectionTable sourceRows={sourceRows} chosenRows={chosenRows} previousQtRows={[previous]}
      selection={{}} locked={false} onEdit={vi.fn()} />);
    const first = screen.getByText('synthetic-alpha').closest('tr')!;
    expect(within(first).getByText('2.5')).toBeTruthy();
    expect(within(first).getByText(/New QT draft/)).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: 'MODEL recommendation' })).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: 'Verified previous QT choice' })).toBeTruthy();
    const immutable = screen.getByText('synthetic-holding').closest('tr')!;
    expect(within(immutable).getByText(/Immutable holdings/)).toBeTruthy();
    expect(within(immutable).queryByText('0')).toBeNull();
    expect(within(immutable).getAllByText('Unavailable').length).toBeGreaterThan(0);
  });

  it('keeps signed owner deltas exact and immutable holdings read-only in the complete book table', () => {
    const sourceRows = structuredClone(proposal().seed_rows);
    const chosenRows = structuredClone(draft().selection_rows);
    sourceRows[0].quantity_exact = '-5'; chosenRows[0].quantity_exact = '0';
    sourceRows[1].quantity_exact = '0'; chosenRows[1].quantity_exact = '-5';
    const holding = structuredClone(sourceRows[0]);
    holding.key.strategy_id = 'immutable-3'; holding.key.strategy_name = 'synthetic-holding';
    holding.quantity_exact = '10.25'; holding.editable = false; holding.origin = 'immutable';
    sourceRows.push(holding); chosenRows.push(structuredClone(holding));
    render(<QtSelectionTable sourceRows={sourceRows} chosenRows={chosenRows} selection={{}}
      onEdit={vi.fn()} locked={false} />);
    const table = screen.getByRole('table', { name: 'QT component quantities' });
    const first = within(table).getByText('synthetic-alpha').closest('tr')!;
    const second = within(table).getByText('synthetic-beta').closest('tr')!;
    const immutable = within(table).getByText('synthetic-holding').closest('tr')!;
    expect(within(first).getByText('+5')).toBeTruthy();
    expect(within(second).getByText('-5')).toBeTruthy();
    expect((within(immutable).getByRole('textbox') as HTMLInputElement).value).toBe('10.25');
    expect(within(immutable).getByRole('textbox')).toHaveProperty('disabled', true);
  });

  it('shows separate source, chosen and exact delta for each owner, then evaluates 5/1 without applying aggregate advice', async () => {
    api.createPreview.mockResolvedValue(clean());
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    const table = await screen.findByRole('table', { name: 'QT component quantities' });
    const first = within(table).getByText('synthetic-alpha').closest('tr')!;
    const second = within(table).getByText('synthetic-beta').closest('tr')!;
    expect(within(first).getByText('4')).toBeTruthy();
    expect((within(first).getByRole('textbox') as HTMLInputElement).value).toBe('5');
    expect(within(first).getByText('+1')).toBeTruthy();
    expect(within(second).getByText('2')).toBeTruthy();
    expect((within(second).getByRole('textbox') as HTMLInputElement).value).toBe('1');
    expect(within(second).getByText('-1')).toBeTruthy();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Evaluate my selection' }));
    expect(api.createPreview).toHaveBeenCalledWith(expect.objectContaining({ draft_id: draft().draft_id,
      draft_revision: 1, draft_digest: draft().draft_digest }));
    expect(await screen.findByText(/Proposed optimizer impact/)).toBeTruthy();
    expect((within(first).getByRole('textbox') as HTMLInputElement).value).toBe('5');
    expect((within(second).getByRole('textbox') as HTMLInputElement).value).toBe('1');
  });

  it('shows evaluator-owned proposed risk only after evaluation and before confirmation', async () => {
    api.createPreview.mockResolvedValue(clean());
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    expect(screen.queryByRole('region', { name: 'Proposed post-change risk' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Confirm these quantities' })).toBeNull();
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    const risk = await screen.findByRole('region', { name: 'Proposed post-change risk' });
    expect(within(risk).getByText(/calculated by the server evaluator for proposed selected-book digest/i).textContent)
      .toContain(clean().selected_book_digest);
    expect(within(risk).getByText(/synthetic_exposure_ratio: 0.12345678901234566 ratio/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Confirm these quantities' })).toBeTruthy();
  });

  it('drops stale evaluated risk when the saved rationale changes', async () => {
    api.createPreview.mockResolvedValue(clean());
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await screen.findByRole('region', { name: 'Proposed post-change risk' });
    const rationale = screen.getByRole('textbox', { name: 'Why should this position change be made?' });
    await userEvent.setup().clear(rationale);
    await userEvent.setup().type(rationale, 'Updated reason after reviewing the proposed risk.');
    expect(screen.queryByRole('region', { name: 'Proposed post-change risk' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Confirm these quantities' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Save draft' })).toHaveProperty('disabled', false);
  });

  it('attributes the request, requires a rationale, and sends its trimmed value without a claimed actor', async () => {
    const legacy: any = structuredClone(fixtures.draft_saved);
    legacy.rationale = null;
    api.getDraft.mockResolvedValue(decodeQtDraft(legacy));
    const updated = structuredClone(fixtures.draft_saved);
    updated.draft_revision = 2; updated.draft_digest = 'd'.repeat(64);
    api.saveDraft.mockResolvedValue(decodeQtDraft(updated));
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    const card = await screen.findByRole('region', { name: 'Position change request' });
    expect(within(card).getByText('John Riley (john@example.com)')).toBeTruthy();
    expect(within(card).getByText(/2 of 2 editable positions differ from MODEL/)).toBeTruthy();
    const rationale = within(card).getByRole('textbox', { name: 'Why should this position change be made?' });
    const save = screen.getByRole('button', { name: 'Save draft' });
    expect(save).toHaveProperty('disabled', true);
    await userEvent.setup().type(rationale, '  Reduce concentration before the event window.  ');
    expect(save).toHaveProperty('disabled', false);
    await userEvent.setup().click(save);
    expect(api.saveDraft).toHaveBeenCalledWith(props.bookId, expect.objectContaining({
      rationale: 'Reduce concentration before the event window.',
    }));
    expect(api.saveDraft.mock.calls[0][1]).not.toHaveProperty('actorId');
    expect(api.saveDraft.mock.calls[0][1]).not.toHaveProperty('actorLabel');
  });

  it('saves exact edited quantities before evaluation and rejects fractional futures', async () => {
    const updated = structuredClone(fixtures.draft_saved);
    updated.draft_revision = 2; updated.draft_digest = 'd'.repeat(64);
    updated.selection_rows[0].quantity_exact = '2.5'; updated.selection_rows[1].quantity_exact = '0';
    api.saveDraft.mockResolvedValue(decodeQtDraft(updated));
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    const first = await screen.findByRole('textbox', { name: /Chosen quantity for synthetic-alpha/ });
    const second = screen.getByRole('textbox', { name: /Chosen quantity for synthetic-beta/ });
    fireEvent.change(first, { target: { value: '2.5' } });
    fireEvent.change(second, { target: { value: '0' } });
    const rationale = screen.getByRole('textbox', { name: 'Why should this position change be made?' });
    await userEvent.setup().clear(rationale);
    await userEvent.setup().type(rationale, 'Reduce gross exposure.');
    await userEvent.setup().click(screen.getByRole('button', { name: 'Save draft' }));
    expect(api.saveDraft).toHaveBeenCalledWith(props.bookId, expect.objectContaining({
      rationale: 'Reduce gross exposure.',
      selection_rows: expect.arrayContaining([
        { key: fixtures.draft_saved.selection_rows[0].key, quantity_exact: '2.5' },
        { key: fixtures.draft_saved.selection_rows[1].key, quantity_exact: '0' },
      ]),
    }));
    expect(await screen.findByText(/Draft revision 2/)).toBeTruthy();
    expect(api.createPreview).not.toHaveBeenCalled();
  });

  it('requires explicit known-breach confirmation and never calls report success for pending override', async () => {
    api.createPreview.mockResolvedValue(breach());
    api.confirmPreview.mockResolvedValue(decodeQtDecision(structuredClone(fixtures.confirm_pending)));
    const onPublished = vi.fn();
    render(<QtProposalWorkspace {...props} onPublished={onPublished} />);
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Confirm and request two approvals' }));
    expect(await screen.findByText('Waiting for two approvals')).toBeTruthy();
    expect(api.confirmPreview).toHaveBeenCalledWith(breach().preview_id, expect.objectContaining({
      action: 'confirm_selected_book', acknowledge_warnings: true,
    }));
    expect(onPublished).not.toHaveBeenCalled();
    expect(screen.queryByText('Report ready')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Send email' })).toBeNull();
  });

  it('reports publication once only after a processed eligible decision from status refresh', async () => {
    api.createPreview.mockResolvedValue(clean()); api.confirmPreview.mockResolvedValue(pending());
    api.getDecision.mockResolvedValue(processed());
    const onPublished = vi.fn();
    render(<QtProposalWorkspace {...props} onPublished={onPublished} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm these quantities' }));
    expect(onPublished).not.toHaveBeenCalled();
    await user.click(await screen.findByRole('button', { name: 'Refresh decision status' }));
    expect(await screen.findByText('Report ready')).toBeTruthy();
    expect(onPublished).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: 'Refresh decision status' }));
    expect(onPublished).toHaveBeenCalledTimes(1);
  });

  it('keeps processed but report-blocked status distinct and cannot publish', async () => {
    api.createPreview.mockResolvedValue(clean()); api.confirmPreview.mockResolvedValue(pending());
    const blocked = structuredClone(fixtures.decision_processed) as unknown as Record<string, any>;
    blocked.report_ready = false; blocked.report_blocked_reasons = ['row_mapping_ambiguous'];
    blocked.receipt.report_eligibility = { status: 'unavailable', reason_codes: ['row_mapping_ambiguous'], row_manifest_digest: null };
    api.getDecision.mockResolvedValue(decodeQtDecision(blocked));
    const onPublished = vi.fn();
    render(<QtProposalWorkspace {...props} onPublished={onPublished} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm these quantities' }));
    await user.click(await screen.findByRole('button', { name: 'Refresh decision status' }));
    expect(await screen.findByText(/Report projection unavailable/)).toBeTruthy();
    expect(onPublished).not.toHaveBeenCalled();
  });

  it('does not publish a processed decision rejected by preview digest provenance', async () => {
    api.createPreview.mockResolvedValue(clean()); api.confirmPreview.mockResolvedValue(pending());
    api.getDecision.mockResolvedValue({ ...processed(), selected_book_digest: 'f'.repeat(64) });
    const onPublished = vi.fn();
    render(<QtProposalWorkspace {...props} onPublished={onPublished} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm these quantities' }));
    await user.click(await screen.findByRole('button', { name: 'Refresh decision status' }));
    expect(onPublished).not.toHaveBeenCalled();
    expect(screen.queryByText('Report ready')).toBeNull();
  });

  it('can edit after an unavailable preview, then requires a fresh save and evaluation', async () => {
    const unavailable = clean(); unavailable.availability = 'unavailable';
    unavailable.confirmable = false; unavailable.unavailable_reasons = ['risk_evidence_unavailable'];
    api.createPreview.mockResolvedValue(unavailable);
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    expect(await screen.findByText(/Unavailable: risk_evidence_unavailable/)).toBeTruthy();
    fireEvent.change(screen.getByRole('textbox', { name: /Chosen quantity for synthetic-alpha/ }),
      { target: { value: '2.5' } });
    expect((screen.getByRole('textbox', { name: /Chosen quantity for synthetic-alpha/ }) as HTMLInputElement).value).toBe('2.5');
    expect(screen.getByRole('button', { name: 'Save draft' })).toHaveProperty('disabled', false);
    expect(screen.queryByRole('button', { name: 'Confirm these quantities' })).toBeNull();
    expect(screen.queryByText(/Unavailable: risk_evidence_unavailable/)).toBeNull();
  });

  it('keeps unavailable capability quantities read-only', async () => {
    const blocked = proposal(); blocked.capability.available = false;
    blocked.workflow_state = 'workflow_unavailable'; blocked.action_grants.can_save_draft = false;
    api.getProposal.mockResolvedValue(blocked);
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    const input = await screen.findByRole('textbox', { name: /Chosen quantity for synthetic-alpha/ });
    expect(input).toHaveProperty('disabled', true);
    expect(screen.getByRole('button', { name: 'Save draft' })).toHaveProperty('disabled', true);
  });

  it('resolves a definite stale confirmation so a refreshed preview can be confirmed', async () => {
    const nextPreview = clean(); nextPreview.preview_id = '30000000-0000-4000-8000-000000000099';
    api.createPreview.mockResolvedValueOnce(clean()).mockResolvedValueOnce(nextPreview);
    api.confirmPreview.mockRejectedValueOnce(new QtApiError(409, 'preview_stale')).mockResolvedValueOnce({
      ...pending(), preview_id: nextPreview.preview_id,
    });
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm these quantities' }));
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('preview_stale'));
    expect(QtRecovery.loadConfirmation(sessionStorage, props.actorId, props.bookId)).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Refresh QT source' }));
    await user.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm these quantities' }));
    expect(api.confirmPreview).toHaveBeenCalledTimes(2);
    expect(api.confirmPreview.mock.calls[1][0]).toBe(nextPreview.preview_id);
  });

  it('keeps A-book pending recovery while B-book confirmation proceeds independently', async () => {
    QtRecovery.stageConfirmation(sessionStorage, { actor_id: props.actorId, book_id: props.bookId,
      preview_id: clean().preview_id, expected_digest: clean().payload_digest,
      idempotency_key: '22222222-2222-4222-8222-222222222222', acknowledge_warnings: false });
    const bookB = 'synthetic-book-B';
    const proposalB = proposal(); proposalB.book_id = bookB;
    proposalB.seed_rows.forEach(row => { row.key.portfolio_id = bookB; });
    const draftB = draft(); draftB.book_id = bookB;
    draftB.selection_rows.forEach(row => { row.key.portfolio_id = bookB; });
    const previewB = clean(); previewB.book_id = bookB;
    previewB.preview_id = '30000000-0000-4000-8000-000000000099';
    previewB.selection_rows.forEach(row => { row.key.portfolio_id = bookB; });
    api.getProposal.mockResolvedValue(proposalB); api.getDraft.mockResolvedValue(draftB);
    api.createPreview.mockResolvedValue(previewB);
    api.confirmPreview.mockResolvedValue({ ...pending(), book_id: bookB, preview_id: previewB.preview_id });
    render(<QtProposalWorkspace {...props} bookId={bookB} onPublished={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm these quantities' }));
    expect(api.confirmPreview).toHaveBeenCalledTimes(1);
    expect(QtRecovery.loadConfirmation(sessionStorage, props.actorId, props.bookId)?.preview_id).toBe(clean().preview_id);
    expect(QtRecovery.loadConfirmation(sessionStorage, props.actorId, bookB)?.preview_id).toBe(previewB.preview_id);
  });

  it('locks quantities and retains the warning while confirmation outcome is uncertain', async () => {
    api.createPreview.mockResolvedValue(clean());
    api.confirmPreview.mockRejectedValue(new QtMutationUncertainError());
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm these quantities' }));
    const input = screen.getByRole('textbox', { name: /Chosen quantity for synthetic-alpha/ }) as HTMLInputElement;
    expect(input).toHaveProperty('disabled', true);
    fireEvent.change(input, { target: { value: '2.5' } });
    expect(input.value).toBe('5');
    expect(screen.getByRole('alert').textContent).toMatch(/outcome is uncertain/);
    expect(screen.getByRole('button', { name: 'Recover confirmation' })).toHaveProperty('disabled', false);
    expect(screen.queryByRole('button', { name: 'Acknowledge resolved confirmation' })).toBeNull();
    expect(QtRecovery.loadConfirmation(sessionStorage, props.actorId, props.bookId)?.preview_id).toBe(clean().preview_id);
  });

  it('retains a potentially committed confirmation after a consumed-preview conflict', async () => {
    api.createPreview.mockResolvedValue(clean());
    api.confirmPreview.mockRejectedValue(new QtApiError(409, 'preview_consumed'));
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm these quantities' }));
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('preview_consumed'));
    expect(QtRecovery.loadConfirmation(sessionStorage, props.actorId, props.bookId)?.preview_id).toBe(clean().preview_id);
    expect(screen.getByRole('button', { name: 'Recover confirmation' })).toHaveProperty('disabled', false);
    expect(api.confirmPreview).toHaveBeenCalledTimes(1);
  });

  it('clears only an acknowledged processed decision before starting another proposal in the same book', async () => {
    api.createPreview.mockResolvedValue(clean()); api.confirmPreview.mockResolvedValue(processed());
    const onPublished = vi.fn();
    render(<QtProposalWorkspace {...props} onPublished={onPublished} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm these quantities' }));
    expect(await screen.findByText('Report ready')).toBeTruthy();
    expect(QtRecovery.loadConfirmation(sessionStorage, props.actorId, props.bookId)).not.toBeNull();
    await user.click(screen.getByRole('button', { name: 'Acknowledge resolved confirmation' }));
    expect(QtRecovery.loadConfirmation(sessionStorage, props.actorId, props.bookId)).toBeNull();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save draft' })).toHaveProperty('disabled', false));
    expect(screen.getByRole('textbox', { name: /Chosen quantity for synthetic-alpha/ })).toHaveProperty('disabled', false);
    expect(api.confirmPreview).toHaveBeenCalledTimes(1);
    expect(onPublished).toHaveBeenCalledTimes(1);
  });

  it('does not post on mount with a recovery record; an explicit action replays its original key', async () => {
    QtRecovery.stageConfirmation(sessionStorage, { actor_id: '101', book_id: props.bookId,
      preview_id: clean().preview_id, expected_digest: clean().payload_digest,
      idempotency_key: '22222222-2222-4222-8222-222222222222', acknowledge_warnings: false });
    api.confirmPreview.mockResolvedValue(pending());
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await screen.findByRole('button', { name: 'Recover confirmation' });
    expect(api.confirmPreview).not.toHaveBeenCalled();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Recover confirmation' }));
    expect(api.confirmPreview).toHaveBeenCalledWith(clean().preview_id, expect.objectContaining({
      idempotency_key: '22222222-2222-4222-8222-222222222222', acknowledge_warnings: false,
    }));
  });

  it('does not publish a recovered decision when its source day cannot be verified', async () => {
    QtRecovery.stageConfirmation(sessionStorage, { actor_id: '101', book_id: props.bookId,
      preview_id: clean().preview_id, expected_digest: clean().payload_digest,
      idempotency_key: '22222222-2222-4222-8222-222222222222', acknowledge_warnings: false });
    api.confirmPreview.mockResolvedValue(processed());
    const onPublished = vi.fn();
    render(<QtProposalWorkspace {...props} onPublished={onPublished} />);
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Recover confirmation' }));
    expect(await screen.findByRole('heading', { name: /Recovered decision/ })).toBeTruthy();
    expect(screen.queryByText('Report ready')).toBeNull();
    expect(onPublished).not.toHaveBeenCalled();
  });

  it('shows one server-recorded approver while retaining pending status', async () => {
    const eligibleProposal = proposal(); eligibleProposal.action_grants.can_approve = true;
    api.getProposal.mockResolvedValue(eligibleProposal);
    const eligible = decodeQtDecision({ ...structuredClone(fixtures.confirm_pending), can_approve: true });
    const one = decodeQtDecision({ ...structuredClone(fixtures.confirm_pending), approvals: [{
      person_id: 'eric_shwartz', display_label: 'Eric Shwartz', user_id: '202', approved_at: '2026-09-25T16:00:00Z',
    }], approvals_count: 1, can_approve: false });
    api.createPreview.mockResolvedValue(breach()); api.confirmPreview.mockResolvedValue(eligible);
    api.approveOverride.mockResolvedValue(one);
    const onPublished = vi.fn();
    render(<QtProposalWorkspace {...props} onPublished={onPublished} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm and request two approvals' }));
    await user.click(await screen.findByRole('button', { name: 'Approve override' }));
    expect(await screen.findByText(/1 of 2 approvals recorded by the server/)).toBeTruthy();
    expect(screen.getByText(/Eric Shwartz approved/)).toBeTruthy();
    expect(screen.getByText('Waiting for two approvals')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Approve override' })).toBeNull();
    expect(api.approveOverride).toHaveBeenCalledTimes(1);
    expect(onPublished).not.toHaveBeenCalled();
  });

  it('clears a server-acknowledged approval recovery slot while the decision stays pending', async () => {
    const eligibleProposal = proposal(); eligibleProposal.action_grants.can_approve = true;
    api.getProposal.mockResolvedValue(eligibleProposal);
    const eligible = decodeQtDecision({ ...structuredClone(fixtures.confirm_pending), can_approve: true });
    const recorded = decodeQtDecision({ ...structuredClone(fixtures.confirm_pending), approvals: [{
      person_id: 'eric_shwartz', display_label: 'Eric Shwartz', user_id: props.actorId,
      approved_at: '2026-09-25T16:00:00Z',
    }], approvals_count: 1, can_approve: false });
    api.createPreview.mockResolvedValue(breach()); api.confirmPreview.mockResolvedValue(eligible);
    api.approveOverride.mockResolvedValue(recorded);
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm and request two approvals' }));
    await user.click(await screen.findByRole('button', { name: 'Approve override' }));
    expect(await screen.findByText(/1 of 2 approvals recorded by the server/)).toBeTruthy();
    expect(QtRecovery.loadApproval(sessionStorage, props.actorId, props.bookId)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Retry approval' })).toBeNull();
    expect(screen.getByText('Waiting for two approvals')).toBeTruthy();
  });

  it('removes the previous actor’s browser recovery on an authenticated actor switch', async () => {
    QtRecovery.stageConfirmation(sessionStorage, { actor_id: props.actorId, book_id: props.bookId,
      preview_id: clean().preview_id, expected_digest: clean().payload_digest,
      idempotency_key: '22222222-2222-4222-8222-222222222222', acknowledge_warnings: false });
    const view = render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await screen.findByRole('button', { name: 'Recover confirmation' });
    view.rerender(<QtProposalWorkspace {...props} actorId="202" onPublished={vi.fn()} />);
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Recover confirmation' })).toBeNull());
    expect(QtRecovery.loadConfirmation(sessionStorage, props.actorId, props.bookId)).toBeNull();
    expect(api.confirmPreview).not.toHaveBeenCalled();
  });

  it('keeps B recovery when A approval settles after the actor switch', async () => {
    const eligibleProposal = proposal(); eligibleProposal.action_grants.can_approve = true;
    api.getProposal.mockResolvedValue(eligibleProposal); api.createPreview.mockResolvedValue(breach());
    api.confirmPreview.mockResolvedValue(decodeQtDecision({ ...fixtures.confirm_pending, can_approve: true }));
    const waiting = deferred<ReturnType<typeof pending>>(); api.approveOverride.mockReturnValue(waiting.promise);
    const view = render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm and request two approvals' }));
    await user.click(await screen.findByRole('button', { name: 'Approve override' }));
    view.rerender(<QtProposalWorkspace {...props} actorId="202" onPublished={vi.fn()} />);
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Retry approval' })).toBeNull());
    const bIntent = { actor_id: '202', book_id: props.bookId, preview_id: clean().preview_id,
      expected_digest: clean().payload_digest, idempotency_key: '22222222-2222-4222-8222-222222222222', acknowledge_warnings: false };
    QtRecovery.stageConfirmation(sessionStorage, bIntent);
    const recordedA = decodeQtDecision({ ...fixtures.confirm_pending, approvals: [{ person_id: 'eric_shwartz',
      display_label: 'Eric Shwartz', user_id: props.actorId, approved_at: '2026-09-25T16:00:00Z' }], approvals_count: 1 });
    await act(async () => { waiting.resolve(recordedA); });
    expect(storedIntents().find(value => value.actor_id === '202')).toEqual(bIntent);
    expect(storedIntents().some(value => value.actor_id === props.actorId)).toBe(false);
    expect(api.approveOverride).toHaveBeenCalledTimes(1);
  });

  it('does not resurrect A recovery when its confirmation returns after B stages an intent', async () => {
    api.createPreview.mockResolvedValue(clean());
    const waiting = deferred<ReturnType<typeof pending>>(); api.confirmPreview.mockReturnValue(waiting.promise);
    const view = render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm these quantities' }));
    view.rerender(<QtProposalWorkspace {...props} actorId="202" onPublished={vi.fn()} />);
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Recover confirmation' })).toBeNull());
    const bIntent = { actor_id: '202', book_id: props.bookId, preview_id: clean().preview_id,
      expected_digest: clean().payload_digest, idempotency_key: '22222222-2222-4222-8222-222222222222', acknowledge_warnings: false };
    QtRecovery.stageConfirmation(sessionStorage, bIntent);
    await act(async () => { waiting.resolve(pending()); });
    expect(storedIntents().find(value => value.actor_id === '202')).toEqual(bIntent);
    expect(storedIntents().some(value => value.actor_id === props.actorId)).toBe(false);
    expect(api.confirmPreview).toHaveBeenCalledTimes(1);
  });

  it('preserves the original same-actor approval intent after its workspace unmounts', async () => {
    const eligibleProposal = proposal(); eligibleProposal.action_grants.can_approve = true;
    api.getProposal.mockResolvedValue(eligibleProposal); api.createPreview.mockResolvedValue(breach());
    api.confirmPreview.mockResolvedValue(decodeQtDecision({ ...fixtures.confirm_pending, can_approve: true }));
    const waiting = deferred<ReturnType<typeof pending>>(); api.approveOverride.mockReturnValue(waiting.promise);
    const view = render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm and request two approvals' }));
    await user.click(await screen.findByRole('button', { name: 'Approve override' }));
    const original = QtRecovery.loadApproval(sessionStorage, props.actorId, props.bookId);
    view.unmount();
    const other = { actor_id: props.actorId, book_id: 'other-book', preview_id: clean().preview_id,
      expected_digest: clean().payload_digest, idempotency_key: '22222222-2222-4222-8222-222222222222', acknowledge_warnings: false };
    QtRecovery.stageConfirmation(sessionStorage, other);
    const recorded = decodeQtDecision({ ...fixtures.confirm_pending, approvals: [{ person_id: 'eric_shwartz',
      display_label: 'Eric Shwartz', user_id: props.actorId, approved_at: '2026-09-25T16:00:00Z' }], approvals_count: 1 });
    await act(async () => { waiting.resolve(recorded); });
    expect(QtRecovery.loadApproval(sessionStorage, props.actorId, props.bookId)).toEqual(original);
    expect(QtRecovery.loadConfirmation(sessionStorage, props.actorId, 'other-book')).toEqual(other);
  });

  it('keeps quantities locked until the saved draft response arrives', async () => {
    const waiting = deferred<ReturnType<typeof draft>>(); api.getDraft.mockReturnValue(waiting.promise);
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    const input = await screen.findByRole('textbox', { name: /Chosen quantity for synthetic-alpha/ });
    expect(input).toHaveProperty('disabled', true);
    expect(screen.getByRole('button', { name: 'Save draft' })).toHaveProperty('disabled', true);
    waiting.resolve(draft());
    await waitFor(() => expect(input).toHaveProperty('disabled', false));
  });

  it('ignores an old preview after an edit and prevents a duplicate write click', async () => {
    const waiting = deferred<ReturnType<typeof clean>>(); api.createPreview.mockReturnValue(waiting.promise);
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    fireEvent.click(screen.getByRole('button', { name: 'Evaluate my selection' }));
    expect(api.createPreview).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByRole('textbox', { name: /Chosen quantity for synthetic-alpha/ }), { target: { value: '2.5' } });
    waiting.resolve(clean());
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Confirm these quantities' })).toBeNull());
  });

  it('ignores a preview response from a prior book after the selected context switches', async () => {
    const waiting = deferred<ReturnType<typeof clean>>(); api.createPreview.mockReturnValue(waiting.promise);
    const onPublished = vi.fn();
    const view = render(<QtProposalWorkspace {...props} onPublished={onPublished} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    view.rerender(<QtProposalWorkspace {...props} bookId="different-book" onPublished={onPublished} />);
    waiting.resolve(clean());
    await screen.findByText('QT proposal for different-book');
    expect(screen.queryByRole('button', { name: 'Confirm these quantities' })).toBeNull();
    expect(onPublished).not.toHaveBeenCalled();
  });

  it('stops mutation actions on server grant revocation', async () => {
    api.createPreview.mockRejectedValue(new QtApiError(403, 'authorization_changed'));
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Save draft' })).toHaveProperty('disabled', true);
  });
});

// The guide beside the quantity boxes is presentation only. These tests pin what it
// says in every state the workspace can be in, and that it follows the boxes: it must
// never advertise an edit the boxes themselves refuse. Overlaps deliberately little with
// QtProposalWorkspace.editGuide.test.tsx and qt-proposal/QtEditGuide.test.tsx.
describe('QT edit guide beside the quantity boxes', () => {
  const guide = () => screen.getByRole('region', { name: 'How QT position changes work' });
  const stepNow = () => within(guide()).queryAllByRole('listitem')
    .filter(item => item.getAttribute('aria-current') === 'step').map(item => item.textContent ?? '');
  const summary = () => within(guide()).getByRole('status').textContent;
  const boxes = () => within(screen.getByRole('table', { name: 'QT component quantities' })).getAllByRole('textbox') as HTMLInputElement[];
  const envelope = (decision: unknown, preview: unknown) => ({ schema_version: 'qt-workflow/v1', book_id: props.bookId,
    source_day: props.sourceDay, decision, preview });
  const lockedSentence = /A decision already exists for this source day/;
  const failedDecision = () => decodeQtDecision({ ...structuredClone(fixtures.decision_processed), report_ready: false,
    report_blocked_reasons: ['receipt_failed'], receipt: { status: 'failed', published_book_digest: null,
      report_eligibility: { status: 'unavailable', reason_codes: ['receipt_failed'], row_manifest_digest: null } } });
  const blockedDecision = () => decodeQtDecision({ ...structuredClone(fixtures.decision_processed), report_ready: false,
    report_blocked_reasons: ['row_manifest_missing'], receipt: { ...structuredClone(fixtures.decision_processed.receipt),
      report_eligibility: { status: 'unavailable', reason_codes: ['row_manifest_missing'], row_manifest_digest: null } } });

  it('starts at step 1 while the draft is still loading, with the boxes and buttons locked', async () => {
    const waiting = deferred<ReturnType<typeof draft>>(); api.getDraft.mockReturnValue(waiting.promise);
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await screen.findAllByRole('textbox');
    expect(stepNow()).toHaveLength(1); expect(stepNow()[0]).toContain('1. Change quantity');
    expect(boxes().every(box => box.disabled)).toBe(true);
    expect(screen.getByRole('button', { name: 'Save draft' })).toHaveProperty('disabled', true);
    waiting.resolve(draft());
    await waitFor(() => expect(stepNow()[0]).toContain('3. Evaluate'));
  });

  it('follows the reader while saving: saved draft 3, unsaved edit 2, saved again 3', async () => {
    const updated = structuredClone(fixtures.draft_saved);
    updated.draft_revision = 2; updated.draft_digest = 'd'.repeat(64);
    updated.selection_rows[0].quantity_exact = '2.5';
    api.saveDraft.mockResolvedValue(decodeQtDraft(updated));
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    const user = userEvent.setup();
    await screen.findAllByRole('textbox');
    expect(stepNow()[0]).toContain('3. Evaluate');
    fireEvent.change(boxes()[0], { target: { value: '2.5' } });
    expect(stepNow()[0]).toContain('2. Save draft');
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    await screen.findByText(/Draft revision 2/);
    expect(stepNow()[0]).toContain('3. Evaluate');
  });

  it('follows the reader through evaluation and confirmation: evaluated 4, confirmed 5', async () => {
    api.createPreview.mockResolvedValue(clean()); api.confirmPreview.mockResolvedValue(processed());
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await screen.findByRole('button', { name: 'Confirm these quantities' });
    expect(stepNow()[0]).toContain('4. Confirm');
    await user.click(screen.getByRole('button', { name: 'Confirm these quantities' }));
    await screen.findByText('Report ready');
    expect(stepNow()).toHaveLength(0);
    expect(within(guide()).getByText(lockedSentence)).toBeTruthy();
  });

  it('goes back to step 2 when a quantity is edited after the evaluation, dropping the stale preview', async () => {
    api.createPreview.mockResolvedValue(clean());
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await screen.findByRole('button', { name: 'Confirm these quantities' });
    expect(stepNow()[0]).toContain('4. Confirm');
    fireEvent.change(boxes()[0], { target: { value: '2.5' } });
    expect(stepNow()[0]).toContain('2. Save draft');
    expect(screen.queryByRole('button', { name: 'Confirm these quantities' })).toBeNull();
  });

  it('compares with MODEL by value, so a differently written equal quantity is not counted as a change', async () => {
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await screen.findAllByRole('textbox');
    expect(summary()).toBe('2 of 2 editable components differ from the MODEL recommendation.');
    fireEvent.change(boxes()[0], { target: { value: '4' } });
    expect(summary()).toBe('1 of 2 editable components differ from the MODEL recommendation.');
    fireEvent.change(boxes()[0], { target: { value: '5' } });
    fireEvent.change(boxes()[1], { target: { value: '2.0' } });
    expect(summary()).toBe('1 of 2 editable components differ from the MODEL recommendation.');
    fireEvent.change(boxes()[0], { target: { value: ' 4.00 ' } });
    expect(summary()).toBe('No quantity differs from the MODEL recommendation yet (2 editable components).');
  });

  it('counts a quantity that cannot be read yet as different rather than pretending it matches', async () => {
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await screen.findAllByRole('textbox');
    fireEvent.change(boxes()[0], { target: { value: '4' } });
    fireEvent.change(boxes()[1], { target: { value: 'abc' } });
    expect(summary()).toBe('1 of 2 editable components differ from the MODEL recommendation.');
  });

  it('says editing is unavailable, and offers no steps, when the workflow is not ready', async () => {
    const blocked = proposal(); blocked.capability.available = false;
    blocked.workflow_state = 'workflow_unavailable'; blocked.action_grants.can_save_draft = false;
    api.getProposal.mockResolvedValue(blocked);
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await screen.findAllByRole('textbox');
    expect(within(guide()).getByText('Editing is unavailable until the current source and your permissions are ready.')).toBeTruthy();
    expect(within(guide()).queryByRole('status')).toBeNull();
    expect(stepNow()).toHaveLength(0);
    expect(within(guide()).queryByText(/Change quantity/)).toBeNull();
    expect(boxes().every(box => box.disabled)).toBe(true);
    expect(within(guide()).queryByRole('button')).toBeNull();
  });

  it('does not advertise editing to a reader who may not save drafts, even when the source is ready', async () => {
    const readOnly = proposal(); readOnly.action_grants.can_save_draft = false; api.getProposal.mockResolvedValue(readOnly);
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await screen.findAllByRole('textbox');
    await waitFor(() => expect(within(guide()).getByText(/Editing is unavailable/)).toBeTruthy());
    expect(stepNow()).toHaveLength(0);
    expect(boxes().every(box => box.disabled)).toBe(true);
    expect(screen.getByRole('button', { name: 'Save draft' })).toHaveProperty('disabled', true);
    expect(screen.getByRole('button', { name: 'Evaluate my selection' })).toHaveProperty('disabled', true);
  });

  it('says editing is paused, not that steps remain, while a confirmation outcome is uncertain', async () => {
    api.createPreview.mockResolvedValue(clean());
    api.confirmPreview.mockRejectedValue(new QtMutationUncertainError());
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Evaluate my selection' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm these quantities' }));
    await screen.findByText(/outcome is uncertain/);
    expect(boxes().every(box => box.disabled)).toBe(true);
    expect(within(guide()).getByText(/Editing is paused right now/)).toBeTruthy();
    expect(stepNow()).toHaveLength(0);
  });

  describe('a decision the server already holds that is still in flight', () => {
    it('locks the boxes and the guide for a pending override, and keeps every write button closed', async () => {
      const scoped = proposal(); scoped.action_grants.can_approve = true; api.getProposal.mockResolvedValue(scoped);
      api.getBookDecision.mockResolvedValue(envelope(decodeQtDecision({ ...fixtures.confirm_pending, can_approve: true }), breach()));
      render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
      await screen.findByRole('region', { name: 'Immutable QT decision review' });
      await waitFor(() => expect(boxes().every(box => box.disabled)).toBe(true));
      expect(within(guide()).getByText(lockedSentence)).toBeTruthy();
      expect(within(guide()).getByText(/Its review and approvals are shown below/)).toBeTruthy();
      expect(stepNow()).toHaveLength(0);
      expect(within(guide()).queryByRole('button')).toBeNull();
      expect(screen.getByRole('button', { name: 'Save draft' })).toHaveProperty('disabled', true);
      expect(screen.getByRole('button', { name: 'Evaluate my selection' })).toHaveProperty('disabled', true);
      fireEvent.change(boxes()[0], { target: { value: '2.5' } });
      expect(boxes()[0].value).toBe('5');
    });

    it('locks the boxes and the guide for a confirmed decision whose receipt is still processing', async () => {
      api.getBookDecision.mockResolvedValue(envelope(decodeQtDecision(structuredClone(fixtures.decision_pending)), clean()));
      render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
      await screen.findByRole('region', { name: 'Immutable QT decision review' });
      await waitFor(() => expect(boxes().every(box => box.disabled)).toBe(true));
      expect(within(guide()).getByText(lockedSentence)).toBeTruthy();
      expect(stepNow()).toHaveLength(0);
      expect(screen.getByRole('button', { name: 'Save draft' })).toHaveProperty('disabled', true);
      expect(screen.getByRole('button', { name: 'Evaluate my selection' })).toHaveProperty('disabled', true);
    });

    it('locks a box the reader had already started editing when the decision turns up late, keeping what was typed', async () => {
      const discovery = deferred<any>(); api.getBookDecision.mockReturnValue(discovery.promise);
      render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
      await screen.findAllByRole('textbox');
      fireEvent.change(boxes()[0], { target: { value: '2.5' } });
      expect(stepNow()[0]).toContain('2. Save draft');
      await act(async () => discovery.resolve(envelope(decodeQtDecision(structuredClone(fixtures.confirm_pending)), breach())));
      await screen.findByRole('region', { name: 'Immutable QT decision review' });
      expect(boxes()[0]).toHaveProperty('disabled', true);
      expect(boxes()[0].value).toBe('2.5');
      expect(within(guide()).getByText(lockedSentence)).toBeTruthy();
    });
  });

  describe('a decision the server already holds that has finished', () => {
    it.each([
      ['processed', () => processed(), /A previous decision for this source day was processed\. Editing starts a new choice; the previous decision stays in the audit history below\./],
      ['processed but report-blocked', () => blockedDecision(), /A previous decision for this source day was processed\. Editing starts a new choice/],
      ['failed', () => failedDecision(), /A previous decision for this source day could not be processed\. Editing starts a new choice; the previous decision stays in the audit history below\./],
    ] as const)('leaves the boxes and the four steps open for a %s decision, and says editing starts a new choice', async (_name, make, sentence) => {
      api.getBookDecision.mockResolvedValue(envelope(make(), clean()));
      render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
      await screen.findByRole('region', { name: 'Immutable QT decision review' });
      expect(boxes().every(box => !box.disabled)).toBe(true);
      expect(within(guide()).queryByText(lockedSentence)).toBeNull();
      expect(stepNow()).toHaveLength(1);
      expect(within(guide()).getByText(sentence)).toBeTruthy();
      fireEvent.change(boxes()[0], { target: { value: '2.5' } });
      expect(boxes()[0].value).toBe('2.5');
      expect(stepNow()[0]).toContain('2. Save draft');
    });

    it('shows no such note, and keeps the four steps, when the server holds no decision', async () => {
      render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
      await screen.findAllByRole('textbox');
      await waitFor(() => expect(api.getBookDecision).toHaveBeenCalled());
      expect(boxes().every(box => !box.disabled)).toBe(true);
      expect(within(guide()).queryByText(lockedSentence)).toBeNull();
      expect(within(guide()).queryByText(/A previous decision/)).toBeNull();
      expect(stepNow()[0]).toContain('3. Evaluate');
    });

    it('leaves the boxes editable when the decision lookup itself failed, since the backend stays the authority', async () => {
      api.getBookDecision.mockRejectedValue(new Error('synthetic lookup failure'));
      render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
      await screen.findByText(/Decision review unavailable/);
      expect(boxes().every(box => !box.disabled)).toBe(true);
      expect(within(guide()).queryByText(lockedSentence)).toBeNull();
    });
  });

  describe('accessibility', () => {
    it('is a labelled region with an ordered four-step list, exactly one step current, and a polite status', async () => {
      render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
      await screen.findAllByRole('textbox');
      const list = within(guide()).getAllByRole('list')[0];
      expect(list.tagName).toBe('OL');
      expect(within(list).getAllByRole('listitem')).toHaveLength(4);
      expect(within(list).getAllByRole('listitem').filter(item => item.hasAttribute('aria-current'))).toHaveLength(1);
      expect(within(guide()).getByRole('status').getAttribute('aria-live')).toBe('polite');
    });

    it('announces only its own summary: the guide holds a single live region', async () => {
      render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
      await screen.findAllByRole('textbox');
      expect(guide().querySelectorAll('[aria-live], [role="status"], [role="alert"]')).toHaveLength(1);
    });

    it('is reachable by id and can hold focus, for the Edit positions button to fall back on', async () => {
      render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
      await screen.findAllByRole('textbox');
      const section = document.getElementById('qt-proposal-workspace')!;
      expect(section).toBe(screen.getByRole('region', { name: 'QT proposal workspace' }));
      expect(section.getAttribute('tabindex')).toBe('-1');
      section.focus();
      expect(document.activeElement).toBe(section);
    });
  });
});
