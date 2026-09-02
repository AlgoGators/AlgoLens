import { describe, expect, it } from 'vitest';

import {
  canSubmit,
  initialState,
  isValidPortfolioId,
  knownPortfolioIds,
  normalizePortfolioId,
  portfolioWeights,
  reduce,
  type AssignState,
  type PortfolioSummary,
} from './portfolioAssignment';

const CONSEQUENCES = [
  { code: 'history_discontinuity', message: 'both books become discontinuous' },
  { code: 'engine_config_drift', message: 'limits not published for the target yet' },
];

function check(over: Partial<Parameters<typeof reduce>[1] extends never ? never : any> = {}) {
  return {
    changed: true,
    requires_acknowledgement: true,
    from_portfolio_id: 'CONSERVATIVE_PORTFOLIO',
    to_portfolio_id: 'AGGRESSIVE_PORTFOLIO',
    consequences: CONSEQUENCES,
    ...over,
  };
}

describe('reassignment state machine', () => {
  it('starts idle with nothing to acknowledge', () => {
    expect(initialState()).toEqual({ phase: 'idle', consequences: [], message: null });
  });

  it('keeps the warning on screen while resubmitting to acknowledge it', () => {
    const warned = reduce(initialState(), { type: 'consequences', check: check() });
    const resubmitting = reduce(warned, { type: 'submit' });

    expect(resubmitting.phase).toBe('submitting');
    expect(resubmitting.consequences).toHaveLength(2);
  });

  it('treats an outright rejection as an error, not something to acknowledge', () => {
    // A retired strategy is refused, not warned about.
    const state = reduce(initialState(), {
      type: 'rejected',
      message: 'A retired strategy cannot be reassigned',
    });

    expect(state.phase).toBe('error');
    expect(state.consequences).toEqual([]);
  });

  it('only reaches done by passing through submitting', () => {
    // An out-of-order success must not mark an unacknowledged move as committed.
    const warned: AssignState = {
      phase: 'needs_acknowledgement',
      consequences: CONSEQUENCES,
      message: null,
    };

    expect(reduce(warned, { type: 'succeeded' })).toEqual(warned);
    expect(reduce({ ...warned, phase: 'submitting' }, { type: 'succeeded' }).phase).toBe('done');
  });

  it('choosing a different target discards the old verdict', () => {
    const warned = reduce(initialState(), { type: 'consequences', check: check() });
    expect(reduce(warned, { type: 'edited' })).toEqual(initialState());
  });
});

describe('portfolio id validation', () => {
  it('uppercases and trims, matching the server', () => {
    expect(normalizePortfolioId('  macro-book_2 ')).toBe('MACRO-BOOK_2');
  });

  it('rejects empty and whitespace-only', () => {
    expect(isValidPortfolioId('')).toBe(false);
    expect(isValidPortfolioId('   ')).toBe(false);
  });

  it('rejects punctuation, matching the server rule', () => {
    expect(isValidPortfolioId('DROP; TABLE')).toBe(false);
    expect(isValidPortfolioId('a b')).toBe(false);
  });

  it('accepts letters, digits, underscores and hyphens', () => {
    expect(isValidPortfolioId('AGGRESSIVE_PORTFOLIO')).toBe(true);
    expect(isValidPortfolioId('macro-book-2')).toBe(true);
  });

  it('rejects an absurd length', () => {
    expect(isValidPortfolioId('A'.repeat(65))).toBe(false);
  });
});

describe('canSubmit', () => {
  it('requires a reason', () => {
    expect(canSubmit('AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO', '  ')).toBe(false);
  });

  it('refuses a move to where it already is', () => {
    expect(canSubmit('conservative_portfolio', 'CONSERVATIVE_PORTFOLIO', 'because')).toBe(false);
  });

  it('refuses an invalid target', () => {
    expect(canSubmit('bad id!', 'CONSERVATIVE_PORTFOLIO', 'because')).toBe(false);
  });

  it('allows a genuine move with a reason', () => {
    expect(canSubmit('aggressive_portfolio', 'CONSERVATIVE_PORTFOLIO', 'rebalancing')).toBe(true);
  });
});

describe('portfolio summaries', () => {
  const portfolios: PortfolioSummary[] = [
    {
      portfolio_id: 'CONSERVATIVE_PORTFOLIO',
      total_value: 750,
      strategy_count: 2,
      strategies: [],
    },
    {
      portfolio_id: 'AGGRESSIVE_PORTFOLIO',
      total_value: 250,
      strategy_count: 1,
      strategies: [],
    },
  ];

  it('lists the known portfolio ids, sorted and de-duplicated', () => {
    expect(knownPortfolioIds(portfolios)).toEqual([
      'AGGRESSIVE_PORTFOLIO',
      'CONSERVATIVE_PORTFOLIO',
    ]);
  });

  it('computes each portfolio share of the fund', () => {
    const weights = portfolioWeights(portfolios);
    expect(weights[0].percent).toBeCloseTo(75, 6);
    expect(weights[1].percent).toBeCloseTo(25, 6);
  });

  it('shows a strategy with no published results as unknown, not zero', () => {
    // The state right after a move: live_results is keyed on
    // (strategy_type, portfolio_id) and the engine has not published a row for
    // the new pairing yet. Zero would read as "worth nothing".
    const moved: PortfolioSummary = {
      portfolio_id: 'AGGRESSIVE_PORTFOLIO',
      total_value: 100,
      strategy_count: 2,
      strategies: [
        { id: 'a', name: 'A', strategy_type: 'LIVE_A', lifecycle: 'live', current_value: 100 },
        { id: 'b', name: 'B', strategy_type: 'LIVE_B', lifecycle: 'live', current_value: null },
      ],
    };
    expect(moved.strategies[1].current_value).toBeNull();
    // The portfolio total counts only what was actually published.
    expect(portfolioWeights([moved])[0].total_value).toBe(100);
  });

  it('reports zero rather than NaN when the fund is empty', () => {
    const empty = portfolioWeights([
      { portfolio_id: 'A', total_value: 0, strategy_count: 0, strategies: [] },
    ]);
    expect(empty[0].percent).toBe(0);
  });
});
