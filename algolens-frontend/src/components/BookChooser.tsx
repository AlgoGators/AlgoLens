import { useEffect, useRef, useState } from 'react';
import { Briefcase, ChevronRight, X } from 'lucide-react';

import { bookChoices, type BookChoice } from '../domain/portfolio/bookChoices';
import type { PortfolioSummary } from '../domain/portfolio/portfolioAssignment';
import { PortfolioApiService } from '../infrastructure/api/portfolioApi';

interface BookChooserProps {
  strategyId: string;
  strategyName: string;
  books: string[];
  primary?: string;
  theme: string;
  onChoose: (portfolioId: string) => void;
  onClose: () => void;
}

function describeValue(choice: BookChoice): { text: string; muted: boolean } {
  if (choice.mockCapital !== undefined) {
    return {
      text: choice.mockCapital != null
        ? `$${choice.mockCapital.toLocaleString('en-US', { maximumFractionDigits: 0 })} mock`
        : 'mock capital',
      muted: true,
    };
  }
  if (choice.currentValue === undefined) return { text: '', muted: true };
  // Nothing published is not "worth $0". Say which it is.
  if (choice.currentValue === null) return { text: 'nothing published yet', muted: true };
  return {
    text: `$${choice.currentValue.toLocaleString('en-US', { maximumFractionDigits: 0 })}`,
    muted: false,
  };
}

/**
 * Asked when a strategy that trades in several books is opened: which book?
 *
 * Each book is a separate ledger -- its own positions, history and limits -- so
 * opening "the strategy" without naming one would quietly mean the primary.
 * The per-book values come from the same summary the Portfolios section reads;
 * the list is usable before they arrive, and says nothing rather than $0 for a
 * book whose value is unknown.
 */
export function BookChooser({
  strategyId,
  strategyName,
  books,
  primary,
  theme,
  onChoose,
  onClose,
}: BookChooserProps) {
  const isDark = theme === 'dark';
  const [portfolios, setPortfolios] = useState<PortfolioSummary[] | null>(null);
  const firstOption = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let live = true;
    PortfolioApiService.getPortfolios()
      .then(p => { if (live) setPortfolios(p); })
      // Values are a courtesy. Without them the books are still choosable.
      .catch(() => {});
    return () => { live = false; };
  }, []);

  useEffect(() => {
    firstOption.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const choices = bookChoices(strategyId, books, primary, portfolios);

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="book-chooser-title"
        onClick={e => e.stopPropagation()}
        className={`w-full max-w-md rounded-xl border shadow-xl ${
          isDark ? 'bg-gray-950 border-gray-800 text-white' : 'bg-white border-gray-200 text-black'
        }`}
      >
        <div className={`flex items-start justify-between px-5 py-4 border-b ${isDark ? 'border-gray-800' : 'border-gray-200'}`}>
          <div>
            <h2 id="book-chooser-title" className="text-lg">{strategyName}</h2>
            <p className={`text-sm ${isDark ? 'text-gray-400' : 'text-gray-500'}`}>
              Trades in {choices.length} books. Which one do you want to see?
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className={`p-1 rounded-lg ${isDark ? 'hover:bg-gray-800' : 'hover:bg-gray-100'}`}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <ul className="p-2">
          {choices.map((choice, i) => {
            const value = describeValue(choice);
            return (
              <li key={choice.portfolioId}>
                <button
                  ref={i === 0 ? firstOption : undefined}
                  onClick={() => onChoose(choice.portfolioId)}
                  className={`group flex w-full items-center justify-between gap-3 rounded-lg px-3 py-3 text-left transition-colors ${
                    isDark ? 'hover:bg-gray-900 focus:bg-gray-900' : 'hover:bg-gray-50 focus:bg-gray-50'
                  } focus:outline-none focus:ring-2 focus:ring-orange-500`}
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <Briefcase className="w-4 h-4 flex-shrink-0 text-orange-500" />
                    <span className="truncate font-mono text-sm">{choice.portfolioId}</span>
                    {choice.isPrimary && (
                      <span className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${
                        isDark ? 'bg-gray-800 text-gray-300' : 'bg-gray-100 text-gray-600'
                      }`}>
                        primary
                      </span>
                    )}
                  </span>
                  <span className="flex flex-shrink-0 items-center gap-2">
                    <span className={`text-sm tabular-nums ${
                      value.muted ? (isDark ? 'text-gray-500' : 'text-gray-400') : ''
                    }`}>
                      {value.text}
                    </span>
                    <ChevronRight className={`w-4 h-4 transition-transform group-hover:translate-x-0.5 ${
                      isDark ? 'text-gray-600' : 'text-gray-400'
                    }`} />
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
