import React, { useState } from 'react';
import { Header } from './Header';
import { PortfolioOverview } from './PortfolioOverview';
import { StrategyList } from './StrategyList';
import { StrategyDetail } from './StrategyDetail';
import { BottomNav } from './BottomNav';
import { ProfileScreen } from './ProfileScreen';
import { AccountSettings } from './AccountSettings';
import { PrivacySettings } from './PrivacySettings';
import { StrategyBuilder } from './StrategyBuilder';
import { NewsView } from './NewsView';
import { EmptyPortfolioScreen } from './EmptyPortfolioScreen';
import { portfolioData } from '../data/portfolioData';
import { useTheme } from '../contexts/ThemeContext';

interface DashboardProps {
  onLogout: () => void;
}

type SettingsScreen = 'profile' | 'account' | 'privacy' | null;
type ActiveTab = 'portfolio' | 'builder' | 'news' | 'profile';

export function Dashboard({ onLogout }: DashboardProps) {
  const [selectedStrategy, setSelectedStrategy] = useState<string | null>(null);
  const [settingsScreen, setSettingsScreen] = useState<SettingsScreen>(null);
  const [showBuilder, setShowBuilder] = useState(false);
  const [activeTab, setActiveTab] = useState<ActiveTab>('portfolio');
  const { theme } = useTheme();

  // Check if portfolio has any positions
  const hasPositions = portfolioData.strategies.length > 0 &&
    portfolioData.strategies.some(s => s.positions.length > 0);

  const handleTabChange = (tab: string) => {
    setActiveTab(tab as ActiveTab);
    setSelectedStrategy(null);

    if (tab === 'builder') {
      setShowBuilder(true);
    } else if (tab === 'profile') {
      setSettingsScreen('profile');
    } else {
      setShowBuilder(false);
      setSettingsScreen(null);
    }
  };

  const handleBuilderClose = () => {
    setShowBuilder(false);
    setActiveTab('portfolio');
  };

  const handleNewsClose = () => {
    setActiveTab('portfolio');
  };

  return (
    <div className={`min-h-screen pb-20 md:pb-0 ${theme === 'dark' ? 'bg-black text-white' : 'bg-white text-black'
      }`}>
      {activeTab !== 'news' && (
        <Header
          onProfileClick={() => {
            setSettingsScreen('profile');
            setActiveTab('profile');
          }}
          onBuilderClick={() => {
            setShowBuilder(true);
            setActiveTab('builder');
          }}
          onHomeClick={() => {
            setShowBuilder(false);
            setActiveTab('portfolio');
            setSelectedStrategy(null);
          }}
        />
      )}

      {activeTab === 'portfolio' && (
        <div className="max-w-5xl mx-auto px-4 md:px-6 py-6 md:py-8">
          {!hasPositions ? (
            <EmptyPortfolioScreen onClose={() => {
              // Close action - could navigate to a help page or do nothing
            }} />
          ) : !selectedStrategy ? (
            <>
              <PortfolioOverview data={portfolioData} onBuilderClick={() => {
                setShowBuilder(true);
                setActiveTab('builder');
              }} />
              <StrategyList
                strategies={portfolioData.strategies}
                onSelectStrategy={setSelectedStrategy}
              />
            </>
          ) : (
            <StrategyDetail
              strategy={portfolioData.strategies.find(s => s.id === selectedStrategy)!}
              onBack={() => setSelectedStrategy(null)}
            />
          )}
        </div>
      )}

      {activeTab === 'news' && (
        <NewsView onClose={handleNewsClose} />
      )}

      <BottomNav activeTab={activeTab} onTabChange={handleTabChange} />

      {settingsScreen === 'profile' && (
        <ProfileScreen
          onClose={() => {
            setSettingsScreen(null);
            setActiveTab('portfolio');
          }}
          onLogout={onLogout}
          onNavigate={(screen) => setSettingsScreen(screen)}
        />
      )}

      {settingsScreen === 'account' && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-end md:items-center justify-center">
          <div className={`w-full md:w-[500px] h-full md:h-[80vh] md:rounded-2xl overflow-hidden ${theme === 'dark' ? 'bg-black text-white' : 'bg-white text-black'
            }`}>
            <AccountSettings onBack={() => setSettingsScreen('profile')} />
          </div>
        </div>
      )}

      {settingsScreen === 'privacy' && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-end md:items-center justify-center">
          <div className={`w-full md:w-[500px] h-full md:h-[80vh] md:rounded-2xl overflow-hidden ${theme === 'dark' ? 'bg-black text-white' : 'bg-white text-black'
            }`}>
            <PrivacySettings onBack={() => setSettingsScreen('profile')} />
          </div>
        </div>
      )}

      {showBuilder && (
        <StrategyBuilder
          strategies={portfolioData.strategies}
          onClose={handleBuilderClose}
        />
      )}
    </div>
  );
}