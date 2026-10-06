// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Dashboard } from './Dashboard';
import type { PortfolioData } from '../domain/portfolio/portfolioData';

const getPortfolioData = vi.hoisted(() => vi.fn());
vi.mock('../application/portfolio/portfolioService', () => ({
  PortfolioApplicationService: { getPortfolioData, testConnectivity: vi.fn() },
}));
vi.mock('../adapters/react/ThemeContext', () => ({ useTheme: () => ({ theme: 'light' }) }));
vi.mock('../adapters/react/useAuth', () => ({ useAuth: () => ({ user: { role: 'admin', capabilities: ['manage_books', 'manage_incubation'] } }) }));
vi.mock('./Header', () => ({ Header: (p: any) => <div>
  <button onClick={p.onHomeClick}>Header Portfolio</button>
  <button onClick={p.onBuilderClick}>Header Builder</button>
  <button onClick={p.onProfileClick}>Header Profile</button>
</div> }));
vi.mock('./BottomNav', () => ({ BottomNav: () => null }));
vi.mock('./PortfolioOverview', () => ({ PortfolioOverview: () => <h1>Fund Performance</h1> }));
vi.mock('./StrategyList', () => ({ StrategyList: () => <h2>Investment Strategies</h2> }));
vi.mock('./StrategyBuilder', () => ({ StrategyBuilder: () => <h1>Strategy Selection</h1> }));
vi.mock('./ProfileScreen', () => ({ ProfileScreen: (p: any) => <div role="dialog" aria-label="Account"><button onClick={p.onClose}>Close Profile</button></div> }));
vi.mock('./AccountSettings', () => ({ AccountSettings: () => null }));
vi.mock('./PrivacySettings', () => ({ PrivacySettings: () => null }));
vi.mock('./BooksScreen', () => ({ BooksScreen: () => null }));
vi.mock('./IncubationScreen', () => ({ IncubationScreen: () => null }));
vi.mock('./NewsView', () => ({ NewsView: () => null }));
vi.mock('./StrategyDetail', () => ({ StrategyDetail: () => null }));

const flatPortfolio = {
  totalValue: 100000, totalInvested: 100000, totalReturn: 0, totalReturnPercent: 0,
  historicalData: [{ date: '2026-09-18', value: 100000 }],
  strategies: [{
    id: 'trend', name: 'Trend', description: '', dataAvailable: true,
    invested: 100000, currentValue: 100000, return: 0, returnPercent: 0,
    positions: [], historicalData: [{ date: '2026-09-18', value: 100000 }],
    bestDay: null, worstDay: null, metrics: {}, executions: [], finalizedPositions: [],
    managers: [], lastUpdate: '2026-09-18', portfolio_id: 'MACRO_BOOK', books: ['MACRO_BOOK'],
  }],
} as unknown as PortfolioData;

beforeEach(() => getPortfolioData.mockReset().mockResolvedValue(flatPortfolio));

it('does not offer a fake setup action when no strategies are available', async () => {
  getPortfolioData.mockResolvedValueOnce({ ...flatPortfolio, strategies: [] });
  render(<Dashboard onLogout={() => {}} />);
  const setup = await screen.findByRole('button', { name: 'Self-service setup unavailable' });
  expect(screen.getByRole('heading', { name: 'No Strategies Available' })).toBeTruthy();
  expect((setup as HTMLButtonElement).disabled).toBe(true);
  expect(screen.queryByRole('button', { name: 'Get Started' })).toBeNull();
  expect(screen.getByText(/Contact your fund manager/)).toBeTruthy();
});

it('keeps a flat portfolio history and strategies available', async () => {
  render(<Dashboard onLogout={() => {}} />);
  expect(await screen.findByRole('heading', { name: 'Fund Performance' })).toBeTruthy();
  expect(screen.getByRole('heading', { name: 'Investment Strategies' })).toBeTruthy();
  expect(screen.queryByRole('heading', { name: 'No Strategies Available' })).toBeNull();
});

it('renders exactly one major screen through Builder, Profile, and close', async () => {
  render(<Dashboard onLogout={() => {}} />);
  await screen.findByRole('heading', { name: 'Fund Performance' });
  fireEvent.click(screen.getByRole('button', { name: 'Header Builder' }));
  expect(screen.getByRole('heading', { name: 'Strategy Selection' })).toBeTruthy();
  expect(screen.queryByRole('heading', { name: 'Fund Performance' })).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: 'Header Profile' }));
  expect(screen.getByRole('dialog', { name: 'Account' })).toBeTruthy();
  expect(screen.queryByRole('heading', { name: 'Strategy Selection' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Close Profile' }));
  expect(screen.getByRole('heading', { name: 'Fund Performance' })).toBeTruthy();
});

it('offers a scoped retry with member-safe copy and no debug probe', async () => {
  getPortfolioData.mockRejectedValueOnce(new Error('sensitive origin detail')).mockResolvedValueOnce(flatPortfolio);
  render(<Dashboard onLogout={() => {}} />);
  expect((await screen.findByRole('alert')).textContent).toContain('Could not load portfolio data.');
  expect(document.body.textContent).not.toContain('sensitive origin detail');
  expect(screen.queryByRole('button', { name: /Debug Test/i })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  await waitFor(() => expect(getPortfolioData).toHaveBeenCalledTimes(2));
  expect(await screen.findByRole('heading', { name: 'Fund Performance' })).toBeTruthy();
});
