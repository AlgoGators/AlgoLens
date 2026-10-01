// @vitest-environment jsdom

import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import fixtures from '../../../contracts/qt-workflow-v1.json';
import { decodeQtDraft, decodeQtProposal } from '../domain/portfolio/qtPreview';
import { QtRecovery } from '../infrastructure/api/qtRecovery';
import { QtProposalWorkspace } from './QtProposalWorkspace';

const api = vi.hoisted(() => ({
  getProposal: vi.fn(), getDraft: vi.fn(), saveDraft: vi.fn(), createPreview: vi.fn(),
  confirmPreview: vi.fn(), approveOverride: vi.fn(), getDecision: vi.fn(), getBookDecision: vi.fn(),
}));

vi.mock('../infrastructure/api/qtPreviewApi', async importOriginal => ({
  ...await importOriginal<typeof import('../infrastructure/api/qtPreviewApi')>(),
  QtPreviewApi: api,
}));

const props = {
  actorId: '101',
  actorLabel: 'Demo Reviewer (demo.reviewer@localhost)',
  bookId: 'synthetic-book-A',
  sourceDay: '2026-09-25',
};

beforeEach(() => {
  vi.resetAllMocks();
  sessionStorage.clear();
  QtRecovery.activateActor(sessionStorage, props.actorId);
  api.getProposal.mockResolvedValue(decodeQtProposal(structuredClone(fixtures.proposal_ready)));
  api.getDraft.mockResolvedValue(decodeQtDraft(structuredClone(fixtures.draft_saved)));
  api.getBookDecision.mockResolvedValue({
    schema_version: 'qt-workflow/v1', book_id: props.bookId, source_day: props.sourceDay,
    decision: null, preview: null,
  });
});

afterEach(() => { sessionStorage.clear(); });

describe('compact QT position editor layout', () => {
  it('organizes the request and quantities without the instructional checklist', async () => {
    render(<QtProposalWorkspace {...props} embedded onPublished={vi.fn()} />);

    const details = await screen.findByRole('region', { name: 'Position change request' });
    const quantities = screen.getByRole('region', { name: 'Position quantities' });

    expect(screen.queryByRole('region', { name: 'How QT position changes work' })).toBeNull();
    expect(screen.queryByText('Changing positions')).toBeNull();
    expect(screen.getByRole('heading', { name: 'Change details' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Position quantities' })).toBeTruthy();
    expect(details.textContent).toContain('Demo Reviewer (demo.reviewer@localhost)');
    expect(details.textContent).toContain('2 of 2 editable positions differ from MODEL.');
    expect(quantities.contains(screen.getByRole('table', { name: 'QT component quantities' }))).toBe(true);
    expect(details.compareDocumentPosition(quantities) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
