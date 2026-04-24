import { defineConfig, devices } from '@playwright/test'

// Playwright configuration for frontend E2E smoke tests (#335).
//
// Design choices:
//  - Chromium only. Adding firefox/webkit roughly triples CI wall time
//    for zero extra regression-signal on a smoke suite of three flows.
//  - `webServer` is started automatically. Local devs can override by
//    pointing PLAYWRIGHT_BASE_URL at an already-running server, which
//    also disables the auto-start (`reuseExistingServer: true`).
//  - `retries: 1` on CI only. Retries mask real flake locally; in CI
//    a single retry buys us robustness against the occasional dev-server
//    cold-start flake without encouraging flaky tests to land.
//  - A dedicated `setup` project runs globalSetup (login + storageState
//    capture) once per run and gates all other projects via `dependencies`.
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:5173'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  timeout: 30_000,
  expect: { timeout: 5_000 },

  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    {
      name: 'setup',
      testMatch: /global\.setup\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        storageState: 'e2e/.auth/user.json',
      },
      dependencies: ['setup'],
    },
  ],

  webServer: {
    command: 'npm run dev',
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
})
