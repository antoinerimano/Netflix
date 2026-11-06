// ESLint (npm run lint): the rules Create React App used to check during the build
// (eslint-config-react-app), for JSX in .js files.
import js from '@eslint/js';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';

export default [
  { ignores: ['build/**', 'build-e2e/**', 'node_modules/**'] },
  {
    files: ['src/**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: { ...globals.browser },
    },
    settings: { react: { version: 'detect' } },
    plugins: { react, 'react-hooks': reactHooks },
    rules: {
      ...js.configs.recommended.rules,
      'react/jsx-uses-vars': 'error',
      'react/jsx-uses-react': 'error',
      'react/jsx-no-undef': 'error',
      'react/jsx-key': 'warn',
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      'no-unused-vars': ['warn', { args: 'none', ignoreRestSiblings: true, caughtErrors: 'none' }],
      'no-empty': ['warn', { allowEmptyCatch: true }],
    },
  },
  {
    files: ['src/**/*.test.{js,jsx}', 'src/setupTests.js'],
    languageOptions: { globals: { ...globals.browser, ...globals.node, ...globals.vitest } },
  },
];
