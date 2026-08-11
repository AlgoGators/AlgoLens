import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';
import type { CombinedMetrics } from '@/models';
import { COLORS, STRATEGY_COLORS } from './chartTheme';

interface AllocationChartsProps {
  metrics: CombinedMetrics;
  theme: string;
}

export function AllocationCharts({ metrics, theme }: AllocationChartsProps) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-4">
      <div className={`p-4 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
        }`}>
        <h3 className={`text-xs uppercase tracking-wider mb-3 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
          Asset Allocation
        </h3>
        <ResponsiveContainer width="100%" height={180}>
          <PieChart>
            <Pie
              data={metrics.assetAllocation.slice(0, 5)}
              dataKey="value"
              nameKey="symbol"
              cx="50%"
              cy="50%"
              outerRadius={70}
              label={({ symbol, percentage }) => `${symbol} ${percentage.toFixed(0)}%`}
              labelLine={false}
            >
              {metrics.assetAllocation.slice(0, 5).map((entry, index) => (
                <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                backgroundColor: theme === 'dark' ? '#1f2937' : '#fff',
                border: theme === 'dark' ? '1px solid #374151' : '1px solid #e5e7eb',
                fontSize: '14px',
                fontWeight: '600',
                color: theme === 'dark' ? '#fff' : '#000'
              }}
              formatter={(value: number) => [`$${(value / 1000).toFixed(0)}k`]}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>

      <div className={`p-4 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
        }`}>
        <h3 className={`text-xs uppercase tracking-wider mb-3 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
          Strategy Split
        </h3>
        <ResponsiveContainer width="100%" height={180}>
          <PieChart>
            <Pie
              data={metrics.strategyAllocation}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              outerRadius={70}
              label={({ percentage }) => `${percentage.toFixed(0)}%`}
              labelLine={false}
            >
              {metrics.strategyAllocation.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={STRATEGY_COLORS[index % STRATEGY_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                backgroundColor: theme === 'dark' ? '#1f2937' : '#fff',
                border: theme === 'dark' ? '1px solid #374151' : '1px solid #e5e7eb',
                fontSize: '14px',
                fontWeight: '600',
                color: theme === 'dark' ? '#fff' : '#000'
              }}
              formatter={(value: number) => [`$${(value / 1000).toFixed(0)}k`]}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
