// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { OverrideHistory } from './OverrideHistory';
import type { PositionOverride } from '../infrastructure/api/portfolioApi';

vi.mock('../adapters/react/ThemeContext', () => ({ useTheme: () => ({ theme: 'light' }) }));
const getOverrides = vi.hoisted(() => vi.fn());
vi.mock('../infrastructure/api/portfolioApi', () => ({
  PortfolioApiService: { getPositionOverrides: getOverrides },
}));
afterEach(() => { cleanup(); getOverrides.mockReset(); });
function deferred() {
  let resolve!: (rows: PositionOverride[]) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<PositionOverride[]>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function rows(symbol: string): PositionOverride[] {
  return [{ id: 1, symbol, user_id: '7', source_app: 'algolens', strategy_id: 'trend',
    before_state: { quantity: 1 }, after_state: { quantity: 2 }, reason: 'hedge',
    risk_check_result: null, overrode_risk: false, created_at: '2026-09-18T12:00:00Z' }];
}
it('clears secondary history immediately when returning to the primary book', async () => {
  const primary = deferred();
  getOverrides.mockResolvedValueOnce(rows('SECONDARY')).mockReturnValueOnce(primary.promise);
  const { rerender } = render(<OverrideHistory strategyId="trend" portfolioId="secondary" />);
  await screen.findByText('SECONDARY');
  rerender(<OverrideHistory strategyId="trend" portfolioId="primary" />);
  expect(screen.queryByText('SECONDARY')).toBeNull();
  expect(screen.getByText('Loading…')).toBeTruthy();
  await act(async () => primary.resolve(rows('PRIMARY')));
  expect(screen.getByText('PRIMARY')).toBeTruthy();
});
it('ignores an old book response arriving after the current response', async () => {
  const secondary = deferred();
  const primary = deferred();
  getOverrides.mockReturnValueOnce(secondary.promise).mockReturnValueOnce(primary.promise);
  const { rerender } = render(<OverrideHistory strategyId="trend" portfolioId="secondary" />);
  rerender(<OverrideHistory strategyId="trend" portfolioId="primary" />);
  await act(async () => primary.resolve(rows('PRIMARY')));
  await act(async () => secondary.resolve(rows('SECONDARY')));
  expect(screen.getByText('PRIMARY')).toBeTruthy();
  expect(screen.queryByText('SECONDARY')).toBeNull();
});
it('ignores a stale failure after a strategy switch', async () => {
  const old = deferred();
  getOverrides.mockReturnValueOnce(old.promise).mockResolvedValueOnce(rows('CURRENT'));
  const { rerender } = render(<OverrideHistory strategyId="old" portfolioId="primary" />);
  rerender(<OverrideHistory strategyId="new" portfolioId="primary" />);
  await screen.findByText('CURRENT');
  await act(async () => old.reject(new Error('old error')));
  expect(screen.getByText('CURRENT')).toBeTruthy();
  expect(screen.queryByText('old error')).toBeNull();
});
it('refreshes the same scope after a successful edit and says the list is bounded', async () => {
  getOverrides.mockResolvedValueOnce([]).mockResolvedValueOnce(rows('FRESH'));
  const { rerender } = render(
    <OverrideHistory strategyId="trend" portfolioId="primary" refreshKey={0} />,
  );
  await screen.findByText(/No manual edits/);
  rerender(<OverrideHistory strategyId="trend" portfolioId="primary" refreshKey={1} />);
  await screen.findByText('FRESH');
  expect(getOverrides).toHaveBeenCalledTimes(2);
  expect(screen.getByText(/Newest 100 manual edits/i)).toBeTruthy();
});

it('keeps the six-column history readable through horizontal scrolling on narrow screens', async () => {
  getOverrides.mockResolvedValue(rows('ES'));
  render(<OverrideHistory strategyId="trend" portfolioId="primary" />);

  const header = (await screen.findByText('When')).parentElement;
  const table = header?.parentElement;
  expect(table?.className).toContain('min-w-[840px]');
  expect(table?.parentElement?.className).toContain('overflow-x-auto');
});
