// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import fixtures from '../../../../contracts/qt-workflow-v1.json';
import { QtMutationUncertainError } from './qtPreviewApi';
import { QtRecovery, QtRecoveryStorageError } from './qtRecovery';
import type { QtDecision } from '../../domain/portfolio/qtPreview';

const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } });
const intent = { actor_id: '101', book_id: 'synthetic-book-A', preview_id: fixtures.preview_clean.preview_id,
  expected_digest: fixtures.preview_clean.payload_digest,
  idempotency_key: '22222222-2222-4222-8222-222222222222', acknowledge_warnings: false };

beforeEach(() => { sessionStorage.clear(); QtRecovery.activateActor(sessionStorage, '101'); });
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });

it.each(['submit', 'retry'] as const)('preserves uncertain approval intent before %s settles mismatched immutable bindings', async operation => {
  const approval = { actor_id: '101', book_id: intent.book_id,
    request_id: fixtures.confirm_pending.request_id!, idempotency_key: intent.idempotency_key };
  const fetch = vi.fn().mockResolvedValue(json({ ...fixtures.confirm_pending,
    approvals: [{ person_id: 'hemdutt_rao', display_label: 'Hemdutt Rao', user_id: '101',
      approved_at: '2026-09-25T16:00:00Z' }], approvals_count: 1, can_approve: false,
    read_set_digest: 'e'.repeat(64) }));
  vi.stubGlobal('fetch', fetch);
  QtRecovery.stageApproval(sessionStorage, approval);
  const linked = (decision: QtDecision) => decision.read_set_digest === fixtures.confirm_pending.read_set_digest;
  const request = operation === 'submit' ? QtRecovery.submitApproval(sessionStorage, approval, () => true, linked) :
    QtRecovery.retryApproval(sessionStorage, '101', intent.book_id, () => true, linked);
  await expect(request).rejects.toBeInstanceOf(QtMutationUncertainError);
  expect(QtRecovery.loadApproval(sessionStorage, '101', intent.book_id)).toEqual(approval);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it('stores only minimal confirmation identity before one POST and never POSTs on reload', async () => {
  const fetch = vi.fn().mockResolvedValue(json(fixtures.decision_pending));
  vi.stubGlobal('fetch', fetch);
  const stored = QtRecovery.stageConfirmation(sessionStorage, intent);
  expect(stored).toEqual(intent);
  expect(Object.keys(JSON.parse(sessionStorage.getItem(sessionStorage.key(0)!)!)).sort())
    .toEqual(Object.keys(intent).sort());
  expect(QtRecovery.loadConfirmation(sessionStorage, '101', 'synthetic-book-A')).toEqual(intent);
  expect(fetch).not.toHaveBeenCalled();
  const decision = await QtRecovery.recoverConfirmation(sessionStorage, '101', 'synthetic-book-A');
  expect(decision?.decision_id).toBe(fixtures.decision_pending.decision_id);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ action: 'confirm_selected_book',
    expected_digest: intent.expected_digest, idempotency_key: intent.idempotency_key,
    acknowledge_warnings: false });
  fetch.mockResolvedValue(json(fixtures.decision_processed));
  await QtRecovery.recoverConfirmation(sessionStorage, '101', 'synthetic-book-A');
  expect(fetch.mock.calls[1][1].method).toBe('GET');
});

it('cannot consume another book record and preserves same-actor pending recovery', () => {
  QtRecovery.stageConfirmation(sessionStorage, intent);
  expect(QtRecovery.loadConfirmation(sessionStorage, '101', 'other-book')).toBeNull();
  expect(QtRecovery.loadConfirmation(sessionStorage, '101', 'synthetic-book-A')).toEqual(intent);
});

it('discards prior-actor confirmation and approval browser intents on authenticated actor change', () => {
  QtRecovery.stageConfirmation(sessionStorage, intent);
  const approval = { actor_id: '101', book_id: intent.book_id,
    request_id: fixtures.confirm_pending.request_id!, idempotency_key: intent.idempotency_key };
  QtRecovery.stageApproval(sessionStorage, approval);
  QtRecovery.activateActor(sessionStorage, '202');
  expect(QtRecovery.loadConfirmation(sessionStorage, '202', intent.book_id)).toBeNull();
  expect(QtRecovery.loadConfirmation(sessionStorage, '101', intent.book_id)).toBeNull();
  expect(QtRecovery.loadApproval(sessionStorage, '101', intent.book_id)).toBeNull();
});

it('discards a legacy global prior-actor intent on actor change', () => {
  sessionStorage.setItem('algolens.qt.confirmation.v1', JSON.stringify(intent));
  QtRecovery.activateActor(sessionStorage, '202');
  expect(QtRecovery.loadConfirmation(sessionStorage, '202', intent.book_id)).toBeNull();
  expect(sessionStorage.getItem('algolens.qt.confirmation.v1')).toBeNull();
});

it('does not infer the authenticated actor from a stale recovery load or clear', () => {
  QtRecovery.activateActor(sessionStorage, '202');
  const active = { ...intent, actor_id: '202' };
  QtRecovery.stageConfirmation(sessionStorage, active);
  expect(QtRecovery.loadConfirmation(sessionStorage, '101', intent.book_id)).toBeNull();
  expect(QtRecovery.clearConfirmation(sessionStorage, '101', intent.book_id)).toBe(false);
  expect(QtRecovery.loadConfirmation(sessionStorage, '202', intent.book_id)).toEqual(active);
});

it('rejects late confirmation persistence after an A to B to A actor epoch change', async () => {
  let resolve!: (response: Response) => void;
  const fetch = vi.fn().mockReturnValue(new Promise<Response>(yes => { resolve = yes; }));
  vi.stubGlobal('fetch', fetch);
  const previous = QtRecovery.submitConfirmation(sessionStorage, intent);
  QtRecovery.activateActor(sessionStorage, '202');
  QtRecovery.activateActor(sessionStorage, '101');
  const active = { ...intent, idempotency_key: '33333333-3333-4333-8333-333333333333' };
  QtRecovery.stageConfirmation(sessionStorage, active);
  resolve(json(fixtures.decision_pending));
  await previous;
  expect(QtRecovery.loadConfirmation(sessionStorage, '101', intent.book_id)).toEqual(active);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it.each(['submit', 'retry'] as const)('preserves known approval recovery after stale %s GET settlement', async operation => {
  let resolve!: (response: Response) => void;
  const fetch = vi.fn().mockReturnValue(new Promise<Response>(yes => { resolve = yes; }));
  vi.stubGlobal('fetch', fetch);
  const approval = { actor_id: '101', book_id: intent.book_id,
    request_id: fixtures.confirm_pending.request_id!, idempotency_key: intent.idempotency_key };
  const stored = { ...approval, decision_id: fixtures.confirm_pending.decision_id };
  sessionStorage.setItem('algolens.qt.approval.v1', JSON.stringify(stored));
  let current = true;
  const previous = operation === 'submit' ? QtRecovery.submitApproval(sessionStorage, approval, () => current) :
    QtRecovery.retryApproval(sessionStorage, '101', intent.book_id, () => current);
  current = false;
  resolve(json({ ...fixtures.confirm_pending, approvals: [{ person_id: 'hemdutt_rao',
    display_label: 'Hemdutt Rao', user_id: '101', approved_at: '2026-09-25T16:00:00Z' }],
    approvals_count: 1, can_approve: false }));
  await previous;
  expect(QtRecovery.loadApproval(sessionStorage, '101', intent.book_id)).toEqual(stored);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][1].method).toBe('GET');
});

it('keeps an unresolved confirmation key instead of overwriting recovery identity', () => {
  QtRecovery.stageConfirmation(sessionStorage, intent);
  expect(() => QtRecovery.stageConfirmation(sessionStorage, { ...intent,
    idempotency_key: '33333333-3333-4333-8333-333333333333' })).toThrow(QtRecoveryStorageError);
  expect(QtRecovery.loadConfirmation(sessionStorage, '101', 'synthetic-book-A')).toEqual(intent);
});

it('keeps a pending A-book intent when a B-book confirmation is staged for the same actor', () => {
  QtRecovery.stageConfirmation(sessionStorage, intent);
  const other = { ...intent, book_id: 'synthetic-book-B', preview_id: '30000000-0000-4000-8000-000000000099',
    idempotency_key: '33333333-3333-4333-8333-333333333333' };
  expect(QtRecovery.stageConfirmation(sessionStorage, other)).toEqual(other);
  expect(QtRecovery.loadConfirmation(sessionStorage, '101', 'synthetic-book-A')).toEqual(intent);
  expect(QtRecovery.loadConfirmation(sessionStorage, '101', 'synthetic-book-B')).toEqual(other);
  expect(QtRecovery.clearConfirmation(sessionStorage, '101', 'synthetic-book-B')).toBe(true);
  expect(QtRecovery.loadConfirmation(sessionStorage, '101', 'synthetic-book-A')).toEqual(intent);
  expect(QtRecovery.loadConfirmation(sessionStorage, '101', 'synthetic-book-B')).toBeNull();
});

it('preserves an old global recovery record while a different book gets scoped storage', () => {
  sessionStorage.setItem('algolens.qt.confirmation.v1', JSON.stringify(intent));
  const other = { ...intent, book_id: 'synthetic-book-B', preview_id: '30000000-0000-4000-8000-000000000099',
    idempotency_key: '33333333-3333-4333-8333-333333333333' };
  QtRecovery.stageConfirmation(sessionStorage, other);
  expect(QtRecovery.loadConfirmation(sessionStorage, '101', 'synthetic-book-A')).toEqual(intent);
  expect(QtRecovery.loadConfirmation(sessionStorage, '101', 'synthetic-book-B')).toEqual(other);
});

it('clears only the matching scoped record before a new confirmation can be staged', () => {
  QtRecovery.stageConfirmation(sessionStorage, intent);
  expect(QtRecovery.clearConfirmation(sessionStorage, '101', 'other-book')).toBe(false);
  expect(QtRecovery.clearConfirmation(sessionStorage, '101', 'synthetic-book-A')).toBe(true);
  expect(QtRecovery.loadConfirmation(sessionStorage, '101', 'synthetic-book-A')).toBeNull();
  const next = { ...intent, idempotency_key: '33333333-3333-4333-8333-333333333333' };
  expect(QtRecovery.stageConfirmation(sessionStorage, next)).toEqual(next);
});

it('blocks confirmation before POST when durable recovery storage fails', async () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
  const broken: Storage = { length: 0, clear() {}, key: () => null, removeItem() {},
    getItem() { throw new Error('disabled'); }, setItem() { throw new Error('disabled'); } };
  await expect(QtRecovery.submitConfirmation(broken, intent)).rejects.toBeInstanceOf(QtRecoveryStorageError);
  expect(fetch).not.toHaveBeenCalled();
});

it('treats a wrong-book confirmation response as uncertain and retains recovery identity', async () => {
  const fetch = vi.fn().mockResolvedValue(json({ ...fixtures.decision_pending, book_id: 'other-book' }));
  vi.stubGlobal('fetch', fetch);
  await expect(QtRecovery.submitConfirmation(sessionStorage, intent)).rejects.toBeInstanceOf(QtMutationUncertainError);
  expect(QtRecovery.loadConfirmation(sessionStorage, '101', 'synthetic-book-A')).toEqual(intent);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it('keeps one approval key for explicit retry after response loss', async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new TypeError('offline')).mockResolvedValueOnce(json(fixtures.confirm_pending));
  vi.stubGlobal('fetch', fetch);
  const approval = { actor_id: '101', book_id: 'synthetic-book-A',
    request_id: fixtures.confirm_pending.request_id!, idempotency_key: intent.idempotency_key };
  await expect(QtRecovery.submitApproval(sessionStorage, approval)).rejects.toThrow();
  expect(QtRecovery.loadApproval(sessionStorage, '101', 'synthetic-book-A')).toEqual(approval);
  expect(fetch).toHaveBeenCalledTimes(1);
  await QtRecovery.retryApproval(sessionStorage, '101', 'synthetic-book-A');
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(fetch.mock.calls[1][1].body).toBe(fetch.mock.calls[0][1].body);
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ action: 'approve', idempotency_key: approval.idempotency_key });
});

it('replays an uncertain confirmation with identical bytes and then refreshes status by GET', async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new TypeError('response lost'))
    .mockResolvedValueOnce(json(fixtures.decision_pending))
    .mockResolvedValueOnce(json(fixtures.decision_processed));
  vi.stubGlobal('fetch', fetch);
  await expect(QtRecovery.submitConfirmation(sessionStorage, intent)).rejects.toThrow();
  expect(QtRecovery.loadConfirmation(sessionStorage, '101', 'synthetic-book-A')).toEqual(intent);
  const decision = await QtRecovery.recoverConfirmation(sessionStorage, '101', 'synthetic-book-A');
  expect(decision?.decision_id).toBe(fixtures.decision_pending.decision_id);
  expect(fetch.mock.calls[1][1].body).toBe(fetch.mock.calls[0][1].body);
  const refreshed = await QtRecovery.submitConfirmation(sessionStorage, intent);
  expect(refreshed.report_ready).toBe(true);
  expect(fetch.mock.calls[2][1].method).toBe('GET');
  expect(fetch).toHaveBeenCalledTimes(3);
});

it('does not replace a pending approval retry key with another key', async () => {
  const fetch = vi.fn().mockRejectedValue(new TypeError('offline'));
  vi.stubGlobal('fetch', fetch);
  const approval = { actor_id: '101', book_id: 'synthetic-book-A',
    request_id: fixtures.confirm_pending.request_id!, idempotency_key: intent.idempotency_key };
  await expect(QtRecovery.submitApproval(sessionStorage, approval)).rejects.toThrow();
  await expect(QtRecovery.submitApproval(sessionStorage, { ...approval,
    idempotency_key: '33333333-3333-4333-8333-333333333333' })).rejects.toBeInstanceOf(QtRecoveryStorageError);
  await expect(QtRecovery.submitApproval(sessionStorage, { ...approval,
    request_id: '50000000-0000-4000-8000-000000000099' })).rejects.toBeInstanceOf(QtRecoveryStorageError);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(QtRecovery.loadApproval(sessionStorage, '101', 'synthetic-book-A')).toEqual(approval);
});

it('releases an acknowledged R1 approval slot so a later R2 in the same book can post', async () => {
  const recorded = { ...fixtures.confirm_pending, approvals: [{ person_id: 'hemdutt_rao',
    display_label: 'Hemdutt Rao', user_id: '101', approved_at: '2026-09-25T16:00:00Z' }],
    approvals_count: 1, can_approve: false };
  const later = { ...recorded, request_id: '50000000-0000-4000-8000-000000000099',
    decision_id: '40000000-0000-4000-8000-000000000099' };
  const fetch = vi.fn().mockResolvedValueOnce(json(recorded)).mockResolvedValueOnce(json(later));
  vi.stubGlobal('fetch', fetch);
  const first = { actor_id: '101', book_id: intent.book_id,
    request_id: fixtures.confirm_pending.request_id!, idempotency_key: intent.idempotency_key };
  await QtRecovery.submitApproval(sessionStorage, first);
  expect(QtRecovery.loadApproval(sessionStorage, '101', intent.book_id)).toBeNull();
  const second = { ...first, request_id: later.request_id,
    idempotency_key: '33333333-3333-4333-8333-333333333333' };
  await QtRecovery.submitApproval(sessionStorage, second);
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(JSON.parse(fetch.mock.calls[1][1].body).idempotency_key).toBe(second.idempotency_key);
});
