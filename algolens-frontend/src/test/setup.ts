/**
 * Shared test setup.
 *
 * The only thing here is unmounting components between tests, and it is here
 * rather than in each file because forgetting it does not fail loudly -- it
 * makes every query find two of everything, several tests later, in a file that
 * did nothing wrong. React Testing Library registers this itself when a test
 * framework exposes a global `afterEach`; this project does not set
 * `globals: true`, so it has to be wired explicitly.
 *
 * Guarded on `document`, because most suites in this repository test pure
 * functions and run under the node environment, where there is nothing to
 * clean up and `@testing-library/react` cannot even be imported.
 */
import { afterEach } from 'vitest';

if (typeof document !== 'undefined') {
  const { cleanup } = await import('@testing-library/react');
  afterEach(cleanup);
}
