/**
 * The one-line hint above the quantity boxes: what kind of number each editable
 * instrument takes. It names only the asset types that are present and that it
 * has words for, so an unfamiliar type adds nothing (and never leaves a bare
 * full stop behind). Pure text; no effect on what may be entered.
 */
export const QUANTITY_PHRASES: Readonly<Record<string, string>> = {
  FUTURE: 'Whole contracts for futures',
  EQUITY: 'fractions allowed for equities',
};

export function quantityHint(types: Iterable<string>, phrases: Readonly<Record<string, string>> = QUANTITY_PHRASES): string | null {
  const present = new Set(types);
  const parts = Object.entries(phrases)
    .filter(([type]) => present.has(type))
    .map(([, phrase]) => phrase.trim().replace(/\.+$/, ''))
    .filter(phrase => phrase.length > 0);
  if (parts.length === 0) return null;
  const sentence = parts.join('; ');
  return `${sentence.charAt(0).toUpperCase()}${sentence.slice(1)}.`;
}
