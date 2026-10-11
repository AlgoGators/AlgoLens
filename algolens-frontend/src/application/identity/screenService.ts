import { parseScreenAccess, type ScreenAccess } from '../../domain/identity/screens';
import { AccessApi, InvestorApi } from '../../infrastructure/api/accessApi';
import type { AdminUser, ScreenChange } from '../../infrastructure/api/accessApi';
import { ApiError } from '../../infrastructure/api/apiRequest';

export { ApiError };
export type { AdminUser, ScreenChange };

/** Screen access as the app sees it. */
export const ScreenService = {
  /** The signed-in user's screens (throws when the server cannot say). */
  async myAccess(): Promise<ScreenAccess> {
    return parseScreenAccess(await AccessApi.myScreens());
  },
  users: AccessApi.users,
  setScreens: AccessApi.setScreens,
};

/** The investor screen and the admin's reports. */
export const InvestorService = InvestorApi;

const REMEMBER_KEY = 'algolens.screen';

/** The last screen this browser showed (a per-viewer convenience only). */
export function rememberedScreen(): string | null {
  try {
    return window.localStorage.getItem(REMEMBER_KEY);
  } catch {
    return null;
  }
}

export function rememberScreen(screen: string): void {
  try {
    window.localStorage.setItem(REMEMBER_KEY, screen);
  } catch {
    // private window or blocked storage: nothing to remember
  }
}
