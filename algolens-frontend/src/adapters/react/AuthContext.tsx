import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { IdentityApplicationService } from '../../application/identity/authService';
import type { User } from '@/models';

interface AuthContextType {
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, firstName: string, lastName: string) => Promise<void>;
  logout: () => Promise<void>;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const API_URL = IdentityApplicationService.getApiUrl();
const DEV_MODE = IdentityApplicationService.isDevMode();

console.log('[AuthContext] Initialized with API_URL:', API_URL, 'DEV_MODE:', DEV_MODE);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // The access token now lives in an httpOnly cookie that JavaScript cannot read,
  // so we can no longer restore the session from localStorage. Instead we ask the
  // server who we are: /auth/verify authenticates via the cookie and returns the
  // user, or 401 if there is no valid session. `credentials: 'include'` is required
  // for the browser to send the cookie.
  useEffect(() => {
    let cancelled = false;

    const restoreSession = async () => {
      try {
        const restoredUser = await IdentityApplicationService.restoreSession();
        if (!cancelled && restoredUser) {
          setUser(restoredUser);
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };

    restoreSession();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = async (email: string, password: string) => {
    const authenticatedUser = await IdentityApplicationService.login(email, password);
    // The token was set as an httpOnly cookie by the server; we only keep the
    // user profile in memory.
    setUser(authenticatedUser);
  };

  const register = async (email: string, password: string, firstName: string, lastName: string) => {
    const registeredUser = await IdentityApplicationService.register(email, password, firstName, lastName);
    setUser(registeredUser);
  };

  const logout = async () => {
    await IdentityApplicationService.logout();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, login, register, logout, isLoading }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
