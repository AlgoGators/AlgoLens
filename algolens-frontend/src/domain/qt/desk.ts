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

/** Who published the day (live_run_metadata.publish_source, migration 026;
 * read from published_by before it). 'system' is an older engine publish. */
export type PublishSource = 'desk' | 'fallback' | 'model-only' | 'system';

export interface PublishedRecord {
  published_by: string | null;
  published_at: string | null;
  publish_source?: PublishSource | null;
  /** When the engine e-mailed the book (026); null until then, or before 026. */
  sent_at?: string | null;
}

/** The day's clock, in America/New_York, computed by the server. */
export interface DeskDeadlines {
  timezone: string;
  /** Today in New York. */
  today: string;
  /** The date approveBy/fallbackAt refer to: the desk's book date, or today. */
  bookDate: string;
  approveBy: string;
  fallbackAt: string;
  /** Today's deadlines (the next book's, while the desk shows an older day). */
  todayApproveBy: string;
  todayFallbackAt: string;
  /** The server's view at serverTime: bookDate's 10:00 New York has passed. */
  approvalClosed: boolean;
}

export interface DeskState {
  portfolioId: string;
  /** The server's clock when it answered (ISO, UTC): the desk counts down from it. */
  serverTime?: string;
  deadlines?: DeskDeadlines;
  /** Whether the database records publish_source and sent_at (migration 026). */
  sendTracked?: boolean;
  deskEditable: boolean;
  date: string | null;
  seeded: boolean;
  books: { system: BookPosition[]; qt_proposal: BookPosition[]; qt: BookPosition[] };
  comparison: ComparisonRow[];
  latestSave: DeskCommand | null;
  overrideRequests: OverrideRequestRow[];
  publish: DeskCommand | null;
  /** From live_run_metadata.published_at (C3): the day is frozen once set. */
  published: PublishedRecord | null;
  /** Why save, override request and approval are closed: published, or an approval is open. */
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
  // The desk's approval of the day is the engine's publish command.
  publish: 'Approval',
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

/** Who published the day, from the 026 column or else from published_by. */
export function publishSourceOf(published: PublishedRecord | null | undefined): PublishSource | null {
  if (!published) return null;
  const source = published.publish_source;
  if (source === 'desk' || source === 'fallback' || source === 'model-only') return source;
  const by = published.published_by ?? '';
  if (!by) return null;
  if (by.startsWith('system:fallback')) return 'fallback';
  if (by === 'system:model-only') return 'model-only';
  if (by.startsWith('system:')) return 'system';
  return 'desk';
}

/**
 * Whether the day is closed to desk actions: 'published' when
 * live_run_metadata says so (C3: also an engine publish with no publish row)
 * or its publish row is done; 'publishing' while an approval is pending or
 * running.
 */
export function deskLock(state: DeskState): 'published' | 'publishing' | null {
  if (state.locked === 'published' || state.published?.published_at || state.publish?.status === 'done') {
    return 'published';
  }
  if (
    state.locked === 'publishing' ||
    state.publish?.status === 'pending' ||
    state.publish?.status === 'running'
  ) {
    return 'publishing';
  }
  return null;
}

export const LOCKED_APPROVED = 'Approved';
export const LOCKED_FALLBACK = "Not approved: the model's book was sent (fallback)";
export const LOCKED_ENGINE = 'Published by the engine';
export const LOCKED_APPROVING = 'Approval in progress';

/** Why the day's book takes no more desk actions, or null. */
export function deskLockedReason(state: DeskState): string | null {
  const lock = deskLock(state);
  if (lock === 'publishing') return LOCKED_APPROVING;
  if (lock !== 'published') return null;
  const source = publishSourceOf(state.published) ?? 'desk';
  if (source === 'fallback') return LOCKED_FALLBACK;
  if (source === 'desk') return LOCKED_APPROVED;
  return LOCKED_ENGINE;
}

// --- the daily cutoff (approve by 09:30 New York; fallback at 10:00) --------

export const CUTOFF_RULE =
  "Approve by 09:30 New York. Approved books are e-mailed at 09:30. If nothing is approved by 10:00, the model's book is sent.";

/** serverTime minus the browser's clock when the answer arrived: add it to Date.now(). */
export function serverClockOffsetMs(serverTime: string | undefined | null, receivedAtMs: number): number {
  const server = serverTime ? Date.parse(serverTime) : Number.NaN;
  return Number.isFinite(server) ? server - receivedAtMs : 0;
}

/** "1h 02m 05s", "29m 59s", "0m 09s"; 0 once the moment has passed. */
export function formatCountdown(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return h > 0 ? `${h}h ${pad(m)}m ${pad(sec)}s` : `${m}m ${pad(sec)}s`;
}

/** hh:mm in New York (24-hour) of an ISO instant. */
export function newYorkTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return '';
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(at);
}

function before(nowMs: number, iso: string | undefined): boolean {
  const at = iso ? Date.parse(iso) : Number.NaN;
  return Number.isFinite(at) && nowMs < at;
}

/** Whether 10:00 New York of the book date has passed (or the book is a past day). */
export function approvalClosed(state: DeskState, nowMs?: number): boolean {
  const d = state.deadlines;
  if (!d) return false;
  if (state.date && state.date < d.today) return true;
  if (nowMs === undefined) return d.approvalClosed;
  return !before(nowMs, d.fallbackAt);
}

export type DayPhase =
  | 'awaiting-model-run'
  | 'open'
  | 'approving'
  | 'approved'
  | 'sent'
  | 'fallback'
  | 'engine';

export interface DayStatus {
  phase: DayPhase;
  title: string;
  detail: string;
  /** The instant (ms, server time) the countdown runs to, or null for none. */
  countdownTo: number | null;
  /** What the countdown counts down to, e.g. "left to approve". */
  countdownLabel: string | null;
}

/**
 * The desk's day as one of the cutoff's states, at `nowMs` on the server's
 * clock (Date.now() + serverClockOffsetMs): awaiting the model run, open,
 * approved (sends at 09:30), approved and sent, or not approved (the model's
 * book was sent at 10:00).
 */
export function deskDayStatus(state: DeskState, nowMs: number): DayStatus {
  const d = state.deadlines;
  const at = (iso: string | undefined) => (iso ? Date.parse(iso) : null);
  const status = (
    phase: DayPhase,
    title: string,
    detail: string,
    countdownTo: number | null = null,
    countdownLabel: string | null = null,
  ): DayStatus => ({
    phase,
    title,
    detail,
    countdownTo: countdownTo !== null && countdownTo > nowMs ? countdownTo : null,
    countdownLabel: countdownTo !== null && countdownTo > nowMs ? countdownLabel : null,
  });

  const today = d?.today;
  const pastDay = Boolean(state.date && today && state.date < today);
  if (!state.date || !state.seeded || pastDay) {
    const forDay = today ?? state.date ?? 'today';
    const nextApproveBy = at(pastDay || !state.date ? d?.todayApproveBy : d?.approveBy);
    return status(
      'awaiting-model-run',
      'Awaiting model run',
      `The ${forDay} model run has not seeded the QT proposal yet. Approve by 09:30 New York once it has.`,
      nextApproveBy,
      'until 09:30 New York',
    );
  }

  const lock = deskLock(state);
  if (lock === 'published') {
    const published = state.published;
    const source = publishSourceOf(published) ?? 'desk';
    const sentAt = published?.sent_at ?? null;
    const by = published?.published_by ?? 'unknown';
    if (source === 'fallback') {
      return status(
        'fallback',
        "Not approved — model book sent at 10:00 (fallback)",
        sentAt
          ? `Nothing was approved by 10:00 New York; the engine published the model's book and e-mailed it at ${newYorkTime(sentAt)}.`
          : "Nothing was approved by 10:00 New York; the engine published the model's book.",
      );
    }
    if (source === 'model-only' || source === 'system') {
      return status(
        'engine',
        sentAt ? `Published by the engine, sent at ${newYorkTime(sentAt)}` : 'Published by the engine',
        `Published by ${by}.`,
      );
    }
    if (sentAt) {
      return status('sent', `Approved and sent at ${newYorkTime(sentAt)}`, `Approved by ${by}.`);
    }
    if (before(nowMs, d?.approveBy)) {
      return status(
        'approved',
        'Approved — sends at 09:30',
        `Approved by ${by}. The day is frozen; the engine e-mails it at 09:30 New York.`,
        at(d?.approveBy),
        'until the e-mail',
      );
    }
    return status(
      'approved',
      state.sendTracked === false ? 'Approved' : 'Approved — sends at 09:30',
      state.sendTracked === false
        ? `Approved by ${by}. This database does not record when the e-mail went out (migration 026).`
        : `Approved by ${by}. Waiting for the engine to e-mail it.`,
    );
  }

  const late = d ? !before(nowMs, d.approveBy) : false;
  const detail = late
    ? "09:30 New York has passed: an approval now is e-mailed at once. At 10:00 the model's book is sent instead."
    : CUTOFF_RULE;
  if (lock === 'publishing') {
    return status('approving', 'Approving — waiting for the engine', detail);
  }
  if (!approvalClosed(state, nowMs)) {
    return status(
      'open',
      'Open — approve by 09:30',
      detail,
      at(late ? d?.fallbackAt : d?.approveBy),
      late ? "until the model's book is sent" : 'left to approve',
    );
  }

  return status(
    'fallback',
    "Not approved — model book sent at 10:00 (fallback)",
    "Nothing was approved by 10:00 New York. The engine publishes and sends the model's book; this page updates once it has.",
  );
}

/**
 * Why Approve is closed, or null. Approval is open every day, edited or
 * not, until 10:00 New York (server time `nowMs`; without it, the server's
 * view when it answered), unless the day is published or one is in progress.
 */
export function approveBlockedReason(state: DeskState, nowMs?: number): string | null {
  if (!state.date) return 'No book for today yet';
  const locked = deskLockedReason(state);
  if (locked) return locked;
  if (approvalClosed(state, nowMs)) {
    return `Approval of the ${state.date} book closed at 10:00 New York; the model's book is sent instead`;
  }
  if (!state.seeded) return 'The proposal is not seeded yet';
  return null;
}

/** @deprecated the pre-cutoff name of approveBlockedReason. */
export const publishBlockedReason = approveBlockedReason;

function closedForEdits(state: DeskState, nowMs?: number): string | null {
  return approvalClosed(state, nowMs) ? `The ${state.date} book closed at 10:00 New York` : null;
}

/** Editing the proposal: closed on a published day, while an approval is open, and from 10:00. */
export function editBlockedReason(state: DeskState, nowMs?: number): string | null {
  if (!state.seeded) return 'The proposal is not seeded yet';
  return deskLockedReason(state) ?? closedForEdits(state, nowMs);
}

/** One override request a day is in play at a time (C2); none from 10:00. */
export function overrideBlockedReason(state: DeskState, nowMs?: number): string | null {
  if (!state.seeded) return 'The proposal is not seeded yet';
  const locked = deskLockedReason(state) ?? closedForEdits(state, nowMs);
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
