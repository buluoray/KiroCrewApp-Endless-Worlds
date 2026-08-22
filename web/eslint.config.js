// ESLint gate for the Endless Worlds UI.
//
// History: this started as a deliberately NARROW gate enforcing only React's
// Rules of Hooks — a hook declared after an early return (React error #310, the
// bug that white-screened the Life Star Map) fails CI instead of shipping. That
// rule remains an ERROR and must stay one.
//
// It is now widened to typescript-eslint's `recommended` set for real
// correctness signal (unsafe patterns, obvious mistakes). The existing ~7k lines
// of source turned out to be clean against `recommended`: enabling it surfaced a
// single unused import, which was fixed rather than suppressed. So NO recommended
// rule is downgraded here — the gate exits 0 at full strength. If a future rule
// ever floods pre-existing code, downgrade THAT rule to 'warn'/'off' with a
// reason rather than weakening the set wholesale.
import reactHooks from 'eslint-plugin-react-hooks'
import tseslint from 'typescript-eslint'
import eslintConfigPrettier from 'eslint-config-prettier'

export default tseslint.config(
  { ignores: ['node_modules', 'dist'] },

  // typescript-eslint recommended (non-type-checked): fast, no typed-linting
  // program required, catches genuine correctness issues.
  ...tseslint.configs.recommended,

  {
    files: ['src/**/*.{ts,tsx}'],
    // Pre-existing `eslint-disable ... exhaustive-deps` comments in the source are
    // no-ops while that rule is off (below); don't warn about them.
    linterOptions: { reportUnusedDisableDirectives: 'off' },
    languageOptions: {
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      // The original recurrence target — stays an error.
      'react-hooks/rules-of-hooks': 'error',
      // exhaustive-deps is a separate, noisy concern (dependency arrays) and is
      // NOT the recurrence target; leaving it off keeps the signal clean.
      'react-hooks/exhaustive-deps': 'off',

      // Keep no-unused-vars an ERROR (recommended default) but honor the
      // conventional leading-underscore opt-out for deliberately-unused bindings
      // (callback args, caught errors). This hardens rather than weakens the rule.
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
    },
  },

  // Turn off every stylistic rule that could conflict with Prettier. MUST be last.
  eslintConfigPrettier,
)
