/**
 * A futures price, shown to the precision the contract actually trades in.
 *
 * Fixing this at two decimals broke the arithmetic on the row: natural gas
 * closed at 2.958 and rendered as "$2.96", so a reader multiplying the
 * displayed price by the quantity and the contract size got $888,000 where
 * the Notional column correctly said $887,400. Equities-style cent precision
 * does not fit a book that also holds Euro FX at 1.0915.
 *
 * Two decimals minimum so an index future still reads as money, four maximum
 * so the smallest tick in this universe survives. Trailing zeros beyond the
 * second decimal are dropped, so ES stays "$5,310.75".
 */
export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '\u2014';
  return `$${value.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  })}`;
}

/**
 * A dollar figure for a chart axis.
 *
 * The P&L-by-symbol axis divided by 1,000 and rounded to whole thousands, so a
 * chart whose largest bar was $640 of realised P&L labelled its ticks
 * "$0k $0k $0k $1k $1k". Thousands are only a useful unit once there are
 * thousands to show.
 */
export function formatAxisDollars(value: number): string {
  if (!Number.isFinite(value)) return '';
  if (Math.abs(value) >= 10000) return `$${(value / 1000).toFixed(0)}k`;
  if (Math.abs(value) >= 1000) return `$${(value / 1000).toFixed(1)}k`;
  return `$${Math.round(value)}`;
}

/**
 * A percentage for a chart axis.
 *
 * Whole percent is right for a chart spanning tens of points and useless for
 * one spanning less than a point, where every tick rounds to the same number.
 */
export function formatAxisPercent(value: number): string {
  if (!Number.isFinite(value)) return '';
  if (Math.abs(value) >= 10) return `${value.toFixed(0)}%`;
  if (Math.abs(value) >= 1) return `${value.toFixed(1)}%`;
  return `${value.toFixed(2)}%`;
}
