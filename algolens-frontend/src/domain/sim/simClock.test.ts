import { describe, expect, it } from 'vitest';
import { newYorkClock, simBannerText, simOffsetMs } from './simClock';

describe('sim banner clock', () => {
  it('formats an instant in New York time', () => {
    expect(newYorkClock(Date.parse('2026-10-15T13:29:05Z'))).toBe('2026-10-15 09:29:05');
    expect(newYorkClock(Date.parse('2026-12-01T15:01:00Z'))).toBe('2026-12-01 10:01:00');
  });

  it('says SIMULATION with the clock', () => {
    expect(simBannerText(Date.parse('2026-10-15T14:01:00Z'))).toBe(
      'SIMULATION — clock 2026-10-15 10:01:00 New York',
    );
  });

  it('keeps the server offset so the banner can tick', () => {
    const browser = Date.parse('2026-10-14T20:00:00Z');
    expect(simOffsetMs('2026-10-15T13:30:00+00:00', browser)).toBe(17.5 * 3600 * 1000);
    expect(simOffsetMs('not a time', browser)).toBeNaN();
  });
});
