import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    // D-59: a coverage gate on the logic the screens run on (domain rules and application
    // services); `npm run test:coverage` in CI fails below it.
    coverage: {
      provider: 'v8',
      include: ['src/domain/**', 'src/application/**'],
      exclude: ['**/*.test.ts'],
      thresholds: { lines: 85, functions: 85, statements: 85, branches: 80 },
    },
  },
});
