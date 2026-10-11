import React, { useState, ReactNode } from 'react';
import { Header } from './Header';
import { ProfileScreen } from './ProfileScreen';
import { AccountSettings } from './AccountSettings';
import { PrivacySettings } from './PrivacySettings';
import { useTheme } from '../adapters/react/ThemeContext';

interface ScreenFrameProps {
  onLogout: () => void;
  children: ReactNode;
}

type SettingsScreen = 'profile' | 'account' | 'privacy' | null;

/**
 * The QT, Investor and Admin screens' page: the same header (with the screen
 * switcher, without the member tabs) and the same profile/settings sheets as
 * the member screen.
 */
export function ScreenFrame({ onLogout, children }: ScreenFrameProps) {
  const { theme } = useTheme();
  const [settingsScreen, setSettingsScreen] = useState<SettingsScreen>(null);
  const dark = theme === 'dark';

  const sheet = (content: ReactNode) => (
    <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-end md:items-center justify-center">
      <div
        className={`w-full md:w-[500px] h-full md:h-[80vh] md:rounded-2xl overflow-hidden ${
          dark ? 'bg-black text-white' : 'bg-white text-black'
        }`}
      >
        {content}
      </div>
    </div>
  );

  return (
    <div className={`min-h-screen ${dark ? 'bg-black text-white' : 'bg-white text-black'}`}>
      <Header memberNav={false} onProfileClick={() => setSettingsScreen('profile')} />
      <main className="max-w-5xl mx-auto px-4 md:px-6 py-6 md:py-8">{children}</main>

      {settingsScreen === 'profile' && (
        <ProfileScreen
          onClose={() => setSettingsScreen(null)}
          onLogout={onLogout}
          onNavigate={screen => setSettingsScreen(screen)}
        />
      )}
      {settingsScreen === 'account' &&
        sheet(<AccountSettings onBack={() => setSettingsScreen('profile')} />)}
      {settingsScreen === 'privacy' &&
        sheet(<PrivacySettings onBack={() => setSettingsScreen('profile')} />)}
    </div>
  );
}

/** A section heading in the style of the member screen's tables. */
export function SectionTitle({ children }: { children: ReactNode }) {
  const { theme } = useTheme();
  return (
    <h3
      className={`text-sm uppercase tracking-wider mb-4 ${
        theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
      }`}
    >
      {children}
    </h3>
  );
}

/** A bordered card in the style of the member screen. */
export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  const { theme } = useTheme();
  return (
    <div
      className={`border rounded-lg ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'} ${className}`}
    >
      {children}
    </div>
  );
}
