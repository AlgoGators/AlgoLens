import React from 'react';
import { useTheme } from '../../adapters/react/ThemeContext';
import {
  formatRiskValue,
  riskBadge,
  riskBindingLine,
  riskMovedSymbols,
  riskReadings,
  riskUnavailable,
  type DeskRiskResult,
  type RiskBadgeTone,
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

/**
 * The engine's risk check of the day's qt book (contract C9): whether the
 * desk's positions are within the risk limits, which limit bound and by how
 * much, the configured limits next to the stored book, and the symbols a step
 * moved. Risk steps (cap, overlay, clip, trim) are breaches; trading rules
 * (sign_close, rounding, buffer, search, hold) are shown but are not.
 */
export function RiskReport({ risk }: { risk: DeskRiskResult | null | undefined }) {
  const { theme } = useTheme();
  const dark = theme === 'dark';
  if (!risk) return null;
  const muted = dark ? 'text-gray-400' : 'text-gray-500';
  const rule = dark ? 'border-t border-gray-800' : 'border-t border-gray-200';
  const badge = riskBadge(risk);
  const header = <h4 className={`text-xs uppercase tracking-wider mb-2 ${muted}`}>Risk check</h4>;
  const badgeEl = (
    <span
      data-testid="risk-badge"
      className={`inline-block rounded border px-2 py-1 text-sm font-medium ${badgeTone(badge.tone, dark)}`}
    >
      {badge.label}
    </span>
  );

  if (riskUnavailable(risk)) {
    return (
      <div className="mt-4" data-testid="risk-report">
        {header}
        {badgeEl}
        <p className={`mt-1 text-xs ${muted}`}>Approval stays closed until the risk check can be read.</p>
      </div>
    );
  }

  const binding = riskBindingLine(risk);
  const readings = riskReadings(risk).filter(r => r.reading !== null || r.limit !== null);
  const moved = riskMovedSymbols(risk);
  const waived = risk.approvedOverride;

  return (
    <div className="mt-4" data-testid="risk-report">
      {header}
      {badgeEl}
      {binding && <p className="mt-2 text-sm">{binding}</p>}

      {risk.breaches.length > 0 && (
        <ul className={`mt-2 list-disc pl-5 text-sm ${waived ? muted : ''}`} data-testid="risk-breaches">
          {risk.breaches.map((b, i) => (
            <li key={`${b.term}-${i}`}>
              <span className="font-mono">{b.term}</span>: {b.detail}
            </li>
          ))}
        </ul>
      )}

      {readings.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="text-sm" data-testid="risk-limits">
            <thead>
              <tr className={muted}>
                <th className="text-left font-normal py-1 pr-4">Measure</th>
                <th className="text-right font-normal py-1 pr-4">Stored book</th>
                <th className="text-right font-normal py-1">Limit</th>
              </tr>
            </thead>
            <tbody>
              {readings.map(r => (
                <tr key={r.label} className={`${rule} ${r.over ? (dark ? 'text-red-300' : 'text-red-700') : ''}`}>
                  <td className="py-1 pr-4">{r.label}</td>
                  <td className="py-1 pr-4 text-right">{formatRiskValue(r.reading, r.format)}</td>
                  <td className="py-1 text-right">{formatRiskValue(r.limit, r.format)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {moved.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm" data-testid="risk-symbols">
            <thead>
              <tr className={muted}>
                <th className="text-left font-normal py-1 pr-4">Symbol</th>
                <th className="text-right font-normal py-1 pr-4">Asked</th>
                <th className="text-right font-normal py-1 pr-4">Given</th>
                <th className="text-left font-normal py-1 pr-4">Moved by</th>
                <th className="text-left font-normal py-1" />
              </tr>
            </thead>
            <tbody>
              {moved.map(s => (
                <tr key={s.symbol} className={rule}>
                  <td className="py-1 pr-4">{s.symbol}</td>
                  <td className="py-1 pr-4 text-right">{s.asked}</td>
                  <td className="py-1 pr-4 text-right">{s.given}</td>
                  <td className="py-1 pr-4">{s.movedBy}</td>
                  <td className="py-1">
                    {s.category === 'risk' ? (
                      <span
                        className={`rounded border px-1 text-xs ${badgeTone(waived ? 'waived' : 'breach', dark)}`}
                      >
                        risk
                      </span>
                    ) : (
                      <span className={`text-xs ${muted}`}>
                        <span className={`rounded border px-1 ${badgeTone('muted', dark)}`}>rule</span> trading rule,
                        not a breach
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
