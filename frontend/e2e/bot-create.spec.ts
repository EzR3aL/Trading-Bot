import { test, expect } from '@playwright/test'

// Smoke coverage for the "create bot" wizard (#335).
//
// The wizard lives behind the authenticated /bots route. Without real
// credentials we cannot reach it, so the whole walk-through is gated
// on E2E_USER. The env-free subtest asserts the /login redirect, which
// proves at minimum that the route guard is wired up.
test.describe('bot create wizard', () => {
  test('unauthenticated visit redirects to /login', async ({ browser }) => {
    // Bypass the project-level storageState to exercise the guard.
    const ctx = await browser.newContext({
      storageState: { cookies: [], origins: [] },
    })
    const page = await ctx.newPage()
    await page.goto('/bots')
    // Wait for the login form — proves the <Navigate> guard fired.
    // Asserting on URL alone is racy because React-Router's Navigate
    // runs after the initial document load fires.
    await expect(page.getByLabel(/username/i)).toBeVisible({ timeout: 15_000 })
    await expect(page).toHaveURL(/\/login/)
    await ctx.close()
  })

  test('walks through the wizard to the review step', async ({ page }) => {
    test.skip(
      !process.env.E2E_USER || !process.env.E2E_PASS,
      'Requires E2E_USER and E2E_PASS env vars',
    )

    await page.goto('/bots')

    // Open the wizard. The button copy is localized ("New Bot" / "Neuer Bot");
    // match by role + partial label to stay resilient.
    await page
      .getByRole('button', { name: /new bot|neuer bot|create|erstellen/i })
      .first()
      .click()

    // Step 1 — Name
    await page.getByLabel(/name/i).first().fill('e2e-smoke-bot')
    await page.getByRole('button', { name: /next|weiter/i }).click()

    // Subsequent steps (strategy, data sources, exchange, notifications,
    // schedule) vary per-exchange. Repeatedly click "Next/Weiter" until
    // we land on Review or the button disappears. Cap iterations so a
    // regression that breaks navigation fails fast instead of hanging.
    for (let i = 0; i < 6; i++) {
      const nextBtn = page.getByRole('button', { name: /^(next|weiter)$/i })
      if (!(await nextBtn.isVisible().catch(() => false))) break
      await nextBtn.click()
      await page.waitForTimeout(150)
    }

    // At the end of the wizard we expect either a "Review/Save/Create"
    // button or a completion toast.
    const finalButton = page.getByRole('button', {
      name: /save|create|speichern|erstellen|review/i,
    })
    await expect(finalButton.first()).toBeVisible({ timeout: 10_000 })
  })
})
