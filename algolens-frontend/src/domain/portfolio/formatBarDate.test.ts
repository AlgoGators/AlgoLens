import { describe, expect, it } from 'vitest';

import { formatBarDate } from './formatBarDate';

describe('a bar keeps its own day', () => {
  it('does not shift the day for a reader west of Greenwich', () => {
    // new Date('2026-08-03').toLocaleDateString() renders "Aug 2" in any
    // negative-offset timezone, which is how a book move dated the 3rd was
    // captioned the 2nd.
    expect(formatBarDate('2026-08-03')).toBe('Aug 3, 2026');
  });

  it('reads a full ISO stamp as its calendar day', () => {
    expect(formatBarDate('2026-08-03T23:30:00Z')).toBe('Aug 3, 2026');
  });

  it('honours a caller-supplied format', () => {
    expect(formatBarDate('2026-08-03', { month: 'long', day: 'numeric' })).toBe(
      'August 3'
    );
  });

  it('crosses a year boundary without drifting', () => {
    expect(formatBarDate('2026-01-01')).toBe('Jan 1, 2026');
    expect(formatBarDate('2025-12-31')).toBe('Dec 31, 2025');
  });
});

describe('what it will not guess at', () => {
  it('returns nothing for nothing', () => {
    expect(formatBarDate(null)).toBe('');
    expect(formatBarDate(undefined)).toBe('');
  });

  it('hands back an unrecognised stamp unchanged', () => {
    expect(formatBarDate('not a date')).toBe('not a date');
  });
});
