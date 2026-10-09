import { useEffect, useRef, useState } from 'react';
import { DeskService } from '../../application/qt/deskService';
import {
  POLL_INTERVAL_MS,
  shouldKeepPolling,
  type DeskCommand,
} from '../../domain/qt/desk';

/**
 * Poll one command row every 2 s until the engine finishes it (done, refused,
 * failed) or 5 minutes pass. `timedOut` is true when polling gave up while the
 * row was still pending or running.
 */
export function useCommandPoll(initial: DeskCommand | null, onFinal?: (c: DeskCommand) => void) {
  const [command, setCommand] = useState<DeskCommand | null>(initial);
  const [timedOut, setTimedOut] = useState(false);
  const onFinalRef = useRef(onFinal);
  onFinalRef.current = onFinal;

  useEffect(() => {
    setCommand(initial);
    setTimedOut(false);
    if (!initial) return;
    const started = Date.now();
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    // onFinal fires only for a row that finished while we watched it, not
    // for one that was already final when handed in.
    const tick = (current: DeskCommand, polled: boolean) => {
      if (cancelled) return;
      if (!shouldKeepPolling(current.status, started, Date.now())) {
        if (current.status === 'pending' || current.status === 'running') setTimedOut(true);
        else if (polled) onFinalRef.current?.(current);
        return;
      }
      timer = setTimeout(async () => {
        try {
          const next = await DeskService.command(current.id);
          if (cancelled) return;
          setCommand(next);
          tick(next, true);
        } catch {
          if (!cancelled) tick(current, polled);
        }
      }, POLL_INTERVAL_MS);
    };
    tick(initial, false);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // Restart only when a different command is handed in.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial?.id]);

  return { command, timedOut };
}
