import { ArrowLeft, Clock } from 'lucide-react';
import type { IncubatingStrategy } from '@/models';
import { formatIncubationDate, formatMockCapital } from '@/lib/incubationUtils';
import { useTheme } from '../../adapters/react/ThemeContext';

interface Props {
  strategy: IncubatingStrategy;
  onBack: () => void;
}

export function IncubationDetailHeader({ strategy, onBack }: Props) {
  const { theme } = useTheme();
  const dark = theme === 'dark';

  return (
    <>
      <button
        onClick={onBack}
        className={`flex items-center gap-2 mb-6 px-4 py-2 rounded-lg transition-colors ${
          dark
            ? 'text-gray-300 hover:text-white hover:bg-gray-900'
            : 'text-gray-700 hover:text-black hover:bg-gray-100'
        }`}
      >
        <ArrowLeft className="w-5 h-5" />
        <span>Back to Incubation</span>
      </button>

      <div className="mb-6">
        <h1 className="text-2xl md:text-3xl mb-1">{strategy.name}</h1>
        <p className={dark ? 'text-gray-400' : 'text-gray-500'}>
          {strategy.description || strategy.id}
        </p>
        <div
          className={`text-sm mt-2 flex flex-wrap items-center gap-3 ${
            dark ? 'text-gray-400' : 'text-gray-500'
          }`}
        >
          <span>{formatMockCapital(strategy.mock_capital)} mock capital</span>
          <span>•</span>
          <span>Started {formatIncubationDate(strategy.incubation_started_at)}</span>
          <span>•</span>
          <span className="flex items-center gap-1">
            <Clock className="w-4 h-4" />
            {strategy.days_elapsed}d / {strategy.window_days}d
          </span>
        </div>
      </div>
    </>
  );
}
