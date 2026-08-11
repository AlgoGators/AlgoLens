import { useTheme } from '../../adapters/react/ThemeContext';

interface Props {
  progress: number;
  daysRemaining: number;
  positionsCount: number;
}

function StatCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs mb-1 uppercase tracking-wider text-gray-500">{label}</div>
      <div className="text-2xl">{value}</div>
    </div>
  );
}

export function IncubationStats({ progress, daysRemaining, positionsCount }: Props) {
  const { theme } = useTheme();

  return (
    <div
      className={`grid grid-cols-1 md:grid-cols-3 gap-4 mb-8 border-y py-4 ${
        theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
      }`}
    >
      <StatCell label="Progress" value={`${Math.round(progress)}%`} />
      <StatCell label="Remaining" value={`${daysRemaining}d`} />
      <StatCell label="Positions" value={String(positionsCount)} />
    </div>
  );
}
