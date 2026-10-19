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

/**
 * The desk's toggle inside the QT book, by the role each book plays in the day (D-24): the
 * model's proposal (A), the desk's request (B) and the final book that goes out (C).
 */
export const BOOK_TOGGLE_OPTIONS: { book: PositionBook; label: string }[] = [
  { book: 'system', label: 'Proposal (A)' },
  { book: 'qt_proposal', label: 'Request (B)' },
  { book: 'qt', label: 'Final (C)' },
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

/**
 * D-18, D-24: a portfolio as the screens show it. A group is one portfolio, named for its model
 * book (the fund's own, e.g. "Conservative"); a portfolio alone is named for itself.
 */
export function portfolioName(group: PortfolioGroup): string {
  const model = group.portfolios.find(p => !p.desk_editable);
  return (model ?? group.portfolios[0])?.name ?? group.group;
}

/** The book a portfolio opens on: its QT book when it has one (ruling 20), else its model book. */
export function representative(group: PortfolioGroup): PortfolioEntry {
  return group.portfolios.find(p => p.desk_editable) ?? group.portfolios[0];
}

/** The group a portfolio id belongs to. */
export function groupOf(groups: PortfolioGroup[], portfolioId: string | null): PortfolioGroup | null {
  if (!portfolioId) return null;
  return groups.find(g => g.portfolios.some(p => p.portfolio_id === portfolioId)) ?? null;
}

/** One side of a portfolio's Model / QT switch (decision 18, D-68). */
export interface BookChoice {
  key: 'model' | 'qt';
  label: 'Model' | 'QT';
  portfolio: PortfolioEntry;
  /** The book read; null = the API's default (the QT book, or the model book while none). */
  book: PositionBook | null;
}

/**
 * D-68: a portfolio's two books. Model is the group's model book (a portfolio the desk does not
 * edit), or, while the group has none, the QT portfolio's own model rows; QT is the
 * desk-edited book. A portfolio with no QT book has only its model book.
 */
export function bookChoices(group: PortfolioGroup): BookChoice[] {
  const desk = group.portfolios.find(p => p.desk_editable);
  const model = group.portfolios.find(p => !p.desk_editable);
  const choices: BookChoice[] = [];
  if (model) choices.push({ key: 'model', label: 'Model', portfolio: model, book: 'system' });
  else if (desk) choices.push({ key: 'model', label: 'Model', portfolio: desk, book: 'system' });
  if (desk) choices.push({ key: 'qt', label: 'QT', portfolio: desk, book: null });
  return choices;
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
  // D-37: the book named on the toggle has no rows of its own (the model book has no QT book).
  const missing = /"missingBook"\s*:\s*"([a-z_]+)"/.exec(message);
  if (missing) {
    const label = BOOK_TOGGLE_OPTIONS.find(o => o.book === missing[1])?.label ?? missing[1];
    return `This portfolio has no ${label} book: no run has written ${label} rows for it. Its numbers are on its model book.`;
  }
  if (/\b404\b/.test(message)) {
    return 'No run has written this portfolio yet. Its books appear after its first model run.';
  }
  return `Could not load this book: ${message}`;
}

/** The groups holding a desk-edited portfolio (the QT screen). */
export function deskGroups(groups: PortfolioGroup[]): PortfolioGroup[] {
  return groups.filter(group => group.portfolios.some(p => p.desk_editable));
}
