/**
 * Pure logic behind reassigning a strategy to another portfolio.
 *
 * Same shape as positionEdit.ts, and for the same reason: moving a live
 * strategy between portfolios is not a neutral edit. Both portfolios' histories
 * become discontinuous at the move, which silently corrupts every number
 * computed across that boundary — cumulative return, drawdown, and the
 * qt/system/benchmark attribution.
 *
 * So the backend answers an unacknowledged move with 409 and the consequences,
 * and the user must take a second, deliberate action. A component that
 * resubmitted automatically would satisfy every visual review and quietly
 * remove the only thing standing between a mis-click and a corrupted book.
 */

export type AssignmentConsequence = {
  code: string;
  message: string;
};

export type AssignmentCheck = {
  changed: boolean;
  requires_acknowledgement: boolean;
  from_portfolio_id: string | null;
  to_portfolio_id: string;
  consequences: AssignmentConsequence[];
};

export type AssignPhase =
  | 'idle'
  | 'submitting'
  | 'needs_acknowledgement'
  | 'error'
  | 'done';

export type AssignState = {
  phase: AssignPhase;
  consequences: AssignmentConsequence[];
  message: string | null;
};

export type AssignEvent =
  | { type: 'submit' }
  | { type: 'consequences'; check: AssignmentCheck }
  | { type: 'rejected'; message: string }
  | { type: 'succeeded' }
  | { type: 'edited' };

export function initialState(): AssignState {
  return { phase: 'idle', consequences: [], message: null };
}

export function reduce(state: AssignState, event: AssignEvent): AssignState {
  switch (event.type) {
    case 'submit':
      // Keeps `consequences`: when the user resubmits to acknowledge, the
      // warning must stay on screen rather than flickering away.
      return { ...state, phase: 'submitting', message: null };

    case 'consequences':
      return {
        phase: 'needs_acknowledgement',
        consequences: event.check.consequences,
        message: null,
      };

    case 'rejected':
      // NOT acknowledgeable — a retired strategy, a bad id, a server error.
      // There is nothing for the user to override.
      return { phase: 'error', consequences: [], message: event.message };

    case 'succeeded':
      // Only reach done from submitting, so an out-of-order success from a
      // stale promise cannot mark an unacknowledged move as committed.
      if (state.phase === 'submitting') {
        return { phase: 'done', consequences: [], message: null };
      }
      return state;

    case 'edited':
      // Picking a different target portfolio invalidates a verdict computed
      // for the old one.
      return initialState();

    default: {
      const _exhaustive: never = event;
      return state;
    }
  }
}

/** Client-side mirror of the server rule, so the button can be disabled early. */
export function normalizePortfolioId(raw: string): string {
  return raw.trim().toUpperCase();
}

export function isValidPortfolioId(raw: string): boolean {
  const id = normalizePortfolioId(raw);
  if (id.length === 0 || id.length > 64) return false;
  return /^[A-Z0-9_-]+$/.test(id);
}

export function canSubmit(target: string, currentPortfolioId: string, reason: string): boolean {
  if (!isValidPortfolioId(target)) return false;
  // Moving somewhere it already is does nothing.
  if (normalizePortfolioId(target) === currentPortfolioId) return false;
  // A move with no stated reason is indistinguishable from an accident when
  // read back months later — same rule the position editor applies.
  return reason.trim().length > 0;
}

export type PortfolioSummary = {
  portfolio_id: string;
  total_value: number;
  strategy_count: number;
  strategies: {
    id: string;
    name: string;
    strategy_type: string;
    lifecycle: string;
    /** null when the engine has published nothing for this (strategy, portfolio). */
    current_value: number | null;
    /** Trial size when incubating. Never counted toward a book total. */
    mock_capital?: number | null;
    /** true for the book the engine reads where a single answer is needed. */
    is_primary?: boolean;
  }[];
};

/** Every portfolio currently in use, for the picker. Sorted, de-duplicated. */
export function knownPortfolioIds(portfolios: PortfolioSummary[]): string[] {
  return Array.from(new Set(portfolios.map(p => p.portfolio_id))).sort();
}

/** What share of the whole fund each portfolio represents. */
export function portfolioWeights(
  portfolios: PortfolioSummary[],
): { portfolio_id: string; total_value: number; percent: number }[] {
  const total = portfolios.reduce((sum, p) => sum + p.total_value, 0);
  return portfolios.map(p => ({
    portfolio_id: p.portfolio_id,
    total_value: p.total_value,
    // A zero-value fund would make every share NaN; report 0 instead.
    percent: total > 0 ? (p.total_value / total) * 100 : 0,
  }));
}
