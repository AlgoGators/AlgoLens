// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';

import fixtures from '../../../../contracts/qt-workflow-v1.json';
import { verifySessionRequest } from '../api/authApi';
import { PortfolioApiService } from '../api/portfolioApi';
import { QtPreviewApi } from '../api/qtPreviewApi';

const unavailableBackend = () => vi.spyOn(globalThis, 'fetch').mockResolvedValue(
  new Response(JSON.stringify({ error: 'backend unavailable in visual demo' }), {
    status: 503,
    headers: { 'Content-Type': 'application/json' },
  }),
);

describe('local position-edit visual demo', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.history.replaceState({}, '', '/');
  });

  it('restores an internal demo reviewer when the local demo is explicitly selected', async () => {
    window.history.replaceState({}, '', '/?demo=position-edit');
    unavailableBackend();

    const session = await verifySessionRequest();

    expect(session).toEqual({
      status: 200,
      user: {
        id: 'demo-qt-reviewer',
        email: 'demo.reviewer@localhost',
        first_name: 'Demo',
        last_name: 'Reviewer',
        role: 'admin',
      },
    });
  });

  it('loads a populated demo portfolio without a database', async () => {
    window.history.replaceState({}, '', '/?demo=position-edit');
    unavailableBackend();

    const portfolio = await PortfolioApiService.getPortfolioData();

    expect(portfolio.strategies).toHaveLength(1);
    expect(portfolio.strategies[0]).toMatchObject({
      id: 'component-1',
      name: 'Synthetic Alpha',
      portfolio_id: 'synthetic-book-A',
      positionStream: 'qt',
      positionsEditable: true,
      dataAvailable: true,
    });
    expect(portfolio.strategies[0].positions).toHaveLength(1);
    expect(portfolio.strategies[0].historicalData.length).toBeGreaterThan(10);
  });

  it('loads the saved rationale and evaluated risk evidence for the edit window', async () => {
    window.history.replaceState({}, '', '/?demo=position-edit');
    unavailableBackend();

    const proposal = await QtPreviewApi.getProposal('synthetic-book-A');
    const draft = await QtPreviewApi.getDraft('synthetic-book-A');
    const decision = await QtPreviewApi.getBookDecision('synthetic-book-A', '2026-09-25');
    const preview = await QtPreviewApi.createPreview({
      book_id: 'synthetic-book-A',
      draft_id: fixtures.draft_saved.draft_id,
      draft_revision: fixtures.draft_saved.draft_revision,
      draft_digest: fixtures.draft_saved.draft_digest,
      expected_source_digest: fixtures.draft_saved.source_digest,
      expected_provenance_digest: fixtures.draft_saved.provenance_digest,
      idempotency_key: '60000000-0000-4000-8000-000000000001',
    });

    expect(proposal.capability).toEqual({ required: true, available: true, version: 1 });
    expect(draft.rationale).toBe('Reduce concentration before the event window.');
    expect(decision).toMatchObject({ decision: null, preview: null });
    expect(preview.evaluation.selected_risk).toMatchObject({
      status: 'evaluated',
      passed: true,
      metrics: [expect.objectContaining({
        code: 'synthetic_exposure_ratio',
        value_diagnostic: '0.12345678901234566',
        unit: 'ratio',
      })],
    });
  });
});
