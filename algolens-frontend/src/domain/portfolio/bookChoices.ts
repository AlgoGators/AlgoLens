import type { PortfolioSummary } from './portfolioAssignment';

/**
 * One book a strategy can be read in, as offered by the book box on its page.
 */
export type BookChoice = {
  portfolioId: string;
  isPrimary: boolean;
  /**
   * The strategy's value in this book.
   *   number     published
   *   null       the engine has published nothing for this pairing yet
   *   undefined  not known (the book summary has not loaded, or omits it)
   */
  currentValue?: number | null;
  /** Set when the strategy is trading mock capital in this book. */
  mockCapital?: number | null;
};

const same = (a: string, b: string) => a.toUpperCase() === b.toUpperCase();

/** Every distinct book, case-insensitively: a legacy lower-case row is the same book. */
export function distinctBooks(books: readonly string[] | undefined): string[] {
  const out: string[] = [];
  for (const b of books ?? []) {
    if (b && !out.some(o => same(o, b))) out.push(b);
  }
  return out;
}

/**
 * The books to offer, primary first and the rest alphabetically.
 *
 * Values, when a per-book summary is supplied, say which book holds what and
 * which has nothing in it yet.
 */
export function bookChoices(
  strategyId: string,
  books: readonly string[] | undefined,
  primary: string | undefined,
  portfolios?: readonly PortfolioSummary[] | null,
): BookChoice[] {
  const choices = distinctBooks(books).map(portfolioId => {
    const isPrimary = primary !== undefined && same(portfolioId, primary);
    const row = portfolios
      ?.find(p => same(p.portfolio_id, portfolioId))
      ?.strategies.find(s => s.id === strategyId);
    const choice: BookChoice = { portfolioId, isPrimary };
    if (row) {
      if (row.lifecycle === 'incubating') {
        choice.mockCapital = row.mock_capital ?? null;
      } else {
        choice.currentValue = row.current_value;
      }
    }
    return choice;
  });

  return choices.sort((a, b) => {
    if (a.isPrimary !== b.isPrimary) return a.isPrimary ? -1 : 1;
    return a.portfolioId.localeCompare(b.portfolioId);
  });
}
