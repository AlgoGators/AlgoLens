import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';

interface User {
  id: string;
  email: string;
  first_name?: string;
  last_name?: string;
  role?: string;
}

interface AuthContextType {
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, firstName: string, lastName: string) => Promise<void>;
  logout: () => Promise<void>;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

// Get API URL from environment variable or default to localhost
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

console.log('[AuthContext] Initialized with API_URL:', API_URL);

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
      console.log('[AuthContext] Restoring session via /auth/verify');
      try {
        const response = await fetch(`${API_URL}/auth/verify`, {
          method: 'GET',
          credentials: 'include',
        });

        if (response.ok) {
          const data = await response.json();
          if (!cancelled) {
            console.log('[AuthContext] Session restored for user:', data.user?.email);
            setUser(data.user);
          }
        } else {
          // 401 here just means "not logged in" -- expected, not an error.
          console.log('[AuthContext] No active session (status', response.status, ')');
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
    const loginUrl = `${API_URL}/auth/login`;
    console.log('[AuthContext] Login attempt started for:', email);

    try {
      const response = await fetch(loginUrl, {
        method: 'POST',
        credentials: 'include', // send/receive the auth cookies
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        const error = await response.json();
        console.error('[AuthContext] Login failed with error:', error);
        throw new Error(error.error || 'Login failed');
      }

      const data = await response.json();
      console.log('[AuthContext] Login successful');
      // The token was set as an httpOnly cookie by the server; we only keep the
      // user profile in memory.
      setUser(data.user);
    } catch (error) {
      if (error instanceof TypeError && error.message.includes('fetch')) {
        console.error('[AuthContext] Network error - Failed to connect to:', loginUrl);
        throw new Error(`Failed to connect to server at ${API_URL}. Please check if the backend is running.`);
      }
      throw error;
    }
  };

  const register = async (email: string, password: string, firstName: string, lastName: string) => {
    const registerUrl = `${API_URL}/auth/register`;
    console.log('[AuthContext] Register attempt started for:', email);

    try {
      const response = await fetch(registerUrl, {
        method: 'POST',
        credentials: 'include', // send/receive the auth cookies
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          email,
          password,
          first_name: firstName,
          last_name: lastName,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        console.error('[AuthContext] Registration failed with error:', error);
        throw new Error(error.error || 'Registration failed');
      }

      const data = await response.json();
      console.log('[AuthContext] Registration successful');
      setUser(data.user);
    } catch (error) {
      if (error instanceof TypeError && error.message.includes('fetch')) {
        console.error('[AuthContext] Network error - Failed to connect to:', registerUrl);
        throw new Error(`Failed to connect to server at ${API_URL}. Please check if the backend is running.`);
      }
      throw error;
    }
  };

  const logout = async () => {
    console.log('[AuthContext] Logout initiated');
    try {
      // Clear the httpOnly cookies server-side. Best-effort: even if this fails
      // (e.g. backend unreachable), we still drop the local user state.
      await fetch(`${API_URL}/auth/logout`, {
        method: 'POST',
        credentials: 'include',
      });
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
