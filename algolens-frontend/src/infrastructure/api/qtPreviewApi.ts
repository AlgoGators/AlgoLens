import {
  decodeQtBookDecision, decodeQtDecision, decodeQtDraft, decodeQtPreview, decodeQtProposal,
  type QtBookDecision, type QtComponentKey, type QtDecision, type QtDraft, type QtPreview, type QtProposal,
} from '../../domain/portfolio/qtPreview';
import { API_BASE_URL, getWithAuth, postWithAuth, putWithAuth, SessionExpiredError } from './httpClient';

export type QtSaveDraftRequest = { expected_source_digest: string; expected_provenance_digest: string;
  expected_draft_revision: number; idempotency_key: string;
  rationale: string;
  selection_rows: Array<{ key: QtComponentKey; quantity_exact: string }> };
export type QtCreatePreviewRequest = { book_id: string; draft_id: string; draft_revision: number;
  draft_digest: string; expected_source_digest: string; expected_provenance_digest: string; idempotency_key: string };
export type QtConfirmRequest = { action: 'confirm_selected_book'; expected_digest: string;
  idempotency_key: string; acknowledge_warnings: boolean };
export type QtApproveRequest = { action: 'approve'; idempotency_key: string };

const errorCodes = new Set([
  'provenance_unresolved', 'draft_stale', 'draft_identity_unresolved', 'preview_unavailable',
  'preview_stale', 'preview_mismatch', 'preview_required', 'preview_consumed',
  'authorization_changed', 'approval_identity_unmapped', 'decision_not_publishable',
  'idempotency_conflict', 'workflow_unavailable',
]);
const maxResponseBytes = 2 * 1024 * 1024;
const bookUrl = (bookId: string) => `${API_BASE_URL}/portfolio/qt-books/${encodeURIComponent(bookId)}`;

export class QtApiError extends Error {
  constructor(readonly status: number, readonly code: string) {
    super('QT action is unavailable. Refresh its status before continuing.');
    this.name = 'QtApiError';
  }
}
export class QtMutationUncertainError extends Error {
  constructor() { super('QT action status is uncertain. Recover the same request before trying again.'); this.name = 'QtMutationUncertainError'; }
}
export class QtReadError extends Error {
  constructor(readonly status?: number) { super('QT data could not be loaded.'); this.name = 'QtReadError'; }
}

async function boundedJson(response: Response): Promise<unknown> {
  if (!/^application\/json(?:\s*;|\s*$)/i.test(response.headers.get('content-type') ?? '')) throw new Error('invalid_content_type');
  const declared = response.headers.get('content-length');
  if (declared !== null && /^\d+$/.test(declared) && Number(declared) > maxResponseBytes) throw new Error('response_too_large');
  const reader = response.body?.getReader();
  if (!reader) throw new Error('missing_body');
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxResponseBytes) { await reader.cancel(); throw new Error('response_too_large'); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
}

function knownError(raw: unknown, status: number): QtApiError | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const data = raw as Record<string, unknown>;
  const detail = data.error;
  if (data.schema_version !== 'qt-workflow/v1' || !detail || typeof detail !== 'object' || Array.isArray(detail)) return null;
  const error = detail as Record<string, unknown>;
  return typeof error.code === 'string' && errorCodes.has(error.code) && typeof error.message === 'string' &&
    typeof error.retryable === 'boolean' ? new QtApiError(status, error.code) : null;
}

async function result<T>(response: Response, mutation: boolean, decode: (raw: unknown) => T): Promise<T> {
  if (!response.ok) {
    if (mutation && response.status >= 500) throw new QtMutationUncertainError();
    let error: QtApiError | null = null;
    try { error = knownError(await boundedJson(response), response.status); } catch { /* fixed error below */ }
    if (error) throw error;
    throw mutation ? new QtMutationUncertainError() : new QtReadError(response.status);
  }
  try { return decode(await boundedJson(response)); }
  catch { throw mutation ? new QtMutationUncertainError() : new QtReadError(); }
}

async function read<T>(url: string, signal: AbortSignal | undefined, decode: (raw: unknown) => T): Promise<T> {
  try { return await result(await getWithAuth(url, signal), false, decode); }
  catch (error) {
    if (error instanceof SessionExpiredError || error instanceof QtApiError || error instanceof QtReadError ||
      (error instanceof DOMException && error.name === 'AbortError')) throw error;
    throw new QtReadError();
  }
}
async function mutate<T>(request: () => Promise<Response>, decode: (raw: unknown) => T): Promise<T> {
  try { return await result(await request(), true, decode); }
  catch (error) {
    if (error instanceof SessionExpiredError || error instanceof QtApiError || error instanceof QtMutationUncertainError) throw error;
    throw new QtMutationUncertainError();
  }
}

export class QtPreviewApi {
  static getBookDecision(bookId: string, sourceDay: string, signal?: AbortSignal): Promise<QtBookDecision> {
    return read(`${bookUrl(bookId)}/decision?source_day=${encodeURIComponent(sourceDay)}`, signal, raw => {
      const value = decodeQtBookDecision(raw);
      if (value.book_id !== bookId || value.source_day !== sourceDay) throw new Error('wrong_scope');
      return value;
    });
  }
  static getProposal(bookId: string, signal?: AbortSignal): Promise<QtProposal> {
    return read(`${bookUrl(bookId)}/proposal`, signal, raw => {
      const value = decodeQtProposal(raw);
      if (value.book_id !== bookId) throw new Error('wrong_book');
      return value;
    });
  }
  static getDraft(bookId: string, signal?: AbortSignal): Promise<QtDraft> {
    return read(`${bookUrl(bookId)}/draft`, signal, raw => {
      const value = decodeQtDraft(raw);
      if (value.book_id !== bookId) throw new Error('wrong_book');
      return value;
    });
  }
  static saveDraft(bookId: string, request: QtSaveDraftRequest): Promise<QtDraft> {
    const body: QtSaveDraftRequest = { expected_source_digest: request.expected_source_digest,
      expected_provenance_digest: request.expected_provenance_digest,
      expected_draft_revision: request.expected_draft_revision, idempotency_key: request.idempotency_key,
      rationale: request.rationale,
      selection_rows: request.selection_rows.map(row => ({ key: {
        portfolio_id: row.key.portfolio_id, strategy_id: row.key.strategy_id,
        strategy_name: row.key.strategy_name, date: row.key.date,
        symbol: row.key.symbol, portfolio_type: row.key.portfolio_type,
      }, quantity_exact: row.quantity_exact })) };
    return mutate(() => putWithAuth(`${bookUrl(bookId)}/draft`, body), raw => {
      const value = decodeQtDraft(raw);
      if (value.book_id !== bookId || value.state !== 'saved' ||
        value.source_digest !== request.expected_source_digest ||
        value.provenance_digest !== request.expected_provenance_digest ||
        value.draft_revision <= request.expected_draft_revision) throw new Error('wrong_draft');
      return value;
    });
  }
  static createPreview(request: QtCreatePreviewRequest): Promise<QtPreview> {
    const body: QtCreatePreviewRequest = { book_id: request.book_id, draft_id: request.draft_id,
      draft_revision: request.draft_revision, draft_digest: request.draft_digest,
      expected_source_digest: request.expected_source_digest,
      expected_provenance_digest: request.expected_provenance_digest, idempotency_key: request.idempotency_key };
    return mutate(() => postWithAuth(`${API_BASE_URL}/portfolio/qt-previews`, body), raw => {
      const value = decodeQtPreview(raw);
      if (value.book_id !== request.book_id || value.draft_id !== request.draft_id ||
        value.draft_revision !== request.draft_revision ||
        value.source_digest !== request.expected_source_digest ||
        value.provenance_digest !== request.expected_provenance_digest) throw new Error('wrong_preview');
      return value;
    });
  }
  static confirmPreview(previewId: string, request: QtConfirmRequest): Promise<QtDecision> {
    const body: QtConfirmRequest = { action: 'confirm_selected_book', expected_digest: request.expected_digest,
      idempotency_key: request.idempotency_key, acknowledge_warnings: request.acknowledge_warnings };
    return mutate(() => postWithAuth(`${API_BASE_URL}/portfolio/qt-previews/${encodeURIComponent(previewId)}/confirm`, body), raw => {
      const value = decodeQtDecision(raw);
      if (value.preview_id !== previewId) throw new Error('wrong_decision');
      return value;
    });
  }
  static approveOverride(requestId: string, request: QtApproveRequest): Promise<QtDecision> {
    const body: QtApproveRequest = { action: 'approve', idempotency_key: request.idempotency_key };
    return mutate(() => postWithAuth(`${API_BASE_URL}/portfolio/qt-override-requests/${encodeURIComponent(requestId)}/approvals`, body), raw => {
      const value = decodeQtDecision(raw);
      if (value.request_id !== requestId) throw new Error('wrong_request');
      return value;
    });
  }
  static getDecision(decisionId: string, signal?: AbortSignal): Promise<QtDecision> {
    return read(`${API_BASE_URL}/portfolio/qt-decisions/${encodeURIComponent(decisionId)}`, signal, raw => {
      const value = decodeQtDecision(raw);
      if (value.decision_id !== decisionId) throw new Error('wrong_decision');
      return value;
    });
  }
}
