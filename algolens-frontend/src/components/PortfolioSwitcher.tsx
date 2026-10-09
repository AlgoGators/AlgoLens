import React from 'react';
import { useTheme } from '../adapters/react/ThemeContext';
import {
  switcherLabel,
  type PortfolioGroup,
} from '../domain/portfolio/portfolioRegistry';

interface PortfolioSwitcherProps {
  groups: PortfolioGroup[];
  selected: string | null;
  onSelect: (portfolioId: string | null) => void;
}

/**
 * The portfolio switcher (ruling 20): sits above everything on the portfolio
 * tab. Related portfolios (one portfolio_group) are shown together, e.g. the
 * QT desk book next to its untouched model twin.
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
        <button type="button" className={chip(selected === null)} onClick={() => onSelect(null)}>
          All strategies
        </button>
        {groups.map(group =>
          group.grouped ? (
            <div
              key={group.group}
              role="group"
              aria-label={group.group}
              className={`flex flex-wrap items-center gap-1 rounded-full px-1 py-0.5 border border-dashed ${
                dark ? 'border-gray-700' : 'border-gray-300'
              }`}
            >
              {group.portfolios.map(entry => (
                <button
                  key={entry.portfolio_id}
                  type="button"
                  className={chip(selected === entry.portfolio_id)}
                  onClick={() => onSelect(entry.portfolio_id)}
                  title={entry.portfolio_id}
                >
                  {switcherLabel(entry)}
                </button>
              ))}
            </div>
          ) : (
            group.portfolios.map(entry => (
              <button
                key={entry.portfolio_id}
                type="button"
                className={chip(selected === entry.portfolio_id)}
                onClick={() => onSelect(entry.portfolio_id)}
                title={entry.portfolio_id}
              >
                {switcherLabel(entry)}
              </button>
            ))
          ),
        )}
      </div>
    </nav>
  );
}
