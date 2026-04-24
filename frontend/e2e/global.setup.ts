import { test as setup, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Single login flow that writes a reusable storageState file.
//
// Every authed spec depends on this via the `setup` Playwright project.
// When E2E_USER/E2E_PASS are not configured we still write an empty
// storageState so the authed specs can load (they skip themselves at
// runtime via test.skip() based on the same env var).
// ESM: `__dirname` is undefined under `"type": "module"`, so rebuild it
// from the file URL.
const SETUP_DIR = path.dirname(fileURLToPath(import.meta.url))
const AUTH_DIR = path.join(SETUP_DIR, '.auth')
const STORAGE_STATE = path.join(AUTH_DIR, 'user.json')

setup('authenticate', async ({ page }) => {
  if (!fs.existsSync(AUTH_DIR)) {
    fs.mkdirSync(AUTH_DIR, { recursive: true })
  }

  const user = process.env.E2E_USER
  const pass = process.env.E2E_PASS

  // No secrets? Write an empty storageState so specs can still load.
  // Each authed spec checks the env var itself and skips with a reason.
  if (!user || !pass) {
    fs.writeFileSync(
      STORAGE_STATE,
      JSON.stringify({ cookies: [], origins: [] }, null, 2),
    )
    return
  }

  await page.goto('/login')
  await page.getByLabel(/username/i).fill(user)
  await page.getByLabel(/password/i).fill(pass)
  await page.getByRole('button', { name: /sign in|log in|anmelden|submit/i }).click()

  // Successful login bounces to the protected root (Dashboard at "/").
  await expect(page).toHaveURL(/\/(dashboard|portfolio|bots)?$/i, { timeout: 15_000 })

  await page.context().storageState({ path: STORAGE_STATE })
})
