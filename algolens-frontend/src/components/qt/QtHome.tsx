import React, { useEffect, useMemo, useState } from 'react';
import { useTheme } from '../../adapters/react/ThemeContext';
import { PortfolioApplicationService } from '../../application/portfolio/portfolioService';
import {
  deskGroups,
  findPortfolio,
  type PortfolioList,
} from '../../domain/portfolio/portfolioRegistry';
import { PortfolioBookView } from '../PortfolioBookView';
import { PortfolioSwitcher } from '../PortfolioSwitcher';
import { DeskPanel } from './DeskPanel';

/**
 * The QT screen: the desk's home. The desk-edited portfolios (next to their
 * model twins), and for the selected one the book with the desk panel: the
 * day's status and 09:30 countdown, edit, override request, Approve, the
 * command history and the settings editor.
 */
export function QtHome() {
  const { theme } = useTheme();
  const dark = theme === 'dark';
  const [list, setList] = useState<PortfolioList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    PortfolioApplicationService.listPortfolios()
      .then(data => {
        if (cancelled) return;
        setList(data);
        const first = deskGroups(data.groups)
          .flatMap(group => group.portfolios)
          .find(p => p.desk_editable);
        setSelectedId(current => current ?? first?.portfolio_id ?? null);
      })
      .catch(err => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const groups = useMemo(() => (list ? deskGroups(list.groups) : []), [list]);
  const selected = findPortfolio(groups, selectedId);
  const muted = dark ? 'text-gray-400' : 'text-gray-600';

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl mb-1">QT desk</h1>
        <p className={`text-sm ${muted}`}>
          Approve by 09:30 New York. Approved books are e-mailed at 09:30. If nothing is approved by
          10:00, the model's book is sent.
        </p>
      </div>

      {error ? (
        <p className="text-sm text-red-500">Could not load the portfolios: {error}</p>
      ) : !list ? (
        <p className={muted}>Loading the desk...</p>
      ) : !list.deskEnabled ? (
        <div
          className={`p-4 rounded-lg border text-sm ${
            dark ? 'border-gray-800 bg-gray-900 text-gray-300' : 'border-gray-200 bg-gray-50 text-gray-700'
          }`}
        >
          The QT desk is not enabled on this server (QT_DESK_ENABLED is off).
        </div>
      ) : groups.length === 0 ? (
        <p className={muted}>No portfolio is desk-edited yet.</p>
      ) : (
        <>
          <PortfolioSwitcher
            groups={groups}
            selected={selected ? selected.portfolio_id : null}
            onSelect={id => setSelectedId(id)}
          />
          {selected ? (
            <PortfolioBookView
              // Remount per portfolio: nothing of the previous one survives a switch.
              key={selected.portfolio_id}
              portfolio={selected}
              onBack={() => setSelectedId(null)}
              backLabel="Back to the desk"
              renderDesk={
                selected.desk_editable
                  ? ({ portfolio, book, reload }) => (
                      <DeskPanel
                        key={portfolio.portfolio_id}
                        portfolioId={portfolio.portfolio_id}
                        book={book}
                        reloadBook={reload}
                      />
                    )
                  : undefined
              }
            />
          ) : (
            <p className={muted}>Choose a portfolio above.</p>
          )}
        </>
      )}
    </div>
  );
}
