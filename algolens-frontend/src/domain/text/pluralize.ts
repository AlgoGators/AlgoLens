/**
 * The right noun for a count, and the count with it.
 *
 * Written down once because it was being written down each time it was needed,
 * and skipped in four places: "1 Holdings", "1 positions", "1 incubating
 * strategies", "1 days".
 */
export function pluralize(count: number, singular: string, plural?: string): string {
  return count === 1 ? singular : plural ?? `${singular}s`;
}

/** The count and its noun: `counted(1, 'position')` is "1 position". */
export function counted(count: number, singular: string, plural?: string): string {
  return `${count} ${pluralize(count, singular, plural)}`;
}
