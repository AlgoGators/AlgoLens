import React, { useState } from 'react';
import { LoginView } from './components/LoginView';
import { RegisterView } from './components/RegisterView';
import { Dashboard } from './components/Dashboard';
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