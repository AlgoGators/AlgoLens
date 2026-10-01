import type { AuthResponse, User } from '../../domain/identity/user';
import { positionEditDemoResponse } from '../demo/positionEditDemo';
import { API_BASE_URL } from './httpClient';

export const DEV_MODE = import.meta.env.VITE_DEV_MODE === '1';

export interface SessionResult {
  user: User | null;
  status: number;
}

export async function verifySessionRequest(): Promise<SessionResult> {
  const url = `${API_BASE_URL}/auth/verify`;
  const init: RequestInit = {
    method: 'GET',
    credentials: 'include',
  };
  const response = positionEditDemoResponse(url, init) ?? await fetch(url, init);

  if (!response.ok) {
    return { user: null, status: response.status };
  }

  const data: AuthResponse = await response.json();
  return { user: data.user, status: response.status };
}

export async function devLoginRequest(): Promise<SessionResult> {
  const response = await fetch(`${API_BASE_URL}/auth/dev-login`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
  });

  if (!response.ok) {
    return { user: null, status: response.status };
  }

  const data: AuthResponse = await response.json();
  return { user: data.user, status: response.status };
}

export async function loginRequest(email: string, password: string): Promise<User> {
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
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

  const data: AuthResponse = await response.json();
  return data.user;
}

export async function registerRequest(
  email: string,
  password: string,
  firstName: string,
  lastName: string
): Promise<User> {
  const response = await fetch(`${API_BASE_URL}/auth/register`, {
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

  const data: AuthResponse = await response.json();
  return data.user;
}

export async function logoutRequest(): Promise<void> {
  const url = `${API_BASE_URL}/auth/logout`;
  const init: RequestInit = {
    method: 'POST',
    credentials: 'include',
  };
  positionEditDemoResponse(url, init) ?? await fetch(url, init);
}
