// @vitest-environment jsdom

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { TradingActivity } from './TradingActivity';

vi.mock('../adapters/react/ThemeContext', () => ({
  useTheme: () => ({ theme: 'light' }),
}));

describe('activity reporting semantics', () => {
  const execution = {
    symbol: 'ES', side: 'BUY' as const, quantity: 1, price: 5000,
    notional: null, commission: 2, date: '2026-09-21',
  };

  it('keeps QT fills visible while an absent QT comparison is unavailable', () => {
    render(<TradingActivity executions={[execution]} finalizedPositions={[]}
      executionsAvailable activityStream="qt" finalizedPositionsAvailable={false} />);

    expect(screen.getByText('ES')).toBeTruthy();
    expect(screen.getByText(/QT closed-position comparison unavailable/i)).toBeTruthy();
    expect(screen.queryByText('Total Positions: 0')).toBeNull();
  });

  it('labels an identified known-empty closed-position comparison as QT', () => {
    render(<TradingActivity executions={[]} finalizedPositions={[]}
      activityStream="qt" finalizedPositionsAvailable />);

    expect(screen.getByText(/QT finalized position results/i)).toBeTruthy();
    expect(screen.getByText('Total Positions: 0')).toBeTruthy();
  });

  it('labels the latest rows as recent and marks an incomplete total partial', () => {
    render(<TradingActivity executions={[execution]} finalizedPositions={[]} />);

    expect(screen.getByText('Recent Executions')).toBeTruthy();
    expect(screen.getByText(/newest, up to 100 records/i)).toBeTruthy();
    expect(screen.getByText(/1 fill has unknown notional/i)).toBeTruthy();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    expect(screen.getByText('Sep 21')).toBeTruthy();
    expect(screen.getByText('QT Finalized Position Results')).toBeTruthy();
    expect(screen.getByText(/QT closed-position comparison unavailable/i)).toBeTruthy();
  });

  it('renders explicit execution unavailability instead of a zero count', () => {
    render(
      <TradingActivity
        executions={[]}
        finalizedPositions={[]}
        executionsAvailable={false}
        executionUnavailableReason="Legacy executions cannot be attributed to the selected stream."
      />,
    );

    expect(screen.getByText(/Legacy executions cannot be attributed/i)).toBeTruthy();
    expect(screen.queryByText(/Fills shown: 0/)).toBeNull();
  });

  it('labels an explicitly attributed execution set with its selected date', () => {
    render(
      <TradingActivity
        executions={[]}
        finalizedPositions={[]}
        executionsAvailable
        executionDate="2026-09-21"
      />,
    );

    expect(screen.getByText('Executions · Sep 21, 2026')).toBeTruthy();
    expect(screen.getByText(/selected QT stream and execution date/i)).toBeTruthy();
  });
});
