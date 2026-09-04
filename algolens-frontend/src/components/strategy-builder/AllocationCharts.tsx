import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';
import type { CombinedMetrics } from '../../domain/portfolio/computeCombinedMetrics';
import { COLORS, STRATEGY_COLORS } from './chartTheme';

interface AllocationChartsProps {
  metrics: CombinedMetrics;
  theme: string;
}

/*
 * Both pies are 200px tall, not 180.
 *
 * Recharts places a slice's label outside the arc at its mid-angle, and a
 * slice big enough to sit astride 12 o'clock has a mid-angle of ~90 degrees,
 * which put its label at y = 12 in a 180px chart. The text is centred on that
 * point, so it straddled the top edge and was cut off: the Strategy Split pie
 * showed "21%" and "29%" and nothing at all for the 49.8% slice, the largest
 * one on the chart. Twenty more pixels puts that label at y = 22, level with
 * the highest label the asset pie already renders cleanly.
 */
export function AllocationCharts({ metrics, theme }: AllocationChartsProps) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-4">
      <div className={`p-4 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
        }`}>
        <h3 className={`text-xs uppercase tracking-wider mb-3 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
          Asset Allocation
        </h3>
        <ResponsiveContainer width="100%" height={200}>
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
        <ResponsiveContainer width="100%" height={200}>
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
