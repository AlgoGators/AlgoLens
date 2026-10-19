/**
 * Which position book a strategy detail response was served from.
 *
 * The API opens on the QT book and falls back to the system book while no QT
 * rows exist for a portfolio; `fellBack` says when that happened.
 */
export type PositionBook = 'system' | 'qt_proposal' | 'qt';

// D-24: the books by the names the desk and the members use (Model and QT, the request B).
const BOOK_NAMES: Record<PositionBook, string> = {
  system: 'Model book',
  qt_proposal: 'Request (B)',
  qt: 'QT book',
};

export function describeServedBook(served: {
  book?: string;
  fellBack?: boolean;
}): string | null {
  if (!served.book) return null;
  const name = BOOK_NAMES[served.book as PositionBook] ?? served.book;
  return served.fellBack ? `${name} (no QT book yet)` : name;
}
