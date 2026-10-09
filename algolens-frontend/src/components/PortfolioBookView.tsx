import React, { useCallback, useEffect, useState } from 'react';
import { useTheme } from '../adapters/react/ThemeContext';
import { PortfolioApplicationService } from '../application/portfolio/portfolioService';
import type { PositionBook } from '../domain/portfolio/bookLabel';
import type { Strategy } from '../domain/portfolio/portfolioData';
import { activeToggleBook, type PortfolioEntry } from '../domain/portfolio/portfolioRegistry';
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
  /** The QT desk panel, when the desk is enabled for this user and portfolio. */
  renderDesk?: (props: DeskSlotProps) => React.ReactNode;
}

/**
 * One portfolio, read by its portfolio id, with the book toggle (ruling 20).
 * Opens on the qt book; the API serves the system book, labelled as such,
 * while the portfolio has no qt book yet.
 */
export function PortfolioBookView({ portfolio, onBack, renderDesk }: PortfolioBookViewProps) {
  const { theme } = useTheme();
  const [requested, setRequested] = useState<PositionBook | null>(null);
  const [strategy, setStrategy] = useState<Strategy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    setRequested(null);
  }, [portfolio.portfolio_id]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    PortfolioApplicationService.getPortfolio(portfolio.portfolio_id, requested)
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
  }, [portfolio.portfolio_id, requested, reloadKey]);

  const reload = useCallback(() => setReloadKey(k => k + 1), []);
  const active = activeToggleBook(requested, strategy?.book);
  const toggle = <BookToggle active={active} onChange={setRequested} disabled={loading} />;

  if (!strategy) {
    return (
      <div>
        <div className="mb-4 flex items-center justify-between gap-4">
          <h1 className="text-2xl">{portfolio.name}</h1>
          {toggle}
        </div>
        <p className={theme === 'dark' ? 'text-gray-400' : 'text-gray-600'}>
          {loading ? 'Loading portfolio...' : error ? `Could not load this book: ${error}` : 'No data.'}
        </p>
      </div>
    );
  }

  return (
    <StrategyDetail
      strategy={strategy}
      onBack={onBack}
      backLabel="Back to all strategies"
      headerExtra={toggle}
    >
      {renderDesk?.({ portfolio, strategy, book: active, reload })}
    </StrategyDetail>
  );
}
