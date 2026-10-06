import { describe, expect, it } from 'vitest';

import { bookChoices, distinctBooks } from './bookChoices';
import type { PortfolioSummary } from './portfolioAssignment';

const portfolios: PortfolioSummary[] = [
  {
    portfolio_id: 'AGGRESSIVE_PORTFOLIO',
    total_value: 528482,
    strategy_count: 2,
    strategies: [
      { id: 'trendfollowing', name: 'Trend Following', strategy_type: 'LIVE_TREND_FOLLOWING', lifecycle: 'live', current_value: 209472.66, is_primary: false },
      { id: 'carry', name: 'Carry', strategy_type: 'LIVE_CARRY', lifecycle: 'live', current_value: null, is_primary: false },
    ],
  },
  {
    portfolio_id: 'CONSERVATIVE_PORTFOLIO',
    total_value: 778027,
    strategy_count: 3,
    strategies: [
      { id: 'trendfollowing', name: 'Trend Following', strategy_type: 'LIVE_TREND_FOLLOWING', lifecycle: 'live', current_value: 523681.65, is_primary: true },
      { id: 'carry', name: 'Carry', strategy_type: 'LIVE_CARRY', lifecycle: 'live', current_value: 254345, is_primary: true },
      { id: 'meanreversion', name: 'Mean Reversion', strategy_type: 'LIVE_MEAN_REVERSION', lifecycle: 'incubating', current_value: null, mock_capital: 100000, is_primary: true },
    ],
  },
];

describe('distinct books', () => {
  it('does not count one book spelled two ways as two', () => {
    expect(distinctBooks(['base_portfolio', 'BASE_PORTFOLIO'])).toEqual(['base_portfolio']);
  });

  it('treats a missing list as no books', () => {
    expect(distinctBooks(undefined)).toEqual([]);
  });
});

describe('what to offer', () => {
  it('puts the primary first, then the rest alphabetically', () => {
    const ids = bookChoices(
      'trendfollowing',
      ['ZETA_BOOK', 'AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'],
      'CONSERVATIVE_PORTFOLIO',
    ).map(c => [c.portfolioId, c.isPrimary]);
    expect(ids).toEqual([
      ['CONSERVATIVE_PORTFOLIO', true],
      ['AGGRESSIVE_PORTFOLIO', false],
      ['ZETA_BOOK', false],
    ]);
  });

  it('carries each book its own value for this strategy', () => {
    const choices = bookChoices(
      'trendfollowing',
      ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'],
      'CONSERVATIVE_PORTFOLIO',
      portfolios,
    );
    expect(choices.map(c => [c.portfolioId, c.currentValue])).toEqual([
      ['CONSERVATIVE_PORTFOLIO', 523681.65],
      ['AGGRESSIVE_PORTFOLIO', 209472.66],
    ]);
  });

  it('says a book has nothing published rather than inventing zero', () => {
    const [, aggressive] = bookChoices(
      'carry',
      ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'],
      'CONSERVATIVE_PORTFOLIO',
      portfolios,
    );
    expect(aggressive.portfolioId).toBe('AGGRESSIVE_PORTFOLIO');
    expect(aggressive.currentValue).toBeNull();
  });

  it('leaves the value unknown when the summary has not loaded', () => {
    const choices = bookChoices('carry', ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'], 'CONSERVATIVE_PORTFOLIO', null);
    expect(choices.every(c => c.currentValue === undefined)).toBe(true);
  });

  it('reports mock capital for an incubating strategy, never a fund value', () => {
    const [choice] = bookChoices('meanreversion', ['CONSERVATIVE_PORTFOLIO'], 'CONSERVATIVE_PORTFOLIO', portfolios);
    expect(choice.mockCapital).toBe(100000);
    expect(choice.currentValue).toBeUndefined();
  });

  it('matches book names without regard to case', () => {
    const [choice] = bookChoices('trendfollowing', ['conservative_portfolio'], 'CONSERVATIVE_PORTFOLIO', portfolios);
    expect(choice.isPrimary).toBe(true);
    expect(choice.currentValue).toBe(523681.65);
  });
});
