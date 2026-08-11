import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useTheme } from '../../adapters/react/ThemeContext';

interface Props {
  data: { date: string; value: number }[];
  positive: boolean;
}

export function IncubationChart({ data, positive }: Props) {
  const { theme } = useTheme();
  const dark = theme === 'dark';

  return (
    <div className="mb-4">
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data}>
          <XAxis dataKey="date" hide />
          <YAxis hide domain={['dataMin - 500', 'dataMax + 500']} />
          <Tooltip
            contentStyle={{
              backgroundColor: dark ? '#1f2937' : '#fff',
              border: dark ? '1px solid #374151' : '1px solid #e5e7eb',
              borderRadius: '8px',
              boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)',
              color: dark ? '#fff' : '#000',
            }}
            formatter={(value: number) => [
              `$${value.toLocaleString('en-US', { minimumFractionDigits: 2 })}`,
              'Mock Equity',
            ]}
            labelFormatter={label =>
              new Date(label).toLocaleDateString('en-US', {
                month: 'short',
                day: 'numeric',
                year: 'numeric',
              })
            }
          />
          <Line
            type="linear"
            dataKey="value"
            stroke={positive ? '#f97316' : '#ef4444'}
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
