import js from '@eslint/js'
import globals from 'globals'
import tseslint from 'typescript-eslint'

// Flat ESLint config (ESLint 9). Type-aware linting is intentionally omitted to keep `lint` fast;
// `tsc --noEmit` (the `typecheck` script) provides full type checking.
export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'coverage'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
  },
)
