import { ChevronDown } from 'lucide-react';

import { bookChoices } from '../domain/portfolio/bookChoices';

interface BookSelectProps {
  /** Every book the strategy is in. */
  books: string[];
  /** The strategy's primary book, marked in the list. */
  primary?: string;
  /** The book currently chosen. */
  value?: string;
  onChange: (portfolioId: string) => void;
  /** Distinguishes the several places this appears, for screen readers and tests. */
  ariaLabel: string;
  theme: string;
  id?: string;
}

/**
 * A box showing which book a strategy is being read in, that opens to the
 * others it belongs to. Primary first, then alphabetically.
 *
 * A native select underneath, so keyboard and screen-reader behaviour come for
 * free; styled to read as the book label it replaces.
 */
export function BookSelect({
  books,
  primary,
  value,
  onChange,
  ariaLabel,
  theme,
  id,
}: BookSelectProps) {
  const isDark = theme === 'dark';
  const choices = bookChoices('', books, primary);

  return (
    <span className="relative inline-flex items-center">
      <select
        id={id}
        aria-label={ariaLabel}
        value={value ?? ''}
        onChange={e => onChange(e.target.value)}
        className={`cursor-pointer appearance-none rounded-lg border py-1 pl-2 pr-7 font-mono text-sm normal-case tracking-normal transition-colors focus:outline-none focus:ring-2 focus:ring-orange-500 ${
          isDark
            ? 'bg-gray-900 border-gray-700 text-white hover:border-orange-500'
            : 'bg-white border-gray-300 text-black hover:border-orange-500'
        }`}
      >
        {choices.map(c => (
          <option key={c.portfolioId} value={c.portfolioId}>
            {c.portfolioId}{c.isPrimary ? ' (primary)' : ''}
          </option>
        ))}
      </select>
      <ChevronDown
        aria-hidden="true"
        className={`pointer-events-none absolute right-2 w-4 h-4 ${isDark ? 'text-gray-400' : 'text-gray-500'}`}
      />
    </span>
  );
}
