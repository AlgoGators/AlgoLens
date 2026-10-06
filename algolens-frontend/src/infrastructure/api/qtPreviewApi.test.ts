// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import fixtures from '../../../../contracts/qt-workflow-v1.json';
import { SessionExpiredError } from './httpClient';
import { QtPreviewApi, QtMutationUncertainError, QtApiError, QtReadError } from './qtPreviewApi';

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { 'Content-Type': 'application/json' },
});
const key = '22222222-2222-4222-8222-222222222222';
const confirm = { action: 'confirm_selected_book' as const,
  expected_digest: fixtures.preview_clean.payload_digest, idempotency_key: key, acknowledge_warnings: false };

afterEach(() => { vi.unstubAllGlobals(); document.cookie = 'csrf_access_token=; Max-Age=0'; });

describe('QT authenticated protocol', () => {
  it('discovers immutable decision evidence with one scoped credentialed GET and no mutation', async () => {
    const envelope = { schema_version: 'qt-workflow/v1', book_id: 'synthetic-book-A', source_day: '2026-09-25',
      decision: fixtures.confirm_pending, preview: fixtures.preview_breach };
    const fetch = vi.fn().mockResolvedValue(json(envelope)); vi.stubGlobal('fetch', fetch);
    const signal = new AbortController().signal;
    expect((await QtPreviewApi.getBookDecision('synthetic-book-A', '2026-09-25', signal)).preview?.selection_rows
      .map(row => row.quantity_exact)).toEqual(['5', '1']);
    expect(fetch).toHaveBeenCalledExactlyOnceWith(expect.stringMatching(/\/qt-books\/synthetic-book-A\/decision\?source_day=2026-09-25$/),
      { method: 'GET', credentials: 'include', cache: 'no-store',
        headers: { Accept: 'application/json', 'Cache-Control': 'no-store' }, signal });
    fetch.mockResolvedValue(json({ ...envelope, decision: null, preview: null, book_id: 'book /?' }));
    await QtPreviewApi.getBookDecision('book /?', '2026-09-25');
    expect(String(fetch.mock.calls[1][0])).toMatch(/\/qt-books\/book%20%2F%3F\/decision\?source_day=2026-09-25$/);
    for (const changed of [{ ...envelope, source_day: '2026-09-26' }, { ...envelope, book_id: 'other-book' },
      { ...envelope, preview: null }]) {
      fetch.mockResolvedValue(json(changed));
      await expect(QtPreviewApi.getBookDecision('synthetic-book-A', '2026-09-25')).rejects.toBeInstanceOf(QtReadError);
    }
    expect(fetch.mock.calls.every(call => call[1].method === 'GET')).toBe(true);
  });
  it('uses one credentialed read, encodes opaque book IDs and forwards abort', async () => {
    const fetch = vi.fn().mockResolvedValue(json(fixtures.proposal_ready));
    vi.stubGlobal('fetch', fetch);
    const signal = new AbortController().signal;
    await QtPreviewApi.getProposal('synthetic-book-A', signal);
    expect(fetch).toHaveBeenCalledExactlyOnceWith(
      expect.stringMatching(/\/portfolio\/qt-books\/synthetic-book-A\/proposal$/),
      { method: 'GET', credentials: 'include', cache: 'no-store',
        headers: { Accept: 'application/json', 'Cache-Control': 'no-store' }, signal },
    );
    fetch.mockResolvedValue(json(fixtures.stale_error, 404));
    await expect(QtPreviewApi.getProposal('book /?')).rejects.toThrow();
    expect(String(fetch.mock.calls[1][0])).toMatch(/\/qt-books\/book%20%2F%3F\/proposal$/);
  });

  it('sends exact draft and preview request bytes through credentialed CSRF helpers', async () => {
    document.cookie = 'csrf_access_token=synthetic-csrf';
    const fetch = vi.fn().mockResolvedValueOnce(json(fixtures.draft_saved)).mockResolvedValueOnce(json(fixtures.preview_clean));
    vi.stubGlobal('fetch', fetch);
    const row = fixtures.draft_saved.selection_rows[0];
    const save = { expected_source_digest: fixtures.draft_saved.source_digest,
      expected_provenance_digest: fixtures.draft_saved.provenance_digest, expected_draft_revision: 0,
      idempotency_key: key, rationale: 'Reduce concentration.',
      selection_rows: [{ key: { ...row.key, browser_only: 'discard' }, quantity_exact: '5' }] };
    await QtPreviewApi.saveDraft('synthetic-book-A', save);
    const create = { book_id: 'synthetic-book-A', draft_id: fixtures.draft_saved.draft_id!, draft_revision: 1,
      draft_digest: fixtures.draft_saved.draft_digest!, expected_source_digest: fixtures.draft_saved.source_digest!,
      expected_provenance_digest: fixtures.draft_saved.provenance_digest!, idempotency_key: key };
    await QtPreviewApi.createPreview(create);
    expect(fetch.mock.calls[0][1]).toMatchObject({ method: 'PUT', credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-TOKEN': 'synthetic-csrf' } });
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ ...save,
      selection_rows: [{ key: row.key, quantity_exact: '5' }] });
    expect(fetch.mock.calls[1][1]).toMatchObject({ method: 'POST', credentials: 'include',
      headers: { 'X-CSRF-TOKEN': 'synthetic-csrf' }, body: JSON.stringify(create) });
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it.each([
    ['source', { source_digest: 'd'.repeat(64) }],
    ['provenance', { provenance_digest: 'd'.repeat(64) }],
  ])('treats a saved draft with wrong %s lineage as uncertain', async (_name, change) => {
    const fetch = vi.fn().mockResolvedValue(json({ ...fixtures.draft_saved, ...change }));
    vi.stubGlobal('fetch', fetch);
    const request = { expected_source_digest: fixtures.draft_saved.source_digest!,
      expected_provenance_digest: fixtures.draft_saved.provenance_digest!, expected_draft_revision: 0,
      idempotency_key: key, rationale: 'Reduce concentration.',
      selection_rows: [{ key: fixtures.draft_saved.selection_rows[0].key, quantity_exact: '5' }] };
    await expect(QtPreviewApi.saveDraft('synthetic-book-A', request)).rejects.toBeInstanceOf(QtMutationUncertainError);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('treats a saved draft whose revision did not advance as uncertain', async () => {
    const fetch = vi.fn().mockResolvedValue(json(fixtures.draft_saved));
    vi.stubGlobal('fetch', fetch);
    await expect(QtPreviewApi.saveDraft('synthetic-book-A', { expected_source_digest: fixtures.draft_saved.source_digest!,
      expected_provenance_digest: fixtures.draft_saved.provenance_digest!, expected_draft_revision: 1,
      idempotency_key: key, rationale: 'Reduce concentration.',
      selection_rows: [{ key: fixtures.draft_saved.selection_rows[0].key, quantity_exact: '5' }] }))
      .rejects.toBeInstanceOf(QtMutationUncertainError);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['source', { expected_source_digest: 'd'.repeat(64) }],
    ['provenance', { expected_provenance_digest: 'd'.repeat(64) }],
  ])('treats a preview for wrong requested %s lineage as uncertain', async (_name, change) => {
    const fetch = vi.fn().mockResolvedValue(json(fixtures.preview_clean));
    vi.stubGlobal('fetch', fetch);
    const request = { book_id: 'synthetic-book-A', draft_id: fixtures.draft_saved.draft_id!, draft_revision: 1,
      draft_digest: fixtures.draft_saved.draft_digest!, expected_source_digest: fixtures.draft_saved.source_digest!,
      expected_provenance_digest: fixtures.draft_saved.provenance_digest!, idempotency_key: key, ...change };
    await expect(QtPreviewApi.createPreview(request)).rejects.toBeInstanceOf(QtMutationUncertainError);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('confirms only digest/action/key/ack and approves without claimed person or role', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(json(fixtures.decision_pending)).mockResolvedValueOnce(json(fixtures.confirm_pending));
    vi.stubGlobal('fetch', fetch);
    await QtPreviewApi.confirmPreview(fixtures.preview_clean.preview_id, confirm);
    await QtPreviewApi.approveOverride(fixtures.confirm_pending.request_id!, { action: 'approve', idempotency_key: key });
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual(confirm);
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ action: 'approve', idempotency_key: key });
    expect(String(fetch.mock.calls[0][0])).toMatch(/\/qt-previews\/[^/]+\/confirm$/);
    expect(String(fetch.mock.calls[1][0])).toMatch(/\/qt-override-requests\/[^/]+\/approvals$/);
  });

  it('decodes draft, decision and preview reads through U1 and rejects wrong response identity', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(json(fixtures.draft_saved)).mockResolvedValueOnce(json(fixtures.decision_processed));
    vi.stubGlobal('fetch', fetch);
    expect((await QtPreviewApi.getDraft('synthetic-book-A')).draft_revision).toBe(1);
    expect((await QtPreviewApi.getDecision(fixtures.decision_processed.decision_id)).report_ready).toBe(true);
    fetch.mockResolvedValueOnce(json({ ...fixtures.decision_processed, decision_id: '40000000-0000-4000-8000-000000000099' }));
    await expect(QtPreviewApi.getDecision(fixtures.decision_processed.decision_id)).rejects.toThrow();
  });

  it('never retries an uncertain mutation, including transport loss, 503 and malformed success', async () => {
    const fetch = vi.fn().mockRejectedValueOnce(new TypeError('offline'))
      .mockResolvedValueOnce(json(fixtures.stale_error, 503))
      .mockResolvedValueOnce(new Response('{', { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetch);
    for (let attempt = 1; attempt <= 3; attempt++) {
      await expect(QtPreviewApi.confirmPreview(fixtures.preview_clean.preview_id, confirm))
        .rejects.toBeInstanceOf(QtMutationUncertainError);
      expect(fetch).toHaveBeenCalledTimes(attempt);
    }
  });

  it('preserves 401/422 session loss and reports trusted 403/409 without leaking body text', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    for (const status of [401, 422]) {
      fetch.mockResolvedValueOnce(new Response('private', { status }));
      await expect(QtPreviewApi.confirmPreview(fixtures.preview_clean.preview_id, confirm))
        .rejects.toBeInstanceOf(SessionExpiredError);
    }
    for (const [status, code] of [[403, 'authorization_changed'], [409, 'preview_stale']] as const) {
      fetch.mockResolvedValueOnce(json({ ...fixtures.stale_error, error: { code, message: 'private', retryable: false } }, status));
      await expect(QtPreviewApi.confirmPreview(fixtures.preview_clean.preview_id, confirm))
        .rejects.toMatchObject({ status, code, name: 'QtApiError' });
    }
    fetch.mockResolvedValueOnce(new Response('<private>', { status: 409 }));
    await expect(QtPreviewApi.confirmPreview(fixtures.preview_clean.preview_id, confirm))
      .rejects.toBeInstanceOf(QtMutationUncertainError);
    expect(fetch).toHaveBeenCalledTimes(5);
    expect(QtApiError.name).toBe('QtApiError');
  });
});
