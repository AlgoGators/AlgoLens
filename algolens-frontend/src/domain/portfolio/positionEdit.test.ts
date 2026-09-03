import { describe, expect, it } from 'vitest';

import {
  buildDiff,
  canSubmit,
  initialState,
  reduce,
  type SubmitState,
} from './positionEdit';

describe('submit state machine', () => {
  it('starts idle with nothing to acknowledge', () => {
    expect(initialState()).toEqual({ phase: 'idle', breaches: [], books: [], message: null });
  });

  it('keeps the breach banner on screen while resubmitting to acknowledge it', () => {
    const breached = reduce(initialState(), {
      type: 'breach',
      risk_check: {
        evaluated: true,
        passed: false,
        breaches: [
          { limit: 'max_gross_notional', limit_value: 1, actual: 2, message: 'over' },
        ],
      },
    });

    const resubmitting = reduce(breached, { type: 'submit' });

    expect(resubmitting.phase).toBe('submitting');
    expect(resubmitting.breaches).toHaveLength(1);
  });

  it('treats an outright rejection as an error, not something to acknowledge', () => {
    const state = reduce(initialState(), {
      type: 'rejected',
      message: 'Strategy not found',
    });

    expect(state.phase).toBe('error');
    expect(state.breaches).toEqual([]);
  });

  it('only reaches done by passing through submitting', () => {
    // The acknowledge-once rule at the machine level: an out-of-order success
    // from a stale promise must not mark a breaching write as committed.
    const breached: SubmitState = {
      phase: 'needs_acknowledgement',
      books: [],
      breaches: [
        { limit: 'max_gross_notional', limit_value: 1, actual: 2, message: 'over' },
      ],
      message: null,
    };

    expect(reduce(breached, { type: 'succeeded' })).toEqual(breached);
    expect(reduce({ ...breached, phase: 'submitting' }, { type: 'succeeded' }).phase).toBe(
      'done',
    );
  });

  it('editing the form discards a verdict computed from the old values', () => {
    const breached = reduce(initialState(), {
      type: 'breach',
      risk_check: {
        evaluated: true,
        passed: false,
        breaches: [
          { limit: 'max_gross_notional', limit_value: 1, actual: 2, message: 'over' },
        ],
      },
    });

    expect(reduce(breached, { type: 'edited' })).toEqual(initialState());
  });
});

describe('ambiguous book', () => {
  it('holds the candidate books and waits for a choice', () => {
    const asked = reduce(reduce(initialState(), { type: 'submit' }), {
      type: 'ambiguous',
      books: ['CONSERVATIVE_PORTFOLIO', 'MACRO_BOOK'],
    });

    expect(asked.phase).toBe('needs_book');
    expect(asked.books).toEqual(['CONSERVATIVE_PORTFOLIO', 'MACRO_BOOK']);
    expect(asked.breaches).toEqual([]);
  });

  it('is not an error: nothing was written, so nothing is reported as refused', () => {
    const asked = reduce(initialState(), { type: 'ambiguous', books: ['A', 'B'] });
    expect(asked.message).toBeNull();
  });

  it('resubmitting with a chosen book passes through submitting before done', () => {
    const asked = reduce(initialState(), { type: 'ambiguous', books: ['A', 'B'] });

    // An out-of-order success while still asking must not commit anything.
    expect(reduce(asked, { type: 'succeeded' }).phase).toBe('needs_book');

    const resubmitting = reduce(asked, { type: 'submit' });
    expect(resubmitting.phase).toBe('submitting');
    expect(reduce(resubmitting, { type: 'succeeded' }).phase).toBe('done');
  });

  it('a breach after choosing a book replaces the question with the warning', () => {
    const asked = reduce(initialState(), { type: 'ambiguous', books: ['A', 'B'] });
    const breached = reduce(reduce(asked, { type: 'submit' }), {
      type: 'breach',
      risk_check: {
        evaluated: true,
        passed: false,
        breaches: [{ limit: 'max_symbol_notional', limit_value: 1, actual: 2, message: 'over' }],
      },
    });
    expect(breached.phase).toBe('needs_acknowledgement');
    expect(breached.books).toEqual([]);
  });

  it('editing a field after the question forgets the candidates', () => {
    const asked = reduce(initialState(), { type: 'ambiguous', books: ['A', 'B'] });
    expect(reduce(asked, { type: 'edited' })).toEqual(initialState());
  });
});

describe('canSubmit', () => {
  it('requires a reason', () => {
    expect(canSubmit('   ', '3')).toBe(false);
  });

  it('requires a quantity', () => {
    expect(canSubmit('rolling', '  ')).toBe(false);
  });

  it('rejects a non-numeric quantity', () => {
    expect(canSubmit('rolling', 'three')).toBe(false);
  });

  it('accepts zero, which closes the position', () => {
    expect(canSubmit('flattening', '0')).toBe(true);
  });

  it('accepts a negative quantity, which is a short', () => {
    expect(canSubmit('going short', '-2')).toBe(true);
  });
});

describe('buildDiff', () => {
  it('shows a new position as having no previous quantity', () => {
    expect(buildDiff(null, { quantity: 3, average_price: null })).toEqual([
      { field: 'Quantity', from: '-', to: '3' },
    ]);
  });

  it('labels a zero quantity as closing', () => {
    const lines = buildDiff({ quantity: 4, average_price: null }, {
      quantity: 0,
      average_price: null,
    });
    expect(lines[0].to).toBe('0 (closing)');
  });

  it('omits quantity when it is unchanged', () => {
    const lines = buildDiff({ quantity: 3, average_price: 100 }, {
      quantity: 3,
      average_price: 100,
    });
    expect(lines).toEqual([]);
  });

  it('omits average price when the field was left blank', () => {
    // Blank means "leave it alone", not "set it to nothing": the backend only
    // overwrites average_price when a value is present.
    const lines = buildDiff({ quantity: 3, average_price: 100 }, {
      quantity: 5,
      average_price: null,
    });
    expect(lines.map(l => l.field)).toEqual(['Quantity']);
  });

  it('shows an average price that is being set for the first time', () => {
    const lines = buildDiff({ quantity: 3, average_price: null }, {
      quantity: 3,
      average_price: 4200,
    });
    expect(lines).toEqual([{ field: 'Average price', from: '-', to: '4200' }]);
  });
});
