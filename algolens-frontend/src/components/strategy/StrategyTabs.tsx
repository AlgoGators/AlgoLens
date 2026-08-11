import { ArrowLeft } from 'lucide-react';
import { useTheme } from '../../adapters/react/ThemeContext';

export type StrategyTab = 'positions' | 'analysis' | 'activity';

const TABS: { id: StrategyTab; label: string }[] = [
  { id: 'positions', label: 'Positions' },
  { id: 'analysis', label: 'Financial Analysis' },
  { id: 'activity', label: 'Trading Activity' },
];

interface Props {
  selected: StrategyTab;
  onSelect: (tab: StrategyTab) => void;
  onBack: () => void;
}

export function StrategyTabs({ selected, onSelect, onBack }: Props) {
  const { theme } = useTheme();
  const dark = theme === 'dark';
  const inactive = dark ? 'text-gray-400 hover:text-white' : 'text-gray-500 hover:text-gray-900';

  return (
    <div className={`flex items-center justify-between mb-6 border-b ${dark ? 'border-gray-800' : 'border-gray-200'}`}>
      <div className="flex items-center gap-4">
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => onSelect(tab.id)}
            className={`pb-3 px-1 transition-colors relative ${selected === tab.id ? 'text-orange-500' : inactive}`}
          >
            {tab.label}
            {selected === tab.id && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-orange-500" />
            )}
          </button>
        ))}
      </div>

      <button
        onClick={onBack}
        className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
          dark
            ? 'text-gray-300 hover:text-white hover:bg-gray-900'
            : 'text-gray-700 hover:text-black hover:bg-gray-100'
        }`}
      >
        <ArrowLeft className="w-5 h-5" />
        <span>Back to Strategies</span>
      </button>
    </div>
  );
}
