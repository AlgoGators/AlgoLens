import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import sonarjs from 'eslint-plugin-sonarjs';

export default tseslint.config(
  { ignores: ['build/**', 'node_modules/**', 'dist/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: {
      'react-hooks': reactHooks,
      sonarjs,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // The one rule the user asked to enforce.
      'sonarjs/cognitive-complexity': ['error', 15],
      // Keep unrelated stylistic noise from blocking; complexity stays an error.
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
      'no-empty': 'warn',
    },
  }
);
