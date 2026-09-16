// @vitest-environment jsdom
//
// A strategy card's figures belong to one book. The card says which, and says
// when there are others to choose from.

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { StrategyList } from './StrategyList';
import type { Strategy } from '../domain/portfolio/portfolioData';

vi.mock('../adapters/react/ThemeContext', () => ({
  useTheme: () => ({ theme: 'light' }),
}));

function strategy(over: Partial<Strategy>): Strategy {
  return {
    id: 'trendfollowing',
    name: 'Trend Following',
    description: '',
    invested: 1,
    currentValue: 1,
    return: 0,
    returnPercent: 0,
    positions: [],
    historicalData: [],
    bestDay: null,
    worstDay: null,
    metrics: { sharpeRatio: null, volatility: null },
    executions: [],
    finalizedPositions: [],
    managers: [],
    lastUpdate: '',
    portfolio_id: 'CONSERVATIVE_PORTFOLIO',
    ...over,
  } as unknown as Strategy;
}

describe('the book on a strategy card', () => {
  it('names the one book a strategy is in', () => {
    render(<StrategyList strategies={[strategy({ books: ['CONSERVATIVE_PORTFOLIO'] })]} onSelectStrategy={() => {}} />);
    expect(screen.getByTestId('card-book').textContent).toBe('CONSERVATIVE_PORTFOLIO');
  });

  it('falls back to the primary when no membership list came back', () => {
    render(<StrategyList strategies={[strategy({ books: undefined })]} onSelectStrategy={() => {}} />);
    expect(screen.getByTestId('card-book').textContent).toBe('CONSERVATIVE_PORTFOLIO');
  });

  it('says how many books, and whose figures the card shows', () => {
    render(
      <StrategyList
        strategies={[strategy({ books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'] })]}
        onSelectStrategy={() => {}}
      />,
    );
    expect(screen.getByTestId('card-book').textContent).toBe(
      'In 2 books · figures for CONSERVATIVE_PORTFOLIO',
    );
  });
});
