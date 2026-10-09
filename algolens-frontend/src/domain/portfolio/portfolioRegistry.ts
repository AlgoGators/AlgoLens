import type { PositionBook } from './bookLabel';

/** One book, keyed by its portfolio id (registry row, AlgoLens#102). */
export interface PortfolioEntry {
  portfolio_id: string;
  id: string;
  name: string;
  description: string;
  strategy_type: string;
  asset_class: 'futures' | 'equity';
  portfolio_group: string | null;
  desk_editable: boolean;
}

/** Portfolios shown together in the switcher (strategy_registry.portfolio_group). */
export interface PortfolioGroup {
  group: string;
  grouped: boolean;
  portfolios: PortfolioEntry[];
}

export interface PortfolioList {
  groups: PortfolioGroup[];
  deskEnabled: boolean;
}

/** The toggle inside a portfolio, in the order the desk works through a day. */
export const BOOK_TOGGLE_OPTIONS: { book: PositionBook; label: string }[] = [
  { book: 'system', label: 'System' },
  { book: 'qt_proposal', label: 'QT proposal' },
  { book: 'qt', label: 'QT' },
];

/**
 * Which toggle is highlighted. Until the user picks a book the page shows
 * the API's default (qt, or system when no qt book exists yet), so the served
 * book is the honest answer; after a pick, the pick.
 */
export function activeToggleBook(
  requested: PositionBook | null,
  served: string | undefined,
): PositionBook {
  if (requested) return requested;
  if (served === 'system' || served === 'qt_proposal' || served === 'qt') return served;
  return 'qt';
}

/** Query string for a book request: none for the default (qt with fallback). */
export function bookQuery(requested: PositionBook | null): string {
  return requested ? `?book=${encodeURIComponent(requested)}` : '';
}

/** A short label for a switcher entry; the desk-edited book is marked. */
export function switcherLabel(entry: PortfolioEntry): string {
  return entry.desk_editable ? `${entry.name} (desk)` : entry.name;
}

/** Find an entry by portfolio id across all groups. */
export function findPortfolio(
  groups: PortfolioGroup[],
  portfolioId: string | null,
): PortfolioEntry | null {
  if (!portfolioId) return null;
  for (const group of groups) {
    const hit = group.portfolios.find(p => p.portfolio_id === portfolioId);
    if (hit) return hit;
  }
  return null;
}

/**
 * A plain sentence for a book that could not be loaded. A 404 from the
 * portfolio endpoint means no run has written the portfolio yet (e.g. a new
 * QT portfolio before its first model run), not a fault.
 */
export function describeBookLoadError(message: string): string {
  if (/\b404\b/.test(message)) {
    return 'No run has written this portfolio yet. Its books appear after its first model run.';
  }
  return `Could not load this book: ${message}`;
}
