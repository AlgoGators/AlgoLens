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
  token: string | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, firstName: string, lastName: string) => Promise<void>;
  logout: () => void;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

// Get API URL from environment variable or default to localhost
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

console.log('[AuthContext] Initialized with API_URL:', API_URL);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    console.log('[AuthContext] Checking for stored credentials');
    const storedToken = localStorage.getItem('token');
    const storedUser = localStorage.getItem('user');

    if (storedToken && storedUser) {
      console.log('[AuthContext] Found stored credentials, restoring session');
      setToken(storedToken);
      setUser(JSON.parse(storedUser));
    } else {
      console.log('[AuthContext] No stored credentials found');
    }
    setIsLoading(false);
  }, []);

  const login = async (email: string, password: string) => {
    const loginUrl = `${API_URL}/auth/login`;
    console.log('[AuthContext] Login attempt started');
    console.log('[AuthContext] API URL:', loginUrl);
    console.log('[AuthContext] Email:', email);

    try {
      console.log('[AuthContext] Sending login request...');
      const response = await fetch(loginUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email, password }),
      });

      console.log('[AuthContext] Response received');
      console.log('[AuthContext] Response status:', response.status);
      console.log('[AuthContext] Response ok:', response.ok);
      console.log('[AuthContext] Response headers:', Object.fromEntries(response.headers.entries()));

      if (!response.ok) {
        const error = await response.json();
        console.error('[AuthContext] Login failed with error:', error);
        throw new Error(error.error || 'Login failed');
      }

      const data = await response.json();
      console.log('[AuthContext] Login successful');
      console.log('[AuthContext] User data:', { ...data.user, id: data.user.id });

      setToken(data.token);
      setUser(data.user);

      localStorage.setItem('token', data.token);
      localStorage.setItem('user', JSON.stringify(data.user));

      console.log('[AuthContext] Credentials stored in localStorage');
    } catch (error) {
      console.error('[AuthContext] Login error details:', {
        name: error instanceof Error ? error.name : 'Unknown',
        message: error instanceof Error ? error.message : String(error),
        stack: error instanceof Error ? error.stack : undefined
      });

      if (error instanceof TypeError && error.message.includes('fetch')) {
        console.error('[AuthContext] Network error - Failed to connect to:', loginUrl);
        console.error('[AuthContext] This could be due to:');
        console.error('[AuthContext] 1. CORS issues');
        console.error('[AuthContext] 2. Backend server not running');
        console.error('[AuthContext] 3. Incorrect API URL');
        console.error('[AuthContext] 4. Network/firewall blocking the request');
        throw new Error(`Failed to connect to server at ${API_URL}. Please check if the backend is running.`);
      }

      throw error;
    }
  };

  const register = async (email: string, password: string, firstName: string, lastName: string) => {
    const registerUrl = `${API_URL}/auth/register`;
    console.log('[AuthContext] Register attempt started');
    console.log('[AuthContext] API URL:', registerUrl);
    console.log('[AuthContext] Email:', email);

    try {
      console.log('[AuthContext] Sending register request...');
      const response = await fetch(registerUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          email,
          password,
          first_name: firstName,
          last_name: lastName
        }),
      });

      console.log('[AuthContext] Response received');
      console.log('[AuthContext] Response status:', response.status);
      console.log('[AuthContext] Response ok:', response.ok);

      if (!response.ok) {
        const error = await response.json();
        console.error('[AuthContext] Registration failed with error:', error);
        throw new Error(error.error || 'Registration failed');
      }

      const data = await response.json();
      console.log('[AuthContext] Registration successful');

      setToken(data.token);
      setUser(data.user);

      localStorage.setItem('token', data.token);
      localStorage.setItem('user', JSON.stringify(data.user));

      console.log('[AuthContext] Credentials stored in localStorage');
    } catch (error) {
      console.error('[AuthContext] Registration error details:', {
        name: error instanceof Error ? error.name : 'Unknown',
        message: error instanceof Error ? error.message : String(error),
        stack: error instanceof Error ? error.stack : undefined
      });

      if (error instanceof TypeError && error.message.includes('fetch')) {
        console.error('[AuthContext] Network error - Failed to connect to:', registerUrl);
        throw new Error(`Failed to connect to server at ${API_URL}. Please check if the backend is running.`);
      }

      throw error;
    }
  };

  const logout = () => {
    console.log('[AuthContext] Logout initiated');
    setUser(null);
    setToken(null);
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    console.log('[AuthContext] Logout completed');
  };

  return (
    <AuthContext.Provider value={{ user, token, login, register, logout, isLoading }}>
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
