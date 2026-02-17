module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  ignorePatterns: ['dist', '.eslintrc.cjs'],
  parser: '@typescript-eslint/parser',
  rules: {
    '@typescript-eslint/no-explicit-any': 'warn',
    '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
    // Data-loading in useEffect with setState is standard React pattern
    'react-hooks/set-state-in-effect': 'off',
    // Accumulator pattern in useMemo/map is safe
    'react-hooks/immutability': 'off',
    'no-empty': ['error', { allowEmptyCatch: true }],
  },
}
