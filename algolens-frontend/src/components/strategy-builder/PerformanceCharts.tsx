import { LineChart, Line, BarChart, Bar, Cell, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts';
import { formatAxisDollars, formatAxisPercent } from '../../domain/portfolio/formatPrice';
import type { CombinedMetrics } from '../../domain/portfolio/computeCombinedMetrics';
import { formatBarDate } from '../../domain/portfolio/formatBarDate';

interface PerformanceChartsProps {
  metrics: CombinedMetrics;
  theme: string;
}

export function PerformanceCharts({ metrics, theme }: PerformanceChartsProps) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-4">
      {/* Daily PnL */}
      <div className={`p-4 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
        }`}>
        <h3 className={`text-xs uppercase tracking-wider mb-3 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
          Daily P&L (30D)
        </h3>
        {!metrics.coverage.comparableDailyReturns && (
          <p className={`mb-2 text-xs ${theme === 'dark' ? 'text-amber-400' : 'text-amber-700'}`}>
            Unavailable: common coverage does not support comparable daily returns.
          </p>
        )}
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={metrics.dailyPnL}>
            <XAxis
              dataKey="date"
              tick={{ fill: theme === 'dark' ? '#6b7280' : '#9ca3af', fontSize: 10 }}
              tickFormatter={(value) => {
                return formatBarDate(String(value), { month: 'numeric', day: 'numeric' });
              }}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fill: theme === 'dark' ? '#6b7280' : '#9ca3af', fontSize: 10 }}
              tickFormatter={formatAxisDollars}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: theme === 'dark' ? '#1f2937' : '#fff',
                border: theme === 'dark' ? '1px solid #374151' : '1px solid #e5e7eb',
                borderRadius: '4px',
                fontSize: '12px',
                color: theme === 'dark' ? '#fff' : '#000'
              }}
              formatter={(value: number) => [`$${value.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`, 'P&L']}
            />
            <Bar dataKey="pnl">
              {metrics.dailyPnL.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.pnl >= 0 ? '#10b981' : '#ef4444'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Cumulative Return */}
      <div className={`p-4 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
        }`}>
        <h3 className={`text-xs uppercase tracking-wider mb-3 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
          Cumulative Return (90D)
        </h3>
        {metrics.coverage.partial && (
          <p className={`mb-2 text-xs ${theme === 'dark' ? 'text-amber-400' : 'text-amber-700'}`}>
            Common coverage only; {metrics.coverage.excludedDates.length} excluded {metrics.coverage.excludedDates.length === 1 ? 'date' : 'dates'}.
          </p>
        )}
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={metrics.historicalPerformance}>
            <XAxis
              dataKey="date"
              tick={{ fill: theme === 'dark' ? '#6b7280' : '#9ca3af', fontSize: 10 }}
              tickFormatter={(value) => {
                return formatBarDate(String(value), { month: 'numeric', day: 'numeric' });
              }}
              interval="preserveStartEnd"
            />
            {/* Whole percent hid the whole axis on a book whose 90-day range
                is under a point: every tick read "0%". Same fault as the P&L
                axis that read "$0k $0k $0k". */}
            <YAxis
              tick={{ fill: theme === 'dark' ? '#6b7280' : '#9ca3af', fontSize: 10 }}
              tickFormatter={formatAxisPercent}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: theme === 'dark' ? '#1f2937' : '#fff',
                border: theme === 'dark' ? '1px solid #374151' : '1px solid #e5e7eb',
                borderRadius: '4px',
                fontSize: '12px',
                color: theme === 'dark' ? '#fff' : '#000'
              }}
              formatter={(value: number) => [`${value.toFixed(2)}%`, 'Return']}
            />
            <Line
              type="monotone"
              dataKey="return"
              stroke="#f97316"
              strokeWidth={2}
              dot={false}
              connectNulls={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
