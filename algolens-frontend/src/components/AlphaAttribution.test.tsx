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

describe('discretionary alpha day matching', () => {
  // The API publishes full ISO stamps, while commonCoverage reports the shared
  // date as a bare calendar day. The comparison has to match on that day.
  it('compares full ISO timestamps on both sides', () => {
    render(
      <AlphaAttribution
        theme="light"
        equityByStream={{
          qt: [
            { date: '2026-09-20T00:00:00.000Z', value: 150 },
            { date: '2026-09-21T00:00:00.000Z', value: 200 },
          ],
          benchmark: [{ date: '2026-09-20T00:00:00.000Z', value: 100 }],
        }}
      />,
    );

    expect(screen.getByText('+$50')).toBeTruthy();
    expect(screen.getByText(/Compared on Sep 20, 2026/)).toBeTruthy();
    expect(screen.getByText(/latest QT point is Sep 21, 2026/i)).toBeTruthy();
  });

  it('compares a full timestamp against a date-only value', () => {
    render(
      <AlphaAttribution
        theme="light"
        equityByStream={{
          qt: [{ date: '2026-09-20T00:00:00Z', value: 160 }],
          benchmark: [{ date: '2026-09-20', value: 100 }],
        }}
      />,
    );

    expect(screen.getByText('+$60')).toBeTruthy();
    expect(screen.getByText(/Compared on Sep 20, 2026/)).toBeTruthy();
  });

  it('compares date-only values against date-only values', () => {
    render(
      <AlphaAttribution
        theme="light"
        equityByStream={{
          qt: [{ date: '2026-09-20', value: 90 }],
          benchmark: [{ date: '2026-09-20', value: 100 }],
        }}
      />,
    );

    expect(screen.getByText(/Compared on Sep 20, 2026/)).toBeTruthy();
    expect(screen.getByText('−$10')).toBeTruthy();
    expect(screen.getByText(/given up vs\. system alone/i)).toBeTruthy();
  });

  it('keeps a stamp just after midnight UTC on its own calendar day', () => {
    render(
      <AlphaAttribution
        theme="light"
        equityByStream={{
          qt: [
            { date: '2026-09-20T00:00:00Z', value: 100 },
            { date: '2026-09-21T00:00:01Z', value: 175 },
          ],
          benchmark: [
            { date: '2026-09-20T00:00:00Z', value: 100 },
            { date: '2026-09-21T00:00:01Z', value: 150 },
          ],
        }}
      />,
    );

    expect(screen.getByText('+$25')).toBeTruthy();
    expect(screen.getByText(/Compared on Sep 21, 2026/)).toBeTruthy();
  });

  it('does not shift a stamp with a UTC offset onto another day', () => {
    render(
      <AlphaAttribution
        theme="light"
        equityByStream={{
          qt: [{ date: '2026-09-20T23:30:00-05:00', value: 130 }],
          benchmark: [{ date: '2026-09-20', value: 100 }],
        }}
      />,
    );

    expect(screen.getByText('+$30')).toBeTruthy();
    expect(screen.getByText(/Compared on Sep 20, 2026/)).toBeTruthy();
  });

  it('uses the last point of a day, and does not report same-day stamps as different latest dates', () => {
    render(
      <AlphaAttribution
        theme="light"
        equityByStream={{
          qt: [
            { date: '2026-09-20T09:00:00Z', value: 120 },
            { date: '2026-09-20T21:00:00Z', value: 180 },
          ],
          benchmark: [{ date: '2026-09-20T00:00:00Z', value: 100 }],
        }}
      />,
    );

    expect(screen.getByText('+$80')).toBeTruthy();
    expect(screen.queryByText(/latest QT point/i)).toBeNull();
  });

  it('reports the comparison as unavailable when a stream has no usable date', () => {
    render(
      <AlphaAttribution
        theme="light"
        equityByStream={{
          qt: [{ date: '', value: 150 }],
          benchmark: [{ date: '2026-09-20', value: 100 }],
        }}
      />,
    );

    expect(screen.getByText(/Not available yet/i)).toBeTruthy();
  });

  it('does not crash on missing or invalid dates', () => {
    const missing = undefined as unknown as string;
    expect(() => render(
      <AlphaAttribution
        theme="light"
        equityByStream={{
          qt: [{ date: missing, value: 150 }],
          benchmark: [{ date: missing, value: 100 }],
        }}
      />,
    )).not.toThrow();
  });

  it('does not crash on invalid date text shared by both streams', () => {
    expect(() => render(
      <AlphaAttribution
        theme="light"
        equityByStream={{
          qt: [{ date: 'not-a-date-at-all', value: 150 }],
          benchmark: [{ date: 'not-a-date-at-all', value: 100 }],
        }}
      />,
    )).not.toThrow();
  });
});
