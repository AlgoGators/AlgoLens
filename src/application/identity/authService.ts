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
  static isDevMode(): boolean {
    return DEV_MODE;
  }

  static async restoreSession(): Promise<User | null> {
    const user = await verifySessionRequest();
    if (user) {
      return user;
    }

    if (DEV_MODE) {
      return devLoginRequest();
    }

    return null;
  }

  static async login(email: string, password: string): Promise<User> {
    try {
      return await loginRequest(email, password);
    } catch (error) {
      if (error instanceof TypeError && error.message.includes('fetch')) {
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
    try {
      return await registerRequest(email, password, firstName, lastName);
    } catch (error) {
      if (error instanceof TypeError && error.message.includes('fetch')) {
        throw new Error(`Failed to connect to server at ${API_BASE_URL}. Please check if the backend is running.`);
      }
      throw error;
    }
  }

  static async logout(): Promise<void> {
    return logoutRequest();
  }
}
