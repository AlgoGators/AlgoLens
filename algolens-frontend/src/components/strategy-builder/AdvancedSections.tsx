import { BarChart, Bar, Cell, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts';
import { ChevronUp, ChevronDown } from 'lucide-react';
import type { CombinedMetrics } from '../../domain/portfolio/computeCombinedMetrics';

export type SectionKey = 'diversification' | 'trading' | 'leverage';
export type ExpandedSections = Record<SectionKey, boolean>;

interface AdvancedSectionsProps {
  metrics: CombinedMetrics;
  theme: string;
  expanded: ExpandedSections;
  onToggle: (section: SectionKey) => void;
}

export function AdvancedSections({ metrics, theme, expanded, onToggle }: AdvancedSectionsProps) {
  const headerClass = `w-full p-3 border text-left flex items-center justify-between ${theme === 'dark' ? 'bg-gray-950 border-gray-800 hover:border-gray-700' : 'bg-gray-50 border-gray-200 hover:border-gray-300'
    }`;
  const labelClass = `text-xs uppercase tracking-wider ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
    }`;

  return (
    <div className="space-y-3">
      {/* Correlation Matrix */}
      <button onClick={() => onToggle('diversification')} className={headerClass}>
        <span className={labelClass}>Correlation Matrix (Top 5)</span>
        {expanded.diversification ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
      </button>

      {expanded.diversification && (
        <div className={`p-4 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
          }`}>
          {metrics.advancedMetrics.correlationMatrix.length === 0 ? (
            <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-500'
              }`}>
              Correlation data unavailable — a real correlation matrix needs per-symbol
              price history, which the API does not expose yet (tracked in issue #56).
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr>
                      <th className="p-1 text-left"></th>
                      {metrics.advancedMetrics.topHoldings.map(h => (
                        <th key={h.symbol} className="p-1 text-center font-mono">{h.symbol}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.advancedMetrics.correlationMatrix.map((row, i) => (
                      <tr key={i}>
                        <td className="p-1 font-mono">{metrics.advancedMetrics.topHoldings[i].symbol}</td>
                        {row.map((corr, j) => (
                          <td key={j} className="p-1">
                            <div
                              className="w-12 h-8 flex items-center justify-center text-white text-xs font-mono"
                              style={{
                                backgroundColor: `rgba(${corr > 0.7 ? '239, 68, 68' : corr > 0.4 ? '251, 146, 60' : '34, 197, 94'
                                  }, ${Math.abs(corr) * 0.7 + 0.3})`
                              }}
                            >
                              {corr.toFixed(2)}
                            </div>
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className={`text-xs mt-3 ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'
                }`}>
                ■ Green: Low correlation (0.3-0.4) • ■ Orange: Moderate (0.4-0.7) • ■ Red: High (0.7+)
              </div>
            </>
          )}
        </div>
      )}

      {/* Trading Activity */}
      <button onClick={() => onToggle('trading')} className={headerClass}>
        <span className={labelClass}>Trading Activity & P/L by Symbol</span>
        {expanded.trading ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
      </button>

      {expanded.trading && (
        <div className={`p-4 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
          }`}>
          {/* Trading Stats */}
          <div className="grid grid-cols-4 gap-3 mb-4">
            <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
              }`}>
              <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
                TRADES
              </div>
              <div className="text-base tabular-nums">{metrics.metrics.totalTrades}</div>
            </div>
            <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
              }`}>
              <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
                PROFIT FACTOR
              </div>
              <div className="text-base tabular-nums">{metrics.metrics.profitFactor.toFixed(2)}</div>
            </div>
            <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
              }`}>
              <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
                AVG WIN
              </div>
              <div className="text-base text-green-500 tabular-nums">${metrics.metrics.avgWin.toFixed(0)}</div>
            </div>
            <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
              }`}>
              <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
                AVG LOSS
              </div>
              <div className="text-base text-red-500 tabular-nums">${Math.abs(metrics.metrics.avgLoss).toFixed(0)}</div>
            </div>
          </div>

          {/* P/L by Symbol */}
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={metrics.symbolPnL} layout="vertical">
              <XAxis
                type="number"
                tick={{ fill: theme === 'dark' ? '#6b7280' : '#9ca3af', fontSize: 10 }}
                tickFormatter={(value) => `$${(value / 1000).toFixed(0)}k`}
              />
              <YAxis
                dataKey="symbol"
                type="category"
                tick={{ fill: theme === 'dark' ? '#6b7280' : '#9ca3af', fontSize: 10 }}
                width={50}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: theme === 'dark' ? '#1f2937' : '#fff',
                  border: theme === 'dark' ? '1px solid #374151' : '1px solid #e5e7eb',
                  fontSize: '14px',
                  fontWeight: '600',
                  color: theme === 'dark' ? '#fff' : '#000'
                }}
                itemStyle={{ color: theme === 'dark' ? '#fff' : '#000' }}
                labelStyle={{ color: theme === 'dark' ? '#fff' : '#000' }}
                formatter={(value: number) => [`$${value.toLocaleString()}`, 'P&L']}
              />
              <Bar dataKey="pnl">
                {metrics.symbolPnL.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.pnl >= 0 ? '#10b981' : '#ef4444'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Leverage & Margin */}
      <button onClick={() => onToggle('leverage')} className={headerClass}>
        <span className={labelClass}>Leverage & Margin Metrics</span>
        {expanded.leverage ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
      </button>

      {expanded.leverage && (
        <div className={`p-4 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
          }`}>
          <div className="grid grid-cols-4 gap-3">
            <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
              }`}>
              <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>GROSS LEV</div>
              <div className="text-base tabular-nums">{metrics.metrics.grossLeverage.toFixed(2)}x</div>
            </div>
            <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
              }`}>
              <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>NET LEV</div>
              <div className="text-base tabular-nums">{metrics.metrics.netLeverage.toFixed(2)}x</div>
            </div>
            <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
              }`}>
              <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>EQ/MARGIN</div>
              <div className="text-base tabular-nums">{metrics.metrics.equityToMarginRatio.toFixed(2)}</div>
            </div>
            <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
              }`}>
              <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>CUSHION</div>
              <div className="text-base tabular-nums">{metrics.metrics.marginCushion.toFixed(1)}%</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
