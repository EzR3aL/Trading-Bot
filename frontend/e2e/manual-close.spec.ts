import { test, expect } from '@playwright/test'

// Smoke coverage for the manual-close flow on /trades (#335).
//
// Requires an authenticated session AND at least one open trade, which
// is hard to guarantee outside of a dedicated seeding fixture. We gate
// the full path on E2E_USER and keep an env-free assertion that the
// /trades route itself renders.
test.describe('manual close flow', () => {
  test('unauthenticated /trades redirects to /login', async ({ browser }) => {
    const ctx = await browser.newContext({
      storageState: { cookies: [], origins: [] },
    })
    const page = await ctx.newPage()
    await page.goto('/trades')
    // Wait for the login form — proves the <Navigate> guard fired.
    // Asserting on URL alone is racy because React-Router's Navigate
    // runs after the initial document load fires.
    await expect(page.getByLabel(/username/i)).toBeVisible({ timeout: 15_000 })
    await expect(page).toHaveURL(/\/login/)
    await ctx.close()
  })

  test('opens the manual close confirm dialog on an open trade', async ({ page }) => {
    test.skip(
      !process.env.E2E_USER || !process.env.E2E_PASS,
      'Requires E2E_USER and E2E_PASS env vars',
    )
    test.skip(
      !process.env.E2E_HAS_OPEN_TRADE,
      'Requires E2E_HAS_OPEN_TRADE=1 — at least one open trade must exist',
    )

    // The manual-close control lives on the Bots view against running
    // bots; the /trades page lists history. We go to /bots which is the
    // canonical place to close a live position (see Bots.tsx ClosePosition
    // mutation hook).
    await page.goto('/bots')

    // Look for a close-position control on any running bot row. The
    // button carries an `XCircle` icon and either a "Close" label or an
    // aria-label from the i18n bundle.
    const closeBtn = page
      .getByRole('button', { name: /close position|position schließen|close/i })
      .first()

    await expect(closeBtn).toBeVisible({ timeout: 10_000 })
    await closeBtn.click()

    // Confirm modal should appear — look for a confirm dialog role
    // and a destructive confirm button.
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(
      dialog.getByRole('button', { name: /confirm|bestätigen|yes|ja|close/i }),
    ).toBeVisible()
  })
})
