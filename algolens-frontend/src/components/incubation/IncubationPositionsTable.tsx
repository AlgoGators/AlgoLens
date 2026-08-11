import type { IncubationPerformance } from '@/models';
import { formatIncubationDate } from '@/lib/incubationUtils';
import { useTheme } from '../../adapters/react/ThemeContext';

interface Props {
  positions: IncubationPerformance['positions'];
}

function formatEntryPrice(price: number | null): string {
  if (price === null) return 'N/A';
  return `$${price.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function IncubationPositionsTable({ positions }: Props) {
  const { theme } = useTheme();
  const dark = theme === 'dark';
  const lastIndex = positions.length - 1;

  return (
    <div>
      <h3
        className={`text-sm uppercase tracking-wider mb-4 ${
          dark ? 'text-gray-400' : 'text-gray-500'
        }`}
      >
        Incubation Positions
      </h3>
      <div
        className={`border rounded-lg overflow-x-auto ${
          dark ? 'border-gray-800' : 'border-gray-200'
        }`}
      >
        <div
          className={`grid grid-cols-4 gap-4 p-4 text-sm min-w-[640px] border-b ${
            dark
              ? 'bg-gray-900 border-gray-800 text-gray-400'
              : 'bg-gray-50 border-gray-200 text-gray-500'
          }`}
        >
          <div>Date</div>
          <div>Symbol</div>
          <div className="text-right">Quantity</div>
          <div className="text-right">Entry Price</div>
        </div>
        {positions.map((position, index) => (
          <div
            key={`${position.date}-${position.symbol}-${index}`}
            className={`grid grid-cols-4 gap-4 p-4 min-w-[640px] ${
              dark ? 'hover:bg-gray-900' : 'hover:bg-gray-50'
            } ${index !== lastIndex ? (dark ? 'border-b border-gray-800' : 'border-b border-gray-200') : ''}`}
          >
            <div>{formatIncubationDate(position.date)}</div>
            <div>{position.symbol}</div>
            <div className="text-right">{position.quantity ?? 0}</div>
            <div className="text-right">{formatEntryPrice(position.entry_price)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
