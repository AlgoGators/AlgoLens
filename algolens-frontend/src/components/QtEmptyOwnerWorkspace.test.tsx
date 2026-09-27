// @vitest-environment jsdom
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import fixtures from '../../../contracts/qt-workflow-v1.json';
import { decodeQtDraft, decodeQtProposal } from '../domain/portfolio/qtPreview';
import { QtProposalWorkspace } from './QtProposalWorkspace';

const api = vi.hoisted(() => ({ getProposal: vi.fn(), getDraft: vi.fn(), saveDraft: vi.fn(),
  createPreview: vi.fn(), confirmPreview: vi.fn(), approveOverride: vi.fn(), getDecision: vi.fn(), getBookDecision: vi.fn() }));
vi.mock('../infrastructure/api/qtPreviewApi', async importOriginal => ({
  ...await importOriginal<typeof import('../infrastructure/api/qtPreviewApi')>(), QtPreviewApi: api,
}));
const marker = () => ({ schema_version: 'qt-empty-owner-choice/v2',
  model_publication_id: fixtures.proposal_ready.seed_publication_id,
  owner_document_digest: 'a'.repeat(64), configured_owner_names: ['EQUITY_MEAN_REVERSION'] });
const proposal = () => ({ ...structuredClone(fixtures.proposal_ready), schema_version: 'qt-workflow/v2',
  seed_rows: [], saved_qt_rows: [], empty_owner: marker() });
const saved = () => ({ ...structuredClone(fixtures.draft_saved), schema_version: 'qt-workflow/v2',
  selection_rows: [], empty_owner: marker() });
const absent = () => ({ ...saved(), state: 'absent', draft_id: null, draft_revision: 0, draft_digest: null });
const props = { actorId: '101', bookId: fixtures.proposal_ready.book_id, sourceDay: fixtures.proposal_ready.source_day };

beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear();
  api.getProposal.mockResolvedValue(decodeQtProposal(proposal()));
  api.getDraft.mockResolvedValue(decodeQtDraft(absent()));
  api.getBookDecision.mockResolvedValue({ schema_version: 'qt-workflow/v1', book_id: props.bookId,
    source_day: props.sourceDay, decision: null, preview: null });
});

describe('verified empty QT selection', () => {
  it('starts a new draft only after explicitly saving a verified processed predecessor', async () => {
    const previous = { ...saved(), state: 'consumed', successor: {
      decision_id: '10000000-0000-4000-8000-000000000001',
      attempt_id: '20000000-0000-4000-8000-000000000001',
      preview_id: '30000000-0000-4000-8000-000000000001', publication_digest: 'c'.repeat(64),
    } };
    const next = { ...saved(), draft_id: '40000000-0000-4000-8000-000000000001',
      draft_revision: previous.draft_revision + 1, draft_digest: 'd'.repeat(64) };
    api.getDraft.mockResolvedValue(decodeQtDraft(previous));
    api.saveDraft.mockResolvedValue(decodeQtDraft(next));
    api.createPreview.mockRejectedValue(new Error('synthetic evaluation unavailable'));
    const onPublished = vi.fn();
    render(<QtProposalWorkspace {...props} onPublished={onPublished} />);
    await screen.findByText('Draft revision 1 (consumed)');
    expect(screen.getByRole('region', { name: 'Verified empty selection' }).textContent).toContain('Save to start a new choice');
    expect(api.saveDraft).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Evaluate my selection' }).hasAttribute('disabled')).toBe(true);
    await userEvent.setup().click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(api.saveDraft).toHaveBeenCalledTimes(1));
    expect(api.saveDraft.mock.calls[0][1]).toMatchObject({ expected_draft_revision: previous.draft_revision,
      expected_source_digest: proposal().source_digest, expected_provenance_digest: proposal().provenance_digest,
      selection_rows: [] });
    const evaluate = screen.getByRole('button', { name: 'Evaluate my selection' });
    await waitFor(() => expect(evaluate.hasAttribute('disabled')).toBe(false));
    await userEvent.setup().click(evaluate);
    await waitFor(() => expect(api.createPreview).toHaveBeenCalledTimes(1));
    expect(api.createPreview.mock.calls[0][0]).toMatchObject({ draft_id: next.draft_id,
      draft_revision: next.draft_revision, draft_digest: next.draft_digest });
    expect(api.confirmPreview).not.toHaveBeenCalled();
    expect(onPublished).not.toHaveBeenCalled();
  });

  it('explicitly saves exact empty rows and evaluates that saved draft without implying publication', async () => {
    api.saveDraft.mockResolvedValue(decodeQtDraft(saved()));
    api.createPreview.mockRejectedValue(new Error('synthetic evaluation unavailable'));
    const onPublished = vi.fn();
    render(<QtProposalWorkspace {...props} onPublished={onPublished} />);
    const save = await screen.findByRole('button', { name: 'Save draft' });
    await waitFor(() => expect(save.hasAttribute('disabled')).toBe(false));
    expect(screen.getByRole('region', { name: 'Verified empty selection' }).textContent).toContain('EQUITY_MEAN_REVERSION');
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.getByRole('button', { name: 'Evaluate my selection' }).hasAttribute('disabled')).toBe(true);
    await userEvent.setup().click(save);
    await waitFor(() => expect(api.saveDraft).toHaveBeenCalledTimes(1));
    expect(api.saveDraft.mock.calls[0][1]).toMatchObject({ selection_rows: [], expected_draft_revision: 0,
      expected_source_digest: proposal().source_digest, expected_provenance_digest: proposal().provenance_digest });
    const evaluate = screen.getByRole('button', { name: 'Evaluate my selection' });
    await waitFor(() => expect(evaluate.hasAttribute('disabled')).toBe(false));
    await userEvent.setup().click(evaluate);
    await waitFor(() => expect(api.createPreview).toHaveBeenCalledTimes(1));
    expect(api.createPreview.mock.calls[0][0]).toMatchObject({ draft_id: saved().draft_id,
      draft_revision: saved().draft_revision, draft_digest: saved().draft_digest });
    expect(api.confirmPreview).not.toHaveBeenCalled();
    expect(onPublished).not.toHaveBeenCalled();
  });

  it('does not infer permission from an unmarked empty legacy proposal and saved draft', async () => {
    const p = proposal(); p.schema_version = 'qt-workflow/v1'; Reflect.deleteProperty(p, 'empty_owner');
    const d = saved(); d.schema_version = 'qt-workflow/v1'; Reflect.deleteProperty(d, 'empty_owner');
    api.getProposal.mockResolvedValue(decodeQtProposal(p)); api.getDraft.mockResolvedValue(decodeQtDraft(d));
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await screen.findByText('Draft revision 1 (saved)');
    expect(screen.getByRole('button', { name: 'Save draft' }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByRole('button', { name: 'Evaluate my selection' }).hasAttribute('disabled')).toBe(true);
    expect(screen.queryByRole('region', { name: 'Verified empty selection' })).toBeNull();
  });

  it('blocks both actions when independently valid proposal and draft owner evidence differ', async () => {
    const d = saved(); d.empty_owner.owner_document_digest = 'f'.repeat(64);
    api.getDraft.mockResolvedValue(decodeQtDraft(d));
    render(<QtProposalWorkspace {...props} onPublished={vi.fn()} />);
    await screen.findByRole('button', { name: 'Save draft' });
    expect(screen.getByRole('button', { name: 'Save draft' }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByRole('button', { name: 'Evaluate my selection' }).hasAttribute('disabled')).toBe(true);
    expect(api.saveDraft).not.toHaveBeenCalled();
  });
});
