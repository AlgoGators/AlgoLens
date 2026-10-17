import { describe, expect, it } from 'vitest';
import {
  BOOK_TOGGLE_OPTIONS,
  describeBookLoadError,
  activeToggleBook,
  bookQuery,
  deskGroups,
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

describe('describeBookLoadError', () => {
  it('explains a portfolio with no run yet', () => {
    expect(describeBookLoadError('API request failed: 404 NOT FOUND. Body: {}')).toMatch(/No run has written/);
  });

  it('says a named book has no rows instead of showing another book (D-37)', () => {
    const message = 'API request failed: 404 NOT FOUND. Body: {"error":"X has no qt rows","missingBook":"qt"}';
    expect(describeBookLoadError(message)).toBe(
      'This portfolio has no QT book: no run has written QT rows for it. Its numbers are on System.',
    );
  });

  it('passes other failures through', () => {
    expect(describeBookLoadError('API request failed: 500')).toBe('Could not load this book: API request failed: 500');
  });
});

describe('deskGroups', () => {
  it('keeps only the groups holding a desk-edited portfolio, twin included', () => {
    const qt: PortfolioGroup = {
      group: 'qt_conservative',
      grouped: true,
      portfolios: [
        entry({ portfolio_id: 'QT', portfolio_group: 'qt_conservative', desk_editable: true }),
        entry({ portfolio_id: 'QTM', portfolio_group: 'qt_conservative' }),
      ],
    };
    const plain: PortfolioGroup = { group: 'P', grouped: false, portfolios: [entry({})] };
    expect(deskGroups([plain, qt])).toEqual([qt]);
    expect(deskGroups([plain])).toEqual([]);
  });
});
