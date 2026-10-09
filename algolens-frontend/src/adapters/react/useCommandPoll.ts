import { useCallback, useEffect, useRef, useState } from 'react';
import { DeskApiError, DeskService } from '../../application/qt/deskService';
import {
  isFatalPollError,
  pollDelayMs,
  pollPhase,
  shouldKeepPolling,
  type DeskCommand,
  type PollPhase,
} from '../../domain/qt/desk';

/**
 * Poll one command row until the engine finishes it (done, refused, failed):
 * every 2 s for the first minute, then every 15 s, for up to the engine's job
 * timeout (30 min).
 *
 * - `phase` is 'slow' past 5 minutes (still running on the engine, not a
 *   failure) and 'gaveUp' once polling stopped at 30 minutes;
 * - a 4xx answer stops polling and is returned as `error` (asking again would
 *   not change it); network errors and 5xx keep polling;
 * - `refresh()` asks again now and restarts the clock.
 */
export function useCommandPoll(initial: DeskCommand | null, onFinal?: (c: DeskCommand) => void) {
  const [command, setCommand] = useState<DeskCommand | null>(initial);
  const [phase, setPhase] = useState<PollPhase>('normal');
  const [error, setError] = useState<string | null>(null);
  const [generation, setGeneration] = useState(0);
  const onFinalRef = useRef(onFinal);
  onFinalRef.current = onFinal;
  const latest = useRef<DeskCommand | null>(initial);

  useEffect(() => {
    latest.current = initial;
    setCommand(initial);
  }, [initial?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setPhase('normal');
    setError(null);
    const start = latest.current;
    if (!start) return;
    const started = Date.now();
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    // onFinal fires only for a row that finished while we watched it, not
    // for one that was already final when handed in.
    const tick = (current: DeskCommand, polled: boolean) => {
      if (cancelled) return;
      const elapsed = Date.now() - started;
      if (!shouldKeepPolling(current.status, started, Date.now())) {
        if (current.status === 'pending' || current.status === 'running') setPhase('gaveUp');
        else if (polled) onFinalRef.current?.(current);
        return;
      }
      setPhase(pollPhase(elapsed));
      timer = setTimeout(async () => {
        try {
          const next = await DeskService.command(current.id);
          if (cancelled) return;
          latest.current = next;
          setCommand(next);
          tick(next, true);
        } catch (err) {
          if (cancelled) return;
          if (err instanceof DeskApiError && isFatalPollError(err.status)) {
            setError(`Could not read command #${current.id}: ${err.message}`);
            return;
          }
          tick(current, polled);
        }
      }, generation > 0 && !polled ? 0 : pollDelayMs(elapsed));
    };
    tick(start, false);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // Restart when a different command is handed in, or on refresh().
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial?.id, generation]);

  const refresh = useCallback(() => setGeneration(g => g + 1), []);

  return { command, phase, timedOut: phase === 'gaveUp', error, refresh };
}
