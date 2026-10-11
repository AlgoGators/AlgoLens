import React from 'react';
import { Briefcase, Shield, TrendingUp, Users } from 'lucide-react';
import { useScreens } from '../adapters/react/ScreenContext';
import { useTheme } from '../adapters/react/ThemeContext';
import { SCREEN_LABELS, type AppScreen } from '../domain/identity/screens';

const ICONS: Record<AppScreen, React.ComponentType<{ className?: string }>> = {
  member: Users,
  investor: Briefcase,
  qt: TrendingUp,
  admin: Shield,
};

/**
 * Member · Investor · QT · Admin: the screens this user holds (an admin assigns
 * them). Hidden when there is only one.
 */
export function ScreenSwitcher() {
  const { theme } = useTheme();
  const { available, active, setActive } = useScreens();
  const dark = theme === 'dark';

  if (available.length < 2) return null;

  return (
    <div
      role="tablist"
      aria-label="Screen"
      data-testid="screen-switcher"
      className={`flex items-center gap-1 rounded-full p-1 border ${
        dark ? 'border-gray-800 bg-gray-950' : 'border-gray-200 bg-gray-50'
      }`}
    >
      {available.map(screen => {
        const Icon = ICONS[screen];
        const isActive = screen === active;
        return (
          <button
            key={screen}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => setActive(screen)}
            className={`flex items-center gap-1.5 px-2.5 md:px-3 py-1 rounded-full text-xs md:text-sm transition-colors whitespace-nowrap ${
              isActive
                ? 'bg-orange-500 text-white'
                : dark
                  ? 'text-gray-400 hover:text-orange-500'
                  : 'text-gray-500 hover:text-orange-500'
            }`}
          >
            <Icon className="w-3.5 h-3.5" />
            <span className={isActive ? '' : 'hidden sm:inline'}>{SCREEN_LABELS[screen]}</span>
          </button>
        );
      })}
    </div>
  );
}
