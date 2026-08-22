// A deliberately NARROW ESLint gate: enforce React's Rules of Hooks so a hook
// declared after an early return (React error #310 — the bug that white-screened
// the Life Star Map) fails CI instead of shipping. Only `rules-of-hooks` is an
// error; nothing else is enabled, so this never floods the existing code with
// style/formatting findings. Widen it later on purpose, not by accident.
import reactHooks from 'eslint-plugin-react-hooks'
import tsParser from '@typescript-eslint/parser'

export default [
  {
    files: ['src/**/*.{ts,tsx}'],
    // Pre-existing `eslint-disable ... exhaustive-deps` comments in the source are
    // no-ops while that rule is off (below); don't warn about them — this gate is
    // about rules-of-hooks only, and stays silent otherwise.
    linterOptions: { reportUnusedDisableDirectives: 'off' },
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      // exhaustive-deps is a separate, noisy concern (dependency arrays) and is
      // NOT the recurrence target here; leaving it off keeps the signal clean.
      'react-hooks/exhaustive-deps': 'off',
    },
  },
]
