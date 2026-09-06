import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { periodReturn } from '../domain/portfolio/periodReturn';
import { filterByPeriod } from '../domain/portfolio/filterByPeriod';
import { formatBarDate } from '../domain/portfolio/formatBarDate';
import {
  breaksWithin,
  latestSegment,
  withBreakGaps,
} from '../domain/portfolio/historySegments';
import { ArrowLeft, TrendingUp, TrendingDown } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts';
import type { Strategy } from '../domain/portfolio/portfolioData';
import { useTheme } from '../adapters/react/ThemeContext';
import { FinancialAnalysis } from './FinancialAnalysis';
import { PositionBreakdown } from './PositionBreakdown';
import { PortfolioApiService } from '../infrastructure/api/portfolioApi';
import { OverrideHistory } from './OverrideHistory';
import { TradingActivity } from './TradingActivity';
import { AlphaAttribution } from './AlphaAttribution';

interface StrategyDetailProps {
  strategy: Strategy;
  onBack: () => void;
  /** Re-fetch the book after a manual position edit. */
  onPositionsChanged?: () => void;
}

export function StrategyDetail({ strategy, onBack, onPositionsChanged }: StrategyDetailProps) {
  // Which book is on screen. A strategy can trade a different universe, with
  // different limits, in each book it belongs to; the view used to show the
  // primary one and offer no way to reach the others, so the rest of a
  // strategy's positions were simply unreachable from the app.
  const books = strategy.books ?? (strategy.portfolio_id ? [strategy.portfolio_id] : []);
  const [book, setBook] = useState<string | undefined>(strategy.portfolio_id);
  // The detail for `book`. Null means "use the prop", which is the primary.
  const [bookDetail, setBookDetail] = useState<Strategy | null>(null);
  const [bookLoading, setBookLoading] = useState(false);
  const [bookError, setBookError] = useState<string | null>(null);

  // The strategy the positions tab renders. Everything else on this screen is
  // strategy-level and stays as it was.
  const shown = bookDetail ?? strategy;

  const loadBook = useCallback(async (target: string | undefined) => {
    if (!target || target === strategy.portfolio_id) {
      setBookDetail(null);
      setBookError(null);
      return;
    }
    setBookLoading(true);
    setBookError(null);
    try {
      setBookDetail(await PortfolioApiService.getStrategy(strategy.id, target));
    } catch (err) {
      setBookDetail(null);
      setBookError(err instanceof Error ? err.message : 'Could not load that book');
    } finally {
      setBookLoading(false);
    }
  }, [strategy.id, strategy.portfolio_id]);

  // A different strategy was opened: go back to its own primary book.
  useEffect(() => {
    setBook(strategy.portfolio_id);
    setBookDetail(null);
    setBookError(null);
  }, [strategy.id, strategy.portfolio_id]);

  // An edit landed. Re-read whichever book is on screen, and let the dashboard
  // re-read the primary.
  const handlePositionsChanged = useCallback(() => {
    void loadBook(book);
    onPositionsChanged?.();
  }, [book, loadBook, onPositionsChanged]);

  const [selectedPeriod, setSelectedPeriod] = useState('1M');
  const [selectedTab, setSelectedTab] = useState<'positions' | 'analysis' | 'activity'>('positions');
  const { theme } = useTheme();
  const isPositive = (strategy.return ?? 0) >= 0;
  const periods = ['1W', '1M', '3M', '1Y', 'ALL'];

  // Filter data based on selected period
  const filteredData = useMemo(
    () => filterByPeriod(strategy.historicalData, selectedPeriod),
    [selectedPeriod, strategy.historicalData]
  );

  // Where this window's curve changes book. Only breaks a reader can actually
  // see on the chart are worth drawing or naming.
  const visibleBreaks = useMemo(
    () => breaksWithin(filteredData, strategy.historyBreaks),
    [filteredData, strategy.historyBreaks]
  );

  // The plotted series lifts the pen at each break. `connectNulls` is
  // deliberately not set: connecting them is exactly what must not happen.
  const plotted = useMemo(
    () => withBreakGaps(filteredData, strategy.historyBreaks),
    [filteredData, strategy.historyBreaks]
  );

  // The window's return, measured over the newest unbroken stretch only. A
  // return that spans a book change adds up two different portfolios.
  const windowReturn = useMemo(() => {
    return periodReturn(latestSegment(filteredData, strategy.historyBreaks));
  }, [filteredData, strategy.historyBreaks]);
  // The window's direction, for chart colours. An unknown window is
  // drawn in the neutral-positive colour rather than not drawn at all.
  const gaining = (windowReturn?.value ?? 0) >= 0;

  const periodLabel = selectedPeriod === 'ALL' ? 'All Time' : selectedPeriod;

  return (
    <div>
      <button
        onClick={onBack}
        className={`flex items-center gap-2 mb-6 px-4 py-2 rounded-lg transition-colors ${theme === 'dark'
          ? 'text-gray-300 hover:text-white hover:bg-gray-900'
          : 'text-gray-700 hover:text-black hover:bg-gray-100'
          }`}
      >
        <ArrowLeft className="w-5 h-5" />
        <span>Back to Strategies</span>
      </button>

      <div className="mb-6">
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <h1 className="text-2xl md:text-3xl mb-1">{strategy.name}</h1>
            <p className={theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}>
              {strategy.description}
            </p>
            <div className={`text-sm mt-2 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              {strategy.lastUpdate}
            </div>
          </div>
        </div>
      </div>

      <div className="mb-6">
        <div className="text-3xl md:text-4xl mb-2">
          ${strategy.currentValue.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </div>
        {/* Null means the window holds fewer than two points, so there is no
            return to state. This used to state "$0.00 (+0.00%)" -- a flat
            period, rather than a period nothing is known about. */}
        {windowReturn === null ? (
          <div className={`text-lg ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
            &mdash; no data for {periodLabel}
          </div>
        ) : (
          <div className={`flex items-center gap-2 text-lg ${gaining ? 'text-orange-500' : 'text-red-500'}`}>
            {gaining ? <TrendingUp className="w-5 h-5" /> : <TrendingDown className="w-5 h-5" />}
            <span>
              ${Math.abs(windowReturn.value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ({windowReturn.percent >= 0 ? '+' : ''}{windowReturn.percent.toFixed(2)}%) {periodLabel}
            </span>
          </div>
        )}
      </div>

      <div className="mb-4">
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={plotted}>
            <defs>
              <linearGradient id="stratLineGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={gaining ? "#f97316" : "#ef4444"} stopOpacity={theme === 'dark' ? 0.2 : 0.1} />
                <stop offset="100%" stopColor={gaining ? "#f97316" : "#ef4444"} stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="date"
              hide
            />
            <YAxis
              hide
              domain={['dataMin - 500', 'dataMax + 500']}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: theme === 'dark' ? '#1f2937' : '#fff',
                border: theme === 'dark' ? '1px solid #374151' : '1px solid #e5e7eb',
                borderRadius: '8px',
                boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)',
                color: theme === 'dark' ? '#fff' : '#000'
              }}
              formatter={(value) =>
                typeof value === 'number'
                  ? [`$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, 'Value']
                  : ['—', 'Value']
              }
              labelFormatter={(label) => formatBarDate(label as string)}
            />
            <Line
              type="linear"
              dataKey="value"
              stroke={gaining ? "#f97316" : "#ef4444"}
              strokeWidth={2}
              dot={false}
              fill="url(#stratLineGradient)"
            />
          </LineChart>
        </ResponsiveContainer>
        {visibleBreaks.map(brk => (
          <p
            key={brk.date}
            className={`mt-2 text-xs ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}`}
          >
            History restarts {formatBarDate(brk.date)}: moved from{' '}
            {brk.fromPortfolioId} to {brk.toPortfolioId}. The
            line breaks because the two sides are different portfolios, and the
            window return above measures only the stretch since the move.
          </p>
        ))}
      </div>

      {/* Is QT's judgement adding value? Renders an explanation instead of a
          chart until both streams exist. */}
      <div className="mb-8">
        <AlphaAttribution equityByStream={strategy.equityByStream} theme={theme} />
      </div>

      <div className={`flex items-center justify-between mb-8 border-b ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
        }`}>
        {periods.map((period) => (
          <button
            key={period}
            onClick={() => setSelectedPeriod(period)}
            className={`px-3 py-3 text-sm transition-colors relative ${selectedPeriod === period
              ? 'text-orange-500'
              : theme === 'dark'
                ? 'text-gray-400 hover:text-white'
                : 'text-gray-500 hover:text-gray-900'
              }`}
          >
            {period}
            {selectedPeriod === period && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-orange-500" />
            )}
          </button>
        ))}
      </div>

      {/* Tab Navigation */}
      <div className={`flex items-center justify-between mb-6 border-b ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
        }`}>
        <div className="flex items-center gap-4">
          <button
            onClick={() => setSelectedTab('positions')}
            className={`pb-3 px-1 transition-colors relative ${selectedTab === 'positions'
              ? 'text-orange-500'
              : theme === 'dark'
                ? 'text-gray-400 hover:text-white'
                : 'text-gray-500 hover:text-gray-900'
              }`}
          >
            Positions
            {selectedTab === 'positions' && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-orange-500" />
            )}
          </button>
          <button
            onClick={() => setSelectedTab('analysis')}
            className={`pb-3 px-1 transition-colors relative ${selectedTab === 'analysis'
              ? 'text-orange-500'
              : theme === 'dark'
                ? 'text-gray-400 hover:text-white'
                : 'text-gray-500 hover:text-gray-900'
              }`}
          >
            Financial Analysis
            {selectedTab === 'analysis' && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-orange-500" />
            )}
          </button>
          <button
            onClick={() => setSelectedTab('activity')}
            className={`pb-3 px-1 transition-colors relative ${selectedTab === 'activity'
              ? 'text-orange-500'
              : theme === 'dark'
                ? 'text-gray-400 hover:text-white'
                : 'text-gray-500 hover:text-gray-900'
              }`}
          >
            Trading Activity
            {selectedTab === 'activity' && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-orange-500" />
            )}
          </button>
        </div>

        <button
          onClick={onBack}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${theme === 'dark'
              ? 'text-gray-300 hover:text-white hover:bg-gray-900'
              : 'text-gray-700 hover:text-black hover:bg-gray-100'
            }`}
        >
          <ArrowLeft className="w-5 h-5" />
          <span>Back to Strategies</span>
        </button>
      </div>

      {/* Tab Content */}
      {selectedTab === 'positions' && (
        <>
          {books.length > 1 && (
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <label
                htmlFor="book-view"
                className={`text-xs uppercase tracking-wider ${
                  theme === 'dark' ? 'text-gray-500' : 'text-gray-500'
                }`}
              >
                Book
              </label>
              <select
                id="book-view"
                aria-label="Which book to show"
                value={book ?? ''}
                onChange={e => { setBook(e.target.value); void loadBook(e.target.value); }}
                className={`rounded-lg border px-2 py-1.5 text-sm font-mono ${
                  theme === 'dark'
                    ? 'bg-gray-900 border-gray-700 text-white'
                    : 'bg-white border-gray-300 text-black'
                }`}
              >
                {books.map(b => (
                  <option key={b} value={b}>
                    {b}{b === strategy.portfolio_id ? ' (primary)' : ''}
                  </option>
                ))}
              </select>
              <span className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-500'}`}>
                Each book has its own positions and its own risk limits.
              </span>
              {bookLoading && (
                <span className={`text-xs ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}`}>
                  Loading…
                </span>
              )}
            </div>
          )}

          {bookError && (
            <div className="mb-4 rounded-lg border border-red-500/50 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
              {bookError}
            </div>
          )}

          <PositionBreakdown
            positions={shown.positions}
            strategyId={strategy.id}
            portfolioId={shown.portfolio_id ?? book}
            books={books}
            onEdited={handlePositionsChanged}
          />
          {/* The audit trail sits directly under the book it describes. It was
              being written on every edit and read by nobody. */}
          <div className="mt-8">
            <OverrideHistory strategyId={strategy.id} />
          </div>
        </>
      )}

      {selectedTab === 'analysis' && (
        <FinancialAnalysis metrics={strategy.metrics} />
      )}

      {selectedTab === 'activity' && (
        <TradingActivity
          executions={strategy.executions}
          finalizedPositions={strategy.finalizedPositions}
        />
      )}
    </div>
  );
}