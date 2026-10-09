import { describe, expect, it } from 'vitest';
import {
  BOOK_TOGGLE_OPTIONS,
  activeToggleBook,
  bookQuery,
  findPortfolio,
  switcherLabel,
  type PortfolioEntry,
  type PortfolioGroup,
} from './portfolioRegistry';

const entry = (over: Partial<PortfolioEntry>): PortfolioEntry => ({
  portfolio_id: 'P',
  id: 'p',
  name: 'P',
  description: '',
  strategy_type: 'LIVE_TREND_FOLLOWING',
  asset_class: 'futures',
  portfolio_group: null,
  desk_editable: false,
  ...over,
});

describe('book toggle', () => {
  it('offers system, qt_proposal and qt in that order', () => {
    expect(BOOK_TOGGLE_OPTIONS.map(o => o.book)).toEqual(['system', 'qt_proposal', 'qt']);
  });

  it('highlights the served book until the user picks one', () => {
    expect(activeToggleBook(null, 'qt')).toBe('qt');
    expect(activeToggleBook(null, 'system')).toBe('system');
    expect(activeToggleBook(null, undefined)).toBe('qt');
    expect(activeToggleBook(null, 'weird')).toBe('qt');
  });

  it('highlights the pick once made, whatever was served', () => {
    expect(activeToggleBook('qt_proposal', 'system')).toBe('qt_proposal');
  });

  it('asks the API for the default book without a query', () => {
    expect(bookQuery(null)).toBe('');
    expect(bookQuery('qt_proposal')).toBe('?book=qt_proposal');
  });
});

describe('switcher', () => {
  const groups: PortfolioGroup[] = [
    { group: 'C', grouped: false, portfolios: [entry({ portfolio_id: 'C', name: 'Trend' })] },
    {
      group: 'qt_conservative',
      grouped: true,
      portfolios: [
        entry({ portfolio_id: 'QT', name: 'QT TF', portfolio_group: 'qt_conservative', desk_editable: true }),
        entry({ portfolio_id: 'QTM', name: 'QT TF (model)', portfolio_group: 'qt_conservative' }),
      ],
    },
  ];

  it('finds a portfolio by id across groups', () => {
    expect(findPortfolio(groups, 'QTM')?.name).toBe('QT TF (model)');
    expect(findPortfolio(groups, 'nope')).toBeNull();
    expect(findPortfolio(groups, null)).toBeNull();
  });

  it('marks the desk book', () => {
    expect(switcherLabel(groups[1].portfolios[0])).toBe('QT TF (desk)');
    expect(switcherLabel(groups[1].portfolios[1])).toBe('QT TF (model)');
    expect(switcherLabel(groups[0].portfolios[0])).toBe('Trend');
  });
});
