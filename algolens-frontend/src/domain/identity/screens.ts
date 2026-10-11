/**
 * Screen access (Dom, 2026-10-11): an admin assigns each user any of the
 * member, investor and qt screens; admin (exec_board) is a role, not a
 * screen. The server decides (GET /api/me/screens) and enforces every route;
 * this module only decides which screen the app shows.
 */

export type Screen = 'member' | 'investor' | 'qt';
export type AppScreen = Screen | 'admin';

/** Landing preference: a user holding several screens opens on the first held. */
export const SCREEN_ORDER: Screen[] = ['qt', 'member', 'investor'];

export const SCREEN_LABELS: Record<AppScreen, string> = {
  member: 'Member',
  investor: 'Investor',
  qt: 'QT',
  admin: 'Admin',
};

export interface ScreenAccess {
  screens: Screen[];
  isAdmin: boolean;
}

export const NO_ACCESS: ScreenAccess = { screens: [], isAdmin: false };

export function isScreen(value: unknown): value is Screen {
  return value === 'member' || value === 'investor' || value === 'qt';
}

/** The API's answer, cleaned: unknown screens dropped, in landing order. */
export function parseScreenAccess(data: unknown): ScreenAccess {
  const raw = (data ?? {}) as { screens?: unknown; is_admin?: unknown };
  const held = new Set(Array.isArray(raw.screens) ? raw.screens.filter(isScreen) : []);
  return {
    screens: SCREEN_ORDER.filter(screen => held.has(screen)),
    isAdmin: raw.is_admin === true,
  };
}

/** The screens the switcher offers, in order; Admin last, for admins. */
export function availableScreens(access: ScreenAccess): AppScreen[] {
  const screens: AppScreen[] = SCREEN_ORDER.filter(screen => access.screens.includes(screen));
  if (access.isAdmin) screens.push('admin');
  return screens;
}

/**
 * The screen to show: the remembered choice while it is still available,
 * otherwise the first available one; null means "access pending" (no screen
 * and not an admin).
 */
export function landingScreen(access: ScreenAccess, remembered?: string | null): AppScreen | null {
  const available = availableScreens(access);
  if (remembered && (available as string[]).includes(remembered)) {
    return remembered as AppScreen;
  }
  return available[0] ?? null;
}

/** The screen set an admin edit produces: toggling one screen on or off. */
export function toggleScreen(screens: Screen[], screen: Screen, on: boolean): Screen[] {
  const held = new Set(screens);
  if (on) held.add(screen);
  else held.delete(screen);
  return SCREEN_ORDER.filter(s => held.has(s));
}

/** Whether a row's draft differs from what the server holds. */
export function screensChanged(saved: Screen[], draft: Screen[]): boolean {
  if (saved.length !== draft.length) return true;
  const held = new Set(saved);
  return draft.some(screen => !held.has(screen));
}
