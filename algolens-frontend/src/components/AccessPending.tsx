import React from 'react';
import { Lock } from 'lucide-react';
import logo from '../assets/logo.png';
import { useAuth } from '../adapters/react/AuthContext';
import { useTheme } from '../adapters/react/ThemeContext';

interface AccessPendingProps {
  onLogout: () => void;
  onRetry: () => void;
  /** Set when the screens could not be loaded (rather than none assigned). */
  error?: string;
}

/** A signed-in user with no screen yet: an admin assigns access. */
export function AccessPending({ onLogout, onRetry, error }: AccessPendingProps) {
  const { theme } = useTheme();
  const { user } = useAuth();
  const dark = theme === 'dark';

  return (
    <div
      className={`min-h-screen flex items-center justify-center px-4 ${
        dark ? 'bg-black text-white' : 'bg-white text-black'
      }`}
    >
      <div
        className={`w-full max-w-md border rounded-2xl p-8 text-center ${
          dark ? 'border-gray-800' : 'border-gray-200'
        }`}
      >
        <img
          src={logo}
          alt="ALGO"
          className="h-8 mx-auto mb-6"
          style={dark ? { filter: 'invert(1) hue-rotate(180deg)' } : undefined}
        />
        <Lock className="w-8 h-8 mx-auto mb-4 text-orange-500" />
        {error ? (
          <>
            <h1 className="text-xl mb-2">Could not load your access</h1>
            <p className={`text-sm mb-6 ${dark ? 'text-gray-400' : 'text-gray-600'}`}>{error}</p>
          </>
        ) : (
          <>
            <h1 className="text-xl mb-2">Access pending</h1>
            <p className={`text-sm mb-6 ${dark ? 'text-gray-400' : 'text-gray-600'}`}>
              You are signed in{user?.email ? ` as ${user.email}` : ''}, but no screen is assigned to
              your account yet. An admin assigns your access; check back once they have.
            </p>
          </>
        )}
        <div className="flex items-center justify-center gap-3">
          <button
            type="button"
            onClick={onRetry}
            className="text-sm bg-orange-500 text-white px-4 py-2 rounded-lg hover:bg-orange-600 transition-colors"
          >
            Check again
          </button>
          <button
            type="button"
            onClick={onLogout}
            className={`text-sm px-4 py-2 rounded-lg transition-colors ${
              dark ? 'text-gray-400 hover:text-white hover:bg-gray-900' : 'text-gray-600 hover:bg-gray-100'
            }`}
          >
            Log out
          </button>
        </div>
      </div>
    </div>
  );
}
