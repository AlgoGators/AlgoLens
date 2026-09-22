// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { BooksScreen } from './BooksScreen';
import { IncubationActions } from './IncubationActions';

const api = vi.hoisted(() => ({
  getBooks: vi.fn(),
  createBook: vi.fn(),
  deleteBook: vi.fn(),
  addStrategyToBook: vi.fn(),
  changeIncubation: vi.fn(),
}));
vi.mock('../infrastructure/api/portfolioApi', () => ({ PortfolioApiService: api }));
vi.mock('../adapters/react/ThemeContext', () => ({ useTheme: () => ({ theme: 'light' }) }));

const emptyBook = {
  portfolio_id: 'MACRO_BOOK', name: 'Macro', description: '', declared: true,
  strategy_count: 0, strategies: [],
};

beforeEach(() => {
  Object.values(api).forEach(mock => mock.mockReset());
  api.getBooks.mockResolvedValue([]);
});

describe('network-uncertain mutation outcomes', () => {
  it('catches a thrown book creation without retrying', async () => {
    api.createBook.mockRejectedValue(new Error('offline'));
    render(<BooksScreen />);
    await screen.findByText(/AlgoLens registry and reporting membership/i);
    fireEvent.change(screen.getByLabelText('Identifier'), { target: { value: 'MACRO_BOOK' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create book' }));
    await screen.findByRole('alert');
    expect(screen.getByRole('alert').textContent).toMatch(/outcome is uncertain/i);
    expect(api.createBook).toHaveBeenCalledTimes(1);
  });

  it('catches a thrown book deletion without retrying', async () => {
    api.getBooks.mockResolvedValue([emptyBook]);
    api.deleteBook.mockRejectedValue(new Error('offline'));
    render(<BooksScreen />);
    fireEvent.click(await screen.findByRole('button', { name: 'Delete MACRO_BOOK' }));
    await screen.findByRole('alert');
    expect(screen.getByRole('alert').textContent).toMatch(/outcome is uncertain/i);
    expect(api.deleteBook).toHaveBeenCalledTimes(1);
  });

  it('catches a thrown incubation transition and keeps the decision open', async () => {
    api.changeIncubation.mockRejectedValue(new Error('offline'));
    render(
      <IncubationActions
        strategyId="trend" strategyName="Trend" daysElapsed={20} windowDays={30}
        theme="light" onChanged={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Mark live in AlgoLens' }));
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'reviewed' } });
    fireEvent.click(screen.getByRole('button', { name: 'Mark live' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/outcome is uncertain/i));
    expect(screen.getByText('Mark Trend live in AlgoLens')).toBeTruthy();
    expect(api.changeIncubation).toHaveBeenCalledTimes(1);
  });

  it('keeps a pending incubation transition single-flight and non-dismissible', () => {
    api.changeIncubation.mockReturnValue(new Promise(() => undefined));
    render(
      <IncubationActions
        strategyId="trend" strategyName="Trend" daysElapsed={30} windowDays={30}
        theme="light" onChanged={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Mark live in AlgoLens' }));
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'reviewed' } });

    const submit = screen.getByRole('button', { name: 'Mark live' });
    fireEvent.click(submit);
    fireEvent.click(submit);

    expect(api.changeIncubation).toHaveBeenCalledTimes(1);
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Cancel' }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('registry and runtime boundaries', () => {
  it('states that registry changes are not immediate but can block next publication', async () => {
    render(<BooksScreen />);
    expect(await screen.findByText(/AlgoLens registry and reporting membership/i)).toBeTruthy();
    expect(screen.getByText(/do not immediately start or stop a process/i)).toBeTruthy();
    expect(screen.getByText(/can block the next engine publication/i)).toBeTruthy();
  });

  it('states that marking a strategy live is not immediate and needs next-run approval', () => {
    render(
      <IncubationActions
        strategyId="trend" strategyName="Trend" daysElapsed={30} windowDays={30}
        theme="light" onChanged={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Mark live in AlgoLens' }));
    expect(screen.getByText(/does not immediately enable the trading engine or deploy capital/i)).toBeTruthy();
    expect(screen.getByText(/can block the next engine publication/i)).toBeTruthy();
  });

  it('states that marking a strategy retired is not immediate and needs next-run approval', () => {
    render(
      <IncubationActions
        strategyId="trend" strategyName="Trend" daysElapsed={30} windowDays={30}
        theme="light" onChanged={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Mark retired in AlgoLens' }));
    expect(screen.getByText(/does not immediately stop or disable the trading engine/i)).toBeTruthy();
    expect(screen.getByText(/can block the next engine publication/i)).toBeTruthy();
  });
});
