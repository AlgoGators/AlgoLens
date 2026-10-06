import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // Most suites here test pure functions and want no DOM. A component test
    // opts in with a `@vitest-environment jsdom` docblock at the top of the
    // file, which keeps the fast majority fast -- spinning up jsdom costs about
    // thirty seconds across the suite.
    environment: 'node',
    setupFiles: ['./src/test/setup.ts'],
  },
});
