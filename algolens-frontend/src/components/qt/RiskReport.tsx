import React from 'react';
import { useTheme } from '../../adapters/react/ThemeContext';
import {
  bookReadings,
  checkUsage,
  formatCheckValue,
  RISK_CHECK_STATUS_LABEL,
  riskBadge,
  riskBindingLine,
  riskChecks,
  riskMovedSymbols,
  riskUnavailable,
  type DeskRiskResult,
  type RiskBadgeTone,
  type RiskCheck,
  type RiskCheckStatus,
} from '../../domain/qt/desk';

function badgeTone(tone: RiskBadgeTone, dark: boolean): string {
  switch (tone) {
    case 'ok':
      return dark ? 'bg-green-950 border-green-800 text-green-200' : 'bg-green-50 border-green-300 text-green-800';
    case 'breach':
      return dark ? 'bg-red-950 border-red-800 text-red-200' : 'bg-red-50 border-red-300 text-red-800';
    case 'waived':
      return dark ? 'bg-amber-950 border-amber-800 text-amber-200' : 'bg-amber-50 border-amber-300 text-amber-900';
    default:
      return dark ? 'bg-gray-900 border-gray-700 text-gray-200' : 'bg-gray-50 border-gray-300 text-gray-800';
  }
}

function statusTone(status: RiskCheckStatus, waived: boolean): RiskBadgeTone {
  if (status === 'within') return 'ok';
  if (status === 'not_measured') return 'muted';
  return waived ? 'waived' : 'breach';
}

function barColor(tone: RiskBadgeTone): string {
  switch (tone) {
    case 'breach':
      return 'bg-red-500';
    case 'waived':
      return 'bg-amber-500';
    case 'muted':
      return 'bg-gray-400';
    default:
      return 'bg-green-500';
  }
}

/** One limit: its name, the stored book against the max, and how much of the max it uses. */
function LimitCard({ check, waived, dark }: { check: RiskCheck; waived: boolean; dark: boolean }) {
  const tone = statusTone(check.status, waived);
  const usage = checkUsage(check);
  const attention = check.status === 'bound' || check.status === 'over';
  const muted = dark ? 'text-gray-400' : 'text-gray-500';
  const frame = attention
    ? badgeTone(tone, dark)
    : dark ? 'border-gray-800 bg-gray-900' : 'border-gray-200 bg-white';
  return (
    <div
      data-testid={`risk-check-${check.term}`}
      title={check.detail || undefined}
      className={`rounded-lg border px-3 py-2 min-w-0 ${frame}`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs truncate" title={check.label}>{check.label}</span>
        {check.status !== 'within' && (
          <span className={`shrink-0 rounded border px-1 text-[10px] uppercase tracking-wide ${badgeTone(tone, dark)}`}>
            {RISK_CHECK_STATUS_LABEL[check.status] ?? check.status}
          </span>
        )}
      </div>
      <div className="mt-1 font-mono text-sm tabular-nums">
        {formatCheckValue(check.value, check.unit)}
        <span className={`text-xs ${muted}`}> / {formatCheckValue(check.max, check.unit)}</span>
      </div>
      <div
        className={`mt-1 h-1 rounded-full ${dark ? 'bg-gray-800' : 'bg-gray-100'}`}
        role="meter"
        aria-label={`${check.label} used`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={usage === null ? undefined : Math.round(usage * 100)}
      >
        {usage !== null && (
          <div className={`h-1 rounded-full ${barColor(tone)}`} style={{ width: `${Math.round(Math.min(usage, 1) * 100)}%` }} />
        )}
      </div>
      {attention && check.detail && <p className="mt-1 text-xs leading-snug">{check.detail}</p>}
    </div>
  );
}

/**
 * The engine's risk check of the day's qt book (contract C9): whether the
 * desk's positions are within the risk limits, every limit with the stored
 * book's reading against its max (trade-ngin's labels, units and maxes,
 * breach or not), the multipliers, and the symbols a step moved. Risk steps
 * (cap, overlay, clip, trim) are breaches; trading rules (sign_close,
 * rounding, buffer, search, hold) are shown but are not. Details sit in the
 * cards' tooltips unless a limit needs attention.
 */
export function RiskReport({ risk }: { risk: DeskRiskResult | null | undefined }) {
  const { theme } = useTheme();
  const dark = theme === 'dark';
  if (!risk) return null;
  const muted = dark ? 'text-gray-400' : 'text-gray-500';
  const rule = dark ? 'border-t border-gray-800' : 'border-t border-gray-200';
  const badge = riskBadge(risk);
  const badgeEl = (
    <span
      data-testid="risk-badge"
      className={`inline-block rounded border px-2 py-0.5 text-sm font-medium ${badgeTone(badge.tone, dark)}`}
    >
      {badge.label}
    </span>
  );

  if (riskUnavailable(risk)) {
    return (
      <div className="mt-4" data-testid="risk-report">
        <h4 className={`text-xs uppercase tracking-wider mb-2 ${muted}`}>Risk check</h4>
        {badgeEl}
        <p className={`mt-1 text-xs ${muted}`}>Approval stays closed until the risk check can be read.</p>
      </div>
    );
  }

  const binding = riskBindingLine(risk);
  const checks = riskChecks(risk);
  const readings = bookReadings(risk);
  const multipliers = risk.multipliers ?? [];
  const moved = riskMovedSymbols(risk);
  const waived = risk.approvedOverride;
  const riskMoves = moved.some(s => s.category === 'risk');

  return (
    <div className="mt-4" data-testid="risk-report">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className={`text-xs uppercase tracking-wider ${muted}`}>Risk check</h4>
        {badgeEl}
        {binding && <span className="text-sm">{binding}</span>}
      </div>

      {risk.breaches.length > 0 && (
        <ul className={`mt-2 space-y-0.5 text-xs ${waived ? muted : ''}`} data-testid="risk-breaches">
          {risk.breaches.map((b, i) => (
            <li key={`${b.term}-${i}`}>
              <span className="font-mono">{b.term}</span> · {b.detail}
            </li>
          ))}
        </ul>
      )}

      {checks.length > 0 && (
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4" data-testid="risk-limits">
          {checks.map(c => (
            <LimitCard key={c.term} check={c} waived={waived} dark={dark} />
          ))}
        </div>
      )}

      {(multipliers.length > 0 || readings.length > 0) && (
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs" data-testid="risk-multipliers">
          {multipliers.map(x => (
            <span key={x.name} title={x.detail || undefined} data-testid={`risk-multiplier-${x.name}`}>
              <span className={muted}>{x.label}</span>{' '}
              <span className="font-mono">
                {x.value === null || !Number.isFinite(x.value) ? '-' : Number(x.value.toPrecision(4))}
              </span>
            </span>
          ))}
          {readings.map(r => (
            <span key={r.label}>
              <span className={muted}>{r.label}</span> <span className="font-mono">{r.value}</span>
            </span>
          ))}
        </div>
      )}

      {moved.length > 0 && (
        <details className="mt-3" open={riskMoves && !waived}>
          <summary className={`cursor-pointer text-xs ${muted}`}>
            Symbols the engine moved ({moved.length}
            {riskMoves ? ', by a risk limit' : ', by trading rules only'})
          </summary>
          <div className="mt-1 overflow-x-auto">
            <table className="w-full text-sm" data-testid="risk-symbols">
              <thead>
                <tr className={muted}>
                  <th className="text-left font-normal py-1 pr-4">Symbol</th>
                  <th className="text-right font-normal py-1 pr-4">Asked</th>
                  <th className="text-right font-normal py-1 pr-4">Given</th>
                  <th className="text-left font-normal py-1">Moved by</th>
                </tr>
              </thead>
              <tbody>
                {moved.map(s => (
                  <tr key={s.symbol} className={rule}>
                    <td className="py-1 pr-4">{s.symbol}</td>
                    <td className="py-1 pr-4 text-right font-mono">{s.asked}</td>
                    <td className="py-1 pr-4 text-right font-mono">{s.given}</td>
                    <td className="py-1">
                      {s.movedBy}{' '}
                      <span
                        className={`ml-1 rounded border px-1 text-[10px] uppercase ${badgeTone(
                          s.category === 'risk' ? (waived ? 'waived' : 'breach') : 'muted',
                          dark,
                        )}`}
                        title={s.category === 'risk' ? 'a risk limit' : 'a trading rule, not a breach'}
                      >
                        {s.category === 'risk' ? 'risk' : 'rule'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}
