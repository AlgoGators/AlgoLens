// @vitest-environment jsdom
//
// Which book is this page about? Every number on a strategy's page -- value,
// history, metrics, executions, positions -- is read by (strategy, book). The
// page used to name the book only in small print above the positions table,
// and only the positions table followed the book picker; the value, the chart
// and the other two tabs stayed on the primary book with no label.
//
// Choosing a book the engine had not traded yet printed
//   API request failed: 404 NOT FOUND. Body: {"code":"no_data_for_book",...}
// and left the primary book's positions on screen under a picker naming the
// other book. Both found by driving the app, not by a test; these pin them.

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { StrategyDetail } from './StrategyDetail';
import type { Strategy } from '../domain/portfolio/portfolioData';
import { ApiError } from '../infrastructure/api/httpClient';

vi.mock('../adapters/react/ThemeContext', () => ({
  useTheme: () => ({ theme: 'light' }),
}));

// The children are stubbed down to the one thing these tests care about:
// which book's data each of them was handed.
vi.mock('./PositionBreakdown', () => ({
  PositionBreakdown: (p: {
    portfolioId?: string;
    positions: { symbol: string }[];
    bookControl?: React.ReactNode;
  }) => (
    <div>
      <div data-testid="positions">
        {p.portfolioId}:{p.positions.map(x => x.symbol).join(',')}
      </div>
      {p.bookControl}
    </div>
  ),
}));
vi.mock('./FinancialAnalysis', () => ({
  FinancialAnalysis: (p: { metrics: { tag?: string } }) => (
    <div data-testid="analysis">{p.metrics.tag}</div>
  ),
}));
vi.mock('./TradingActivity', () => ({
  TradingActivity: (p: { executions: { tag?: string }[] }) => (
    <div data-testid="activity">{p.executions.map(e => e.tag).join(',')}</div>
  ),
}));
vi.mock('./OverrideHistory', () => ({ OverrideHistory: () => null }));
vi.mock('./AlphaAttribution', () => ({ AlphaAttribution: () => null }));
vi.mock('recharts', () => {
  const Stub = () => null;
  return {
    LineChart: Stub, Line: Stub, XAxis: Stub, YAxis: Stub, Tooltip: Stub,
    ResponsiveContainer: Stub,
  };
});

// A plain function rather than a vi.fn spy. The spy tracks every promise it
// returns, and a rejected one it has handed out fails the test even after the
// component has caught it -- which is exactly the path these tests exercise.
type Impl = (id: string, book?: string) => Promise<Strategy>;
let getStrategyImpl: Impl = async () => { throw new Error('getStrategy not set'); };
const getStrategyCalls: unknown[][] = [];
vi.mock('../infrastructure/api/portfolioApi', () => ({
  PortfolioApiService: {
    getStrategy: (id: string, book?: string) => {
      getStrategyCalls.push([id, book]);
      return getStrategyImpl(id, book);
    },
  },
}));

function strategy(over: Partial<Strategy> & { tag: string }): Strategy {
  const { tag, ...rest } = over;
  return {
    id: 'trendfollowing',
    name: 'Trend Following',
    description: 'Systematic trend following',
    invested: 500000,
    currentValue: 523681.65,
    return: 23681.65,
    returnPercent: 4.74,
    positions: [{ symbol: `${tag}-POS` }],
    historicalData: [],
    bestDay: null,
    worstDay: null,
    metrics: { tag },
    executions: [{ tag }],
    finalizedPositions: [],
    managers: [],
    lastUpdate: '2026-09-15',
    portfolio_id: 'CONSERVATIVE_PORTFOLIO',
    books: ['CONSERVATIVE_PORTFOLIO'],
    ...rest,
  } as unknown as Strategy;
}

/** The book box in the row at the top of the page. */
const topBox = () => screen.getByRole('combobox', { name: 'Which book to show' }) as HTMLSelectElement;
/** The book box beside "Today's Positions". */
const headingBox = () => screen.getByRole('combobox', { name: 'Book for these positions' }) as HTMLSelectElement;

beforeEach(() => {
  getStrategyCalls.length = 0;
  getStrategyImpl = async () => { throw new Error('getStrategy not set'); };
});

describe('the page says which book it is about', () => {
  it('names the book even when there is only one', () => {
    render(<StrategyDetail strategy={strategy({ tag: 'C' })} onBack={() => {}} />);
    expect(screen.getByTestId('book-name').textContent).toBe('CONSERVATIVE_PORTFOLIO');
    expect(screen.queryByRole('combobox')).toBeNull();
  });

  it('offers every book, marking the primary, when there are several', () => {
    render(
      <StrategyDetail
        strategy={strategy({
          tag: 'C',
          books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'],
        })}
        onBack={() => {}}
      />,
    );
    const picker = topBox();
    expect(picker.value).toBe('CONSERVATIVE_PORTFOLIO');
    expect(Array.from(picker.options).map(o => o.textContent)).toEqual([
      'CONSERVATIVE_PORTFOLIO (primary)',
      'AGGRESSIVE_PORTFOLIO',
    ]);
  });
});

describe('switching book switches the whole page', () => {
  const primary = () =>
    strategy({ tag: 'C', books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'] });

  it('re-reads value, positions, metrics and executions from the chosen book', async () => {
    getStrategyImpl = async () =>
      strategy({
        tag: 'A',
        currentValue: 111111,
        portfolio_id: 'AGGRESSIVE_PORTFOLIO',
        books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'],
      });
    render(<StrategyDetail strategy={primary()} onBack={() => {}} />);

    fireEvent.change(topBox(), {
      target: { value: 'AGGRESSIVE_PORTFOLIO' },
    });

    await waitFor(() =>
      expect(screen.getByTestId('positions').textContent).toBe('AGGRESSIVE_PORTFOLIO:A-POS'),
    );
    expect(getStrategyCalls).toEqual([['trendfollowing', 'AGGRESSIVE_PORTFOLIO']]);
    expect(screen.getByText('$111,111.00')).toBeTruthy();

    fireEvent.click(screen.getByText('Financial Analysis'));
    expect(screen.getByTestId('analysis').textContent).toBe('A');
    fireEvent.click(screen.getByText('Trading Activity'));
    expect(screen.getByTestId('activity').textContent).toBe('A');
  });

  it('shows an empty book as empty, not as the primary book under its name', async () => {
    getStrategyImpl = async () => {
      throw new ApiError(
        'API request failed: 404 NOT FOUND. Body: {"code":"no_data_for_book"}',
        404,
        'no_data_for_book',
        'The engine has not published any results for this strategy in AGGRESSIVE_PORTFOLIO yet.',
      );
    };
    render(<StrategyDetail strategy={primary()} onBack={() => {}} />);

    fireEvent.change(topBox(), {
      target: { value: 'AGGRESSIVE_PORTFOLIO' },
    });

    const status = (await screen.findByText(/Nothing published for Trend Following in/)).closest('[role=status]') as HTMLElement;
    expect(status.textContent).toContain('Nothing published for Trend Following in AGGRESSIVE_PORTFOLIO yet');
    // None of the primary book's numbers survive under the other book's name.
    expect(screen.queryByTestId('positions')).toBeNull();
    expect(screen.queryByText('$523,681.65')).toBeNull();
    // And no raw API text anywhere.
    expect(document.body.textContent).not.toContain('API request failed');
    expect(topBox().value).toBe('AGGRESSIVE_PORTFOLIO');
  });

  it('on any other failure, says so plainly and keeps the picker on the book shown', async () => {
    getStrategyImpl = async () => {
      throw new ApiError(
        'API request failed: 500 INTERNAL SERVER ERROR. Body: {...}',
        500,
        undefined,
        'Failed to fetch strategy',
      );
    };
    render(<StrategyDetail strategy={primary()} onBack={() => {}} />);

    fireEvent.change(topBox(), {
      target: { value: 'AGGRESSIVE_PORTFOLIO' },
    });

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe('Failed to fetch strategy');
    expect(document.body.textContent).not.toContain('API request failed');
    expect(topBox().value).toBe('CONSERVATIVE_PORTFOLIO');
    expect(screen.getByTestId('positions').textContent).toBe('CONSERVATIVE_PORTFOLIO:C-POS');
  });

  it('going back to the primary book clears an empty-book notice', async () => {
    getStrategyImpl = async () => {
      throw new ApiError('x', 404, 'no_data_for_book', 'none yet');
    };
    render(<StrategyDetail strategy={primary()} onBack={() => {}} />);
    const picker = topBox();

    fireEvent.change(picker, { target: { value: 'AGGRESSIVE_PORTFOLIO' } });
    await screen.findByText(/Nothing published for/);

    fireEvent.change(picker, { target: { value: 'CONSERVATIVE_PORTFOLIO' } });
    await waitFor(() => expect(screen.queryByRole('status')).toBeNull());
    expect(screen.getByTestId('positions').textContent).toBe('CONSERVATIVE_PORTFOLIO:C-POS');
  });
});

describe('opening straight onto a chosen book', () => {
  const primary = () =>
    strategy({ tag: 'C', books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'] });
  const aggressive = () =>
    strategy({
      tag: 'A',
      currentValue: 111111,
      portfolio_id: 'AGGRESSIVE_PORTFOLIO',
      books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'],
    });

  it('loads the chosen book and shows its positions', async () => {
    getStrategyImpl = async () => aggressive();
    render(
      <StrategyDetail strategy={primary()} initialBook="AGGRESSIVE_PORTFOLIO" onBack={() => {}} />,
    );

    expect(topBox().value).toBe('AGGRESSIVE_PORTFOLIO');
    await waitFor(() =>
      expect(screen.getByTestId('positions').textContent).toBe('AGGRESSIVE_PORTFOLIO:A-POS'),
    );
    expect(getStrategyCalls).toEqual([['trendfollowing', 'AGGRESSIVE_PORTFOLIO']]);
  });

  it('never shows the primary book while the chosen one is loading', async () => {
    let release: (s: Strategy) => void = () => {};
    getStrategyImpl = () => new Promise<Strategy>(r => { release = r; });
    render(
      <StrategyDetail strategy={primary()} initialBook="AGGRESSIVE_PORTFOLIO" onBack={() => {}} />,
    );

    expect(screen.getByRole('status').textContent).toContain('Loading Trend Following in AGGRESSIVE_PORTFOLIO');
    expect(screen.queryByTestId('positions')).toBeNull();
    expect(screen.queryByText('$523,681.65')).toBeNull();

    release(aggressive());
    await waitFor(() =>
      expect(screen.getByTestId('positions').textContent).toBe('AGGRESSIVE_PORTFOLIO:A-POS'),
    );
  });

  it('opening on the primary book asks the API for nothing', () => {
    render(
      <StrategyDetail strategy={primary()} initialBook="CONSERVATIVE_PORTFOLIO" onBack={() => {}} />,
    );
    expect(screen.getByTestId('positions').textContent).toBe('CONSERVATIVE_PORTFOLIO:C-POS');
    expect(getStrategyCalls).toEqual([]);
  });

  it('a slow answer for an earlier choice does not overwrite a later one', async () => {
    const pending: Record<string, (s: Strategy) => void> = {};
    getStrategyImpl = (_id, book) => new Promise<Strategy>(r => { pending[book as string] = r; });
    const books = ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO', 'MACRO_BOOK'];
    render(
      <StrategyDetail strategy={strategy({ tag: 'C', books })} onBack={() => {}} />,
    );
    const picker = topBox();

    fireEvent.change(picker, { target: { value: 'AGGRESSIVE_PORTFOLIO' } });
    fireEvent.change(picker, { target: { value: 'MACRO_BOOK' } });

    pending.MACRO_BOOK(strategy({ tag: 'M', portfolio_id: 'MACRO_BOOK', books }));
    await waitFor(() =>
      expect(screen.getByTestId('positions').textContent).toBe('MACRO_BOOK:M-POS'),
    );

    // The first request comes back last. It must be ignored.
    pending.AGGRESSIVE_PORTFOLIO(strategy({ tag: 'A', portfolio_id: 'AGGRESSIVE_PORTFOLIO', books }));
    await new Promise(r => setTimeout(r, 0));
    expect(screen.getByTestId('positions').textContent).toBe('MACRO_BOOK:M-POS');
    expect((picker as HTMLSelectElement).value).toBe('MACRO_BOOK');
  });
});

describe('the book box beside the positions heading', () => {
  const primary = () =>
    strategy({ tag: 'C', books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'] });

  it('shows the book on screen and offers the others', () => {
    render(<StrategyDetail strategy={primary()} onBack={() => {}} />);
    const box = headingBox();
    expect(box.value).toBe('CONSERVATIVE_PORTFOLIO');
    expect(Array.from(box.options).map(o => o.value)).toEqual([
      'CONSERVATIVE_PORTFOLIO',
      'AGGRESSIVE_PORTFOLIO',
    ]);
  });

  it('switches the whole page to the book chosen in it', async () => {
    getStrategyImpl = async () =>
      strategy({
        tag: 'A',
        currentValue: 111111,
        portfolio_id: 'AGGRESSIVE_PORTFOLIO',
        books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'],
      });
    render(<StrategyDetail strategy={primary()} onBack={() => {}} />);

    fireEvent.change(headingBox(), { target: { value: 'AGGRESSIVE_PORTFOLIO' } });

    await waitFor(() =>
      expect(screen.getByTestId('positions').textContent).toBe('AGGRESSIVE_PORTFOLIO:A-POS'),
    );
    expect(screen.getByText('$111,111.00')).toBeTruthy();
    // Both boxes read the same book: there is one choice, shown twice.
    expect(headingBox().value).toBe('AGGRESSIVE_PORTFOLIO');
    expect(topBox().value).toBe('AGGRESSIVE_PORTFOLIO');
  });

  it('is not offered for a strategy in one book', () => {
    render(<StrategyDetail strategy={strategy({ tag: 'C' })} onBack={() => {}} />);
    expect(screen.queryByRole('combobox', { name: 'Book for these positions' })).toBeNull();
  });

  it('an empty book offers a way back from inside its notice', async () => {
    getStrategyImpl = async () => {
      throw new ApiError('x', 404, 'no_data_for_book', 'none yet');
    };
    render(<StrategyDetail strategy={primary()} onBack={() => {}} />);

    fireEvent.change(headingBox(), { target: { value: 'AGGRESSIVE_PORTFOLIO' } });
    const back = await screen.findByRole('combobox', { name: 'Choose another book' });

    fireEvent.change(back, { target: { value: 'CONSERVATIVE_PORTFOLIO' } });
    await waitFor(() =>
      expect(screen.getByTestId('positions').textContent).toBe('CONSERVATIVE_PORTFOLIO:C-POS'),
    );
  });
});
