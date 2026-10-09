/**
 * QT desk rules on the browser side (contract sections 4 and 7).
 *
 * The server re-checks everything; these rules only keep the form honest:
 * whole contracts, 0 = flatten, a reason on every change.
 */

export type CommandKind = 'save' | 'override_request' | 'override_decision' | 'publish';
export type CommandStatus = 'pending' | 'running' | 'done' | 'refused' | 'failed';

export interface DeskCommand {
  id: number;
  portfolio_id: string;
  date: string;
  kind: CommandKind;
  status: CommandStatus;
  requested_by: string;
  reason: string | null;
  payload: Record<string, unknown>;
  parent_id: number | null;
  approver_role: 'vp' | 'president' | null;
  token_expires_at: string | null;
  result: Record<string, unknown> | null;
  message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface BookPosition {
  symbol: string;
  quantity: number;
  average_price: number | null;
  moved_by: string | null;
}

export interface ComparisonRow {
  symbol: string;
  asked: number | null;
  given: number | null;
  moved_by: string | null;
  differs: boolean;
}

export interface OverrideRequestRow extends DeskCommand {
  decision: DeskCommand | null;
}

export interface DeskState {
  portfolioId: string;
  deskEditable: boolean;
  date: string | null;
  seeded: boolean;
  books: { system: BookPosition[]; qt_proposal: BookPosition[]; qt: BookPosition[] };
  comparison: ComparisonRow[];
  latestSave: DeskCommand | null;
  overrideRequests: OverrideRequestRow[];
  publish: DeskCommand | null;
  /** From live_run_metadata.published_at (C3): the day is frozen once set. */
  published: { published_by: string | null; published_at: string | null } | null;
  /** Why save, override request and publish are closed: published, or a publish is open. */
  locked?: 'published' | 'publishing' | null;
  /** The day's override request still in play (C2), if any. */
  openOverrideRequestId?: number | null;
}

/** One row of the book an override request snapshotted (C1). */
export interface SnapshotRow {
  strategy_name: string;
  symbol: string;
  quantity: number;
}

export interface SymbolChoice {
  symbol: string;
  root: string;
  name: string;
  sector: string | null;
  price: number;
  price_date: string | null;
}

export interface QuantityChange {
  symbol: string;
  quantity: number;
  /** The quantity the form showed (null for a symbol not in the proposal). The
   * server refuses the save (409) if the proposal no longer holds it. */
  expected: number | null;
}

export const MAX_ABS_CONTRACTS = 100_000;
/** Poll every 2 s for the first minute, then every 15 s. */
export const POLL_INTERVAL_MS = 2_000;
export const POLL_SLOW_INTERVAL_MS = 15_000;
export const POLL_FAST_FOR_MS = 60_000;
/** After this long a command is shown as still running on the engine, not failed. */
export const POLL_SLOW_NOTICE_MS = 5 * 60_000;
/** The engine's job timeout (QT_JOB_TIMEOUT, 30 min): polling stops there. */
export const POLL_BUDGET_MS = 30 * 60_000;
/** @deprecated the old 5-minute budget; kept for callers that name it. */
export const POLL_TIMEOUT_MS = POLL_SLOW_NOTICE_MS;

const WHOLE = /^[+-]?\d+$/;

/** A typed quantity as whole contracts, or an error message. */
export function parseContracts(raw: string): { value: number } | { error: string } {
  const text = raw.trim();
  if (!WHOLE.test(text)) return { error: 'Whole contracts only (0 flattens)' };
  const value = Number.parseInt(text, 10);
  if (Math.abs(value) > MAX_ABS_CONTRACTS) {
    return { error: `At most ${MAX_ABS_CONTRACTS.toLocaleString('en-US')} contracts` };
  }
  return { value };
}

export interface EditValidation {
  changes: QuantityChange[];
  /** Per-symbol input errors. */
  fieldErrors: Record<string, string>;
  /** Errors not tied to one input (reason, nothing changed). */
  formErrors: string[];
  ok: boolean;
}

/**
 * Validate the edit form. `draft` holds the typed quantity per symbol, for
 * symbols already in the proposal and symbols added from the picker
 * (`added`). Unchanged symbols are not sent.
 */
export function validateEdit(
  proposal: BookPosition[],
  draft: Record<string, string>,
  added: string[],
  reason: string,
): EditValidation {
  const held = new Map(proposal.map(p => [p.symbol, p.quantity]));
  const changes: QuantityChange[] = [];
  const fieldErrors: Record<string, string> = {};
  const formErrors: string[] = [];

  const symbols = [...proposal.map(p => p.symbol), ...added.filter(s => !held.has(s))];
  for (const symbol of symbols) {
    const raw = draft[symbol];
    const isNew = !held.has(symbol);
    if (raw === undefined || raw.trim() === '') {
      if (isNew) fieldErrors[symbol] = 'Enter a quantity for the new symbol';
      continue;
    }
    const parsed = parseContracts(raw);
    if ('error' in parsed) {
      fieldErrors[symbol] = parsed.error;
      continue;
    }
    if (isNew && parsed.value === 0) {
      fieldErrors[symbol] = 'A new symbol needs a non-zero quantity';
      continue;
    }
    if (!isNew && parsed.value === held.get(symbol)) continue;
    changes.push({ symbol, quantity: parsed.value, expected: isNew ? null : held.get(symbol)! });
  }

  if (!reason.trim()) formErrors.push('A reason is required');
  if (changes.length === 0 && Object.keys(fieldErrors).length === 0) {
    formErrors.push('No quantity changed');
  }
  return {
    changes,
    fieldErrors,
    formErrors,
    ok: changes.length > 0 && formErrors.length === 0 && Object.keys(fieldErrors).length === 0,
  };
}

export function isFinal(status: CommandStatus | undefined | null): boolean {
  return status === 'done' || status === 'refused' || status === 'failed';
}

/** Keep polling a command row until it is final or the engine's job timeout has passed. */
export function shouldKeepPolling(
  status: CommandStatus | undefined | null,
  startedAtMs: number,
  nowMs: number,
): boolean {
  return !isFinal(status) && nowMs - startedAtMs < POLL_BUDGET_MS;
}

/** The wait before the next poll: 2 s for the first minute, 15 s after. */
export function pollDelayMs(elapsedMs: number): number {
  return elapsedMs < POLL_FAST_FOR_MS ? POLL_INTERVAL_MS : POLL_SLOW_INTERVAL_MS;
}

/** A poll error that will not go away by asking again (4xx): stop and show it. */
export function isFatalPollError(status: number | undefined | null): boolean {
  return typeof status === 'number' && status >= 400 && status < 500 && status !== 408 && status !== 429;
}

/**
 * How long a still-open command has been watched: 'normal', 'slow' (past 5
 * minutes: still running on the engine) or 'gaveUp' (past the job timeout:
 * polling stopped; a manual refresh asks again).
 */
export type PollPhase = 'normal' | 'slow' | 'gaveUp';

export function pollPhase(elapsedMs: number): PollPhase {
  if (elapsedMs >= POLL_BUDGET_MS) return 'gaveUp';
  if (elapsedMs >= POLL_SLOW_NOTICE_MS) return 'slow';
  return 'normal';
}

const KIND_NAMES: Record<CommandKind, string> = {
  save: 'Save',
  override_request: 'Override request',
  override_decision: 'Override decision',
  publish: 'Publish',
};

/**
 * One plain sentence for a command row's state; refusals and failures say
 * why. `phase` (or the legacy `true`, = 'slow') says how long it has been
 * watched: an open command past 5 minutes is still running on the engine,
 * not a failure.
 */
export function describeCommand(command: DeskCommand | null, phase: PollPhase | boolean = 'normal'): string {
  if (!command) return '';
  const kind = KIND_NAMES[command.kind] ?? command.kind;
  const why = command.message ? `: ${command.message}` : '';
  const watched: PollPhase = phase === true ? 'slow' : phase === false ? 'normal' : phase;
  if (!isFinal(command.status) && watched !== 'normal') {
    const state = command.status === 'running' ? 'still running on the engine' : 'still waiting for the engine';
    return watched === 'gaveUp'
      ? `${kind} is ${state} after 30 minutes. Nothing failed; it stays queued. Refresh to check again.`
      : `${kind} is ${state} after 5 minutes. It stays queued; the engine picks pending commands up every minute.`;
  }
  switch (command.status) {
    case 'pending':
      return `${kind} sent; waiting for the engine`;
    case 'running':
      return `${kind}: the engine is working on it`;
    case 'done':
      return `${kind} done${why}`;
    case 'refused':
      return `${kind} REFUSED by the engine${why || ' (no reason given)'}`;
    case 'failed':
      return `${kind} FAILED${why || ' (no reason given)'}`;
    default:
      return `${kind}: ${command.status}`;
  }
}

/**
 * Why the day's book takes no more desk actions, or null. A day is published
 * when live_run_metadata says so (C3: also the engine's own non-trading-day
 * publish, which has no publish row) or its publish row is done; a pending or
 * running publish closes it too.
 */
export function deskLockedReason(state: DeskState): 'Published' | 'Publish in progress' | null {
  if (state.locked === 'published' || state.published?.published_at || state.publish?.status === 'done') {
    return 'Published';
  }
  if (
    state.locked === 'publishing' ||
    state.publish?.status === 'pending' ||
    state.publish?.status === 'running'
  ) {
    return 'Publish in progress';
  }
  return null;
}

/** Publishing is open every day, edited or not, unless one is queued or done. */
export function publishBlockedReason(state: DeskState): string | null {
  if (!state.date) return 'No book for today yet';
  return deskLockedReason(state);
}

/** Editing the proposal: closed on a published day and while a publish is open. */
export function editBlockedReason(state: DeskState): string | null {
  if (!state.seeded) return 'The proposal is not seeded yet';
  return deskLockedReason(state);
}

/** One override request a day is in play at a time (C2). */
export function overrideBlockedReason(state: DeskState): string | null {
  if (!state.seeded) return 'The proposal is not seeded yet';
  const locked = deskLockedReason(state);
  if (locked) return locked;
  if (state.openOverrideRequestId != null) {
    return `Override request #${state.openOverrideRequestId} is still open`;
  }
  return null;
}

/**
 * The proposal's identity: the edit form is keyed on it, so its draft resets
 * whenever the proposal it was typed against changes.
 */
export function proposalKey(proposal: BookPosition[]): string {
  return proposal.map(p => `${p.symbol}=${p.quantity}`).join('|');
}

/** The snapshot's quantity per symbol, netted over sleeves. */
export function snapshotBySymbol(snapshot: SnapshotRow[] | null | undefined): Map<string, number> {
  const bySymbol = new Map<string, number>();
  for (const row of snapshot ?? []) bySymbol.set(row.symbol, (bySymbol.get(row.symbol) ?? 0) + row.quantity);
  return bySymbol;
}

/** Approval links carry the token in the query string: /qt/approve?token=... */
export function approvalTokenFrom(search: string): string | null {
  const token = new URLSearchParams(search).get('token');
  return token && token.trim() ? token.trim() : null;
}
