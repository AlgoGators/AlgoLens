import type { QtDecision } from '../../domain/portfolio/qtPreview';
import { QtMutationUncertainError, QtPreviewApi, QtReadError } from './qtPreviewApi';

export type QtConfirmationIntent = { actor_id: string; book_id: string; preview_id: string;
  expected_digest: string; idempotency_key: string; acknowledge_warnings: boolean };
export type QtApprovalIntent = { actor_id: string; book_id: string; request_id: string; idempotency_key: string };
type StoredConfirmation = QtConfirmationIntent & { decision_id?: string };
type StoredApproval = QtApprovalIntent & { decision_id?: string };
type ActorLifecycle = { actorId: string; epoch: number };
const activeActors = new WeakMap<Storage, ActorLifecycle>();
type CurrentGuard = () => boolean;
const confirmationKey = 'algolens.qt.confirmation.v1';
const approvalKey = 'algolens.qt.approval.v1';
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const digest = /^[0-9a-f]{64}$/;
const account = /^(?:0|[1-9][0-9]*)$/;

export class QtRecoveryStorageError extends Error {
  constructor() { super('QT recovery storage is unavailable. Retry after storage is restored.'); this.name = 'QtRecoveryStorageError'; }
}

function plain(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function validCommon(value: Record<string, unknown>): boolean {
  return typeof value.actor_id === 'string' && account.test(value.actor_id) &&
    typeof value.book_id === 'string' && value.book_id.length > 0 && value.book_id.length <= 512 &&
    typeof value.idempotency_key === 'string' && uuid.test(value.idempotency_key) &&
    (value.decision_id === undefined || (typeof value.decision_id === 'string' && uuid.test(value.decision_id)));
}
function validConfirmation(value: unknown): value is StoredConfirmation {
  if (!plain(value) || !validCommon(value)) return false;
  const fields = ['actor_id', 'book_id', 'preview_id', 'expected_digest', 'idempotency_key', 'acknowledge_warnings'];
  return Object.keys(value).every(field => fields.includes(field) || field === 'decision_id') &&
    fields.every(field => Object.hasOwn(value, field)) &&
    typeof value.preview_id === 'string' && uuid.test(value.preview_id) &&
    typeof value.expected_digest === 'string' && digest.test(value.expected_digest) &&
    typeof value.acknowledge_warnings === 'boolean';
}
function validApproval(value: unknown): value is StoredApproval {
  if (!plain(value) || !validCommon(value)) return false;
  const fields = ['actor_id', 'book_id', 'request_id', 'idempotency_key'];
  return Object.keys(value).every(field => fields.includes(field) || field === 'decision_id') &&
    fields.every(field => Object.hasOwn(value, field)) &&
    typeof value.request_id === 'string' && uuid.test(value.request_id);
}
function put<T>(storage: Storage, key: string, value: T): T {
  try {
    const bytes = JSON.stringify(value);
    storage.setItem(key, bytes);
    if (storage.getItem(key) !== bytes) throw new QtRecoveryStorageError();
    return value;
  } catch { throw new QtRecoveryStorageError(); }
}
function readStored<T>(storage: Storage, key: string, valid: (value: unknown) => value is T): T | null {
  try {
    const bytes = storage.getItem(key);
    if (bytes === null) return null;
    let value: unknown;
    try { value = JSON.parse(bytes); } catch { storage.removeItem(key); return null; }
    if (!valid(value)) { storage.removeItem(key); return null; }
    return value;
  } catch { throw new QtRecoveryStorageError(); }
}
function scopedKey(key: string, actorId: string, bookId: string): string {
  return `${key}.scoped.${encodeURIComponent(actorId)}.${encodeURIComponent(bookId)}`;
}
function discardPriorActor(storage: Storage, actorId: string): void {
  try {
    const keys = Array.from({ length: storage.length }, (_, index) => storage.key(index)).filter((key): key is string => !!key);
    for (const key of keys) {
      if (key === confirmationKey || key.startsWith(`${confirmationKey}.scoped.`)) {
        const value = readStored(storage, key, validConfirmation);
        if (value && value.actor_id !== actorId) storage.removeItem(key);
      } else if (key === approvalKey || key.startsWith(`${approvalKey}.scoped.`)) {
        const value = readStored(storage, key, validApproval);
        if (value && value.actor_id !== actorId) storage.removeItem(key);
      }
    }
  } catch { throw new QtRecoveryStorageError(); }
}
function load<T extends { actor_id: string; book_id: string }>(storage: Storage, key: string, actorId: string, bookId: string,
  valid: (value: unknown) => value is T): T | null {
  const scoped = readStored(storage, scopedKey(key, actorId, bookId), valid);
  const old = readStored(storage, key, valid);
  const legacy = old?.actor_id === actorId && old.book_id === bookId ? old : null;
  if (scoped && (scoped.actor_id !== actorId || scoped.book_id !== bookId ||
      (legacy && JSON.stringify(scoped) !== JSON.stringify(legacy)))) throw new QtRecoveryStorageError();
  return scoped ?? legacy;
}
function stageScoped<T extends { actor_id: string; book_id: string; decision_id?: string }>(storage: Storage, key: string,
  intent: T, valid: (value: unknown) => value is T): T {
  if (activeActors.get(storage)?.actorId !== intent.actor_id) throw new QtRecoveryStorageError();
  const existing = load(storage, key, intent.actor_id, intent.book_id, valid);
  if (existing) {
    const { decision_id: _known, ...original } = existing;
    if (JSON.stringify(original) !== JSON.stringify(intent)) throw new QtRecoveryStorageError();
    return intent;
  }
  return put(storage, scopedKey(key, intent.actor_id, intent.book_id), intent);
}
function clearScoped<T extends { actor_id: string; book_id: string }>(storage: Storage, key: string,
  actorId: string, bookId: string, valid: (value: unknown) => value is T): boolean {
  if (activeActors.get(storage)?.actorId !== actorId) return false;
  if (!load(storage, key, actorId, bookId, valid)) return false;
  const old = readStored(storage, key, valid);
  try {
    storage.removeItem(scopedKey(key, actorId, bookId));
    if (old?.actor_id === actorId && old.book_id === bookId) storage.removeItem(key);
    return true;
  }
  catch { throw new QtRecoveryStorageError(); }
}
function confirmationRequest(intent: QtConfirmationIntent) {
  return { action: 'confirm_selected_book' as const, expected_digest: intent.expected_digest,
    idempotency_key: intent.idempotency_key, acknowledge_warnings: intent.acknowledge_warnings };
}
function rememberDecision<T extends { actor_id: string; book_id: string }>(storage: Storage, key: string,
  intent: T, decision: QtDecision, valid: (value: unknown) => value is T, canPersist: CurrentGuard): void {
  if (!canPersist()) return;
  try {
    const old = readStored(storage, key, valid);
    const destination = old?.actor_id === intent.actor_id && old.book_id === intent.book_id ?
      key : scopedKey(key, intent.actor_id, intent.book_id);
    put(storage, destination, { ...intent, decision_id: decision.decision_id });
  }
  catch { /* the original record remains sufficient for explicit idempotent replay */ }
}
function settleApproval(storage: Storage, intent: QtApprovalIntent, decision: QtDecision, canPersist: CurrentGuard): void {
  if (!canPersist()) return;
  if (decision.book_id === intent.book_id && decision.request_id === intent.request_id &&
      decision.approvals.some(approval => approval.user_id === intent.actor_id)) {
    QtRecovery.clearApproval(storage, intent.actor_id, intent.book_id);
  } else {
    rememberDecision(storage, approvalKey, intent, decision, validApproval, canPersist);
  }
}
function mutationGuard(storage: Storage, actorId: string, isCurrent: CurrentGuard): CurrentGuard {
  const actor = activeActors.get(storage);
  if (!actor || actor.actorId !== actorId || !isCurrent()) throw new QtRecoveryStorageError();
  return () => activeActors.get(storage) === actor && isCurrent();
}
async function readKnownDecision(decisionId: string, bookId: string, previewId?: string, requestId?: string): Promise<QtDecision> {
  const decision = await QtPreviewApi.getDecision(decisionId);
  if (decision.book_id !== bookId || (previewId && decision.preview_id !== previewId) ||
    (requestId && decision.request_id !== requestId)) throw new QtReadError();
  return decision;
}

export class QtRecovery {
  // Called only by the active authenticated lifecycle, never by a recovery read or stale settlement.
  static activateActor(storage: Storage, actorId: string): void {
    const previous = activeActors.get(storage);
    if (previous?.actorId === actorId) return;
    discardPriorActor(storage, actorId);
    activeActors.set(storage, { actorId, epoch: (previous?.epoch ?? 0) + 1 });
  }
  static stageConfirmation(storage: Storage, intent: QtConfirmationIntent): QtConfirmationIntent {
    if (!validConfirmation(intent)) throw new QtRecoveryStorageError();
    return stageScoped(storage, confirmationKey, intent, validConfirmation);
  }
  static loadConfirmation(storage: Storage, actorId: string, bookId: string): StoredConfirmation | null {
    return load(storage, confirmationKey, actorId, bookId, validConfirmation);
  }
  static clearConfirmation(storage: Storage, actorId: string, bookId: string): boolean {
    return clearScoped(storage, confirmationKey, actorId, bookId, validConfirmation);
  }
  static async submitConfirmation(storage: Storage, intent: QtConfirmationIntent, isCurrent: CurrentGuard = () => true): Promise<QtDecision> {
    const canPersist = mutationGuard(storage, intent.actor_id, isCurrent);
    this.stageConfirmation(storage, intent);
    const existing = this.loadConfirmation(storage, intent.actor_id, intent.book_id);
    if (existing?.decision_id) return readKnownDecision(existing.decision_id, intent.book_id, intent.preview_id);
    const decision = await QtPreviewApi.confirmPreview(intent.preview_id, confirmationRequest(intent));
    if (decision.book_id !== intent.book_id) throw new QtMutationUncertainError();
    rememberDecision(storage, confirmationKey, intent, decision, validConfirmation, canPersist);
    return decision;
  }
  // Called only from an explicit user recovery action. Loading the record never sends a POST.
  static async recoverConfirmation(storage: Storage, actorId: string, bookId: string, isCurrent: CurrentGuard = () => true): Promise<QtDecision | null> {
    const canPersist = mutationGuard(storage, actorId, isCurrent);
    const intent = this.loadConfirmation(storage, actorId, bookId);
    if (!intent) return null;
    if (intent.decision_id) return readKnownDecision(intent.decision_id, bookId, intent.preview_id);
    const decision = await QtPreviewApi.confirmPreview(intent.preview_id, confirmationRequest(intent));
    if (decision.book_id !== intent.book_id) throw new QtMutationUncertainError();
    rememberDecision(storage, confirmationKey, intent, decision, validConfirmation, canPersist);
    return decision;
  }
  static loadApproval(storage: Storage, actorId: string, bookId: string): StoredApproval | null {
    return load(storage, approvalKey, actorId, bookId, validApproval);
  }
  static clearApproval(storage: Storage, actorId: string, bookId: string): boolean {
    return clearScoped(storage, approvalKey, actorId, bookId, validApproval);
  }
  static stageApproval(storage: Storage, intent: QtApprovalIntent): QtApprovalIntent {
    if (!validApproval(intent)) throw new QtRecoveryStorageError();
    return stageScoped(storage, approvalKey, intent, validApproval);
  }
  static async submitApproval(storage: Storage, intent: QtApprovalIntent, isCurrent: CurrentGuard = () => true,
    matchesEvidence: (decision: QtDecision) => boolean = () => true): Promise<QtDecision> {
    const canPersist = mutationGuard(storage, intent.actor_id, isCurrent);
    this.stageApproval(storage, intent);
    const existing = this.loadApproval(storage, intent.actor_id, intent.book_id);
    if (existing?.decision_id) {
      const known = await readKnownDecision(existing.decision_id, intent.book_id, undefined, intent.request_id);
      if (!matchesEvidence(known)) throw new QtMutationUncertainError();
      settleApproval(storage, intent, known, canPersist);
      return known;
    }
    const decision = await QtPreviewApi.approveOverride(intent.request_id, { action: 'approve', idempotency_key: intent.idempotency_key });
    if (decision.book_id !== intent.book_id || !matchesEvidence(decision)) throw new QtMutationUncertainError();
    settleApproval(storage, intent, decision, canPersist);
    return decision;
  }
  // Called only after an explicit retry action; the same key and request ID are reused.
  static async retryApproval(storage: Storage, actorId: string, bookId: string, isCurrent: CurrentGuard = () => true,
    matchesEvidence: (decision: QtDecision) => boolean = () => true): Promise<QtDecision | null> {
    const canPersist = mutationGuard(storage, actorId, isCurrent);
    const intent = this.loadApproval(storage, actorId, bookId);
    if (!intent) return null;
    if (intent.decision_id) {
      const known = await readKnownDecision(intent.decision_id, bookId, undefined, intent.request_id);
      if (!matchesEvidence(known)) throw new QtMutationUncertainError();
      settleApproval(storage, intent, known, canPersist);
      return known;
    }
    const decision = await QtPreviewApi.approveOverride(intent.request_id, { action: 'approve', idempotency_key: intent.idempotency_key });
    if (decision.book_id !== intent.book_id || !matchesEvidence(decision)) throw new QtMutationUncertainError();
    settleApproval(storage, intent, decision, canPersist);
    return decision;
  }
}
