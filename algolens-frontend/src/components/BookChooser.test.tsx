// @vitest-environment jsdom
//
// Clicking a strategy that trades in several books asks which book to open.
// Each book is its own ledger, so opening "the strategy" without asking would
// quietly mean the primary one.

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { BookChooser } from './BookChooser';
import type { PortfolioSummary } from '../domain/portfolio/portfolioAssignment';

// A plain function, not a vi.fn spy: see StrategyDetail.test.tsx.
let portfoliosImpl: () => Promise<PortfolioSummary[]> = async () => [];
vi.mock('../infrastructure/api/portfolioApi', () => ({
  PortfolioApiService: { getPortfolios: () => portfoliosImpl() },
}));

const summary: PortfolioSummary[] = [
  {
    portfolio_id: 'AGGRESSIVE_PORTFOLIO',
    total_value: 0,
    strategy_count: 1,
    strategies: [
      { id: 'carry', name: 'Carry', strategy_type: 'LIVE_CARRY', lifecycle: 'live', current_value: null, is_primary: false },
      { id: 'trendfollowing', name: 'Trend Following', strategy_type: 'LIVE_TREND_FOLLOWING', lifecycle: 'live', current_value: 209472.66, is_primary: false },
    ],
  },
  {
    portfolio_id: 'CONSERVATIVE_PORTFOLIO',
    total_value: 0,
    strategy_count: 1,
    strategies: [
      { id: 'trendfollowing', name: 'Trend Following', strategy_type: 'LIVE_TREND_FOLLOWING', lifecycle: 'live', current_value: 523681.65, is_primary: true },
    ],
  },
];

function renderChooser(over: Partial<Parameters<typeof BookChooser>[0]> = {}) {
  const onChoose = vi.fn();
  const onClose = vi.fn();
  render(
    <BookChooser
      strategyId="trendfollowing"
      strategyName="Trend Following"
      books={['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO']}
      primary="CONSERVATIVE_PORTFOLIO"
      theme="light"
      onChoose={onChoose}
      onClose={onClose}
      {...over}
    />,
  );
  return { onChoose, onClose };
}

/** The option buttons, in order, as their visible text. */
function options(): string[] {
  const dialog = screen.getByRole('dialog');
  return within(dialog)
    .getAllByRole('button')
    .filter(b => b.getAttribute('aria-label') !== 'Close')
    .map(b => (b.textContent ?? '').replace(/\s+/g, ' ').trim());
}

beforeEach(() => {
  portfoliosImpl = async () => summary;
});

describe('asking which book', () => {
  it('is a labelled dialog naming the strategy and how many books it is in', () => {
    renderChooser();
    const dialog = screen.getByRole('dialog', { name: 'Trend Following' });
    expect(dialog.textContent).toContain('Trades in 2 books');
  });

  it('lists the primary first, marked, with each book’s own value', async () => {
    renderChooser();
    await waitFor(() =>
      expect(options()).toEqual([
        'CONSERVATIVE_PORTFOLIOprimary$523,682',
        'AGGRESSIVE_PORTFOLIO$209,473',
      ]),
    );
  });

  it('says a book has nothing in it yet rather than showing $0', async () => {
    renderChooser({ strategyId: 'carry', strategyName: 'Carry' });
    await waitFor(() => expect(options()[1]).toBe('AGGRESSIVE_PORTFOLIOnothing published yet'));
  });

  it('is usable before values arrive, and if they never do', async () => {
    portfoliosImpl = async () => { throw new Error('down'); };
    const { onChoose } = renderChooser();
    expect(options()).toEqual(['CONSERVATIVE_PORTFOLIOprimary', 'AGGRESSIVE_PORTFOLIO']);
    fireEvent.click(screen.getByText('AGGRESSIVE_PORTFOLIO'));
    expect(onChoose).toHaveBeenCalledWith('AGGRESSIVE_PORTFOLIO');
  });
});

describe('answering', () => {
  it('opens the book that was clicked', () => {
    const { onChoose, onClose } = renderChooser();
    fireEvent.click(screen.getByText('AGGRESSIVE_PORTFOLIO'));
    expect(onChoose).toHaveBeenCalledWith('AGGRESSIVE_PORTFOLIO');
    expect(onClose).not.toHaveBeenCalled();
  });

  it('puts focus on the first book, so Enter opens the primary', () => {
    renderChooser();
    expect((document.activeElement?.textContent ?? '')).toContain('CONSERVATIVE_PORTFOLIO');
  });

  it('closes on Escape, the close button, or a click outside -- never on a click inside', () => {
    const { onClose, onChoose } = renderChooser();

    fireEvent.click(screen.getByRole('dialog'));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.keyDown(window, { key: 'Escape' });
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    fireEvent.click(screen.getByRole('dialog').parentElement as HTMLElement);
    expect(onClose).toHaveBeenCalledTimes(3);
    expect(onChoose).not.toHaveBeenCalled();
  });
});
