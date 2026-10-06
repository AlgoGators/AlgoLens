// @vitest-environment jsdom
import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { IncubationDetail } from './IncubationDetail';
import type { IncubatingStrategy } from '../domain/portfolio/incubationData';

vi.mock('../adapters/react/ThemeContext', () => ({ useTheme: () => ({ theme: 'light' }) }));
let role: string | undefined = 'general_member';
let userId = 'issue84-reader';
vi.mock('../adapters/react/useAuth', () => ({
  useAuth: () => ({ user: { id: userId, role } }),
}));

const equity: IncubatingStrategy = {
  id: 'inc_meanrev', name: 'Equity Mean Reversion',
  strategy_type: 'LIVE_EQUITY_MEAN_REVERSION', portfolio_id: 'EQUITY_MR_PORTFOLIO',
  mock_capital: 100000, incubation_started_at: '2026-09-01', days_elapsed: 25, window_days: 90,
};
const reply = (portfolioId = 'EQUITY_MR_PORTFOLIO', reason = 'not_published') => new Response(JSON.stringify({
  api_version: 1, scope: { registry_id: 'inc_meanrev', portfolio_id: portfolioId },
  read_at: '2026-09-26T12:00:00Z', status: 'unavailable', reason, publication: null,
}), { headers: { 'Content-Type': 'application/json' } });
const detail = (strategy = equity, isLoading = false, error: string | null = null) =>
  <IncubationDetail strategy={strategy} performance={{ equity_curve: [], positions: [
    { date: '2026-09-25', symbol: 'AAPL', quantity: 1.25, entry_price: 200 },
  ] }} isLoading={isLoading} error={error} onBack={() => {}} onLifecycleChanged={() => {}} />;
const openConfiguration = (panel: HTMLElement) =>
  fireEvent.click(within(panel).getByRole('button', { name: /Published configuration/ }));

describe('issue84 incubation configuration identity', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    role = 'general_member';
    userId = 'issue84-reader';
  });

  it('inspects the registry primary equity book and keeps its fractional equity rows', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(reply());
    render(detail());
    const panel = await screen.findByRole('region', { name: 'Published configuration' });
    openConfiguration(panel);
    expect(await within(panel).findByText('No published configuration for this book.')).toBeTruthy();
    expect(within(panel).getByText('Registry: inc_meanrev')).toBeTruthy();
    expect(within(panel).getByText('Book: EQUITY_MR_PORTFOLIO')).toBeTruthy();
    expect(screen.getByText('AAPL')).toBeTruthy();
    expect(screen.getByText('1.25')).toBeTruthy();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(String(fetch.mock.calls[0][0])).toMatch(/\/portfolio\/strategies\/inc_meanrev\/configuration\?portfolio_id=EQUITY_MR_PORTFOLIO$/);
    expect(fetch.mock.calls[0][1]).toMatchObject({ method: 'GET', credentials: 'include' });
    fireEvent.click(within(panel).getByRole('button', { name: 'Refresh published configuration' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(fetch.mock.calls.every(([url, init]) => String(url).endsWith('portfolio_id=EQUITY_MR_PORTFOLIO') && init?.method === 'GET')).toBe(true);
  });

  it('shows an unsupported equity publication as unavailable without manufacturing configuration', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(reply('EQUITY_MR_PORTFOLIO', 'unsupported_publication'));
    render(detail());
    const panel = await screen.findByRole('region', { name: 'Published configuration' });
    openConfiguration(panel);
    expect(await within(panel).findByText('This publication version is unavailable.')).toBeTruthy();
    expect(within(panel).queryByRole('table', { name: 'Supplied inputs' })).toBeNull();
    expect(within(panel).queryByRole('region', { name: 'Settings actually used' })).toBeNull();
    expect(within(panel).queryByRole('button', { name: /save|activate|approve|propose/i })).toBeNull();
  });

  it('rejects a BASE response on the equity page without falling back or displaying it', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(reply('BASE_PORTFOLIO'));
    render(detail());
    const panel = await screen.findByRole('region', { name: 'Published configuration' });
    openConfiguration(panel);
    expect(await within(panel).findByRole('alert')).toHaveProperty('textContent', 'Published configuration could not be loaded.');
    expect(within(panel).queryByText(/BASE_PORTFOLIO/)).toBeNull();
    expect(within(panel).queryByText('No published configuration for this book.')).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    [true, null], [false, 'Performance temporarily unavailable'],
  ] as const)('keeps configuration reachable when performance loading=%s error=%s', async (loading, error) => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(reply());
    render(detail(equity, loading, error));
    const panel = await screen.findByRole('region', { name: 'Published configuration' });
    openConfiguration(panel);
    expect(await within(panel).findByText('No published configuration for this book.')).toBeTruthy();
  });

  it('clears the previous book immediately and aborts its pending read on a primary-book change', async () => {
    let release: ((response: Response) => void) | undefined;
    let previousSignal: AbortSignal | undefined;
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce((_url, init) => {
        previousSignal = init?.signal ?? undefined;
        return new Promise<Response>(resolve => { release = resolve; });
      })
      .mockResolvedValueOnce(reply('SECOND_EQUITY_BOOK', 'unsupported_publication'));
    const view = render(detail());
    expect(screen.getByText('Registry: inc_meanrev')).toBeTruthy();
    expect(screen.getByText('Book: EQUITY_MR_PORTFOLIO')).toBeTruthy();
    view.rerender(detail({ ...equity, portfolio_id: 'SECOND_EQUITY_BOOK' }));
    expect(screen.queryByText('Book: EQUITY_MR_PORTFOLIO')).toBeNull();
    expect(previousSignal?.aborted).toBe(true);
    openConfiguration(await screen.findByRole('region', { name: 'Published configuration' }));
    expect(await screen.findByText('This publication version is unavailable.')).toBeTruthy();
    await act(async () => { release?.(reply()); });
    expect(screen.queryByText('No published configuration for this book.')).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(String(fetch.mock.calls[1][0])).toMatch(/portfolio_id=SECOND_EQUITY_BOOK$/);
  });

  it('drops configuration immediately when the internal role is lost', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(reply());
    const view = render(detail());
    openConfiguration(await screen.findByRole('region', { name: 'Published configuration' }));
    await screen.findByText('No published configuration for this book.');
    role = 'subscriber_individual';
    view.rerender(detail());
    expect(screen.queryByRole('region', { name: 'Published configuration' })).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each(['subscriber_individual', 'subscriber_enterprise', undefined])('does not read configuration for role %s', async forbiddenRole => {
    role = forbiddenRole;
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(reply());
    render(detail());
    expect(screen.queryByRole('region', { name: 'Published configuration' })).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('does not substitute BASE when the registry portfolio identity is missing', () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(reply());
    render(detail({ ...equity, portfolio_id: '' }));
    expect(screen.queryByRole('region', { name: 'Published configuration' })).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });
});
