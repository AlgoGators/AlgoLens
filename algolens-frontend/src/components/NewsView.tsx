import { FileText, X } from 'lucide-react';
import { useTheme } from '../adapters/react/ThemeContext';

interface NewsViewProps {
  onClose: () => void;
}

/**
 * Fund updates.
 *
 * This screen used to render a written newsletter with figures in it: a 27.3%
 * fund return, +8.1% alpha against the S&P 500, per-strategy returns, Fed rates
 * and CPI. None of it came from anywhere. It was static markup, formatted
 * exactly like the real performance numbers on the Portfolio tab, and shown to
 * every logged-in member, who had no way to tell the difference.
 *
 * There is no updates feed behind this tab: no table, no endpoint, nothing
 * publishing to it. So it says that, rather than filling the space with
 * something that reads like a measurement. When a real source exists this is
 * where it renders; until then an empty screen is the honest one.
 */
export function NewsView({ onClose }: NewsViewProps) {
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <div className={`min-h-screen ${isDark ? 'bg-black text-white' : 'bg-white text-black'}`}>
      <div
        className={`sticky top-0 z-10 border-b ${
          isDark ? 'bg-black border-gray-800' : 'bg-white border-gray-200'
        }`}
      >
        <div className="max-w-5xl mx-auto px-4 md:px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-xl md:text-2xl">News &amp; Updates</h2>
            <p className={`text-sm ${isDark ? 'text-gray-400' : 'text-gray-500'}`}>
              Fund announcements and commentary
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className={`p-2 rounded-full transition-colors md:hidden ${
              isDark ? 'hover:bg-gray-900' : 'hover:bg-gray-100'
            }`}
          >
            <X className="w-5 h-5" />
          </button>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-4 md:px-6 py-16">
        <div
          className={`rounded-xl border px-6 py-12 text-center ${
            isDark ? 'border-gray-800 bg-gray-950' : 'border-gray-200 bg-gray-50'
          }`}
        >
          <FileText
            className={`mx-auto mb-4 h-8 w-8 ${isDark ? 'text-gray-600' : 'text-gray-400'}`}
          />
          <h3 className="mb-2 text-lg">No updates published yet</h3>
          <p
            className={`mx-auto max-w-md text-sm leading-relaxed ${
              isDark ? 'text-gray-400' : 'text-gray-600'
            }`}
          >
            Fund announcements will appear here once there is a source publishing them.
            Performance figures live on the Portfolio tab, where every number is read from
            the trading engine.
          </p>
        </div>
      </div>
    </div>
  );
}
