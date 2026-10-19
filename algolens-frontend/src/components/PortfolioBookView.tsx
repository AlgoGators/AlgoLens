import React, { useCallback, useEffect, useState } from 'react';
import { useTheme } from '../adapters/react/ThemeContext';
import { PortfolioApplicationService } from '../application/portfolio/portfolioService';
import type { PositionBook } from '../domain/portfolio/bookLabel';
import type { Strategy } from '../domain/portfolio/portfolioData';
import {
  activeToggleBook,
  describeBookLoadError,
  type BookChoice,
  type PortfolioEntry,
} from '../domain/portfolio/portfolioRegistry';
import { BookToggle } from './BookToggle';
import { StrategyDetail } from './StrategyDetail';

export interface DeskSlotProps {
  portfolio: PortfolioEntry;
  strategy: Strategy;
  book: PositionBook;
  /** Re-read the book after a desk action changed it. */
  reload: () => void;
}

interface PortfolioBookViewProps {
  portfolio: PortfolioEntry;
  onBack: () => void;
  backLabel?: string;
  /** The member screen (D-68): the portfolio's Model / QT switch in place of the desk's toggle. */
  choices?: BookChoice[];
  /** The portfolio's name (D-24), e.g. the group's. */
  title?: string;
  /** The QT desk panel, when the desk is enabled for this user and portfolio. */
  renderDesk?: (props: DeskSlotProps) => React.ReactNode;
}

/**
 * One portfolio, read by its portfolio id, with the book toggle (ruling 20).
 * Opens on the qt book; the API serves the system book, labelled as such,
 * while the portfolio has no qt book yet.
 */
export function PortfolioBookView({
  portfolio,
  onBack,
  backLabel = 'Back to all portfolios',
  renderDesk,
  choices,
  title,
}: PortfolioBookViewProps) {
  const { theme } = useTheme();
  const dark = theme === 'dark';
  const [requested, setRequested] = useState<PositionBook | null>(null);
  // D-68: which of the portfolio's two books is shown (QT first, ruling 20).
  const [selectedKey, setSelectedKey] = useState<BookChoice['key']>(
    choices?.some(c => c.key === 'qt') ? 'qt' : 'model',
  );
  const choice = choices?.find(c => c.key === selectedKey) ?? null;
  const readId = choice ? choice.portfolio.portfolio_id : portfolio.portfolio_id;
  const readBook = choice ? choice.book : requested;
  const [strategy, setStrategy] = useState<Strategy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

  // On a switch, show nothing of the previous portfolio while the next loads.
  useEffect(() => {
    setRequested(null);
    setStrategy(null);
    setError(null);
  }, [portfolio.portfolio_id]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    PortfolioApplicationService.getPortfolio(readId, readBook)
      .then(data => {
        if (!cancelled) setStrategy(data);
      })
      .catch(err => {
        if (!cancelled) {
          setStrategy(null);
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [readId, readBook, reloadKey]);

  const reload = useCallback(() => setReloadKey(k => k + 1), []);
  const active = activeToggleBook(requested, strategy?.book);
  const toggle = choices ? (
    choices.length > 1 ? (
      <div
        role="radiogroup"
        aria-label="Book"
        data-testid="model-qt-switch"
        className={`inline-flex rounded-lg border overflow-hidden ${dark ? 'border-gray-700' : 'border-gray-300'}`}
      >
        {choices.map(c => (
          <button
            key={c.key}
            type="button"
            role="radio"
            aria-checked={c.key === selectedKey}
            disabled={loading}
            onClick={() => setSelectedKey(c.key)}
            className={`px-3 py-1.5 text-sm ${
              c.key === selectedKey ? 'bg-orange-500 text-white' : dark ? 'text-gray-300' : 'text-gray-700'
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>
    ) : null
  ) : (
    <BookToggle active={active} onChange={setRequested} disabled={loading} />
  );
  const strategiesLine =
    strategy?.strategies && strategy.strategies.length > 0 ? (
      <p className={`mt-2 text-sm ${dark ? 'text-gray-400' : 'text-gray-500'}`} data-testid="portfolio-strategies">
        Strategies:{' '}
        {strategy.strategies
          .map(s => `${s.name} (${s.positions} position${s.positions === 1 ? '' : 's'})`)
          .join(', ')}
      </p>
    ) : null;

  if (!strategy) {
    return (
      <div>
        <div className="mb-4 flex items-center justify-between gap-4">
          <h1 className="text-2xl">{title ?? portfolio.name}</h1>
          {toggle}
        </div>
        <p className={theme === 'dark' ? 'text-gray-400' : 'text-gray-600'}>
          {loading ? 'Loading portfolio...' : error ? describeBookLoadError(error) : 'No data.'}
        </p>
      </div>
    );
  }

  return (
    <StrategyDetail
      strategy={strategy}
      onBack={onBack}
      backLabel={backLabel}
      headerExtra={
        <>
          {toggle}
          {strategiesLine}
        </>
      }
      title={title}
    >
      {renderDesk?.({ portfolio, strategy, book: active, reload })}
    </StrategyDetail>
  );
}
