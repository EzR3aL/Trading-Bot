/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    css: false,
    mockReset: true,
    // v8 coverage instrumentation slows tests ~3x; bump the default 5s
    // timeout so the larger integration-style tests do not flake under
    // `npm run test:coverage`. `npm test` (no coverage) is unaffected in
    // practice because those tests finish well under 5s without v8.
    testTimeout: 20000,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/**/*.d.ts',
        'src/**/*.test.{ts,tsx}',
        'src/**/*.spec.{ts,tsx}',
        'src/**/__tests__/**',
        'src/main.tsx',
        'src/vite-env.d.ts',
        'src/test/**',
      ],
      // Initial floor thresholds. Actual coverage as of PR #334 is
      // ~44.09% statements / 32.97% branches / 40.19% functions /
      // 45.75% lines. Thresholds are set a few percentage points below
      // each to keep CI green while preventing regressions. Ratchet up
      // as tests are added.
      thresholds: {
        statements: 42,
        branches: 30,
        functions: 37,
        lines: 42,
      },
    },
  },
})
