import { useRef, useState } from 'react';
import { RotateCcw, XCircle } from 'lucide-react';

import { PortfolioApiService } from '../infrastructure/api/portfolioApi';

type LifecycleAction = 'start' | 'retire';

interface StrategyLifecycleControlsProps {
  strategyId: string;
  strategyName: string;
  lifecycle: string;
  theme: string;
  onChanged: () => void | Promise<void>;
}

const UNCERTAIN_OUTCOME =
  'The request failed before a response was received. The outcome is uncertain; refresh before retrying.';

export function StrategyLifecycleControls({
  strategyId,
  strategyName,
  lifecycle,
  theme,
  onChanged,
}: StrategyLifecycleControlsProps) {
  const [pending, setPending] = useState<LifecycleAction | null>(null);
  const [reason, setReason] = useState('');
  const [mockCapital, setMockCapital] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const isDark = theme === 'dark';
  const parsedCapital = Number(mockCapital);
  const capitalValid = mockCapital.trim() !== '' && Number.isFinite(parsedCapital) && parsedCapital > 0;

  function begin(action: LifecycleAction) {
    setPending(action);
    setReason('');
    setMockCapital('');
    setError(null);
  }

  async function submit() {
    if (!pending || inFlight.current || reason.trim() === '') return;
    if (pending === 'start' && !capitalValid) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const body = pending === 'start'
        ? { reason: reason.trim(), mock_capital: parsedCapital }
        : { reason: reason.trim() };
      const result = await PortfolioApiService.changeIncubation(strategyId, pending, body);
      if (result.outcome === 'rejected') {
        setError(result.message);
        return;
      }
      setPending(null);
      setReason('');
      setMockCapital('');
      await onChanged();
    } catch {
      setError(UNCERTAIN_OUTCOME);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  const buttonBase = 'inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs';

  if (!pending) {
    return (
      <div className="flex flex-wrap items-center justify-end gap-2">
        {lifecycle !== 'incubating' && (
          <button
            aria-label={`${lifecycle === 'retired' ? 'Restart' : 'Start'} incubation for ${strategyName}`}
            onClick={() => begin('start')}
            className={`${buttonBase} ${isDark ? 'hover:bg-gray-800' : 'hover:bg-gray-200'}`}
          >
            <RotateCcw className="w-3.5 h-3.5" />
            {lifecycle === 'retired' ? 'Restart incubation' : 'Start incubation'}
          </button>
        )}
        {lifecycle !== 'retired' && (
          <button
            aria-label={`Mark ${strategyName} retired`}
            onClick={() => begin('retire')}
            className={`${buttonBase} ${isDark ? 'hover:bg-gray-800' : 'hover:bg-gray-200'}`}
          >
            <XCircle className="w-3.5 h-3.5" />
            Mark retired
          </button>
        )}
      </div>
    );
  }

  return (
    <div className={`mt-3 w-full rounded-lg border p-3 ${
      isDark ? 'border-gray-700 bg-gray-950' : 'border-gray-200 bg-white'
    }`}>
      <div className="text-sm font-medium">
        {pending === 'start'
          ? `${lifecycle === 'retired' ? 'Restart' : 'Start'} incubation for ${strategyName}`
          : `Mark ${strategyName} retired`}
      </div>
      <p className={`mt-1 text-xs ${isDark ? 'text-gray-400' : 'text-gray-500'}`}>
        This does not immediately start or stop a process or deploy capital. The
        registry change can block the next engine publication until a separate
        eligible-admin next-run approval is applied.
      </p>
      {pending === 'start' && (
        <div className="mt-3">
          <label className="block text-xs font-medium" htmlFor={`mock-capital-${strategyId}`}>
            Mock capital
          </label>
          <input
            id={`mock-capital-${strategyId}`}
            type="number"
            min="0"
            step="any"
            value={mockCapital}
            onChange={event => setMockCapital(event.target.value)}
            className={`mt-1 w-full rounded-lg border px-2.5 py-1.5 text-sm ${
              isDark ? 'border-gray-700 bg-gray-900 text-white' : 'border-gray-300 bg-white'
            }`}
          />
        </div>
      )}
      <div className="mt-3">
        <label className="block text-xs font-medium" htmlFor={`lifecycle-reason-${strategyId}`}>
          Lifecycle reason
        </label>
        <textarea
          id={`lifecycle-reason-${strategyId}`}
          value={reason}
          onChange={event => setReason(event.target.value)}
          className={`mt-1 min-h-[64px] w-full rounded-lg border px-2.5 py-1.5 text-sm ${
            isDark ? 'border-gray-700 bg-gray-900 text-white' : 'border-gray-300 bg-white'
          }`}
        />
      </div>
      {error && <div role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</div>}
      <div className="mt-3 flex justify-end gap-2">
        <button
          onClick={() => setPending(null)}
          disabled={busy}
          className={`${buttonBase} disabled:opacity-40 ${isDark ? 'bg-gray-800' : 'bg-gray-200'}`}
        >
          Cancel lifecycle change
        </button>
        <button
          onClick={submit}
          disabled={busy || reason.trim() === '' || (pending === 'start' && !capitalValid)}
          className={`${buttonBase} bg-blue-600 text-white disabled:opacity-40`}
        >
          {busy ? 'Saving…' : pending === 'start' ? 'Start incubation' : 'Mark retired'}
        </button>
      </div>
    </div>
  );
}
