import React from 'react';
import { useTheme } from '../adapters/react/ThemeContext';
import type { PositionBook } from '../domain/portfolio/bookLabel';
import { BOOK_TOGGLE_OPTIONS } from '../domain/portfolio/portfolioRegistry';

interface BookToggleProps {
  active: PositionBook;
  onChange: (book: PositionBook) => void;
  disabled?: boolean;
}

/** Flips a portfolio's view between its system, qt_proposal and qt books. */
export function BookToggle({ active, onChange, disabled }: BookToggleProps) {
  const { theme } = useTheme();
  const dark = theme === 'dark';
  return (
    <div
      role="radiogroup"
      aria-label="Book"
      data-testid="book-toggle"
      className={`inline-flex rounded-lg border overflow-hidden ${dark ? 'border-gray-700' : 'border-gray-300'}`}
    >
      {BOOK_TOGGLE_OPTIONS.map(option => {
        const selected = option.book === active;
        return (
          <button
            key={option.book}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            onClick={() => onChange(option.book)}
            className={`px-3 py-1.5 text-sm transition-colors ${
              selected
                ? 'bg-orange-500 text-white'
                : dark
                  ? 'text-gray-300 hover:bg-gray-900'
                  : 'text-gray-700 hover:bg-gray-100'
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
