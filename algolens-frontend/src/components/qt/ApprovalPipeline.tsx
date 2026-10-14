import React, { useState } from 'react';
import { useTheme } from '../../adapters/react/ThemeContext';
import {
  acceptCBlockedReason,
  approvalPipeline,
  type DeskState,
  type PipelineStage,
} from '../../domain/qt/desk';

const STEPS: { key: string; label: string; stages: PipelineStage[] }[] = [
  { key: 'a', label: "A · model's book", stages: ['a', 'fallback'] },
  { key: 'b', label: 'B · your positions', stages: ['b'] },
  { key: 'c', label: 'C · dynopt + risk', stages: ['checking', 'choose'] },
  { key: 'done', label: 'Approved', stages: ['approved', 'sent'] },
];

interface ApprovalPipelineProps {
  state: DeskState;
  nowMs: number;
  busy: boolean;
  onApproveC: (acknowledged: string[]) => void;
  onAskForB: () => void;
}

/**
 * The A -> B -> C approval (contract C10): where the day stands, and, when the
 * engine's book (C) differs from the desk's positions (B), the desk's choice:
 * approve C knowing it differs, or ask the VP or President to approve B.
 */
export function ApprovalPipeline({ state, nowMs, busy, onApproveC, onAskForB }: ApprovalPipelineProps) {
  const { theme } = useTheme();
  const dark = theme === 'dark';
  const [acknowledged, setAcknowledged] = useState(false);
  const pipeline = approvalPipeline(state);
  const current = STEPS.findIndex(s => s.stages.includes(pipeline.stage));
  const muted = dark ? 'text-gray-400' : 'text-gray-500';
  const rule = dark ? 'border-t border-gray-800' : 'border-t border-gray-200';
  const acceptBlocked = pipeline.stage === 'choose' ? acceptCBlockedReason(state, nowMs) : null;
  const symbols = pipeline.differences.map(d => d.symbol);

  return (
    <div className="mt-3" data-testid="approval-pipeline">
      <ol className="flex flex-wrap items-center gap-1 text-xs" aria-label="Approval steps">
        {STEPS.map((step, i) => {
          const reached = i <= current;
          const here = i === current;
          return (
            <li key={step.key} className="flex items-center gap-1">
              <span
                data-testid={`pipeline-step-${step.key}`}
                aria-current={here ? 'step' : undefined}
                className={`rounded-full border px-2 py-0.5 ${
                  here
                    ? 'border-orange-500 bg-orange-500 text-white'
                    : reached
                      ? dark ? 'border-orange-800 text-orange-300' : 'border-orange-300 text-orange-700'
                      : dark ? 'border-gray-700 text-gray-500' : 'border-gray-300 text-gray-400'
                }`}
              >
                {step.label}
              </span>
              {i < STEPS.length - 1 && <span className={muted}>→</span>}
            </li>
          );
        })}
      </ol>
      <p className="mt-2 text-sm font-medium" data-testid="pipeline-title">{pipeline.title}</p>
      <p className={`text-xs ${muted}`}>{pipeline.detail}</p>

      {pipeline.stage === 'choose' && (
        <div
          data-testid="pipeline-choice"
          role="alert"
          className={`mt-3 rounded border px-3 py-2 text-sm ${
            dark ? 'border-amber-800 bg-amber-950 text-amber-100' : 'border-amber-300 bg-amber-50 text-amber-900'
          }`}
        >
          {pipeline.differences.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="pipeline-differences">
                <thead>
                  <tr className="opacity-70">
                    <th className="text-left font-normal py-1 pr-4">Symbol</th>
                    <th className="text-right font-normal py-1 pr-4">B (yours)</th>
                    <th className="text-right font-normal py-1 pr-4">C (engine)</th>
                    <th className="text-left font-normal py-1">Changed by</th>
                  </tr>
                </thead>
                <tbody>
                  {pipeline.differences.map(d => (
                    <tr key={d.symbol} className={rule}>
                      <td className="py-1 pr-4">{d.symbol}</td>
                      <td className="py-1 pr-4 text-right font-mono">{d.asked}</td>
                      <td className="py-1 pr-4 text-right font-mono">{d.given}</td>
                      <td className="py-1">
                        {d.moved_by}
                        {d.category === 'risk' ? ' (risk limit)' : d.category === 'rule' ? ' (trading rule)' : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="mt-3 flex flex-col gap-2">
            {pipeline.reason === 'changed' && (
              <>
                <label className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    data-testid="accept-c-ack"
                    checked={acknowledged}
                    onChange={e => setAcknowledged(e.target.checked)}
                    disabled={busy || acceptBlocked !== null}
                  />
                  <span>
                    I approve the engine's book (C) knowing it differs from my positions in {symbols.join(', ')}.
                  </span>
                </label>
                <div>
                  <button
                    type="button"
                    data-testid="accept-c-button"
                    className="px-3 py-1 rounded bg-orange-500 text-white disabled:opacity-50"
                    disabled={busy || !acknowledged || acceptBlocked !== null}
                    title={acceptBlocked ?? undefined}
                    onClick={() => onApproveC(symbols)}
                  >
                    Approve C
                  </button>
                  {acceptBlocked && <span className="ml-2 text-xs">{acceptBlocked}</span>}
                </div>
              </>
            )}
            <div>
              <button
                type="button"
                data-testid="ask-for-b-button"
                className="px-3 py-1 rounded border disabled:opacity-50"
                disabled={busy}
                onClick={onAskForB}
              >
                Ask the VP or President to approve B
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
