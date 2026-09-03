/**
 * Render a metric that may be unknown.
 *
 * The API sends null for a figure the engine did not publish or that is
 * mathematically undefined (a Sharpe ratio with zero volatility, a profit
 * factor with no losses, a best day with no days). Rendering null as 0 turns
 * "not known" into a claim -- "0.00x leverage", "$0 margin posted" -- so every
 * tile goes through here and shows an em dash instead.
 */
export function formatMetric(
  value: number | null | undefined,
  digits: number,
  opts: { prefix?: string; suffix?: string; signed?: boolean; abs?: boolean } = {},
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '\u2014';
  const shown = opts.abs ? Math.abs(value) : value;
  const sign = opts.signed && shown >= 0 ? '+' : '';
  return `${sign}${opts.prefix ?? ''}${shown.toFixed(digits)}${opts.suffix ?? ''}`;
}

/** Thousands, e.g. 541200 -> "$541.2k". Unknown stays unknown. */
export function formatThousands(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '\u2014';
  return `$${(value / 1000).toFixed(digits)}k`;
}
