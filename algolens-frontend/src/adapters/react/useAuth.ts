import { useContext } from 'react';

import { AuthContext } from './AuthContext';

/**
 * Lives in its own module so AuthContext.tsx exports only components. React
 * Fast Refresh cannot preserve a module that mixes a component with a hook;
 * every hot update of that file remounted the provider with a new context
 * object while consumers kept the old hook, which threw the error below and
 * blanked the app until a full reload.
 */
export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
