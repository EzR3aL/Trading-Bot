# Frontend Testing & Coverage

## Deutsch

### Überblick

Das Frontend (`frontend/`) nutzt **Vitest** (Testrunner) zusammen mit
**React Testing Library** und **jsdom**. Seit Issue #334 ist zusätzlich
eine Coverage-Erfassung mit dem **v8**-Provider (`@vitest/coverage-v8`)
inklusive erzwungener Mindest-Schwellen eingerichtet.

### Verfügbare npm-Scripts

```bash
cd frontend

npm test             # Alle Tests einmal ausführen (CI-Modus, ohne Coverage)
npm run test:watch   # Watch-Modus während der Entwicklung
npm run test:coverage  # Einmal-Lauf mit Coverage + Threshold-Prüfung
```

### Coverage ausführen

```bash
cd frontend
npm install --legacy-peer-deps   # falls noch nicht installiert
npm run test:coverage
```

Nach dem Lauf:

- Textreport erscheint direkt in der Konsole.
- HTML-Report liegt unter `frontend/coverage/index.html`
  (im Browser öffnen).
- `frontend/coverage/lcov.info` kann von CI-Tools (Codecov, SonarQube)
  konsumiert werden.

Das `frontend/coverage/`-Verzeichnis ist über `frontend/.gitignore`
ausgeschlossen und darf nicht committet werden.

### Konfiguration

Die Coverage-Konfiguration lebt in `frontend/vitest.config.ts` unter
`test.coverage`:

- **Provider:** `v8` (nutzt die Node-V8-Coverage-API, keine Babel-Trans-
  formation nötig).
- **Reporter:** `text`, `html`, `lcov`.
- **Include:** `src/**/*.{ts,tsx}`.
- **Exclude:** Typdefinitionen, Test-Dateien, `main.tsx`, `vite-env.d.ts`
  und das Test-Setup-Verzeichnis.
- **Schwellen (Stand #334):** Statements ≥ 42 %, Branches ≥ 30 %,
  Functions ≥ 37 %, Lines ≥ 42 %. Diese Zahlen liegen bewusst ein paar
  Prozentpunkte unter der tatsächlichen Abdeckung (~44 / 33 / 40 / 46 %)
  und dienen als **Regressionsschutz**, nicht als Qualitätsziel.

### Schwellen erhöhen

Wenn neue Tests dazugekommen sind:

1. `npm run test:coverage` ausführen und die tatsächliche Coverage
   aus der `All files`-Zeile ablesen.
2. `frontend/vitest.config.ts` öffnen und die vier `thresholds`-Werte
   um 2–3 Punkte unter die neuen Istwerte hochschrauben.
3. Änderung committen — CI fängt damit Coverage-Regressionen ab.

### Hinweise

- `v8`-Instrumentierung verlangsamt die Tests merklich. Der globale
  `testTimeout` ist daher auf 20 s gesetzt (`vitest.config.ts`), damit
  integrationsnahe Tests unter Coverage-Last nicht flaky werden.
  `npm test` (ohne Coverage) ist davon in der Praxis nicht betroffen.
- `npm ci --legacy-peer-deps` wird auch in der CI (`.github/workflows/ci.yml`)
  verwendet — wegen eines eslint@8.56-Plugin-Konflikts.

---

## English

### Overview

The frontend (`frontend/`) uses **Vitest** (test runner) together with
**React Testing Library** and **jsdom**. Since issue #334 coverage is
also collected via the **v8** provider (`@vitest/coverage-v8`), with
enforced minimum thresholds.

### Available npm scripts

```bash
cd frontend

npm test             # Run the full suite once (CI mode, no coverage)
npm run test:watch   # Watch mode while developing
npm run test:coverage  # One-shot run with coverage + threshold check
```

### Running coverage

```bash
cd frontend
npm install --legacy-peer-deps   # if not already installed
npm run test:coverage
```

After the run:

- The text report is printed straight to the console.
- The HTML report lives at `frontend/coverage/index.html`
  (open in a browser).
- `frontend/coverage/lcov.info` can be consumed by CI tools (Codecov,
  SonarQube).

The `frontend/coverage/` directory is ignored via `frontend/.gitignore`
and must not be committed.

### Configuration

Coverage configuration lives in `frontend/vitest.config.ts` under
`test.coverage`:

- **Provider:** `v8` (uses Node's native V8 coverage API, no Babel
  transform required).
- **Reporters:** `text`, `html`, `lcov`.
- **Include:** `src/**/*.{ts,tsx}`.
- **Exclude:** type declarations, test files, `main.tsx`,
  `vite-env.d.ts`, and the test-setup folder.
- **Thresholds (as of #334):** statements ≥ 42 %, branches ≥ 30 %,
  functions ≥ 37 %, lines ≥ 42 %. These numbers are intentionally a few
  percentage points below the actual coverage (~44 / 33 / 40 / 46 %)
  and act as a **regression guard**, not as a quality target.

### Raising the thresholds

After adding more tests:

1. Run `npm run test:coverage` and read the actual coverage from the
   `All files` row.
2. Edit `frontend/vitest.config.ts` and bump the four `thresholds`
   values to 2–3 points below the new actuals.
3. Commit the change — CI will now catch coverage regressions.

### Notes

- v8 instrumentation noticeably slows tests down. The global
  `testTimeout` is therefore set to 20 s in `vitest.config.ts` so that
  integration-style tests do not flake under coverage load. `npm test`
  (without coverage) is not affected in practice.
- `npm ci --legacy-peer-deps` is also used by CI
  (`.github/workflows/ci.yml`) because of an eslint@8.56 plugin peer
  conflict.
