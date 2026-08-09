import type { User } from '../../domain/identity/user';
import {
  DEV_MODE,
  devLoginRequest,
  loginRequest,
  logoutRequest,
  registerRequest,
  verifySessionRequest,
} from '../../infrastructure/api/authApi';
import { API_BASE_URL } from '../../infrastructure/api/httpClient';

export class IdentityApplicationService {
  static getApiUrl(): string {
    return API_BASE_URL;
  }

  static isDevMode(): boolean {
    return DEV_MODE;
  }

  static async restoreSession(): Promise<User | null> {
    console.log('[AuthContext] Restoring session via /auth/verify');
    try {
      const session = await verifySessionRequest();

      if (session.user) {
        console.log('[AuthContext] Session restored for user:', session.user.email);
        return session.user;
      }

      if (DEV_MODE) {
        // No active session, but dev mode is on: establish one without
        // credentials via the backend dev-login (which sets the same httpOnly
        // cookie a real login would), so the login screen is skipped entirely.
        console.log('[AuthContext] DEV_MODE on -- requesting dev session');
        const devSession = await devLoginRequest();
        if (devSession.user) {
          console.log('[AuthContext] Dev session established for', devSession.user.email);
          return devSession.user;
        }

        console.warn(
          `[AuthContext] dev-login unavailable (status ${devSession.status}) -- ` +
          'is DEV_MODE=1 set on the backend? Showing login screen.'
        );
        return null;
      }

      // 401 here just means "not logged in" -- expected, not an error.
      console.log('[AuthContext] No active session (status', session.status, ')');
      return null;
    } catch (err) {
      console.warn('[AuthContext] Session check failed (backend unreachable?):', err);
      return null;
    }
  }

  static async login(email: string, password: string): Promise<User> {
    const loginUrl = `${API_BASE_URL}/auth/login`;
    console.log('[AuthContext] Login attempt started for:', email);

    try {
      const user = await loginRequest(email, password);
      console.log('[AuthContext] Login successful');
      return user;
    } catch (error) {
      if (error instanceof TypeError && error.message.includes('fetch')) {
        console.error('[AuthContext] Network error - Failed to connect to:', loginUrl);
        throw new Error(`Failed to connect to server at ${API_BASE_URL}. Please check if the backend is running.`);
      }
      throw error;
    }
  }

  static async register(
    email: string,
    password: string,
    firstName: string,
    lastName: string
  ): Promise<User> {
    const registerUrl = `${API_BASE_URL}/auth/register`;
    console.log('[AuthContext] Register attempt started for:', email);

    try {
      const user = await registerRequest(email, password, firstName, lastName);
      console.log('[AuthContext] Registration successful');
      return user;
    } catch (error) {
      if (error instanceof TypeError && error.message.includes('fetch')) {
        console.error('[AuthContext] Network error - Failed to connect to:', registerUrl);
        throw new Error(`Failed to connect to server at ${API_BASE_URL}. Please check if the backend is running.`);
      }
      throw error;
    }
  }

  static async logout(): Promise<void> {
    console.log('[AuthContext] Logout initiated');
    try {
      // Clear the httpOnly cookies server-side. Best-effort: even if this fails
      // (e.g. backend unreachable), we still drop the local user state.
      await logoutRequest();
    } catch (err) {
      console.warn('[AuthContext] Logout request failed (clearing local state anyway):', err);
    } finally {
      console.log('[AuthContext] Logout completed');
    }
  }
}
