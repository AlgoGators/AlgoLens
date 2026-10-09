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
  published: { published_by: string | null; published_at: string | null } | null;
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
}

export const MAX_ABS_CONTRACTS = 100_000;
export const POLL_INTERVAL_MS = 2_000;
export const POLL_TIMEOUT_MS = 5 * 60_000;

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
    changes.push({ symbol, quantity: parsed.value });
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

/** Keep polling a command row every 2 s until it is final or 5 min have passed. */
export function shouldKeepPolling(
  status: CommandStatus | undefined | null,
  startedAtMs: number,
  nowMs: number,
): boolean {
  return !isFinal(status) && nowMs - startedAtMs < POLL_TIMEOUT_MS;
}

const KIND_NAMES: Record<CommandKind, string> = {
  save: 'Save',
  override_request: 'Override request',
  override_decision: 'Override decision',
  publish: 'Publish',
};

/** One plain sentence for a command row's state; refusals and failures say why. */
export function describeCommand(command: DeskCommand | null, timedOut = false): string {
  if (!command) return '';
  const kind = KIND_NAMES[command.kind] ?? command.kind;
  const why = command.message ? `: ${command.message}` : '';
  switch (command.status) {
    case 'pending':
      return timedOut
        ? `${kind} is still waiting for the engine after 5 minutes. It stays queued; the engine picks pending commands up every minute.`
        : `${kind} sent; waiting for the engine`;
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

/** Publishing is open every day, edited or not, unless one is queued or done. */
export function publishBlockedReason(state: DeskState): string | null {
  if (!state.date) return 'No book for today yet';
  if (state.publish?.status === 'done') return 'Published';
  if (state.publish && (state.publish.status === 'pending' || state.publish.status === 'running')) {
    return 'Publish in progress';
  }
  return null;
}

/** Approval links carry the token in the query string: /qt/approve?token=... */
export function approvalTokenFrom(search: string): string | null {
  const token = new URLSearchParams(search).get('token');
  return token && token.trim() ? token.trim() : null;
}
