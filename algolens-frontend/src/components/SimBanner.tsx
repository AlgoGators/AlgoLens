import { useEffect, useState } from 'react';
import { SIM_POLL_MS, simBannerText, simOffsetMs } from '../domain/sim/simClock';
import { fetchSimState } from '../infrastructure/api/simApi';

/**
 * A fixed banner shown only by the local simulator (backend SIM_MODE=1). On a
 * real deployment GET /api/sim is a 404 and this renders nothing and stops.
 */
export function SimBanner() {
  const [offsetMs, setOffsetMs] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let stopped = false;
    let poll: ReturnType<typeof setInterval> | undefined;
    const refresh = async () => {
      const state = await fetchSimState();
      if (stopped) return;
      if (!state) {
        if (poll) clearInterval(poll);
        return;
      }
      const offset = simOffsetMs(state.serverTime, Date.now());
      if (Number.isFinite(offset)) setOffsetMs(offset);
    };
    refresh().then(() => {
      if (!stopped) poll = setInterval(refresh, SIM_POLL_MS);
    });
    return () => {
      stopped = true;
      if (poll) clearInterval(poll);
    };
  }, []);

  useEffect(() => {
    if (offsetMs === null) return;
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(tick);
  }, [offsetMs]);

  if (offsetMs === null) return null;
  return (
    // Inline styles: index.css is a precompiled Tailwind build, so a class it
    // does not already contain would do nothing.
    <div
      role="status"
      style={{
        position: 'fixed',
        top: 0,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 9999,
        pointerEvents: 'none',
        padding: '2px 12px',
        borderRadius: '0 0 6px 6px',
        background: '#f59e0b',
        color: '#000',
        fontSize: 12,
        fontWeight: 600,
        whiteSpace: 'nowrap',
      }}
    >
      {simBannerText(now + offsetMs)}
    </div>
  );
}
