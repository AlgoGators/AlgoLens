import React, { createContext, useCallback, useContext, useEffect, useState, ReactNode } from 'react';
import {
  rememberedScreen,
  rememberScreen,
  ScreenService,
} from '../../application/identity/screenService';
import {
  availableScreens,
  landingScreen,
  NO_ACCESS,
  type AppScreen,
  type Screen,
  type ScreenAccess,
} from '../../domain/identity/screens';
import { useAuth } from './AuthContext';

interface ScreenContextType {
  access: ScreenAccess;
  /** The screens the switcher offers (Admin last, for admins). */
  available: AppScreen[];
  /** The screen shown; null = access pending (or still loading). */
  active: AppScreen | null;
  setActive: (screen: AppScreen) => void;
  hasScreen: (screen: Screen) => boolean;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

const ScreenContext = createContext<ScreenContextType | undefined>(undefined);

/** Loads the signed-in user's screens (GET /api/me/screens) and keeps the shown one. */
export function ScreenProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [access, setAccess] = useState<ScreenAccess>(NO_ACCESS);
  const [active, setActiveState] = useState<AppScreen | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  // The user whose screens are loaded: until it matches the signed-in user,
  // the app shows "loading", never "access pending".
  const [loadedFor, setLoadedFor] = useState<string | null>(null);

  useEffect(() => {
    if (!user) {
      setAccess(NO_ACCESS);
      setActiveState(null);
      setLoadedFor(null);
      setLoading(false);
      return;
    }
    const userKey = String(user.id);
    let cancelled = false;
    setLoading(true);
    setError(null);
    ScreenService.myAccess()
      .then(next => {
        if (cancelled) return;
        setAccess(next);
        setActiveState(current => landingScreen(next, current ?? rememberedScreen()));
      })
      .catch(err => {
        if (cancelled) return;
        setAccess(NO_ACCESS);
        setActiveState(null);
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (cancelled) return;
        setLoadedFor(userKey);
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [user?.id, reloadKey]);

  const setActive = useCallback(
    (screen: AppScreen) => {
      if (!availableScreens(access).includes(screen)) return;
      rememberScreen(screen);
      setActiveState(screen);
    },
    [access],
  );

  const hasScreen = useCallback((screen: Screen) => access.screens.includes(screen), [access]);
  const reload = useCallback(() => setReloadKey(k => k + 1), []);

  return (
    <ScreenContext.Provider
      value={{
        access,
        available: availableScreens(access),
        active,
        setActive,
        hasScreen,
        loading: loading || (user != null && loadedFor !== String(user.id)),
        error,
        reload,
      }}
    >
      {children}
    </ScreenContext.Provider>
  );
}

export function useScreens() {
  const context = useContext(ScreenContext);
  if (context === undefined) {
    throw new Error('useScreens must be used within a ScreenProvider');
  }
  return context;
}
