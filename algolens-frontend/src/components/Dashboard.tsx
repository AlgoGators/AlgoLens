import React, { useState, useEffect } from 'react';
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
import { IncubationScreen } from './IncubationScreen';
import type { PortfolioData } from '../domain/portfolio/portfolioData';
import { PortfolioApplicationService } from '../application/portfolio/portfolioService';
import { isInternalRole } from '../domain/identity/user';
import { useAuth } from '../adapters/react/AuthContext';
import { useTheme } from '../adapters/react/ThemeContext';

interface DashboardProps {
  onLogout: () => void;
}

type SettingsScreen = 'profile' | 'account' | 'privacy' | null;
type ActiveTab = 'portfolio' | 'incubation' | 'builder' | 'news' | 'profile';

export function Dashboard({ onLogout }: DashboardProps) {
  const [selectedStrategy, setSelectedStrategy] = useState<string | null>(null);
  const [settingsScreen, setSettingsScreen] = useState<SettingsScreen>(null);
  const [showBuilder, setShowBuilder] = useState(false);
  const [activeTab, setActiveTab] = useState<ActiveTab>('portfolio');
  const [portfolioData, setPortfolioData] = useState<PortfolioData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { theme } = useTheme();
  const { user } = useAuth();
  const isInternalMember = isInternalRole(user?.role);

  // Fetch portfolio data on mount
  useEffect(() => {
    const fetchPortfolioData = async () => {
      console.log('[Dashboard] === Starting fetchPortfolioData ===');
      console.log('[Dashboard] Current URL:', window.location.href);
      // Auth is carried by an httpOnly cookie now; JS cannot inspect it here.

      try {
        setIsLoading(true);
        setError(null);
        const data = await PortfolioApplicationService.getPortfolioData();
        console.log('[Dashboard] Portfolio data received successfully:', data);
        setPortfolioData(data);
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : String(err);
        console.error('[Dashboard] === ERROR FETCHING PORTFOLIO ===');
        console.error('[Dashboard] Error:', err);
        console.error('[Dashboard] Error details:', {
          message: errorMessage,
          type: err instanceof Error ? err.constructor.name : typeof err,
          stack: err instanceof Error ? err.stack : 'N/A',
        });

        // Provide debugging hint
        console.error('[Dashboard] DEBUG TIP: Run this in browser console:');
        console.error('  import("./application/portfolio/portfolioService").then(m => m.PortfolioApplicationService.testConnectivity())');
        console.error('  Or open Network tab and look for failed requests');

        // Include the actual error message for debugging
        setError(`Failed to load portfolio data: ${errorMessage}`);
      } finally {
        setIsLoading(false);
        console.log('[Dashboard] fetchPortfolioData complete');
      }
    };

    fetchPortfolioData();
  }, []);

  useEffect(() => {
    if (activeTab === 'incubation' && !isInternalMember) {
      setActiveTab('portfolio');
      setSelectedStrategy(null);
    }
  }, [activeTab, isInternalMember]);

  // Check if portfolio has any positions
  const hasPositions = portfolioData?.strategies && portfolioData.strategies.length > 0 &&
    portfolioData.strategies.some(s => s.positions.length > 0);

  const handleTabChange = (tab: string) => {
    if (tab === 'incubation' && !isInternalMember) {
      return;
    }

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
          activeTab={activeTab}
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
          onIncubationClick={() => {
            if (!isInternalMember) return;
            setShowBuilder(false);
            setSettingsScreen(null);
            setActiveTab('incubation');
            setSelectedStrategy(null);
          }}
        />
      )}

      {activeTab === 'portfolio' && (
        <div className="max-w-5xl mx-auto px-4 md:px-6 py-6 md:py-8">
          {isLoading ? (
            <div className="flex items-center justify-center min-h-[400px]">
              <div className="text-center">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
                <p className={theme === 'dark' ? 'text-gray-400' : 'text-gray-600'}>Loading portfolio data...</p>
              </div>
            </div>
          ) : error ? (
            <div className="flex items-center justify-center min-h-[400px]">
              <div className="text-center max-w-lg">
                <div className="mb-4 p-4 bg-red-100 dark:bg-red-900/30 rounded-lg">
                  <p className="text-red-600 dark:text-red-400 text-sm font-mono break-words text-left max-h-40 overflow-auto">
                    {error}
                  </p>
                </div>
                <div className={`text-sm mb-4 text-left p-3 rounded ${theme === 'dark' ? 'bg-gray-800 text-gray-300' : 'bg-gray-100 text-gray-700'}`}>
                  <p className="font-semibold mb-2">Debug Steps:</p>
                  <ol className="list-decimal list-inside space-y-1 text-xs">
                    <li>Open browser DevTools (F12)</li>
                    <li>Check Console tab for detailed error logs</li>
                    <li>Check Network tab for failed API requests</li>
                    <li>Look for CORS or connection errors</li>
                  </ol>
                </div>
                <div className="flex gap-2 justify-center">
                  <button
                    onClick={() => window.location.reload()}
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                  >
                    Retry
                  </button>
                  <button
                    onClick={() => {
                      console.log('[Dashboard] Running connectivity test...');
                      PortfolioApplicationService.testConnectivity();
                    }}
                    className={`px-4 py-2 rounded-lg ${theme === 'dark' ? 'bg-gray-700 text-white hover:bg-gray-600' : 'bg-gray-200 text-gray-800 hover:bg-gray-300'}`}
                  >
                    Run Debug Test
                  </button>
                </div>
              </div>
            </div>
          ) : !portfolioData || !hasPositions ? (
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

      {activeTab === 'incubation' && isInternalMember && (
        <div className="max-w-5xl mx-auto px-4 md:px-6 py-6 md:py-8">
          <IncubationScreen />
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

      {showBuilder && portfolioData && (
        <StrategyBuilder
          strategies={portfolioData.strategies}
          onClose={handleBuilderClose}
        />
      )}
    </div>
  );
}
