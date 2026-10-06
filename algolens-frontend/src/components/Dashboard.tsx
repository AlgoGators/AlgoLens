import React, { useCallback, useEffect, useRef, useState } from 'react';
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
import { can } from '../domain/identity/user';
import { useAuth } from '../adapters/react/useAuth';
import { useTheme } from '../adapters/react/ThemeContext';
import { BooksScreen } from './BooksScreen';
import { useDialogLifecycle } from './useDialogLifecycle';

interface DashboardProps {
  onLogout: () => void;
}

type SettingsScreen = 'profile' | 'account' | 'privacy' | null;
type ActiveTab = 'portfolio' | 'incubation' | 'builder' | 'books' | 'news' | 'profile';

export function Dashboard({ onLogout }: DashboardProps) {
  const [selectedStrategy, setSelectedStrategy] = useState<string | null>(null);
  // The book the strategy was opened on. Undefined means its primary.
  const [selectedBook, setSelectedBook] = useState<string | undefined>(undefined);
  const [settingsScreen, setSettingsScreen] = useState<SettingsScreen>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab>('portfolio');
  const [portfolioData, setPortfolioData] = useState<PortfolioData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { theme } = useTheme();
  const { user } = useAuth();
  const canManageBooks = can(user, 'manage_books');
  const canManageIncubation = can(user, 'manage_incubation');

  // Hoisted out of the mount effect so a manual position edit can re-run it.
  // `silent` re-reads without flipping the page into its loading state. A
  // refresh after an edit used to unmount the whole strategy view and rebuild
  // it, which threw away everything the reader had set up on screen -- most
  // visibly, which book they were looking at. The first load still shows the
  // spinner, because then there is genuinely nothing to look at.
  const fetchPortfolioData = useCallback(async (opts?: { silent?: boolean }) => {
    console.log('[Dashboard] === Starting fetchPortfolioData ===');
    console.log('[Dashboard] Current URL:', window.location.href);
    // Auth is carried by an httpOnly cookie now; JS cannot inspect it here.

    try {
      if (!opts?.silent) setIsLoading(true);
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

      setError('Could not load portfolio data.');
    } finally {
      setIsLoading(false);
      console.log('[Dashboard] fetchPortfolioData complete');
    }
  }, []);

  useEffect(() => {
    void fetchPortfolioData();
  }, [fetchPortfolioData]);

  // The Books tab changes which books a strategy is in, and the portfolio view
  // reads that from data loaded before the change. Leaving Books re-reads it,
  // quietly, so a strategy just added to a second book offers that book at
  // once instead of after a full page reload.
  const previousTab = useRef<ActiveTab>(activeTab);
  useEffect(() => {
    if (previousTab.current === 'books' && activeTab !== 'books') {
      void fetchPortfolioData({ silent: true });
    }
    previousTab.current = activeTab;
  }, [activeTab, fetchPortfolioData]);

  useEffect(() => {
    if ((activeTab === 'incubation' && !canManageIncubation) ||
        (activeTab === 'books' && !canManageBooks)) {
      setActiveTab('portfolio');
      setSelectedStrategy(null);
    }
  }, [activeTab, canManageBooks, canManageIncubation]);

  // Something to show: an open position anywhere, or a strategy the engine has
  // not published yet. The second case matters -- a fund whose strategies are
  // all still awaiting data is not an empty fund, and the overview is where the
  // "excludes N strategies" notice lives.
  const hasPortfolioContent = Boolean(portfolioData?.strategies?.length);

  const handleTabChange = (tab: string) => {
    if ((tab === 'incubation' && !canManageIncubation) || (tab === 'books' && !canManageBooks)) {
      return;
    }

    setActiveTab(tab as ActiveTab);
    setSelectedStrategy(null);

    if (tab === 'builder') {
      setSettingsScreen(null);
    } else if (tab === 'profile') {
      setSettingsScreen('profile');
    } else {
      setSettingsScreen(null);
    }
  };

  // Opens on the primary book unless one is named. A card click names none:
  // the book is chosen on the strategy page itself, in the box beside
  // "Positions snapshot". A row inside a book on the Portfolios section names
  // its book, so that one opens straight onto it.
  const openStrategy = (strategyId: string, portfolioId?: string) => {
    setSelectedBook(portfolioId);
    setSelectedStrategy(strategyId);
  };

  const handleBuilderClose = () => {
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
            setSelectedStrategy(null);
            setSettingsScreen('profile');
            setActiveTab('profile');
          }}
          onBuilderClick={() => {
            setSettingsScreen(null);
            setSelectedStrategy(null);
            setActiveTab('builder');
          }}
          onHomeClick={() => {
            setSettingsScreen(null);
            setActiveTab('portfolio');
            setSelectedStrategy(null);
          }}
          onBooksClick={() => {
            if (!canManageBooks) return;
            setSettingsScreen(null);
            setActiveTab('books');
            setSelectedStrategy(null);
          }}
          onIncubationClick={() => {
            if (!canManageIncubation) return;
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
                <div role="alert" className="mb-4 p-4 bg-red-100 dark:bg-red-900/30 rounded-lg">
                  <p className="text-red-600 dark:text-red-400 text-sm">
                    {error}
                  </p>
                </div>
                <p className={`mb-4 text-sm ${theme === 'dark' ? 'text-gray-400' : 'text-gray-600'}`}>
                  Retry this portfolio request. No account or book changes will be made.
                </p>
                <div className="flex justify-center">
                  <button
                    onClick={() => void fetchPortfolioData()}
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                  >
                    Retry
                  </button>
                </div>
              </div>
            </div>
          ) : !portfolioData || !hasPortfolioContent ? (
            <EmptyPortfolioScreen />
          ) : !selectedStrategy ? (
            <>
              <PortfolioOverview
                data={portfolioData}
                onBuilderClick={() => {
                  setSettingsScreen(null);
                  setActiveTab('builder');
                }}
                onOpenStrategy={openStrategy}
              />
              <StrategyList
                strategies={portfolioData.strategies}
                onSelectStrategy={id => openStrategy(id)}
              />
            </>
          ) : (
            <StrategyDetail
              strategy={portfolioData.strategies.find(s => s.id === selectedStrategy)!}
              initialBook={selectedBook}
              onBack={() => { setSelectedStrategy(null); setSelectedBook(undefined); }}
              onPositionsChanged={() => fetchPortfolioData({ silent: true })}
            />
          )}
        </div>
      )}

      {activeTab === 'books' && canManageBooks && <BooksScreen />}

      {activeTab === 'incubation' && canManageIncubation && (
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
        <SettingsDialog title="Account Settings" theme={theme} onClose={() => setSettingsScreen('profile')}>
            <AccountSettings onBack={() => setSettingsScreen('profile')} />
        </SettingsDialog>
      )}

      {settingsScreen === 'privacy' && (
        <SettingsDialog title="Privacy & Security" theme={theme} onClose={() => setSettingsScreen('profile')}>
            <PrivacySettings onBack={() => setSettingsScreen('profile')} />
        </SettingsDialog>
      )}

      {activeTab === 'builder' && portfolioData && (
        <StrategyBuilder
          strategies={portfolioData.strategies}
          onClose={handleBuilderClose}
        />
      )}
    </div>
  );
}

function SettingsDialog({
  title,
  theme,
  onClose,
  children,
}: {
  title: string;
  theme: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const dialogRef = useDialogLifecycle(onClose);
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-end md:items-center justify-center">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`w-full md:w-[500px] h-full md:h-[80vh] md:rounded-2xl overflow-hidden ${
          theme === 'dark' ? 'bg-black text-white' : 'bg-white text-black'
        }`}
      >
        {children}
      </div>
    </div>
  );
}
