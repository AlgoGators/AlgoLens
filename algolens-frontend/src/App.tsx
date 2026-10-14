import React, { useState } from 'react';
import { LoginView } from './components/LoginView';
import { RegisterView } from './components/RegisterView';
import { Dashboard } from './components/Dashboard';
import { ApprovalPage } from './components/qt/ApprovalPage';
import { QtHome } from './components/qt/QtHome';
import { InvestorHome } from './components/investor/InvestorHome';
import { AdminHome } from './components/admin/AdminHome';
import { ScreenFrame } from './components/ScreenFrame';
import { AccessPending } from './components/AccessPending';
import { ThemeProvider, useTheme } from './adapters/react/ThemeContext';
import { AuthProvider, useAuth } from './adapters/react/AuthContext';
import { ScreenProvider, useScreens } from './adapters/react/ScreenContext';

function Loading({ label }: { label: string }) {
  const { theme } = useTheme();
  return (
    <div
      className={`min-h-screen flex items-center justify-center ${
        theme === 'dark' ? 'bg-black text-white' : 'bg-white text-black'
      }`}
    >
      <div className="text-lg">{label}</div>
    </div>
  );
}

/** The signed-in user's screen: what an admin assigned them (GET /api/me/screens). */
function SignedIn({ onLogout }: { onLogout: () => void }) {
  const { active, loading, error, reload } = useScreens();

  if (loading && active === null) return <Loading label="Loading..." />;
  if (error) return <AccessPending onLogout={onLogout} error={error} onRetry={reload} />;

  switch (active) {
    case 'member':
      return <Dashboard onLogout={onLogout} />;
    case 'qt':
      return (
        <ScreenFrame onLogout={onLogout}>
          <QtHome />
        </ScreenFrame>
      );
    case 'investor':
      return (
        <ScreenFrame onLogout={onLogout}>
          <InvestorHome />
        </ScreenFrame>
      );
    case 'admin':
      return (
        <ScreenFrame onLogout={onLogout}>
          <AdminHome />
        </ScreenFrame>
      );
    default:
      return <AccessPending onLogout={onLogout} onRetry={reload} />;
  }
}

function AppContent() {
  const { user, logout, isLoading } = useAuth();
  const [showRegister, setShowRegister] = useState(false);

  if (isLoading) {
    return <Loading label="Loading..." />;
  }

  // The override approval link e-mailed by the engine (login required: an
  // anonymous visitor logs in first and lands back on the same URL). Approvers
  // need no screen: the VP and President are named by QT_APPROVERS.
  const onApprovalPage = window.location.pathname === '/qt/approve';

  if (user && onApprovalPage) {
    return <ApprovalPage onDone={() => window.location.assign('/')} />;
  }

  if (user) {
    return <SignedIn onLogout={logout} />;
  }

  return showRegister ? (
    <RegisterView onBackToLogin={() => setShowRegister(false)} />
  ) : (
    <LoginView onNavigateToRegister={() => setShowRegister(true)} />
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <ScreenProvider>
          <AppContent />
        </ScreenProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}
