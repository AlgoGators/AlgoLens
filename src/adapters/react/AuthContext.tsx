import React, { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { IdentityApplicationService } from '../../application/identity/authService';
import type { User } from '../../domain/identity/user';
import { API_BASE_URL } from '../../infrastructure/api/httpClient';

interface AuthContextType {
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, firstName: string, lastName: string) => Promise<void>;
  logout: () => Promise<void>;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

console.log(
  '[AuthContext] Initialized with API_URL:',
  API_BASE_URL,
  'DEV_MODE:',
  IdentityApplicationService.isDevMode()
);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const restoreSession = async () => {
      console.log('[AuthContext] Restoring session via /auth/verify');
      try {
        const restored = await IdentityApplicationService.restoreSession();
        if (!cancelled && restored) {
          console.log('[AuthContext] Session restored for user:', restored.email);
          setUser(restored);
        } else if (!restored) {
          console.log('[AuthContext] No active session');
        }
      } catch (err) {
        console.warn('[AuthContext] Session check failed (backend unreachable?):', err);
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
    console.log('[AuthContext] Login attempt started for:', email);
    const loggedIn = await IdentityApplicationService.login(email, password);
    console.log('[AuthContext] Login successful');
    setUser(loggedIn);
  };

  const register = async (email: string, password: string, firstName: string, lastName: string) => {
    console.log('[AuthContext] Register attempt started for:', email);
    const registered = await IdentityApplicationService.register(email, password, firstName, lastName);
    console.log('[AuthContext] Registration successful');
    setUser(registered);
  };

  const logout = async () => {
    console.log('[AuthContext] Logout initiated');
    try {
      await IdentityApplicationService.logout();
    } catch (err) {
      console.warn('[AuthContext] Logout request failed (clearing local state anyway):', err);
    } finally {
      setUser(null);
      console.log('[AuthContext] Logout completed');
    }
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
