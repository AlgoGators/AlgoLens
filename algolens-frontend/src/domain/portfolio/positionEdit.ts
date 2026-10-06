/**
 * Pure logic behind the position editor.
 *
 * Kept free of React and fetch so the acknowledge-once rule can be tested
 * directly. That rule is the reason the risk gate has any teeth: the backend
 * answers a breaching write with 409, and the user must take a second,
 * deliberate action before it goes through. A component that resubmitted
 * automatically would satisfy every visual review and quietly disable the gate.
 *
 * Ported from AlgoLens PR #32, closed August 2026 on a miscommunication.
 */

import { parseFixedDecimal8 } from '../numbers/fixedDecimal8';

export type ExistingPositionValue = {
  quantity: number;
  average_price: number | null;
  quantity_exact?: string;
  average_price_exact?: string | null;
};

/** Canonicalize accepted form spellings with decimal text only. */
export function normalizeDecimal8Input(value: string): string {
  const input = value.trim();
  if (input.length === 0 || input.length > 128) throw new Error('invalid_fixed_decimal8');
  const match = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d{1,4}))?$/.exec(input);
  if (!match) throw new Error('invalid_fixed_decimal8');
  const exponent = match[5] === undefined ? 0 : parseInt(match[5], 10);
  if (exponent < -1000 || exponent > 1000) throw new Error('invalid_fixed_decimal8');

  const integerPart = match[2] ?? '0';
  const rawDigits = integerPart + (match[3] ?? match[4] ?? '');
  if (!/[1-9]/.test(rawDigits)) return parseFixedDecimal8('0');
  const leading = rawDigits.search(/[1-9]/);
  const digits = rawDigits.slice(leading);
  const point = integerPart.length + exponent - leading;
  if (point > 11 || point < -8) throw new Error('invalid_fixed_decimal8');
  const integer = point <= 0 ? '0' : digits.slice(0, point).padEnd(point, '0');
  const fraction = point <= 0 ? '0'.repeat(-point) + digits : digits.slice(point);
  const significantFraction = fraction.replace(/0+$/, '');
  if (significantFraction.length > 8) throw new Error('invalid_fixed_decimal8');
  const canonical = `${match[1] === '-' ? '-' : ''}${integer}${significantFraction ? `.${significantFraction}` : ''}`;
  return parseFixedDecimal8(canonical);
}

/** A present invalid companion never becomes a rounded legacy number. */
export function positionValueEvidence(existing: ExistingPositionValue): {
  valid: boolean; quantity: string; averagePrice: string;
} {
  let quantity = String(existing.quantity);
  let averagePrice = existing.average_price == null ? '' : String(existing.average_price);
  try {
    if (existing.quantity_exact !== undefined) {
      quantity = parseFixedDecimal8(existing.quantity_exact);
    }
    if (existing.average_price_exact !== undefined) {
      if (existing.average_price_exact === null) {
        if (existing.average_price !== null) throw new Error('invalid_position_evidence');
        averagePrice = '';
      } else {
        if (existing.average_price === null) throw new Error('invalid_position_evidence');
        averagePrice = parseFixedDecimal8(existing.average_price_exact);
        if (averagePrice.startsWith('-')) throw new Error('invalid_position_evidence');
      }
    }
    return { valid: true, quantity, averagePrice };
  } catch {
    return { valid: false, quantity: 'Invalid position evidence', averagePrice: '' };
  }
}

export type RiskBreach = {
  limit: string;
  limit_value: number;
  actual: number;
  message: string;
};

export type RiskCheck = {
  evaluated: boolean;
  passed: boolean;
  breaches: RiskBreach[];
};

export type SubmitPhase =
  | 'idle'
  | 'submitting'
  | 'needs_acknowledgement'
  | 'needs_book'
  | 'error'
  | 'done';

export type SubmitState = {
  phase: SubmitPhase;
  breaches: RiskBreach[];
  /** The books to choose between when the server could not pick one. */
  books: string[];
  message: string | null;
};

export type SubmitEvent =
  | { type: 'submit' }
  | { type: 'breach'; risk_check: RiskCheck }
  | { type: 'ambiguous'; books: string[] }
  | { type: 'rejected'; message: string }
  | { type: 'succeeded' }
  | { type: 'edited' };

export function initialState(): SubmitState {
  return { phase: 'idle', breaches: [], books: [], message: null };
}

export function reduce(state: SubmitState, event: SubmitEvent): SubmitState {
  switch (event.type) {
    case 'submit':
      // Deliberately preserves `breaches`: when the user is resubmitting to
      // acknowledge a breach, the banner must stay on screen rather than
      // flickering away and reappearing.
      return { ...state, phase: 'submitting', message: null };

    case 'breach':
      return {
        phase: 'needs_acknowledgement',
        breaches: event.risk_check.breaches,
        books: [],
        message: null,
      };

    case 'ambiguous':
      // The write did not happen. The server could not tell which book the
      // edit was for and returned the candidates instead of guessing; the
      // form must ask before it resubmits.
      return { phase: 'needs_book', breaches: [], books: event.books, message: null };

    case 'rejected':
      // NOT acknowledgeable. This is the other 409 (and 400/403/500): the write
      // is refused outright, so there is nothing for the user to override.
      return { phase: 'error', breaches: [], books: [], message: event.message };

    case 'succeeded':
      // Only transition to done from submitting. If this event arrived out of
      // order (e.g. a duplicated success from a stale promise), ignore it.
      // This enforces the acknowledge-once rule at the machine level: reaching
      // done must always pass through submitting, so an out-of-order success
      // cannot mark a breaching write as committed.
      if (state.phase === 'submitting') {
        return { phase: 'done', breaches: [], books: [], message: null };
      }
      return state;

    case 'edited':
      // Any change to the form invalidates a verdict computed from the old
      // values. Falling back to idle forces a fresh check.
      return initialState();

    default: {
      // If a new SubmitEvent variant is added without a branch above, this line
      // stops compiling -- a build error rather than an undefined state at runtime.
      const _exhaustive: never = event;
      return state;
    }
  }
}

export function canSubmit(reason: string, quantity: string): boolean {
  if (reason.trim().length === 0) return false;
  if (quantity.trim().length === 0) return false;
  try { normalizeDecimal8Input(quantity); return true; } catch { return false; }
}

/** Blank preserves the existing basis; a supplied price must survive JSON as itself. */
export function isValidAveragePrice(value: string): boolean {
  if (value.trim() === '') return true;
  try { return !normalizeDecimal8Input(value).startsWith('-'); } catch { return false; }
}

export type DiffLine = { field: string; from: string; to: string };

export function buildDiff(
  before: ExistingPositionValue | null,
  after: { quantity: string | number; average_price: string | number | null },
): DiffLine[] {
  const lines: DiffLine[] = [];

  const evidence = before ? positionValueEvidence(before) : null;
  if (evidence && !evidence.valid) throw new Error('invalid_position_evidence');
  const beforeQty = evidence ? normalizeDecimal8Input(evidence.quantity) : '-';
  const nextQty = normalizeDecimal8Input(String(after.quantity));
  const afterQty = nextQty === '0' ? '0 (closing)' : nextQty;
  if (!before || beforeQty !== nextQty) {
    lines.push({ field: 'Quantity', from: beforeQty, to: afterQty });
  }

  const bp = evidence?.averagePrice ? normalizeDecimal8Input(evidence.averagePrice) : null;
  // A blank price field means "leave it alone", not "set it to nothing" --
  // the backend only overwrites average_price when a value is present, so
  // omitting the line when after.average_price is null is correct.
  const nextPrice = after.average_price === null ? null : normalizeDecimal8Input(String(after.average_price));
  if (nextPrice !== null && bp !== nextPrice) {
    lines.push({
      field: 'Average price',
      from: bp === null ? '-' : String(bp),
      to: nextPrice,
    });
  }

  return lines;
}
