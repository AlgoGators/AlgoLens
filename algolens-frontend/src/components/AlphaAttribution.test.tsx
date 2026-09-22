// @vitest-environment jsdom

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { AlphaAttribution } from './AlphaAttribution';

vi.mock('recharts', async () => {
  const React = await import('react');
  return {
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    LineChart: ({ children, data }: { children: React.ReactNode; data: unknown }) => (
      <div data-testid="chart-data" data-chart={JSON.stringify(data)}>{children}</div>
    ),
    Line: ({ dataKey }: { dataKey: string }) => <span data-testid="line">{dataKey}</span>,
    XAxis: () => null,
    YAxis: () => null,
    Tooltip: () => null,
    Legend: () => null,
  };
});

describe('discretionary alpha coverage', () => {
  it('compares QT and benchmark on their newest shared date', () => {
    render(
      <AlphaAttribution
        theme="light"
        equityByStream={{
          qt: [
            { date: '2026-09-20', value: 150 },
            { date: '2026-09-21', value: 200 },
          ],
          benchmark: [{ date: '2026-09-20', value: 100 }],
        }}
      />,
    );

    expect(screen.getByText('+$50')).toBeTruthy();
    expect(screen.getByText(/Compared on Sep 20, 2026/)).toBeTruthy();
    expect(screen.getByText(/latest QT point is Sep 21, 2026/i)).toBeTruthy();
  });

  it('requires the named QT and benchmark streams', () => {
    render(
      <AlphaAttribution
        theme="light"
        equityByStream={{
          qt: [{ date: '2026-09-20', value: 150 }],
          system: [{ date: '2026-09-20', value: 100 }],
        }}
      />,
    );

    expect(screen.getByText(/needs both the QT and benchmark streams/i)).toBeTruthy();
    expect(screen.queryByText(/added by QT/i)).toBeNull();
  });

  it('does not connect stream lines across gaps', () => {
    render(
      <AlphaAttribution
        theme="light"
        equityByStream={{
          qt: [{ date: '2026-09-19', value: 100 }, { date: '2026-09-21', value: 110 }],
          benchmark: [
            { date: '2026-09-19', value: 100 },
            { date: '2026-09-20', value: 101 },
            { date: '2026-09-21', value: 102 },
          ],
        }}
      />,
    );

    expect(screen.getAllByTestId('line').map(line => line.textContent)).toEqual(['qt', 'benchmark']);
    expect(screen.getByText(/1 date excluded from the QT comparison/i)).toBeTruthy();
  });

  it('lifts the chart at a declared portfolio history break', () => {
    render(
      <AlphaAttribution
        theme="light"
        historyBreaks={[{
          date: '2026-09-20',
          fromPortfolioId: 'A',
          toPortfolioId: 'B',
          reason: 'book_change',
        }]}
        equityByStream={{
          qt: [{ date: '2026-09-19', value: 100 }, { date: '2026-09-20', value: 110 }],
          benchmark: [{ date: '2026-09-19', value: 100 }, { date: '2026-09-20', value: 105 }],
        }}
      />,
    );

    expect(screen.getByTestId('chart-data').getAttribute('data-chart'))
      .toContain('2026-09-20 (history break)');
  });
});
