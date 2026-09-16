// @vitest-environment jsdom
//
// A strategy row inside a book already knows its book, so clicking it opens
// the strategy there -- no question asked.

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { PortfolioGrouping } from './PortfolioGrouping';
import type { PortfolioSummary } from '../domain/portfolio/portfolioAssignment';

vi.mock('../adapters/react/ThemeContext', () => ({
  useTheme: () => ({ theme: 'light' }),
}));

const summary: PortfolioSummary[] = [
  {
    portfolio_id: 'AGGRESSIVE_PORTFOLIO',
    total_value: 209472.66,
    strategy_count: 1,
    strategies: [
      { id: 'trendfollowing', name: 'Trend Following', strategy_type: 'LIVE_TREND_FOLLOWING', lifecycle: 'live', current_value: 209472.66, is_primary: false },
    ],
  },
  {
    portfolio_id: 'CONSERVATIVE_PORTFOLIO',
    total_value: 523681.65,
    strategy_count: 2,
    strategies: [
      { id: 'trendfollowing', name: 'Trend Following', strategy_type: 'LIVE_TREND_FOLLOWING', lifecycle: 'live', current_value: 523681.65, is_primary: true },
      { id: 'meanreversion', name: 'Mean Reversion', strategy_type: 'LIVE_MEAN_REVERSION', lifecycle: 'incubating', current_value: null, mock_capital: 100000, is_primary: true },
    ],
  },
];

vi.mock('../infrastructure/api/portfolioApi', () => ({
  PortfolioApiService: { getPortfolios: async () => summary },
}));

async function expanded() {
  fireEvent.click(await screen.findByRole('button', { name: /Portfolios/ }));
}

describe('opening a strategy from its book', () => {
  it('opens the strategy on the book of the row that was clicked', async () => {
    const onOpen = vi.fn();
    render(<PortfolioGrouping onOpenStrategy={onOpen} canOpen={id => id !== 'meanreversion'} />);
    await expanded();

    fireEvent.click(screen.getByRole('button', { name: 'Open Trend Following in AGGRESSIVE_PORTFOLIO' }));
    fireEvent.click(screen.getByRole('button', { name: 'Open Trend Following in CONSERVATIVE_PORTFOLIO' }));
    expect(onOpen.mock.calls).toEqual([
      ['trendfollowing', 'AGGRESSIVE_PORTFOLIO'],
      ['trendfollowing', 'CONSERVATIVE_PORTFOLIO'],
    ]);
  });

  it('leaves a row it cannot open as plain text', async () => {
    render(<PortfolioGrouping onOpenStrategy={() => {}} canOpen={id => id !== 'meanreversion'} />);
    await expanded();
    expect(screen.getByText('Mean Reversion').closest('button')).toBeNull();
  });

  it('is plain text throughout without a handler', async () => {
    render(<PortfolioGrouping />);
    await expanded();
    expect(screen.queryByRole('button', { name: /^Open / })).toBeNull();
  });
});
