// @vitest-environment jsdom

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { BooksScreen } from './BooksScreen';

const api = vi.hoisted(() => ({
  getBooks: vi.fn(), createBook: vi.fn(), deleteBook: vi.fn(),
  addStrategyToBook: vi.fn(), changeIncubation: vi.fn(),
  getLifecycleHistory: vi.fn(), getAssignmentHistory: vi.fn(),
}));
vi.mock('../infrastructure/api/portfolioApi', () => ({ PortfolioApiService: api }));
vi.mock('../adapters/react/ThemeContext', () => ({ useTheme: () => ({ theme: 'light' }) }));

const book = (lifecycle: string) => ({
  portfolio_id: 'BOOK_A', name: 'Book A', description: '', declared: true,
  strategy_count: 1,
  strategies: [{
    id: 'trend', name: 'Trend', strategy_type: 'TREND', lifecycle, is_primary: true,
  }],
});

beforeEach(() => {
  Object.values(api).forEach(mock => mock.mockReset());
  api.getLifecycleHistory.mockResolvedValue([]);
  api.getAssignmentHistory.mockResolvedValue([]);
});

describe('Books lifecycle completion', () => {
  it('shows retired rows and refreshes the registry after restarting incubation', async () => {
    api.getBooks.mockResolvedValueOnce([book('retired')]).mockResolvedValue([book('incubating')]);
    api.changeIncubation.mockResolvedValue({ outcome: 'ok' });
    render(<BooksScreen />);

    fireEvent.click(await screen.findByRole('button', { name: 'Restart incubation for Trend' }));
    fireEvent.change(screen.getByLabelText('Mock capital'), { target: { value: '50000' } });
    fireEvent.change(screen.getByLabelText('Lifecycle reason'), { target: { value: 'second trial' } });
    fireEvent.click(screen.getByRole('button', { name: 'Start incubation' }));

    await waitFor(() => expect(api.getBooks).toHaveBeenCalledTimes(2));
    expect(api.changeIncubation).toHaveBeenCalledWith(
      'trend', 'start', { mock_capital: 50000, reason: 'second trial' },
    );
    expect(await screen.findByText(/· incubating/i)).toBeTruthy();
  });

  it('exposes both audit histories from the registry row', async () => {
    api.getBooks.mockResolvedValue([book('retired')]);
    render(<BooksScreen />);
    fireEvent.click(await screen.findByRole('button', { name: 'Show history for Trend' }));

    await waitFor(() => expect(api.getLifecycleHistory).toHaveBeenCalledWith('trend'));
    expect(api.getAssignmentHistory).toHaveBeenCalledWith('trend');
    expect(screen.getByRole('heading', { name: 'Lifecycle history' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Membership history' })).toBeTruthy();
  });
});
