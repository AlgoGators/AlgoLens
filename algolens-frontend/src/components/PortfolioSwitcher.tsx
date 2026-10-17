import React from 'react';
import { useTheme } from '../adapters/react/ThemeContext';
import {
  portfolioName,
  representative,
  type PortfolioGroup,
} from '../domain/portfolio/portfolioRegistry';

interface PortfolioSwitcherProps {
  groups: PortfolioGroup[];
  selected: string | null;
  onSelect: (portfolioId: string | null) => void;
}

/**
 * The portfolio picker (ruling 20, D-20, D-22): one chip per portfolio above its page. A group
 * (a QT book with its model book) is one portfolio; its two books are the switch inside it. The
 * way back to every portfolio is the page's own back control, not a chip.
 */
export function PortfolioSwitcher({ groups, selected, onSelect }: PortfolioSwitcherProps) {
  const { theme } = useTheme();
  const dark = theme === 'dark';

  const chip = (active: boolean) =>
    `px-3 py-1.5 rounded-full text-sm border transition-colors whitespace-nowrap ${
      active
        ? 'bg-orange-500 border-orange-500 text-white'
        : dark
          ? 'border-gray-700 text-gray-300 hover:bg-gray-900'
          : 'border-gray-300 text-gray-700 hover:bg-gray-100'
    }`;

  return (
    <nav
      aria-label="Portfolio switcher"
      data-testid="portfolio-switcher"
      className={`mb-6 pb-4 border-b ${dark ? 'border-gray-800' : 'border-gray-200'}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        {groups.map(group => {
          const entry = representative(group);
          const active = group.portfolios.some(p => p.portfolio_id === selected);
          return (
            <button
              key={group.group}
              type="button"
              className={chip(active)}
              aria-pressed={active}
              onClick={() => onSelect(entry.portfolio_id)}
              title={group.portfolios.map(p => p.portfolio_id).join(', ')}
            >
              {portfolioName(group)}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
