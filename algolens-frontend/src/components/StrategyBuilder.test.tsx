// @vitest-environment jsdom

import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { Strategy } from '../domain/portfolio/portfolioData';
import { StrategyBuilder } from './StrategyBuilder';

vi.mock('../adapters/react/ThemeContext', () => ({
  useTheme: () => ({ theme: 'light' }),
}));
vi.mock('../infrastructure/api/portfolioApi', () => ({
  PortfolioApiService: { getCorrelations: vi.fn().mockResolvedValue(null) },
}));
vi.mock('recharts', () => {
  const Wrap = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  const Empty = () => null;
  return {
    PieChart: Wrap, Pie: Wrap, ResponsiveContainer: Wrap,
    LineChart: Wrap, BarChart: Wrap, Bar: Wrap,
    Cell: Empty, Tooltip: Empty, XAxis: Empty, YAxis: Empty, Line: Empty,
  };
});

function strategy(id: string, currentValue: number | null): Strategy {
  return {
    id,
    name: id,
    description: '',
    dataAvailable: currentValue !== null,
    invested: 100000,
    currentValue,
    return: currentValue === null ? null : currentValue - 100000,
    returnPercent: currentValue === null ? null : (currentValue - 100000) / 1000,
    positions: currentValue === null ? [{ symbol: 'QT-POS' }] : [],
    positionStrategyNames: [],
    positionDate: '2026-09-23',
    positionsEditable: true,
    positionEditUnavailableReason: null,
    historicalData: [],
    bestDay: null,
    worstDay: null,
    metrics: {},
    executions: [],
    finalizedPositions: [],
    managers: [],
    lastUpdate: '2026-09-23',
  } as unknown as Strategy;
}

describe('StrategyBuilder QT coverage disclosure', () => {
  it('warns before all derived panels and labels mixed-selection figures as measured-only', () => {
    render(<StrategyBuilder strategies={[strategy('Priced', 110000), strategy('Awaiting', null)]} onClose={() => {}} />);

    const warning = screen.getByTestId('builder-coverage');
    const headline = screen.getByText('MEASURED STRATEGY VALUE');
    expect(warning.textContent).toMatch(/1 selected strategy.*QT performance unavailable/i);
    expect(warning.compareDocumentPosition(headline) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText('Measured Strategy Split')).toBeTruthy();
    expect(screen.getByText('Measured Asset Allocation')).toBeTruthy();
    expect(screen.getByText(/value, returns, and risk metrics cover measured strategies only/i)).toBeTruthy();
  });

  it('withholds all derived panels when every selected result is unavailable', () => {
    render(<StrategyBuilder strategies={[strategy('Awaiting', null)]} onClose={() => {}} />);

    expect(screen.getByTestId('builder-coverage').textContent).toMatch(/1 selected strategy.*QT performance unavailable/i);
    expect(screen.getByText(/portfolio value, performance, allocations, and holdings are unavailable/i)).toBeTruthy();
    expect(screen.queryByText('PORTFOLIO VALUE')).toBeNull();
    expect(screen.queryByText(/no starting equity on record/i)).toBeNull();
    expect(screen.queryByText('$0k')).toBeNull();
    expect(screen.queryByText(/0 instruments/i)).toBeNull();
  });

  it('keeps complete-data and empty-selection panel behavior unchanged', () => {
    const complete = render(<StrategyBuilder strategies={[strategy('Priced', 110000)]} onClose={() => {}} />);
    expect(screen.queryByTestId('builder-coverage')).toBeNull();
    expect(screen.getByText('PORTFOLIO VALUE')).toBeTruthy();
    expect(screen.getByText('Strategy Split')).toBeTruthy();

    complete.unmount();
    render(<StrategyBuilder strategies={[]} onClose={() => {}} />);
    expect(screen.queryByTestId('builder-coverage')).toBeNull();
    expect(screen.getByText('PORTFOLIO VALUE')).toBeTruthy();
  });
});
