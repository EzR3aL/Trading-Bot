# Frontend E2E Tests mit Playwright (#335)

## Deutsch

### Überblick
Playwright liefert browser-basierte End-to-End-Tests für drei kritische
Smoke-Flows:

- `login.spec.ts` — Login-Formular rendert + Login mit Credentials
- `bot-create.spec.ts` — Bot-Erstellungs-Wizard durchlaufen
- `manual-close.spec.ts` — Offene Position manuell schließen (Confirm-Dialog)

Die Tests liegen in `frontend/e2e/`. Alle Flows, die echte Credentials
brauchen, werden über `test.skip(!process.env.E2E_USER, ...)` gated — in
CI ohne Secrets laufen sie als "skipped", niemals als "failed".

### Lokal ausführen

```bash
cd frontend
npm install --legacy-peer-deps
npx playwright install chromium   # einmalig
npm run test:e2e                  # headless
npm run test:e2e:headed           # mit sichtbarem Browser
```

Der Playwright `webServer`-Block startet `npm run dev` automatisch und
wartet bis zu 120 Sekunden auf `http://localhost:5173`. Wenn bereits ein
Dev-Server läuft, wird er (lokal) wiederverwendet — in CI wird er immer
frisch gestartet.

### Erforderliche Environment-Variablen

| Variable | Zweck | Pflicht? |
|----------|-------|----------|
| `E2E_USER` | Username eines Test-Accounts | nur für credential-flows |
| `E2E_PASS` | Passwort desselben Accounts | nur für credential-flows |
| `E2E_HAS_OPEN_TRADE` | `1` setzen, wenn Account eine offene Position hat | nur für manual-close |
| `PLAYWRIGHT_BASE_URL` | Override der Basis-URL (Default: `http://localhost:5173`) | nein |

Ohne diese Variablen laufen die env-freien Subtests weiter und
verifizieren zumindest, dass die Routen existieren und Auth-Guards
greifen.

### storageState aktualisieren
Der Playwright-Config hat ein `setup`-Projekt (`e2e/global.setup.ts`),
das einmal pro Testlauf einloggt und den Session-State nach
`frontend/e2e/.auth/user.json` schreibt. Alle authenticated Specs lesen
diesen State anstatt selbst zu loggen.

Der State verfällt, wenn sich das JWT-Signing-Secret oder das
Cookie-Schema ändert. Um ihn manuell zu erneuern:

```bash
rm -rf frontend/e2e/.auth
npm run test:e2e -- --project=setup
```

Die Datei ist per `.gitignore` aus dem Repo ausgeschlossen.

### Test-Reports
Nach jedem Lauf liegt der HTML-Report unter
`frontend/playwright-report/`. In CI wird er als GitHub-Artefakt
hochgeladen (7 Tage Retention). Traces, Videos und Screenshots werden
nur bei Fehlschlägen gespeichert (`retain-on-failure`).

### CI-Verhalten
Der Job `frontend-e2e` in `.github/workflows/ci.yml` hat aktuell
`continue-on-error: true` — ein Fehlschlag ist sichtbar, blockiert aber
keinen Merge. Sobald die Suite ~2 Wochen stabil grün ist, wird das Flag
entfernt.

Secrets, die in GitHub Repo-Settings → Secrets → Actions anzulegen sind:

- `E2E_USER`
- `E2E_PASS`
- `E2E_HAS_OPEN_TRADE` (optional)

---

## English

### Overview
Playwright ships browser-level end-to-end coverage for three critical
smoke flows:

- `login.spec.ts` — login form renders + login with credentials
- `bot-create.spec.ts` — walks through the bot create wizard
- `manual-close.spec.ts` — manually closes an open position (confirm dialog)

Tests live in `frontend/e2e/`. Every flow that needs real credentials is
gated with `test.skip(!process.env.E2E_USER, ...)` — in CI without
secrets the tests skip, they never fail.

### Running locally

```bash
cd frontend
npm install --legacy-peer-deps
npx playwright install chromium   # one-time
npm run test:e2e                  # headless
npm run test:e2e:headed           # visible browser
```

The Playwright `webServer` block boots `npm run dev` automatically and
waits up to 120 seconds for `http://localhost:5173`. A running dev
server is reused locally but always started fresh in CI.

### Required environment variables

| Variable | Purpose | Required? |
|----------|---------|-----------|
| `E2E_USER` | Username of a disposable test account | credential flows only |
| `E2E_PASS` | Password for that account | credential flows only |
| `E2E_HAS_OPEN_TRADE` | Set to `1` when the test account has an open position | manual-close only |
| `PLAYWRIGHT_BASE_URL` | Override the base URL (default `http://localhost:5173`) | no |

Without these variables the env-free subtests still run and verify that
the routes exist and the auth guards redirect correctly.

### Updating storageState
The config registers a `setup` project (`e2e/global.setup.ts`) that logs
in once per run and writes the session to
`frontend/e2e/.auth/user.json`. All authenticated specs read this state
rather than logging in themselves.

The state goes stale if the JWT signing secret or cookie schema
changes. To refresh it manually:

```bash
rm -rf frontend/e2e/.auth
npm run test:e2e -- --project=setup
```

The file is git-ignored.

### Reports
Each run writes an HTML report to `frontend/playwright-report/`. CI
uploads it as a GitHub artifact (7-day retention). Traces, videos, and
screenshots are only kept for failures (`retain-on-failure`).

### CI behaviour
The `frontend-e2e` job in `.github/workflows/ci.yml` currently has
`continue-on-error: true` — failures show up in the checks tab but do
not block merges. The flag will be removed once the suite stays green
for roughly two weeks.

Secrets to add under GitHub repo settings → Secrets → Actions:

- `E2E_USER`
- `E2E_PASS`
- `E2E_HAS_OPEN_TRADE` (optional)
