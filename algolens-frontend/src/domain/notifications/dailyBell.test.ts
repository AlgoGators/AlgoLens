import { describe, expect, it } from 'vitest';
import { dailyBellDue, newYorkDate } from './dailyBell';

describe('dailyBellDue (D-26)', () => {
  it('lights at 09:30 New York in daylight time (13:30 UTC)', () => {
    expect(dailyBellDue(Date.parse('2026-10-15T13:29:59Z'))).toBeNull();
    expect(dailyBellDue(Date.parse('2026-10-15T13:30:00Z'))).toBe('2026-10-15');
  });

  it('lights at 09:30 New York in standard time (14:30 UTC)', () => {
    expect(dailyBellDue(Date.parse('2026-12-15T14:29:59Z'))).toBeNull();
    expect(dailyBellDue(Date.parse('2026-12-15T14:30:00Z'))).toBe('2026-12-15');
  });

  it('stays lit to the end of the New York day', () => {
    // 23:59 New York on 10-15 is 03:59 UTC on 10-16.
    expect(dailyBellDue(Date.parse('2026-10-16T03:59:00Z'))).toBe('2026-10-15');
    expect(dailyBellDue(Date.parse('2026-10-16T04:00:00Z'))).toBeNull();
  });

  it('names the New York date, not the UTC one', () => {
    expect(newYorkDate(Date.parse('2026-10-16T02:00:00Z'))).toBe('2026-10-15');
  });
});
