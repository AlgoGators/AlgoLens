/**
 * The simulator banner (sim/ in the repo). The backend answers GET /api/sim
 * only when SIM_MODE=1; its serverTime is the moved sim clock. The banner
 * keeps the offset between that clock and the browser's, so it can tick
 * between polls.
 */

export const SIM_POLL_MS = 10_000;

export interface SimState {
  sim: boolean;
  serverTime: string;
}

/** Server clock minus browser clock, in ms (NaN when serverTime is unreadable). */
export function simOffsetMs(serverTime: string, browserNowMs: number): number {
  const server = Date.parse(serverTime);
  return Number.isFinite(server) ? server - browserNowMs : Number.NaN;
}

/** "2026-10-15 09:29:05" in New York for an epoch in ms. */
export function newYorkClock(epochMs: number): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date(epochMs));
  const get = (type: string) => parts.find(p => p.type === type)?.value ?? '';
  return `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}:${get('second')}`;
}

export function simBannerText(epochMs: number): string {
  return `SIMULATION — clock ${newYorkClock(epochMs)} New York`;
}
