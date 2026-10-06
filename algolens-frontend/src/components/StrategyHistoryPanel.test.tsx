// @vitest-environment jsdom

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { StrategyHistoryPanel } from './StrategyHistoryPanel';

const api = vi.hoisted(() => ({
  getLifecycleHistory: vi.fn(),
  getAssignmentHistory: vi.fn(),
}));
vi.mock('../infrastructure/api/portfolioApi', () => ({ PortfolioApiService: api }));

beforeEach(() => {
  api.getLifecycleHistory.mockReset();
  api.getAssignmentHistory.mockReset();
  api.getLifecycleHistory.mockResolvedValue([
    {
      id: 4, strategy_id: 'trend', before_state: 'live', after_state: 'retired',
      reason: 'review complete', user_id: '7', created_at: '2026-09-22T12:00:00Z',
    },
  ]);
  api.getAssignmentHistory.mockResolvedValue([
    {
      id: 3, strategy_id: 'trend', user_id: '7', from_portfolio_id: 'BOOK_A',
      to_portfolio_id: 'BOOK_B', lifecycle_at_move: 'live', reason: 'rebalance',
      consequences: [], acknowledged: true, created_at: '2026-09-21T12:00:00Z',
    },
  ]);
});

describe('strategy history panel', () => {
  it('shows lifecycle and membership history for a retired registry row', async () => {
    render(<StrategyHistoryPanel strategyId="trend" strategyName="Trend" theme="light" />);
    fireEvent.click(screen.getByRole('button', { name: 'Show history for Trend' }));

    expect(await screen.findByText('review complete')).toBeTruthy();
    expect(screen.getByText('live → retired')).toBeTruthy();
    expect(screen.getByText('rebalance')).toBeTruthy();
    expect(screen.getByText('BOOK_A → BOOK_B')).toBeTruthy();
    expect(api.getLifecycleHistory).toHaveBeenCalledWith('trend');
    expect(api.getAssignmentHistory).toHaveBeenCalledWith('trend');
  });

  it('refreshes an open panel when a lifecycle transition completes', async () => {
    const { rerender } = render(
      <StrategyHistoryPanel strategyId="trend" strategyName="Trend" theme="light" refreshToken={0} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Show history for Trend' }));
    await screen.findByText('review complete');
    rerender(
      <StrategyHistoryPanel strategyId="trend" strategyName="Trend" theme="light" refreshToken={1} />,
    );

    await waitFor(() => expect(api.getLifecycleHistory).toHaveBeenCalledTimes(2));
    expect(api.getAssignmentHistory).toHaveBeenCalledTimes(2);
  });

  it('does not let an older request overwrite refreshed lifecycle and membership history', async () => {
    let resolveOldLifecycle!: (rows: unknown[]) => void;
    let resolveOldAssignments!: (rows: unknown[]) => void;
    let resolveNewLifecycle!: (rows: unknown[]) => void;
    let resolveNewAssignments!: (rows: unknown[]) => void;
    api.getLifecycleHistory
      .mockReturnValueOnce(new Promise(resolve => { resolveOldLifecycle = resolve; }))
      .mockReturnValueOnce(new Promise(resolve => { resolveNewLifecycle = resolve; }));
    api.getAssignmentHistory
      .mockReturnValueOnce(new Promise(resolve => { resolveOldAssignments = resolve; }))
      .mockReturnValueOnce(new Promise(resolve => { resolveNewAssignments = resolve; }));

    const { rerender } = render(
      <StrategyHistoryPanel strategyId="trend" strategyName="Trend" theme="light" refreshToken={0} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Show history for Trend' }));
    await waitFor(() => expect(api.getLifecycleHistory).toHaveBeenCalledTimes(1));
    rerender(
      <StrategyHistoryPanel strategyId="trend" strategyName="Trend" theme="light" refreshToken={1} />,
    );
    await waitFor(() => expect(api.getLifecycleHistory).toHaveBeenCalledTimes(2));

    await act(async () => {
      resolveNewLifecycle([{
        id: 20, strategy_id: 'trend', before_state: 'live', after_state: 'retired',
        reason: 'new lifecycle audit', user_id: '7', created_at: '2026-09-22T13:00:00Z',
      }]);
      resolveNewAssignments([{
        id: 21, strategy_id: 'trend', user_id: '7', from_portfolio_id: 'BOOK_B',
        to_portfolio_id: null, lifecycle_at_move: 'live', reason: 'new membership audit',
        consequences: [], acknowledged: true, created_at: '2026-09-22T13:00:00Z',
      }]);
    });
    expect(await screen.findByText('new lifecycle audit')).toBeTruthy();
    expect(screen.getByText('new membership audit')).toBeTruthy();

    await act(async () => {
      resolveOldLifecycle([{
        id: 10, strategy_id: 'trend', before_state: 'incubating', after_state: 'live',
        reason: 'stale lifecycle audit', user_id: '7', created_at: '2026-09-21T13:00:00Z',
      }]);
      resolveOldAssignments([{
        id: 11, strategy_id: 'trend', user_id: '7', from_portfolio_id: 'BOOK_A',
        to_portfolio_id: 'BOOK_B', lifecycle_at_move: 'live', reason: 'stale membership audit',
        consequences: [], acknowledged: true, created_at: '2026-09-21T13:00:00Z',
      }]);
    });

    expect(screen.getByText('new lifecycle audit')).toBeTruthy();
    expect(screen.getByText('new membership audit')).toBeTruthy();
    expect(screen.queryByText('stale lifecycle audit')).toBeNull();
    expect(screen.queryByText('stale membership audit')).toBeNull();
  });
});
