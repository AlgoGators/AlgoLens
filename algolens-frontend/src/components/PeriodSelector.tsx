import type { Period } from '@/lib/filterByPeriod';
import { useTheme } from '../adapters/react/ThemeContext';

interface PeriodSelectorProps {
  periods: Period[];
  selected: Period;
  onSelect: (period: Period) => void;
}

/** Underlined period tab row shared by the portfolio, strategy and incubation views. */
export function PeriodSelector({ periods, selected, onSelect }: PeriodSelectorProps) {
  const { theme } = useTheme();

  return (
    <div
      className={`flex items-center justify-between mb-8 border-b ${
        theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
      }`}
    >
      {periods.map(period => (
        <button
          key={period}
          onClick={() => onSelect(period)}
          className={`px-3 py-3 text-sm transition-colors relative ${
            selected === period
              ? 'text-orange-500'
              : theme === 'dark'
                ? 'text-gray-400 hover:text-white'
                : 'text-gray-500 hover:text-gray-900'
          }`}
        >
          {period}
          {selected === period && (
            <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-orange-500" />
          )}
        </button>
      ))}
    </div>
  );
}
