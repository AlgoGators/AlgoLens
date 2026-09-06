/**
 * A daily bar's stamp rendered as its own calendar day.
 *
 * `new Date('2026-08-03')` is parsed as UTC midnight, and `toLocaleDateString`
 * then renders that instant in the reader's timezone -- so everyone west of
 * Greenwich is shown 2 August. Every date on a chart axis, in a tooltip or in a
 * caption is a daily bar's own day, and a bar does not belong to a different
 * day depending on who is looking at it.
 *
 * Parsing the day parts by hand and building a LOCAL date is what keeps it
 * still. A full ISO stamp is reduced to its calendar day first, for the same
 * reason.
 */

const DEFAULT_OPTIONS: Intl.DateTimeFormatOptions = {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
};

export function formatBarDate(
  stamp: string | number | undefined | null,
  options: Intl.DateTimeFormatOptions = DEFAULT_OPTIONS
): string {
  if (stamp == null) return '';

  const day = String(stamp).slice(0, 10);
  const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!parts) {
    // Not a calendar day at all. Hand back what we were given rather than
    // inventing a date from it.
    return String(stamp);
  }

  const local = new Date(
    Number(parts[1]),
    Number(parts[2]) - 1,
    Number(parts[3])
  );
  return local.toLocaleDateString('en-US', options);
}
