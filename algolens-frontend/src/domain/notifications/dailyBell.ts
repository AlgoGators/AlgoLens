import { newYorkClock } from '../sim/simClock';

/** The New York date ("2026-10-15") of an epoch in ms. */
export function newYorkDate(epochMs: number): string {
  return newYorkClock(epochMs).slice(0, 10);
}

/**
 * D-26: the header bell lights from 09:30 New York, in daylight time too (it used a fixed
 * UTC-5, so from March to November it lit at 10:30). Returns the New York date the bell is
 * due for, or null before 09:30 that day.
 */
export function dailyBellDue(epochMs: number): string | null {
  const clock = newYorkClock(epochMs);
  const hours = Number(clock.slice(11, 13));
  const minutes = Number(clock.slice(14, 16));
  return hours > 9 || (hours === 9 && minutes >= 30) ? clock.slice(0, 10) : null;
}
