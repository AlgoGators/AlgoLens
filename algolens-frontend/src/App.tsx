import React, { useState } from 'react';
import { LoginView } from './components/LoginView';
import { RegisterView } from './components/RegisterView';
import { Dashboard } from './components/Dashboard';
import { ApprovalPage } from './components/qt/ApprovalPage';
import { ThemeProvider } from './adapters/react/ThemeContext';
import { AuthProvider, useAuth } from './adapters/react/AuthContext';

function AppContent() {
  const { user, logout, isLoading } = useAuth();
  const [showRegister, setShowRegister] = useState(false);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-lg">Loading...</div>
      </div>
    );
  }

  // The override approval link e-mailed by the engine (login required: an
  // anonymous visitor logs in first and lands back on the same URL).
  const onApprovalPage = window.location.pathname === '/qt/approve';

  if (user && onApprovalPage) {
    return <ApprovalPage onDone={() => window.location.assign('/')} />;
  }

  if (user) {
    return <Dashboard onLogout={logout} />;
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
        <AppContent />
      </AuthProvider>
    </ThemeProvider>
  );
}