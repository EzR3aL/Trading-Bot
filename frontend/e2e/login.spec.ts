import { test, expect } from '@playwright/test'

// Smoke-level login coverage (#335).
//
// The env-free case always runs and protects against the form failing
// to render at all. The credential-driven case only runs when real
// secrets are injected — we do NOT want flaky "login doesn't work"
// failures in CI when the env variables were never provisioned.
test.describe('login flow', () => {
  // Login must render without a stored session — override the project's
  // storageState just for this file.
  test.use({ storageState: { cookies: [], origins: [] } })

  test('renders the login form', async ({ page }) => {
    await page.goto('/login')

    await expect(page.getByLabel(/username/i)).toBeVisible()
    await expect(page.getByLabel(/password/i)).toBeVisible()
    await expect(
      page.getByRole('button', { name: /sign in|log in|anmelden|submit/i }),
    ).toBeVisible()
  })

  test('logs in with valid credentials', async ({ page }) => {
    test.skip(
      !process.env.E2E_USER || !process.env.E2E_PASS,
      'Requires E2E_USER and E2E_PASS env vars',
    )

    await page.goto('/login')
    await page.getByLabel(/username/i).fill(process.env.E2E_USER!)
    await page.getByLabel(/password/i).fill(process.env.E2E_PASS!)
    await page.getByRole('button', { name: /sign in|log in|anmelden|submit/i }).click()

    // Landing page after login is "/" (Dashboard); we accept any
    // non-/login post-auth URL since the app may route to onboarding.
    await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 })
  })
})
