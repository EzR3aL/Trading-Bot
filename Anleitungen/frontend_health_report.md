# Frontend Health Report — 2026-04-23

_Audit Scope: `frontend/` (99 source TS/TSX files, ca. 30.536 LOC inkl. Tests).
Zero Code-Änderungen, nur Inventar und Follow-up-Issues. Basis-Commit: `b3031a2` (main)._

---

## Deutsch

### Zusammenfassung

Das Frontend ist in gutem Zustand: TypeScript läuft unter `strict` mit `noUnusedLocals`/`noUnusedParameters`, keine einzige `@ts-ignore`, Error-Boundaries umhüllen sowohl den gesamten App-Tree als auch jede Route, React-Query ist konsequent als State-Layer eingesetzt und i18n hat Vollständigkeits-Tests mit Parity-Checks. Die Top 3 🔴-Funde betreffen (1) **Shape Drift zwischen Pydantic und TypeScript** — `Trade.builder_fee: number` im FE existiert nicht im Backend-Schema und `take_profit/stop_loss` sind im FE non-nullable, im BE `Optional`; (2) **fehlendes `eslint-plugin-jsx-a11y`** — ohne automatische Accessibility-Prüfung werden Regressionen schleichend eingeführt (bereits 10 `<div onClick>` ohne Keyboard-Handler); (3) **kein globaler `unhandledrejection`-Handler** — unerwartete Promise-Rejections laufen still in die Browser-Konsole, Nutzer und Telemetrie bekommen nichts mit.

Gesamtverteilung: 3 🔴, 5 🟡, 6 🟢.

### 1. TypeScript-Strictness

**🟢 Solide Basis.**
- `tsconfig.json` hat `strict: true`, `noUnusedLocals`, `noUnusedParameters`, `noFallthroughCasesInSwitch` (Zeilen 14–17).
- `0` Vorkommen von `@ts-ignore`/`@ts-expect-error`/`@ts-nocheck` im gesamten `src/`.
- 28 `: any`-Treffer in 14 Dateien — davon liegen 19 in `__tests__`/Tests (explizite Mocks). Produktiv bleiben ~9, z.B. in `pages/Portfolio.tsx` (3×), `pages/Admin.tsx` (1×), `components/bots/BotBuilderStepStrategy.tsx` (1×), `types/riskState.ts` (1×).
- 16 `as any`/`as unknown`-Casts, davon ~5 in Produktivcode (`pages/Bots.tsx`, `components/bots/BotBuilder.tsx`). Einzelne inspizieren.
- `react-hooks/set-state-in-effect` und `react-hooks/immutability` in ESLint bewusst deaktiviert (`.eslintrc.cjs:15–17`) — vertretbar mit Begründung im Kommentar.

### 2. API-Client-Integrität

**🔴 Shape Drift zwischen Python-Schema und TS-Typen.**

Es gibt **keine** OpenAPI-Generierung — TypeScript-Typen in `frontend/src/types/index.ts` sind von Hand gepflegt gegen die Pydantic-Schemas in `src/api/schemas/*.py`. Drift-Funde:

- **`Trade.builder_fee: number`** (`frontend/src/types/index.ts:41`) **existiert nicht in** `TradeResponse` (`src/api/schemas/trade.py:29–60`). Backend serialisiert das Feld nicht, FE liest `trade.builder_fee` → immer `undefined` → wahrscheinlich stumme UI-Bugs in PnL-/Fee-Darstellungen.
- **`Trade.take_profit: number`, `Trade.stop_loss: number`** (`frontend/src/types/index.ts:31–32`) — Backend-Schema hat `Optional[float] = None` (`src/api/schemas/trade.py:38–39`). TypeScript akzeptiert `null` als `number` nicht, was zu Crashes bei neuen Trades ohne TP/SL führen kann, sobald jemand ohne Optional-Chaining zugreift.
- `TokenResponse.access_token` bereits als `Optional` dokumentiert (SEC-012) — **korrekt**.

**🟡 Kein zentraler HTTP-Error-Handler neben `api.interceptors.response.use`.**
- `api/client.ts:185–226` behandelt 401 (Token-Refresh), alles andere landet im Consumer. Es gibt `utils/api-error.ts` (`getApiErrorMessage`) — wird nur an ~15 Stellen benutzt, Consumer-Seite inkonsistent.

**🟢 Token-Management ist exzellent** — Proactive Refresh, `visibilitychange`-Rehydration, Cross-Tab-Sync via `storage`-Event (`api/client.ts:232–265`).

### 3. State Management

**🟢 Zustand-Stores sind Feature-getrennt und schlank.**
- 7 Stores: `authStore`, `filterStore`, `realtimeStore`, `sizeUnitStore`, `themeStore`, `toastStore`, `tourStore` — jeweils <50 Zeilen, klare Verantwortung.
- React-Query für Server-State (`api/queries.ts`) mit konsistenten Query-Keys (Key-Factory in `queries.ts:21–47`).

**🟡 useEffect-Cleanup lückenhaft — setTimeout ohne Clear.**
- `pages/Admin.tsx:69` (`setTimeout(() => setMessage(''), 3000)` in `showMessage`-Callback): Beim Unmount während aktivem Timer feuert das State-Update nach → React-Warning "Can't perform setState on unmounted component" & potenzieller Memory-Leak.
- Gleiches Pattern: `pages/Settings.tsx:216`, `pages/Bots.tsx:214`, `pages/BotPerformance.tsx:474`. 4 Stellen.

**🟡 3× `useEffect(..., [])` mit `eslint-disable react-hooks/exhaustive-deps`**
- `pages/Dashboard.tsx:102`, `pages/Trades.tsx:153`, `hooks/useWebSocket.ts:36`, `components/ui/GuidedTour.tsx:162`, `components/bots/CopyTradingStepExchange.tsx:95` — teilweise bewusst (mount-only Sync), aber ohne Kommentare pro Stelle fehlt die Nachvollziehbarkeit.

### 4. Error Boundaries & Resilience

**🟢 Coverage ist gut.**
- Root-`ErrorBoundary` um den gesamten `App`-Tree (`App.tsx:66–102`).
- `RouteErrorBoundary` um **jede** lazy-geladene Route (11×, `App.tsx:69–94`).
- Spezialisierte `WalletErrorBoundary` in `components/hyperliquid/BuilderFeeApproval.tsx:392` und `HyperliquidSetup.tsx:652` für Wallet-Edge-Cases.
- `OfflineIndicator.tsx` mit `role="alert"` + `aria-live="assertive"`, 3-Fehler-Schwelle, proper cleanup.

**🔴 Kein globaler `unhandledrejection`-Handler.**
- 0 Treffer für `unhandledrejection`, `window.addEventListener('error'`. Alle unawaited Promise-Rejections (z.B. in `showMessage`-Callbacks, Bots.tsx share-Flow) gehen stumm in die Browser-Konsole, keine Telemetrie, keine Toast-Meldung.

**🟡 Nur 1 Datei nutzt AbortController** — `components/ui/OfflineIndicator.tsx` via `AbortSignal.timeout(8000)`. Axios-Request-Cancelation bei Route-Wechsel nicht implementiert; React-Query mildert das weitgehend, aber rohe `api.post('/trades/sync')` in `pages/Trades.tsx:150` auf mount läuft bis zum Ende auch wenn User die Seite verlässt.

### 5. Accessibility

**🔴 `eslint-plugin-jsx-a11y` ist NICHT installiert.**
- `.eslintrc.cjs` (21 Zeilen) listet nur `eslint:recommended`, `plugin:@typescript-eslint/recommended`, `plugin:react-hooks/recommended`. Keine a11y-Rules.
- `package.json` hat keinen Eintrag zu `jsx-a11y` oder `eslint-plugin-jsx-a11y`.
- Folge: Keine CI-Prüfung für Label-Assoziation, Keyboard-Traps, ARIA-Misuse.

**🟡 10 `<div onClick>`-Stellen ohne Keyboard-Handler**
- `pages/AdminBroadcasts.tsx` (2), `pages/Bots.tsx` (3), `pages/BotPerformance.tsx` (1), `components/ui/EditPositionPanel.tsx` (1), `components/ui/ConfirmModal.tsx` (1), `components/ui/GuidedTour.tsx` (1), `components/ui/MobileCollapsibleCard.tsx` (1) — nur 5 `onKeyDown`-Handler in 4 Dateien global.
- Diese Divs sind nicht keyboard-zugänglich (kein Tab, kein Enter).

**🟢 Positiv:**
- Login hat `aria-invalid`, `aria-describedby`, `autoFocus`, `autoComplete` (`pages/Login.tsx:73–103`).
- 124 aria-/role-Attribute in 41 Dateien, `focus-visible`-Regeln in `index.css:1248–1258`.
- `document.documentElement.lang` wird synchron mit `i18n.language` gehalten (`App.tsx:54–56`).

### 6. Performance

**🟢 Viel getan:**
- Code-Splitting: 10 Page-Components via `React.lazy` (`App.tsx:15–24`), `Suspense` mit Loader.
- Vite `manualChunks`: `wallet` (wagmi/viem/rainbowkit) und `charts` (recharts) getrennt (`vite.config.ts:19–26`).
- Virtualisierung via `useVirtualRows` (Issue #249) in `pages/Trades.tsx` — `components/virtualised/useVirtualRows.ts` mit Test.
- `useIntervalPaused` (`hooks/useIntervalPaused.ts`) pausiert Polling bei `document.visibilityState !== 'visible'`.

**🟡 `React.memo` kaum eingesetzt (3 Stellen).**
- Nur `components/ui/DetailGrid.tsx`, `MobileTradeCard.tsx`, `MobilePositionCard.tsx`. Listen in `Bots.tsx` (1.536 LOC!), `AdminUsers.tsx`, `Portfolio.tsx` rendern Karten ohne Memo → jede Parent-State-Änderung re-rendert alle Bot-Cards.
- Zwar kein gemessenes Perf-Problem, aber bei steigender Bot-Anzahl wird's spürbar.

**🟡 Sehr große Page-Files** — sollten in kleinere Komponenten zerlegt werden:
- `pages/Bots.tsx`: 1.536 Zeilen
- `pages/BotPerformance.tsx`: 1.242 Zeilen
- `pages/Admin.tsx`: 1.113 Zeilen
- `components/bots/BotBuilder.tsx`: 782 Zeilen, 10 `useEffect`, nur 1 `aria-label`
- `pages/Portfolio.tsx`: 805 Zeilen

### 7. Theme + i18n

**🟢 Theme-Toggle solide.**
- `themeStore.ts:10–15` wendet Initial-Theme vor Hydration an (kein Flash).
- 52 Treffer `dark:bg-*`/`dark:text-*` über 12 Dateien — Tailwind dark-Mode konsistent.
- Cross-Tab-Sync fehlt aber: anders als `demo_filter` in `filterStore.ts:10` löst ein Theme-Toggle in Tab A keinen Storage-Event-Listener in Tab B aus.

**🟢 i18n ist ausgezeichnet.**
- `i18n-completeness.test.ts` (249 Zeilen!) testet: Top-Level-Section-Parity, totale Keyzahl, Dot-Path-Parity, struktureller Leaf-vs-Object-Mismatch, Tour-Keys, Guide-Keys, Exit-Reason-Label-Uniqueness (guards gegen Bug #194).
- `de.json` und `en.json` je 1.144 Zeilen.

**🟡 Keine Documentation-Lag-Sicherung** — wenn jemand i18n-Keys direkt in Komponenten via `t('newKey')` hardcoded und vergisst, den Key in **beiden** JSONs anzulegen, fällt das erst beim nächsten Testlauf auf, nicht beim Commit. Ein `grep`-Job in CI, der `t\(['"][^'"]+['"]\)` extrahiert und gegen die JSON-Keys joint, wäre nice-to-have.

### 8. Test-Coverage Frontend

**🟢 57 Test-Dateien, 99 Source-Dateien (ca. 58% file coverage).**
- Vitest konfiguriert mit `jsdom`, `mockReset: true`, `src/test/setup.ts` (`vitest.config.ts`).
- Breite Coverage: Alle 7 Stores haben Tests, 11 Page-Tests, 14 UI-Component-Tests, 5 Hook-Tests.
- Testing-Library React + user-event 14 + jest-dom.

**🟡 Kein `coverage`-Script in `package.json`.**
- `scripts.test: "vitest run"`, `test:watch: "vitest"` — kein `vitest run --coverage`. Man weiß nie, wo Coverage-Blind-Spots sind. `@vitest/coverage-v8` ist nicht installiert.

**🟡 Kein E2E-Framework (Playwright/Cypress).**
- Nur `@vitest/browser-playwright` als **transitive** Dep im `package-lock.json`. Kritische Money-Flows (Login → Bot Create → Bot Start → Manual Close, HL-Wizard 4-Step) haben keinen End-to-End-Test.

**🟢 Geld-kritische Hooks sind unit-getestet:**
- `api/__tests__/useUpdateTpSl.test.tsx` (TP/SL-Mutation + Optimistic Update + Rollback)
- `api/__tests__/client.test.ts` (Token-Refresh-Szenarien)
- `stores/__tests__/authStore.test.ts`

### Anhang: Follow-up-Issues

Severity | Issue-Nr. | Titel
---|---|---
🔴 | #329 | frontend: align Trade type with backend TradeResponse schema (builder_fee, nullable TP/SL)
🔴 | #330 | frontend: add eslint-plugin-jsx-a11y to catch accessibility regressions in CI
🔴 | #331 | frontend: add global unhandledrejection + error handler for telemetry and user feedback
🟡 | #332 | frontend: clean up setTimeout timers without cleanup in Admin/Settings/Bots/BotPerformance
🟡 | #333 | frontend: make div-onClick handlers keyboard-accessible (10 sites)
🟡 | #334 | frontend: add coverage script and enforce threshold for frontend tests
🟡 | #335 | frontend: add E2E tests (Playwright) for login, bot-create, manual-close flows
🟡 | #336 | frontend: document eslint-disable react-hooks/exhaustive-deps sites with rationale comments

---

## English

_Audit scope: `frontend/` (99 source TS/TSX files, ca. 30,536 LOC incl. tests).
Zero code changes, inventory and follow-up issues only. Base commit: `b3031a2` (main)._

### Summary

The frontend is in good shape overall: TypeScript runs under `strict` with `noUnusedLocals` / `noUnusedParameters`, zero `@ts-ignore` anywhere, error boundaries wrap both the whole app tree and every route, React-Query is consistently used as the server-state layer, and i18n has completeness tests with parity checks. The top three 🔴 findings concern (1) **shape drift between Pydantic and TypeScript** — `Trade.builder_fee: number` on the FE does not exist in the backend schema, and `take_profit/stop_loss` are non-nullable on the FE but `Optional` on the BE; (2) **missing `eslint-plugin-jsx-a11y`** — without automated accessibility linting, regressions creep in (already 10 `<div onClick>` sites without keyboard handlers); (3) **no global `unhandledrejection` handler** — unawaited promise rejections silently hit the browser console with no telemetry and no user feedback.

Distribution: 3 🔴, 5 🟡, 6 🟢.

### 1. TypeScript Strictness

**🟢 Solid baseline.**
- `tsconfig.json` has `strict: true`, `noUnusedLocals`, `noUnusedParameters`, `noFallthroughCasesInSwitch` (lines 14–17).
- `0` occurrences of `@ts-ignore` / `@ts-expect-error` / `@ts-nocheck` across `src/`.
- 28 `: any` hits in 14 files; 19 live in `__tests__` as explicit mocks. About 9 remain in production code, e.g. `pages/Portfolio.tsx` (3×), `pages/Admin.tsx` (1×), `components/bots/BotBuilderStepStrategy.tsx` (1×), `types/riskState.ts` (1×).
- 16 `as any` / `as unknown` casts, ca. 5 in production (`pages/Bots.tsx`, `components/bots/BotBuilder.tsx`). Worth case-by-case review.
- `react-hooks/set-state-in-effect` and `react-hooks/immutability` are deliberately off in `.eslintrc.cjs:15–17` — justified via comments.

### 2. API Client Integrity

**🔴 Shape drift between Python schema and TS types.**

There is **no** OpenAPI generation — TypeScript types in `frontend/src/types/index.ts` are hand-maintained against Pydantic schemas in `src/api/schemas/*.py`. Drift findings:

- **`Trade.builder_fee: number`** (`frontend/src/types/index.ts:41`) **does not exist in** `TradeResponse` (`src/api/schemas/trade.py:29–60`). Backend never serializes the field; FE reads `trade.builder_fee` → always `undefined` → likely silent UI bugs in PnL/fee displays.
- **`Trade.take_profit: number`, `Trade.stop_loss: number`** (`frontend/src/types/index.ts:31–32`) — backend schema has `Optional[float] = None` (`src/api/schemas/trade.py:38–39`). TypeScript does not accept `null` as `number`, which can crash on new trades without TP/SL whenever code accesses those fields without optional chaining.
- `TokenResponse.access_token` is correctly documented as `Optional` (SEC-012).

**🟡 No central HTTP error handler beyond `api.interceptors.response.use`.**
- `api/client.ts:185–226` handles 401 (token refresh); everything else surfaces to the consumer. `utils/api-error.ts` (`getApiErrorMessage`) exists but is used inconsistently at ~15 sites.

**🟢 Token management is excellent** — proactive refresh, `visibilitychange` rehydration, cross-tab sync via `storage` event (`api/client.ts:232–265`).

### 3. State Management

**🟢 Zustand stores are feature-scoped and lean.**
- 7 stores: `authStore`, `filterStore`, `realtimeStore`, `sizeUnitStore`, `themeStore`, `toastStore`, `tourStore` — each <50 lines, single responsibility.
- React-Query for server state (`api/queries.ts`) with a consistent query-key factory (`queries.ts:21–47`).

**🟡 useEffect cleanup gaps — `setTimeout` without clear.**
- `pages/Admin.tsx:69` (`setTimeout(() => setMessage(''), 3000)` inside `showMessage`): if the component unmounts while the timer is pending, the state update fires on an unmounted component → React warning and potential memory leak.
- Same pattern at `pages/Settings.tsx:216`, `pages/Bots.tsx:214`, `pages/BotPerformance.tsx:474`. Four sites total.

**🟡 5× `useEffect` with `eslint-disable react-hooks/exhaustive-deps`**
- `pages/Dashboard.tsx:102`, `pages/Trades.tsx:153`, `hooks/useWebSocket.ts:36`, `components/ui/GuidedTour.tsx:162`, `components/bots/CopyTradingStepExchange.tsx:95` — partially deliberate (mount-only sync) but lacking per-site rationale comments.

### 4. Error Boundaries & Resilience

**🟢 Coverage is good.**
- Root `ErrorBoundary` wraps the whole app (`App.tsx:66–102`).
- `RouteErrorBoundary` wraps **every** lazy-loaded route (11×, `App.tsx:69–94`).
- Specialized `WalletErrorBoundary` in `components/hyperliquid/BuilderFeeApproval.tsx:392` and `HyperliquidSetup.tsx:652` for wallet edge cases.
- `OfflineIndicator.tsx` uses `role="alert"` + `aria-live="assertive"`, 3-failure threshold, proper cleanup.

**🔴 No global `unhandledrejection` handler.**
- 0 hits for `unhandledrejection`, `window.addEventListener('error'`. All unawaited promise rejections (e.g. in `showMessage` callbacks, Bots.tsx share flow) silently hit the browser console — no telemetry, no toast.

**🟡 Only 1 file uses AbortController** — `components/ui/OfflineIndicator.tsx` via `AbortSignal.timeout(8000)`. Axios request cancellation on route change is not implemented; React-Query mitigates most of the impact, but a raw `api.post('/trades/sync')` on mount in `pages/Trades.tsx:150` runs to completion even if the user navigates away.

### 5. Accessibility

**🔴 `eslint-plugin-jsx-a11y` is NOT installed.**
- `.eslintrc.cjs` (21 lines) lists only `eslint:recommended`, `plugin:@typescript-eslint/recommended`, `plugin:react-hooks/recommended`. No a11y rules.
- `package.json` has no entry for `jsx-a11y`.
- Consequence: no CI enforcement for label association, keyboard traps, ARIA misuse.

**🟡 10 `<div onClick>` sites without keyboard handlers**
- `pages/AdminBroadcasts.tsx` (2), `pages/Bots.tsx` (3), `pages/BotPerformance.tsx` (1), `components/ui/EditPositionPanel.tsx` (1), `components/ui/ConfirmModal.tsx` (1), `components/ui/GuidedTour.tsx` (1), `components/ui/MobileCollapsibleCard.tsx` (1) — only 5 `onKeyDown` handlers across 4 files globally.
- Those divs are not keyboard-reachable (no Tab, no Enter).

**🟢 Positives:**
- Login has `aria-invalid`, `aria-describedby`, `autoFocus`, `autoComplete` (`pages/Login.tsx:73–103`).
- 124 aria-/role- attributes across 41 files, `focus-visible` rules in `index.css:1248–1258`.
- `document.documentElement.lang` kept in sync with `i18n.language` (`App.tsx:54–56`).

### 6. Performance

**🟢 Much already done:**
- Code splitting: 10 page components via `React.lazy` (`App.tsx:15–24`), `Suspense` loader.
- Vite `manualChunks`: `wallet` (wagmi/viem/rainbowkit) and `charts` (recharts) split out (`vite.config.ts:19–26`).
- Virtualization via `useVirtualRows` (Issue #249) in `pages/Trades.tsx` — `components/virtualised/useVirtualRows.ts` with tests.
- `useIntervalPaused` (`hooks/useIntervalPaused.ts`) pauses polling when `document.visibilityState !== 'visible'`.

**🟡 `React.memo` barely used (3 sites).**
- Only `components/ui/DetailGrid.tsx`, `MobileTradeCard.tsx`, `MobilePositionCard.tsx`. Lists in `Bots.tsx` (1,536 LOC!), `AdminUsers.tsx`, `Portfolio.tsx` render cards without memo → any parent state change re-renders every bot card.
- No measured perf problem today, but will hurt once bot counts grow.

**🟡 Very large page files** — should be split into smaller components:
- `pages/Bots.tsx`: 1,536 lines
- `pages/BotPerformance.tsx`: 1,242 lines
- `pages/Admin.tsx`: 1,113 lines
- `components/bots/BotBuilder.tsx`: 782 lines, 10 `useEffect`, only 1 `aria-label`
- `pages/Portfolio.tsx`: 805 lines

### 7. Theme + i18n

**🟢 Theme toggle is solid.**
- `themeStore.ts:10–15` applies the initial theme before hydration (no flash).
- 52 `dark:bg-*` / `dark:text-*` hits across 12 files — consistent Tailwind dark mode.
- Cross-tab sync is missing though: unlike `demo_filter` in `filterStore.ts:10`, a theme toggle in tab A does not trigger a storage-event listener in tab B.

**🟢 i18n is excellent.**
- `i18n-completeness.test.ts` (249 lines!) tests: top-level section parity, total key count, dot-path parity, structural leaf-vs-object mismatch, tour keys, guide keys, exit-reason label uniqueness (guards against bug #194).
- `de.json` and `en.json` are 1,144 lines each.

**🟡 No documentation-lag safeguard** — if someone hardcodes a translation key via `t('newKey')` in a component and forgets to add it to **both** JSONs, it surfaces only on the next test run, not at commit time. A CI grep extracting `t\(['"][^'"]+['"]\)` and joining against the JSON keys would be nice.

### 8. Frontend Test Coverage

**🟢 57 test files, 99 source files (ca. 58% file coverage).**
- Vitest configured with `jsdom`, `mockReset: true`, `src/test/setup.ts` (`vitest.config.ts`).
- Broad coverage: all 7 stores have tests, 11 page tests, 14 UI component tests, 5 hook tests.
- Testing-Library React + user-event 14 + jest-dom.

**🟡 No `coverage` script in `package.json`.**
- `scripts.test: "vitest run"`, `test:watch: "vitest"` — no `vitest run --coverage`. Blind spots are invisible. `@vitest/coverage-v8` is not installed.

**🟡 No E2E framework (Playwright/Cypress).**
- Only `@vitest/browser-playwright` as a **transitive** dep in `package-lock.json`. Money-critical flows (login → bot create → bot start → manual close, HL wizard 4-step) have no end-to-end coverage.

**🟢 Money-critical hooks are unit-tested:**
- `api/__tests__/useUpdateTpSl.test.tsx` (TP/SL mutation + optimistic update + rollback)
- `api/__tests__/client.test.ts` (token-refresh scenarios)
- `stores/__tests__/authStore.test.ts`

### Appendix: Follow-up Issues

Severity | Issue | Title
---|---|---
🔴 | #329 | frontend: align Trade type with backend TradeResponse schema (builder_fee, nullable TP/SL)
🔴 | #330 | frontend: add eslint-plugin-jsx-a11y to catch accessibility regressions in CI
🔴 | #331 | frontend: add global unhandledrejection + error handler for telemetry and user feedback
🟡 | #332 | frontend: clean up setTimeout timers without cleanup in Admin/Settings/Bots/BotPerformance
🟡 | #333 | frontend: make div-onClick handlers keyboard-accessible (10 sites)
🟡 | #334 | frontend: add coverage script and enforce threshold for frontend tests
🟡 | #335 | frontend: add E2E tests (Playwright) for login, bot-create, manual-close flows
🟡 | #336 | frontend: document eslint-disable react-hooks/exhaustive-deps sites with rationale comments
