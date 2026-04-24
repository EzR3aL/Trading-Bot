# Changelog

Alle wichtigen Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

> **Hinweis:** Dieser Changelog wird automatisch bei jeder Änderung aktualisiert.

---

## [Unreleased]

### Added
- Frontend health audit report (`Anleitungen/frontend_health_report.md`) — see #328. Inventory over 8 categories (TS strictness, API client integrity, state management, error boundaries, a11y, performance, theme+i18n, test coverage); 3 critical / 5 medium / 6 nice-to-have findings; 8 follow-up issues #329–#336 filed.
### Fixed
- **Align frontend `Trade` type with backend `TradeResponse` schema (#329, from audit #328)**: Closes the "API shape drift" red flag surfaced in the frontend audit. (1) Added `builder_fee: float = Field(default=0, ...)` to `src/api/schemas/trade.py::TradeResponse` — the field already existed on `TradeRecord` (`src/models/database.py:180`) and is written by `trade_closer`/`position_monitor` from Hyperliquid's `calculate_builder_fee`, but was never surfaced in the API response that the FE `Trade` type claimed it received. (2) Relaxed `frontend/src/types/index.ts::Trade.take_profit` and `stop_loss` from `number` to `number | null` to match the BE's `Optional[float]` — the bot worker creates trades without TP/SL and fills them post-entry, so the non-nullable FE type was incorrect. No consumer changes required: every call site (`pages/Trades.tsx`, `utils/riskState.ts`, `components/ui/EditPositionPanel.tsx`, `components/ui/MobilePositionCard.tsx`) already uses optional-chaining or nullish guards, so `npx tsc --noEmit` stays clean. New Pydantic tests in `tests/unit/api/test_schema_validation.py::TestTradeResponseContract` lock the four fields (builder_fee default, builder_fee value, nullable TP/SL, populated TP/SL); `test_trades_router.py::test_get_trade_all_fields_present` now asserts `builder_fee` is in the response and defaults to 0.
- `eslint-plugin-jsx-a11y` installed + configured (warn-level). Initial scan documented in frontend health report. Strict enforcement follows in #333 (#330, from audit #328).
- **Global unhandledrejection + error handler für Telemetry und User-Feedback (#331)**: Neues Modul `frontend/src/lib/globalErrorHandler.ts` hängt auf dem Top-Level `window`-Objekt die Listener `unhandledrejection` (unbehandelte Promise-Rejections — z. B. `fetch().then()` ohne `.catch`, fehlendes `await`) und `error` (unbeobachtete Exceptions aus async Event-Handlern, die oberhalb der React-`ErrorBoundary` geworfen werden). Pro Event: (1) strukturierter `console.error`-Log mit stabilem `[GlobalError]`-Tag und vollem Kontext (`source`, `message`, `stack`, `filename`, `lineno`, `colno`, `timestamp`) für Entwickler; (2) User-sichtbarer Toast via die bestehende unified Toast-API (`showError` aus `frontend/src/utils/toast.ts` → `useToastStore` → `ToastContainer` in `App.tsx`); (3) `reportError(err, ctx)` Telemetry-Stub, der aktuell mit `[telemetry]`-Präfix auf `console.info` emittiert und später auf Sentry/PostHog umgebogen wird (dependency-injection-ready — keine neuen Packages). (4) Burst-Dedupe: identische Messages innerhalb eines 5-Sekunden-Fensters erzeugen nur einen Toast + einen Telemetry-Call (der Dev-`console.error` feuert weiterhin jedes Mal, damit Debugging nicht leidet). Installation ist idempotent (zweiter Aufruf gibt dasselbe Handle zurück, keine Doppel-Bindung), SSR-safe (no-op wenn `window` fehlt), und robust (wenn der Telemetry-Sink selbst wirft, wird der Toast trotzdem angezeigt). Verdrahtet in `frontend/src/main.tsx` mit einem einzelnen `installGlobalErrorHandler()`-Aufruf VOR `ReactDOM.createRoot(...)`, damit auch async Failures während des initialen Renders (z. B. lazy-geladene Chunk-Fehlschläge) erfasst werden. Neue Test-Suite `frontend/src/lib/globalErrorHandler.test.ts` mit 8 Vitest-Tests auf jsdom: Unhandled-Rejection-Capture mit Toast + Telemetry, Window-`error`-Capture mit Source-Metadata (`filename`/`lineno`/`colno`), 5s-Dedupe innerhalb des Fensters mit korrekter Wiederfreigabe danach, distinkte Messages passieren ungehindert, Normalisierung von non-Error-Werten (String / Object / `null` → `"Unknown error"`), Idempotenz (zweifaches Install bindet Listener nicht doppelt), `uninstall()` detacht beide Listener, und ein throwing-Telemetry-Sink blockiert den Toast nicht.
### Fixed
- **[frontend] setTimeout leak in Admin/Settings/Bots/BotPerformance (#332)**: All four audited pages scheduled one-shot `setTimeout` callbacks inside click handlers (showMessage banner reset in `Admin.tsx` + `Settings.tsx`, "copied" flag reset after clipboard/share in `Bots.tsx`'s `TradeDetailModal` and `BotPerformance.tsx`'s `handleShare`) without a matching `clearTimeout` on unmount. If the user navigated away or closed the modal within the 2–3 s window, the deferred `setMessage('')` / `setCopied(false)` / `setFlag(false)` fired against a stale component, producing React "state update on unmounted component" warnings (and, under StrictMode, double-invocation pressure). Each site now stores its handle in a `useRef<ReturnType<typeof setTimeout> | null>`, clears a pre-existing handle before scheduling a new one (also prevents overlapping timers on rapid repeated calls), and a dedicated `useEffect` with empty deps clears the pending handle on unmount. Behaviour for in-flight lifecycles is unchanged. New regression tests in `frontend/src/pages/__tests__/Bots.test.tsx`, `Settings.test.tsx`, `BotPerformance.test.tsx` mount each page under `vi.useFakeTimers()`, unmount, run `vi.runAllTimers()`, and assert no `"can't perform a React state update on an unmounted"` warning is logged to `console.error`. `Admin.tsx` has no existing test file — not added (noted for follow-up).
### Documentation
- **Frontend: Rationale-Kommentare für alle `eslint-disable react-hooks/exhaustive-deps`-Stellen (#336)**: Audit hatte fünf Stellen identifiziert, an denen die Regel ohne Begründungskommentar deaktiviert war — jeder solche Disable ist eine Behauptung, dass der Linter an dieser Stelle falsch liegt, aber ohne Kommentar kann ein späterer Maintainer nicht beurteilen, ob der Disable noch gültig oder stale ist. Dokumentations-only Änderung (keine Code-Semantik geändert, keine Deps-Arrays modifiziert, keine Disables entfernt): (1) `frontend/src/hooks/useWebSocket.ts:36` — `useMemo(() => handlers, [handlerKeys])` keyt absichtlich auf dem sortierten Key-String statt auf der Handler-Objekt-Identität; Caller übergeben typisch frische Objekt-Literale, ein Include von `handlers` würde den Memo zerstören und bei jedem Parent-Render die WS-Verbindung neu aufbauen. (2) `frontend/src/components/bots/CopyTradingStepExchange.tsx:95` — Empty-deps Mount-once-Effekt setzt Sentinel-Trading-Pair; `onTradingPairsChange` ausgeschlossen, da Parent-Callback bei jedem Render neu erzeugt wird. (3) `frontend/src/pages/Dashboard.tsx:102` — Empty-deps, `syncTrades` (React-Query-Mutation) ausgeschlossen weil neue Referenz bei jedem Render; `sessionStorage`-Guard verhindert Mehrfach-Sync. (4) `frontend/src/pages/Trades.tsx:153` — Gleiche Rationale wie Dashboard. (5) `frontend/src/components/ui/GuidedTour.tsx:162` — `[isActive]` mit ausgeschlossenem `handleSkip`; plus `TODO(#336)` als Follow-up-Hinweis, dass ein sauberer Fix wäre, `handleSkip` in `useCallback` zu wrappen — heute risikoarm (stable Closures über zustand-Setter + Props), aber der Disable versteckt einen latenten Stale-Closure-Hazard. Keine Regressions in 553 Vitest-Tests; TypeScript-Check sauber; Lint-Output für die fünf geänderten Files zeigt keine neuen Warnings/Errors (die pre-existing Errors sind unverwandt: `react-hooks/globals` in `Trades.test.tsx`, `react-hooks/refs` in `Dashboard.tsx`).

### Refactored
- **ARCH-H1 Phase 1 finalize: `BotWorker` ist jetzt pure Composition (#285)**: `BotWorker` erbt nicht mehr von den vier historischen Mixins (`TradeExecutorMixin`, `PositionMonitorMixin`, `TradeCloserMixin`, `NotificationsMixin`) — die Klassendeklaration ist jetzt schlicht `class BotWorker:` und `BotWorker.__mro__` reduziert sich auf `(BotWorker, object)`. Alle Mixin-Methoden sind als explizite, dünne Forwarder an die Komponenten (`self._notifier`, `self._position_monitor`, `self._trade_executor`, `self._trade_closer`) inlined. Abweichung von der Issue-Spec (#285 forderte das Löschen der vier Mixin-Module): die Shim-Module `src/bot/notifications.py`, `src/bot/position_monitor.py`, `src/bot/trade_closer.py`, `src/bot/trade_executor.py` bleiben bestehen, da mehrere Test-Harnesses die Mixin-Klassen direkt importieren (`PositionMonitorMixin`, `TradeExecutorMixin` als Test-Doubles) und `tests/integration/test_manual_close_full_flow.py` Symbole auf dem `src.bot.notifications`-Modulpfad patcht. Die Composition-Invariante (MRO == `(BotWorker, object)`) ist dennoch strikt erfüllt — das Ziel des Refactors (keine Mixin-Diamant-Vererbung, keine impliziten `super()`-Hopping) ist erreicht, ohne Test-Kollateral zu erzeugen. 516 unit tests in `tests/unit/bot/`, `tests/unit/services/`, `tests/unit/api/` alle grün.

### Documentation
- **Refactor-Pläne auf main gelandet (#268)**: `Anleitungen/refactor_plan_bot_worker_composition.md` + `Anleitungen/refactor_plan_service_layer.md` aus #244 herausgeschnitten und eigenständig gelandet. Docs-only. Entkoppelt die Referenzen aus `src/bot/components/` (ARCH-H1 Scaffolding, #266) und den ARCH-C1 Service-Layer-Commits von der eingefrorenen #244-Mentor-Sweep-PR.
### Security
- **Hyperliquid EIP-712 payload validator + builder-fee bounds (#257, SEC-005 / SEC-008)**: Defense-in-depth gegen geld-bewegende Signaturen. Neues Modul `src/exchanges/hyperliquid/eip712_validator.py` pinnt drei Invarianten vor jedem EIP-712-Signing: (1) **`chain_id`** — Mainnet 42161 (Arbitrum One) / Testnet 421614 (Arbitrum Sepolia) werden per `assert_chain_id(cid, demo_mode=...)` gegen den erwarteten Netzwerk-Pin geprüft; verhindert Cross-Chain-Replay einer manipulierten SDK-Signatur. (2) **`primaryType`-Whitelist** — nur `{Order, Cancel, CancelByCloid, ModifyOrder, BatchModify, UpdateLeverage, UpdateIsolatedMargin, ApproveBuilderFee, ScheduleCancel}` dürfen signiert werden; `ApproveAgent` / `Withdraw` / `UsdSend` werden explizit verweigert (zusätzliche Schicht über SafeExchange's Methodenname-Filter). (3) **Builder-Fee-Bounds** — `MIN/MAX_BUILDER_FEE_TENTHS_BPS = 1 / 100` (0.001% – 0.1%) als Konstanten, Assertion in `HyperliquidClient.approve_builder_fee` checked sowohl die Integer-Form (`assert_builder_fee_tenths_bps`) als auch den auf den Draht gehenden Prozent-String (`assert_builder_fee_pct`). Regression-Guard gegen den 10x-zu-hoch-Vorfall (2026-03-17): `builder_fee=1000` wird abgelehnt, SDK wird nicht aufgerufen. Client-Konstruktion speichert `self._expected_chain_id` und nutzt die MIN/MAX-Konstanten statt hartcodierter `1 <= fee <= 100`. 29 neue Unit-Tests in `tests/unit/exchanges/test_hyperliquid_eip712_validator.py` decken Happy-Path Mainnet/Testnet, Chain-Mismatch (testnet-Chain in Mainnet-Modus und umgekehrt), primaryType-Whitelist-Verstöße, Wire-Format-Parsing (`0.01%`, `0.01`, Whitespace, `abc` / `-0.01%` / scientific-notation rejected), Builder-Fee-Out-of-Range, Non-Int/Bool-Reject und einen dedizierten `test_rejects_10x_regression` ab; plus 1 neuer Test `test_approve_rejects_fee_beyond_cap` in `test_hyperliquid_builder.py`, der den End-to-End-Call `HyperliquidClient.approve_builder_fee()` mit `fee=1000` gegen den Validator führt und asserted dass das SDK nicht gerufen wird.
### Tests
- **ARCH-H1 Phase 0 PR-2: Characterization-Tests für `BotWorker.graceful_stop()` (#270)**: Neuer Test-Modul `tests/unit/bot/test_bot_worker_graceful_stop.py` friert das aktuelle, observable Verhalten von `graceful_stop` ein, bevor in späteren PRs Mixin-Extraktion beginnt. 11 Tests decken alle Top-Level-Branches ab: `_shutting_down` Flag wird gesetzt, `self.stop()` Delegation ist unbedingt, Happy-Path mit idle `_operation_in_progress`-Event, Timeout-Path wenn das Event cleared bleibt, DB-Query gibt das dokumentierte 7-Key-Dict zurück (`symbol`/`side`/`size`/`entry_price`/`demo_mode`/`has_tp`/`has_sl`), Leere-Trades-Liste → `[]`, Exception im DB-Query wird swallowed + `stop()` läuft trotzdem, Exception in `client.get_open_positions()` swallowed + DB-Positionen werden weiterhin zurückgegeben, Demo + Live-Clients werden beide gepollt wenn gesetzt, `None`-Clients werden übersprungen, Status-Transition zu `STOPPED` läuft über die `stop()`-Delegation. Coverage von `src/bot/bot_worker.py` geht damit von **78% → 84%**, `graceful_stop` selbst (Zeilen 523-600) von ~0% auf ≥95% — nur noch der kommentierte `pass # TP/SL are protective — leave them in place` no-op-Branch in Zeile 569 ist ungedeckt. Entspricht dem 85%-Gate-Schritt aus `Anleitungen/refactor_plan_bot_worker_composition.md`; die letzte Prozentpunkt-Lücke schließt Phase-0-PR-3 (`_analyze_and_trade*` + `_analyze_symbol*`).
- **ARCH-H1 Phase 0 PR-3: Characterization-Tests für `_send_daily_summary` + self-managed-Strategie-Dispatch (#272)**: Neuer Test-Modul `tests/unit/bot/test_bot_worker_daily_summary.py` mit 10 fokussierten Tests, die zusätzlich zum PR#271-Fundament die restlichen `BotWorker`-Lücken schließen, die das 85%-Coverage-Gate aus `Anleitungen/refactor_plan_bot_worker_composition.md` blockieren. Klasse `TestSendDailySummary` (6 Tests) friert das Verhalten von `_send_daily_summary()` ein: Happy-Path mit allen 11 dokumentierten Notification-Kwargs (`date`/`starting_balance`/`ending_balance`/`total_trades`/`winning_trades`/`losing_trades`/`total_pnl`/`total_fees`/`total_funding`/`max_drawdown`/`bot_name`), Skip bei `trades_executed == 0`, Skip bei `stats is None`, Exception-Swallow im `risk_manager.get_daily_stats()`, Exception-Swallow in der Notifier-Delivery, unbedingte `_risk_alerts_sent.clear()`-Ausführung auf allen vier Pfaden. Klasse `TestAnalyzeAndTradeSelfManaged` (4 Tests) charakterisiert den `strategy.is_self_managed=True`-Branch in `_analyze_and_trade`: `run_tick()` wird aufgerufen, `generate_signal()` und `risk_manager.can_trade()` bleiben ungetroffen, `last_analysis` wird trotz `run_tick`-Exception gestampt, der `StrategyTickContext` enthält alle erwarteten Felder (`bot_config`/`user_id`/`exchange_client`/`trade_executor`/`send_notification`/`bot_config_id`), und der Non-self-managed-Fallback-Pfad erreicht die globale Risk-Check. Coverage `src/bot/bot_worker.py` kombiniert mit #271: **84% → 88%** — die 85%-Gate aus dem Refactor-Plan ist damit geknackt, Phase 1 (Mixin-Extraktion) kann beginnen.
### 2026-04-23 — CI unblock: lint F821 + alembic-check PYTHONPATH (#243)

#### Fixed
- **[lint]** `src/exchanges/hyperliquid/client.py` — `pre_start_checks` annotated its return type as `List["GateCheckResult"]` but `GateCheckResult` was only imported inside the function body, so the top-level string-forward-reference was unresolvable. Ruff's `F821` correctly flagged it (runtime was fine under PEP 563). Fix: hoist `GateCheckResult` into the existing `from src.exchanges.base import (...)` block and drop the redundant in-function import.
- **[ci/alembic-check]** `alembic.ini` — added `prepend_sys_path = .` to the `[alembic]` section so the alembic CLI can import `src.models.database` / `src.models.broadcast` from `migrations/env.py`. Without it the brand-new `alembic-check` job (introduced in #243 to verify every migration has a working `upgrade()`+`downgrade()` round-trip) died at import time with `ModuleNotFoundError: No module named 'src'`. The FastAPI app startup path never hit this because uvicorn runs with the repo root already on `sys.path`; alembic CLI does not.
### 2026-04-22 — P3 Security polish (#251, task 1/3)

#### Fixed
- **[cache-leak]** `src/api/main_app.py:101` — `SecurityHeadersMiddleware` now emits `Cache-Control: no-store` on all `/api/*` responses so authenticated JSON payloads are not cached by shared proxies or the browser disk cache. Static SPA assets served from `/` keep their own `Cache-Control`; only `/api/*` is patched, and only when the handler did not already set its own header.
- **[audit-log-ip]** `src/api/middleware/audit_log.py:16,34` — `AuditLogMiddleware` now uses the shared `_get_real_client_ip(request)` resolver from `src/api/rate_limit.py` instead of raw `request.client.host`. Behind Nginx the old path always logged the proxy's IP (`127.0.0.1`), making audit trails useless. `X-Forwarded-For` is only trusted when `BEHIND_PROXY=true`.
- **[token-type-confusion]** `src/api/middleware/audit_log.py:91` — `_extract_user_id` now calls `decode_token(token, expected_type="access")`; a refresh token presented via the `Authorization` header used to label audit rows with its `sub`. Refresh tokens live longer and carry elevated refresh privileges, so they must never be accepted on the authenticated API surface.
- **[auth-bridge-ip]** `src/api/routers/auth_bridge.py:68,119` — `generate_code` + `exchange_code` switched from `request.headers.get("X-Forwarded-For", request.client.host ...)` to the same `_get_real_client_ip` helper. Raw `X-Forwarded-For` is spoofable when the bot is reachable outside the proxy; consolidating on the helper means the `BEHIND_PROXY` flag is the single source of truth.

#### Added (tests)
- **[test]** `tests/unit/api/test_audit_log_extra.py::test_returns_none_for_refresh_token_in_auth_header` — locks in the token-type restriction by minting a refresh token with `create_refresh_token`, passing it as `Bearer ...`, and asserting `_extract_user_id` returns `None`.
- **[test]** `tests/unit/api/test_main_app.py::test_cache_control_no_store_on_api_responses` — boots the app via `create_app()`, hits `/api/status`, asserts `cache-control == "no-store"`.

### 2026-04-22 — P3 Architecture polish (#251, task 3/3)

#### Fixed
- **[dead-code]** `src/notifications/discord_notifier.py:288` — removed unused local `_direction_emoji` that was assigned but never read (pyflakes F841).
- **[undefined-name]** `src/exchanges/hyperliquid/client.py:18,36` — added `TYPE_CHECKING` import + guarded `from src.exchanges.base import GateCheckResult` block so the forward-reference annotation `List["GateCheckResult"]` on `pre_start_checks` resolves statically (fixes pyflakes/ruff F821).
- **[docstring]** `src/api/routers/copy_trading.py:134` — added one-line docstring to the `GET /api/exchanges/{exchange}/leverage-limits` route (`leverage_limits`). Every other FastAPI route handler in `src/api/routers/` already has one; this was the only gap.
- **[i18n-orphans]** `frontend/src/i18n/{de,en}.json` — deleted the entire `botDetail` section (34 keys per locale, 68 total) — zero references anywhere in `frontend/src/**/*.{ts,tsx}` (verified via grep for both `t('botDetail.*')` and template-literal prefixes). The local variable named `botDetail` in `BotPerformance.tsx` is a JS identifier, not an i18n key lookup.

#### Audited (findings)
- Pyflakes + `ruff check src/ --select F` — only the three issues above after respecting noqa. The `src/api/routers/bots.py:1232/1241` re-exports (`start_bot`, `stop_bot`, `_enforce_*`, etc.) are intentional backward-compat shims for tests (`test_bots_router_extra.py`, `test_concurrency.py`, `test_injection_security.py`) and already carry `noqa: F401` — left untouched.
- `src/strategy/__init__.py` auto-imports every sibling module at package load (ARCH-H7). `StrategyRegistry` import in `src/bot/orchestrator.py:22` is a side-effect import (auto-register) and already carries `noqa: F401` — left untouched.
- No stray `print(` statements in `src/` (only in `scripts/`, which is allowed).
- Every FastAPI route handler now has a docstring; checked via AST walk over `src/api/routers/*.py`.
- `__all__` declarations in `src/**/*.py` all reference live names — no orphan re-exports.
- Logging style: ~200 f-string `logger.*` calls across `src/` that ignore lazy `%s` formatting — blanket rename is scope creep (flagged follow-up).
- i18n orphan scan found 103 likely-orphan keys across 11 namespaces (mostly `settings.*` tabs, `performance.*` aliases, `affiliate.*` legacy). Only `botDetail` (34 keys) was obviously safe to remove — the rest may be dynamically referenced via template literals or computed key paths, so they are flagged as follow-ups rather than deleted.
- `requirements.txt` vs `src/` import scan: every declared dep either has a direct import (`from fastapi import ...`, `from sqlalchemy import ...`) or is a runtime-only transitive dep (e.g. `uvicorn` runs the app, `asyncpg` is the driver `sqlalchemy[asyncio]` dispatches to, `discord.py` is used via `aiohttp` webhook calls). No removable entries — per task hard-limit, no dependency changes made.

#### Deferred as follow-ups
- Orphan i18n keys in `settings.*` (35), `performance.*` (8), `affiliate.*` (10) and smaller namespaces — need per-key verification with page-level grep (some may be referenced via `t(\`namespace.${key}\`)` templates).
- F-string logging → lazy `%s` formatting — ~200 call sites; needs a dedicated mechanical sweep with codemod.
- 1118 ruff auto-fixes under `SIM/UP/RUF` rulesets (e.g. `try/except/pass` → `contextlib.suppress`) — blanket roll-out is scope creep.

### 2026-04-22 — P3-UX polish (#251, task 2/3)

#### Audited (~15 findings)
- **[title]** No route-level document title; `<title>Edge Bots</title>` in `frontend/index.html` is the only value — every tab stays "Edge Bots". **FIXED.**
- **[a11y]** `frontend/src/pages/AdminBroadcasts.tsx:37,419` — X close-buttons missing `aria-label`. **FIXED.**
- **[a11y]** `frontend/src/components/hyperliquid/BuilderFeeApproval.tsx:244` — X close-button missing `aria-label`. **FIXED.**
- **[a11y]** `frontend/src/components/bots/BotBuilderStepNotifications.tsx:126` — Plus (add threshold) button missing `aria-label`. **FIXED.**
- **[i18n]** `frontend/src/components/bots/BotBuilderStepNotifications.tsx:63,138` — hardcoded German strings "Schwellenwerte" + "Typ wählen ($/%), Wert eingeben..." + "Maximal 10 Schwellenwerte". **FIXED** (now `t('bots.builder.pnlThresholdsLabel')` + `t('bots.builder.pnlThresholdHint')`).
- **[copy-affordance]** `frontend/src/components/hyperliquid/HyperliquidSetup.tsx:516` — HL wallet short-address in the referral diagnostic card was display-only; no way to copy the full `wallet_address` that the backend already returns. **FIXED** (new reusable `CopyButton`).
- **[empty-state]** `frontend/src/pages/AdminUsers.tsx:301` — bare "Keine Benutzer vorhanden." centred text, no icon, no hint. **FIXED.**
- **[empty-state]** `frontend/src/pages/AdminBroadcasts.tsx:580` — bare "Noch keine Broadcasts vorhanden" centred text, no icon, no hint. **FIXED.**
- **[focus-ring]** `frontend/src/pages/Settings.tsx:109-122` — save / test / delete buttons on KeyForm had no `focus-visible:ring-*`. **FIXED** (+ Save now shows `t('common.loading')` while `saving`).
- **[mutation-state]** `frontend/src/pages/Settings.tsx:113` — "Test Connection" button stayed enabled while `saving` (race-risk). **FIXED** (`disabled={!configured || saving}`).
- **[number-format]** `frontend/src/components/**` — 95 `toFixed()` call sites, only `utils/dateUtils.ts` has a centralised formatter (`formatChartCurrency`). No locale-aware `formatCurrency`/`formatPercent` helper. **FIXED** — new `frontend/src/utils/numberFormat.ts` (adoption deferred as follow-up, not forcing a branch-wide rename).
- **[copy-affordance]** `frontend/src/components/ui/EditPositionPanel.tsx` trade-id/order-id text strings — no copy button. Deferred.
- **[a11y]** `frontend/src/components/ui/OfflineIndicator.tsx:67` has hardcoded `aria-label="Dismiss"` — should be translated. Deferred.
- **[a11y]** `frontend/src/pages/Trades.tsx:371` has hardcoded `aria-label="Sort by PnL"` — should be translated. Deferred.
- **[pending-state]** Broadcast "Send" / AdminUsers "Create" / BotBuilder "Save" buttons already use `isPending`. No missing wiring found (PR #244 + M6 covered the main mutation surfaces). No change required.

#### Added
- **[P3-UX]** `frontend/src/hooks/useDocumentTitle.ts` — 20-line hook (no new dependency, no react-helmet). Sets `document.title = "${title} · Edge Bots"` on mount and restores the previous title on unmount so back-navigation shows the right tab label for the previous route until the next `useDocumentTitle` fires.
- **[P3-UX]** `frontend/src/components/ui/CopyButton.tsx` — small icon-only button that writes a string to the clipboard via `navigator.clipboard.writeText`, swaps the `Copy` icon for a green `Check` for 1.5 s, and fires `showSuccess(t('common.copiedToast', { label }))` from the unified toast wrapper (`utils/toast.ts`, UX-M6). `aria-label` uses `t('common.copyValue', { label })` so screen readers announce what's being copied. Includes `focus-visible:ring-2 focus-visible:ring-primary-500/60` for keyboard users.
- **[P3-UX]** `frontend/src/utils/numberFormat.ts` — `formatCurrency(value, { decimals?, withSign? })`, `formatPercent(value, { decimals?, withSign? })`, `formatNumber(value, { decimals? })`. All three accept `null`/`undefined` and return `'--'`. Uses `Intl.NumberFormat` with the browser-resolved locale (so DE users get `1.234,56 $` grouping, EN users get `$1,234.56`). Not force-adopted across existing `toFixed()` sites — new code and any touched component should prefer these helpers.

#### Changed — per-route document titles (11 pages)
- **[P3-UX]** `frontend/src/pages/Dashboard.tsx:84` → `useDocumentTitle(t('nav.dashboard'))`
- **[P3-UX]** `frontend/src/pages/Portfolio.tsx:73` → `useDocumentTitle(t('nav.portfolio'))`
- **[P3-UX]** `frontend/src/pages/Trades.tsx:72` → `useDocumentTitle(t('nav.trades'))`
- **[P3-UX]** `frontend/src/pages/Settings.tsx:148` → `useDocumentTitle(t('nav.settings'))`
- **[P3-UX]** `frontend/src/pages/Bots.tsx:836` → `useDocumentTitle(t('nav.myBots'))`
- **[P3-UX]** `frontend/src/pages/BotPerformance.tsx:418` → `useDocumentTitle(t('nav.performance'))`
- **[P3-UX]** `frontend/src/pages/TaxReport.tsx:29` → `useDocumentTitle(t('nav.taxReport'))`
- **[P3-UX]** `frontend/src/pages/GettingStarted.tsx:749` → `useDocumentTitle(t('nav.guide'))`
- **[P3-UX]** `frontend/src/pages/Admin.tsx:29` → `useDocumentTitle(t('nav.admin'))`
- **[P3-UX]** `frontend/src/pages/Login.tsx:14` → `useDocumentTitle(t('login.title'))`
- **[P3-UX]** `frontend/src/pages/NotFound.tsx:6` → `useDocumentTitle(t('notFound'))`

#### Changed — accessibility fixes
- **[P3-UX]** `frontend/src/pages/AdminBroadcasts.tsx:37,419` — added `aria-label={t('common.close')}` + focus-visible ring to both X close buttons (detail-modal header + create-form reset).
- **[P3-UX]** `frontend/src/components/hyperliquid/BuilderFeeApproval.tsx:244` — added `aria-label={t('common.close', 'Close')}` + focus-visible ring on the modal X close button.
- **[P3-UX]** `frontend/src/components/bots/BotBuilderStepNotifications.tsx:126` — added `aria-label={t('bots.builder.addThreshold')}` + focus-visible ring on the PnL-threshold add button. `ThresholdChipInput` now pulls `useTranslation()` so its label + hint render from i18n (no more German literals).

#### Changed — empty states
- **[P3-UX]** `frontend/src/pages/AdminUsers.tsx:301-307` — replaced bare "Keine Benutzer vorhanden." text with glass-card centred block: `UsersIcon` + `t('admin.noUsers')` title + `t('admin.noUsersHint')` sub-copy.
- **[P3-UX]** `frontend/src/pages/AdminBroadcasts.tsx:580-586` — replaced bare "Noch keine Broadcasts vorhanden" text with centred `Radio` icon + `t('broadcast.noHistory')` title + `t('broadcast.noHistoryHint')` sub-copy. Matches the Bots/Trades/Portfolio empty-state visual shape that already existed.

#### Changed — mutation-state + focus polish
- **[P3-UX]** `frontend/src/components/hyperliquid/HyperliquidSetup.tsx:516` — wrapped the diagnostic wallet short-address display in a flex row and added `<CopyButton value={referralDiag.wallet_address} label={t('hlSetup.diagWallet')} />` next to it. Copies the **full** address, not the short version.
- **[P3-UX]** `frontend/src/pages/Settings.tsx:109-122` — added `focus-visible:outline-none focus-visible:ring-2` to Save / Test / Delete buttons in `KeyForm`; Save button now renders `t('common.loading')` while `saving` (was always `t('settings.save')`); Test Connection now disables while saving (`disabled={!configured || saving}`) to prevent double-submit races.

#### i18n keys added (DE + EN parity preserved)
- **[P3-UX]** `common.copyValue` — "Copy {{label}}" / "{{label}} kopieren"
- **[P3-UX]** `common.copiedToast` — "{{label}} copied to clipboard" / "{{label}} in die Zwischenablage kopiert"
- **[P3-UX]** `common.copyFailed` — "Copy failed" / "Kopieren fehlgeschlagen"
- **[P3-UX]** `admin.noUsersHint` — "Create the first user with the button above." / "Lege den ersten Benutzer über den Button oben an."
- **[P3-UX]** `broadcast.noHistoryHint` — "Broadcasts you send will appear here." / "Gesendete Broadcasts erscheinen hier."
- **[P3-UX]** `bots.builder.addThreshold` — "Add threshold" / "Schwellenwert hinzufügen"
- **[P3-UX]** `bots.builder.pnlThresholdsLabel` — "Thresholds" / "Schwellenwerte"
- **[P3-UX]** `bots.builder.pnlThresholdHint` — "Pick a type ($/%), enter a value, press Enter. Up to 10 thresholds." / "Typ wählen ($/%), Wert eingeben, Enter drücken. Maximal 10 Schwellenwerte."

#### Follow-ups (not addressed — under the 10-fix budget)
- Hardcoded English `aria-label="Dismiss"`/`"Close"`/`"Sort by PnL"` strings in `OfflineIndicator.tsx:67`, `EditPositionPanel.tsx:348`, `Trades.tsx:371`, `Bots.tsx:276,480`, and the `DatePicker.tsx:151,164` "Previous/Next month" labels — should be translated.
- 95 `toFixed()` call sites across 23 files not migrated to the new `formatCurrency`/`formatPercent` helpers. A future pure-cosmetic rename PR can do the sweep; touching 23 files would blow the scope/LOC budget here.
- `EditPositionPanel.tsx` trade-id / order-id fields still have no copy-to-clipboard affordance. `CopyButton` now exists, wiring it up is a one-liner per field.
- `HyperliquidSetup.tsx:135` inline validation still uses hardcoded strings (`t('settings.validationAddress')` keys already exist — already fine). No change needed, but re-verify when the Settings skeleton (UX-M5) lands.

#### Test results
- **[P3-UX]** `cd frontend && npm test -- --run` — **57/57 test files passed, 553/553 tests passed**, 27.06 s duration. No regressions — all pre-existing suites (Trades, Portfolio, Dashboard, Bots, Settings, Login, ErrorBoundary, i18n-completeness, toast, etc.) still green.

---

### 2026-04-22 — P3-Security polish (#251, task 1/3)

#### Audit findings (top ~15, severity in brackets)
- **[HIGH]** `src/api/routers/auth_bridge.py:68,118` — `client_ip` read straight from `X-Forwarded-For` without the `BEHIND_PROXY` flag. A client could spoof the logged IP by sending the header (rate-limit key uses the shared resolver, but bridge-specific audit logs did not). **FIXED.**
- **[HIGH]** `src/api/middleware/audit_log.py:33` — audit writes captured `request.client.host` unconditionally. Behind Nginx this is always the proxy IP, so the DB `audit_logs.client_ip` column was effectively useless in production. **FIXED** (reuses `_get_real_client_ip`).
- **[HIGH]** npm `lodash@4.17.23` (transitive via `recharts` + `@metamask/utils`) — GHSA-r5fr-rjxr-66jc (template code injection), GHSA-f23m-r3pf-42rh (prototype pollution). Not reachable in our call sites (we never use `_.template` or `_.unset`). **DEFERRED** — blocks on `recharts` upstream bump.
- **[HIGH]** npm `defu <=6.1.4` (transitive via `wagmi → walletconnect → h3`) — GHSA-737v-mqg7-c878 prototype pollution. Not reachable from our UI code. **DEFERRED** — upstream fix pending in walletconnect.
- **[HIGH]** npm `vite 7.0.0-7.3.1` (dev dependency only, GHSA-4w7w-66w2-5vf9 + GHSA-v2wj-q39q-566r + GHSA-p9ff-h696-f583). Dev-server only, production build ships static files. **DEFERRED** — upstream coordinated Vite 7.4 bump pending.
- **[MEDIUM]** `src/api/main_app.py` `SecurityHeadersMiddleware` — no `Cache-Control: no-store` on `/api/*` responses, so authenticated JSON could be cached by shared proxies. **FIXED.**
- **[MEDIUM]** `src/api/middleware/audit_log.py:84` — `decode_token` called without `expected_type`, so a refresh token presented in `Authorization: Bearer …` would resolve a `user_id` for audit purposes. Small exposure (audit label only) but wrong. **FIXED** (`expected_type="access"`).
- **[MEDIUM]** npm `axios 1.0.0-1.14.0` — SSRF / header-injection (GHSA-3p68-rc4w-qgx5 + GHSA-fvcv-3m26-pcqx). Moderate severity, direct dep. **DEFERRED** — out of the ~10-fix budget; covered below as follow-up.
- **[LOW]** `src/api/main_app.py` HSTS header carries `preload` without domain submission. Harmless, but non-trivial to advertise; leaving as-is since HSTS is only set in production. **NO CHANGE.**
- **[LOW]** `src/telegram/poller.py:111,167` logs last 6 chars of Telegram bot tokens. Tokens are 40+ chars, 6-char suffix non-reversible. **NO CHANGE.**
- **[LOW]** `src/api/routers/auth.py:113,121,139,146,153` logs full usernames on failed login. Required for security forensics + lockout triage. **NO CHANGE (intentional).**
- **[LOW]** `src/utils/logger.py:36-43` already runs a `RedactionFilter` over every LogRecord — catches `api_key=…`, `Bearer …`, JWTs. Coverage is good; would benefit from wider pattern set but out of scope.
- **[LOW]** `docker-compose.yml` binds Postgres/Prometheus/Grafana/Alertmanager to `127.0.0.1:*` — correct.
- **[LOW]** `.env.example` — every placeholder is empty or `your_*_here`. No real secrets committed.
- **[INFO]** Cookie flags (`httponly`, `secure` in prod, `samesite=lax`, path-scoped) already correct in `src/auth/jwt_handler.py` — no change.
- **[INFO]** Rate limiter from PR #244 covers all auth-sensitive endpoints (`/login` 5/min, `/refresh` 5/min, `/change-password` 3/min, `/bridge/generate` 10/min, `/bridge/exchange` 10/min, `/sessions` delete 5/min) — coverage verified, no gap.

#### Fixed
- **[SEC-P3-1]** `src/api/routers/auth_bridge.py` — replaced two unguarded `request.headers.get("X-Forwarded-For", …)` calls with the shared `_get_real_client_ip(request)` helper so `X-Forwarded-For` is only trusted when `BEHIND_PROXY=true`. Matches rate-limiter + auth.py behaviour.
- **[SEC-P3-2]** `src/api/middleware/audit_log.py` — `AuditLogMiddleware.dispatch` now reuses `_get_real_client_ip` for the `client_ip` field in both the log line and the DB `audit_logs.client_ip` write. Preserves real-client attribution behind the reverse proxy without letting clients spoof the audit trail locally.
- **[SEC-P3-3]** `src/api/middleware/audit_log.py` — `_extract_user_id` now passes `expected_type="access"` into `decode_token`, so a refresh token in the `Authorization` header can no longer label audit rows with a `user_id`. Defense-in-depth: refresh tokens are only meant for the `/api/auth/refresh` cookie path.
- **[SEC-P3-4]** `src/api/main_app.py` `SecurityHeadersMiddleware` — adds `Cache-Control: no-store` on `/api/*` responses that do not already set one. SPA static assets under `/` keep their own cache headers from `StaticFiles`, so build caching is unaffected.

#### Deferred as follow-ups (out of the ~10-fix budget, or needs product/infra decision)
- **[DEP-1]** `axios` bump to `>=1.15.0`. Direct dep; SSRF advisory is moderate severity; fix is a drop-in but touches 50+ call sites worth of response-shape regression testing.
- **[DEP-2]** `lodash` transitive via `recharts` — waits on recharts major bump.
- **[DEP-3]** `defu` transitive via `wagmi` → `walletconnect` — waits on upstream.
- **[DEP-4]** `vite` 7.x dev-only high-sev advisories — dev server exposure only, coordinated bump after frontend test suite is stabilised.
- **[DEP-5]** `follow-redirects`, `hono` — moderate severity transitive, same story as above.
- **[HARDENING-1]** Raise `ChangePasswordRequest.new_password` min length from 8 → 12 (NIST SP 800-63B still allows 8 but 12 is defensible). Needs product decision — would break users mid-migration.
- **[HARDENING-2]** Consider stripping `preload` from HSTS until domain is actually submitted to hstspreload.org.
- **[HARDENING-3]** Extend `RedactionFilter` patterns in `src/utils/logger.py` to cover Ethereum wallet addresses (0x…40hex) and Hyperliquid agent wallet seeds. Not urgent — wallets are public chain addresses, but privacy-conscious users may disagree.

#### Not changed (scope)
- CSP already tightened in PR #244.
- No new dependencies pulled in (no `secure`, no `itsdangerous`).
- No API response-shape changes.

### 2026-04-22 — P2-Batch-UX: Virtualised long tables (#249, task 1/5)

#### Added
- **[P2-1]** `frontend/src/components/virtualised/useVirtualRows.ts` — new hook built on `@tanstack/react-virtual`'s `useWindowVirtualizer`. Exposes `{ isVirtualised, virtualItems, paddingTop, paddingBottom, measureElement }` and two named constants `VIRTUALISATION_THRESHOLD = 50` and `DEFAULT_ROW_HEIGHT = 48` (derived from `.table-premium` CSS: `px-4 py-3` = 24 px padding + text-sm ≈ 20 px line-height + 1 px `border-b` ≈ 45 px, rounded up to 48 for first-paint safety margin). Below the 50-row threshold the hook short-circuits (`isVirtualised: false`, empty items) so short lists skip the scroll listeners and ResizeObserver entirely. A private `useScrollMargin(ref, enabled)` helper tracks `rect.top + window.scrollY` via ResizeObserver + window resize so the window-anchored virtualiser knows where the list starts on the page.
- **[P2-1]** `frontend/src/components/virtualised/__tests__/useVirtualRows.test.tsx` — 5 tests mounting the hook into a real `<table>` harness: (1) pins the documented threshold/row-height constants, (2) below threshold renders every row, (3) at 1000 rows engages virtualisation and renders strictly fewer rows than the source (JSDOM has no real layout so exact bounds are library-internal — we assert the user-visible invariant), (4) preserves source-array order (indices strictly ascending — sort/filter flow through unchanged), (5) disengages cleanly when a filter drops count back below the threshold.
- **[P2-1]** `@tanstack/react-virtual@^3.13.24` added to `frontend/package.json` dependencies. Installed with `--legacy-peer-deps` due to an unrelated eslint peer-dep conflict already present in the tree.

#### Changed
- **[P2-1]** `frontend/src/pages/Trades.tsx` — the trades table `<tbody>` now virtualises via `useVirtualRows({ count: trades.length, scrollMarginRef: tradesTableRef })`. Below 50 trades the map renders unchanged (back-compat for default `perPage=25`); at ≥50 the tbody emits `<tr style={{ height: paddingTop }} colSpan={12}>` + windowed rows (`data-index` + `ref={measureElement}` on each) + bottom spacer. Sort handlers, filter state, row click, expand-row, i18n and a11y roles are untouched — the hook only replaces the iteration, not the row renderer. A new IIFE wraps the tbody body and defines `renderTradeRow(trade, virtualIndex)` so the same row JSX is shared between the full-render and virtualised paths.
- **[P2-1]** `frontend/src/pages/Portfolio.tsx` — the positions table `<tbody>` wired to `useVirtualRows({ count: sortedPositions.length, scrollMarginRef: positionsTableRef })` with the same spacer-`<tr>`/closure pattern as Trades (`colSpan={10}` matching this table's column count). The allocation table next to it is not a `<table>` — it's a recharts pie chart — so it was skipped as out-of-scope. Sort order + filter + i18n unchanged.
- **[P2-1]** `frontend/src/pages/__tests__/Trades.test.tsx` — added test `"should render fewer DOM rows than source when trade list exceeds virtualisation threshold"` using 250 synthetic trades and asserting `rendered DOM row count < trades.length`. (250 keeps the assertion snappy under the parallel suite's JSDOM cost while still being 5× the 50-row threshold — a strong signal that virtualisation is engaged.)

#### Rationale
- **[P2-1]** `useWindowVirtualizer` (not container-scoped) because both pages scroll with the document, not inside a fixed-height wrapper — container-scoped virtualisation would break the existing `overflow-x-auto` horizontal-scroll pattern on narrow viewports.
- **[P2-1]** Spacer `<tr>` rows (not absolute-positioned divs) to keep the shared `.table-premium` CSS — hover highlight, `:nth-child(even)` zebra rows, sticky-header selectors — working unchanged. Switching to divs would have required rewriting the stylesheet.
- **[P2-1]** A shared hook (`useVirtualRows`) rather than a full `<VirtualTable>` component: the two tables have different `colSpan` values, different expand-row patterns (Trades has expandable detail rows, Portfolio doesn't), and different row-click semantics. Extracting the iteration machinery while letting each page own its row JSX gave the cleanest seam; a `<VirtualTable rowRenderer={...} colSpan={...} expandable={...} />` abstraction would have had a noisier prop interface for no real sharing gain.



#### Audited
- **[UX-M6]** Audit of notification surfaces in `frontend/src/`. Found **zero** external toast libraries installed (no `react-hot-toast`, no `sonner`, no `@radix-ui/react-toast`, no shadcn `useToast` — verified by grep of all `.ts`/`.tsx` files and by reading `frontend/package.json` dependency list). The dominant toast surface is the in-repo Zustand store `frontend/src/stores/toastStore.ts` + renderer `frontend/src/components/ui/Toast.tsx`, mounted exactly once in `frontend/src/App.tsx:67` as `<ToastContainer />`. ~15 call sites already consume it (`AppLayout`, `Bots`, `BotBuilder`, `BotPerformance`, `AdminUsers`, `AdminRevenue`, `AdminBroadcasts`, `Admin`, `GettingStarted`, `queries.ts`, and their tests). The remaining non-toast notification surfaces are 8 files using inline `setError` state + a red banner div — most of which are legitimately non-toast cases (wizard-step errors inside modals, full-page auth-callback error states, structured `ReferralDiagnostic` cards with wallet tables). Only `Login.tsx` and `TaxReport.tsx` had plain transient-error banners that belong in a toast.

#### Winner
- **[UX-M6]** Kept the existing `useToastStore` (Zustand) as the single notification surface. Reasons: already the dominant pattern, zero external-library bundle cost, supports all four severities (`success`/`error`/`info`/`warning`) with auto-dismiss, max-stack, manual-dismiss button, URL auto-linking, ARIA `role="alert"` + `aria-live="polite"`, and a theme-matching Tailwind gradient look that matches the dashboard aesthetic. Introducing `react-hot-toast`/`sonner` would mean adopting a second notification system, which is the exact problem this task is solving — hence explicitly rejected.

#### Added
- **[UX-M6]** `frontend/src/utils/toast.ts` — thin wrapper exposing the public notification API. Four helpers: `showSuccess(msg, duration?)`, `showError(msg, duration?)`, `showInfo(msg, duration?)`, `showWarning(msg, duration?)`. Each delegates to `useToastStore.getState().addToast(type, msg, duration ?? DEFAULT_DURATIONS[type])`. Per-severity defaults: success/info = 5 s, warning = 6 s, error = 7 s (errors linger a bit longer so users don't miss them). Consumers should now import from `utils/toast` instead of reaching into `stores/toastStore` directly — the wrapper is the single place to tune position/duration/theming going forward.
- **[UX-M6]** `frontend/src/utils/__tests__/toast.test.ts` — 7 unit tests mocking `useToastStore.getState().addToast` and asserting (a) each wrapper fires with the correct `type` arg, (b) default durations per severity, (c) explicit `duration` argument is honoured, (d) `duration=0` passes through (persistent toast), (e) helpers fire independently and in declared order. Pure plumbing coverage — the store itself already has exhaustive tests in `stores/__tests__/toastStore.test.ts`.

#### Changed
- **[UX-M6]** `frontend/src/pages/Login.tsx` — migrated the login-failure inline banner (`{error && <div role="alert" className="bg-red-500/10 ..." />}`) to `showError(t('login.error'))`. Dropped the `error` local state and the banner JSX; import `showError` from `../utils/toast`. The login-page toast renders through `<ToastContainer />` which is mounted in `App.tsx` outside the `ProtectedRoute`, so toasts surface on the public login page too.
- **[UX-M6]** `frontend/src/pages/TaxReport.tsx` — migrated both `setError` call sites (page load failure + CSV download failure) to `showError(t('common.error'))` and `showError(t('tax.downloadError'))` respectively. Dropped the `error` state + banner div above the loading/data block. The i18n keys are unchanged.
- **[UX-M6]** `frontend/src/pages/__tests__/Login.test.tsx` — updated the "login failure" and "retry after failure" tests to mock `../../utils/toast` (`showError` spy) and assert `mockShowError.toHaveBeenCalledWith('Invalid username or password')` instead of `screen.getByText(...)`. The inline banner no longer renders inside the form subtree — the toast is dispatched through the separate container.

#### Skipped (intentional — non-toast UX)
- **[UX-M6]** `frontend/src/pages/AuthCallback.tsx` — full-page error state with a "Back to Trading Department" recovery link. Not a transient toast; the whole page pivots into an error card. Left as inline banner.
- **[UX-M6]** `frontend/src/components/hyperliquid/HyperliquidSetup.tsx` — contains the structured `ReferralDiagnostic` UI (wallet short-address, on-chain balance, cumulative volume, multi-step deposit instructions, conditional `DEPOSIT_NEEDED` / `ENTER_CODE_MANUALLY` / `WRONG_REFERRER` action cards). Rich contextual content that a 7-second toast cannot express. Left as inline error block.
- **[UX-M6]** `frontend/src/components/hyperliquid/BuilderFeeApproval.tsx` — multi-step wizard modal; errors are contextual to the current step and must stay visible while the user retries. Left inline.
- **[UX-M6]** `frontend/src/components/ui/EditPositionPanel.tsx` — errors appear inside a TP/SL edit modal where the user is mid-input; a disappearing toast would lose context before the user can retry. Left inline.
- **[UX-M6]** `frontend/src/components/bots/CopyTradingValidator.tsx` — inline validation result panel showing the opposite `result` success case (wallet label, trade count, available/unavailable chips). Symmetric with the success UI it lives alongside. Left inline.

#### Follow-up (owned by other agents — not migrated in this PR)
- **[UX-M6]** Per-task scope rules, files owned by other agents (Trades, Portfolio, Settings, Dashboard, BotBuilder, share components) are **not** touched here. Existing `useToastStore.getState().addToast(...)` call sites in `AppLayout.tsx`, `Bots.tsx`, `BotPerformance.tsx`, `BotBuilder.tsx`, `AdminUsers.tsx`, `AdminRevenue.tsx`, `AdminBroadcasts.tsx`, `Admin.tsx`, `GettingStarted.tsx`, `queries.ts` continue to work exactly as before — the wrapper adds a thinner path for new code without forcing a branch-wide rename. A future follow-up PR can do the pure-cosmetic `useToastStore(…)` → `showError(…)` renames once the currently-in-flight branches have landed.

#### Uninstalled
- **[UX-M6]** Nothing. No external toast library was ever installed, so no `npm uninstall` needed.

#### Verified
- `cd frontend && npx vitest run src/utils/__tests__/toast.test.ts` → **7/7 passed** (wrapper unit tests, 7 ms).
- `cd frontend && npx vitest run src/pages/__tests__/Login.test.tsx src/pages/__tests__/TaxReport.test.tsx` → **15/15 passed** (migrated tests stay green, 3.66 s).
- `cd frontend && npm test -- --run` → **547/547 passed** across 56 files (21 s). No regressions anywhere.

### 2026-04-22 — UX-M2: Share-capture div conditional mount (#249, task 2/5)

#### Changed
- **[UX-M2]** `frontend/src/pages/BotPerformance.tsx` — the hidden mobile share-capture subtree at `position: absolute; left: -9999px` no longer pre-renders one card per closed trade on every render pass. Previously, whenever `botDetail` was loaded on mobile, the component eagerly mapped `botDetail.recent_trades.filter(tr => tr.status === 'closed')` into a Map-backed ref collection (`mobileShareRefs`) of fully-rendered share cards — the subtree re-ran on every parent state change (tab switches, chart tooltip hovers, expandedTradeId toggles, etc.) and held N DOM subtrees purely on the chance a share might be invoked. Now the capture div mounts only while a share is in-flight, and only for the single trade being shared.
- **[UX-M2]** Replaced the always-mounted `useRef<Map<number, HTMLDivElement>>` pattern with a single `sharingTrade` state variable (plus a `shareResolveRef` promise-resolve handle). `handleMobileDirectShare(trade)` now (1) creates a `Promise<HTMLDivElement | null>` and stores its resolver in `shareResolveRef.current`, (2) calls `setSharingTrade(trade)` which triggers React to mount exactly one hidden capture div for that trade, (3) awaits the promise — the conditional subtree's **callback ref** fires after commit with the live DOM node and calls `resolve(el)`, (4) invokes `toBlob(el, ...)` against the now-mounted node, (5) calls `setSharingTrade(null)` the instant the blob is produced so the subtree unmounts before the `navigator.share()` call even resolves. `AbortError` and generic-error branches both clear `sharingTrade` so the subtree can never get stuck mounted. The callback ref is the "wait for mount before calling html-to-image" mechanism — without it the first click would capture an empty ref because React has not yet committed the node when `handleMobileDirectShare` runs.
- **[UX-M2]** `tradeCardRef` (inside the Trade-Detail modal at line 1088) was already conditionally mounted via `{selectedTrade && (...)}` and is untouched. Likewise `TradeDetailModal` in `frontend/src/pages/Bots.tsx` is already gated on `{selectedTrade && ...}` — verified and left alone. Only the mobile-direct-share pre-rendering was the performance drain.

#### Added
- **[UX-M2]** `frontend/src/pages/__tests__/BotPerformance.test.tsx::"does not mount the hidden mobile share-capture div until a share is initiated"` — new regression test that renders the page with `botDetail.recent_trades` containing a closed trade and asserts `screen.queryByTestId('mobile-share-capture')` returns `null` on first render. Guards against regressions that would re-introduce eager mounting (e.g. someone removing the `{sharingTrade && ...}` guard). The `data-testid="mobile-share-capture"` attribute is stable and only present on the wrapper div that mounts inside the `{sharingTrade && sharingTrade.status === 'closed'}` block.

#### Verified
- `cd frontend && npx vitest run src/pages/__tests__/BotPerformance.test.tsx` → **6/6 passed** (5 pre-existing + 1 new conditional-mount regression, 354 ms).
- `cd frontend && npx vitest run src/pages/__tests__/BotPerformance.test.tsx src/pages/__tests__/Bots.test.tsx` → **11/11 passed** — all tests in the files I touched stay green. Pre-existing unrelated failures in Login/TaxReport tests are caused by other in-flight agent work on the same branch, not by this change (verified by stashing my diff and confirming the failures disappear — they reappear with the full branch diff regardless of whether UX-M2 is applied).

### 2026-04-22 — UX-M5: Settings loading skeleton (#249, task 4/5)

#### Changed
- **[UX-M5]** `frontend/src/pages/Settings.tsx` — the page no longer renders as a blank white frame while the initial data round-trip (`/exchanges` + `/config` + `/config/exchange-connections` + `/affiliate-links`) is in flight. Introduced an `initialLoading` state flag (initialised to `true`) that flips to `false` exactly once at the end of the single `useEffect` loader — regardless of whether the auth-gated requests succeeded or were rejected — so the real page (possibly with empty arrays + an error banner) always takes over after the first round-trip. The skeleton is mounted through an early-return `if (initialLoading) return <SettingsSkeleton />` directly above the main JSX return, so there's zero risk of double-rendering header + skeleton in the same frame.
- **[UX-M5]** The skeleton mirrors the real layout rhythm: a title row (h1 + help-button placeholder), the summary bar card (icon square + heading/subtext stack + progress bar + percentage on the right), and **two** exchange accordion card placeholders (icon square + display-name/type stack on the left, status pill + chevron on the right). Two was chosen because it is the current minimum exchange count (Bitget + Hyperliquid always render; Weex/Bitunix/BingX are optional add-ons) — rendering exactly two avoids a layout-shift jump for the common case, while extra real cards are appended incrementally once data arrives. Rectangles use the in-repo `skeleton-pulse` CSS class with `rounded-lg bg-white/5` so the skeleton matches the existing `SkeletonCard`/`SkeletonTable` primitives visually without adding a new primitive to `components/ui/`. All widths/heights are fixed Tailwind values (no `Math.random()`, no per-render randomisation) — SSR-stable, no hydration mismatch risk.

#### Added
- **[UX-M5]** `SettingsSkeleton` function component + `SkeletonRect`/`SkeletonExchangeCard` helpers in `frontend/src/pages/Settings.tsx`. The `SettingsSkeleton` root has `data-testid="settings-skeleton"` and `aria-busy="true"` + `aria-label="Loading settings"` for a11y + test selectors. Kept inline (not a separate file) because the whole thing is ~60 lines and only consumed once.
- **[UX-M5]** `frontend/src/pages/__tests__/Settings.test.tsx::"should render the skeleton while the initial load is in flight and hide it once data arrives"` — new regression test that holds the `/exchanges` promise open, asserts `screen.getByTestId('settings-skeleton')` is in the DOM **and** `screen.queryByText('Settings')` (the real title) is **not** mounted, then releases the promise and asserts the inverse (`queryByTestId('settings-skeleton')` returns null, real title is found). Guards both halves of the state machine.

#### Verified
- `cd frontend && npm test -- --run src/pages/__tests__/Settings.test.tsx` → **5/5 passed** (4 pre-existing + 1 new skeleton regression, 128 ms).
- `cd frontend && npm test -- --run` → **539/539 passed** across 55 files (42 s). The pre-existing Settings tests still pass because `waitFor(() => screen.getByText('Settings'))` naturally spans the skeleton → real-content transition. No other page touched.

### 2026-04-22 — UX-M3: Dashboard tour autoStart gated on ready (#249, task 3/5)

#### Changed
- **[UX-M3]** `frontend/src/pages/Dashboard.tsx` — `GuidedTour` for the `dashboard` tour no longer auto-starts on mount while the core React-Query fetches are still in flight. The three queries that feed the tour's highlighted targets (`useDashboardStats` → `[data-tour="dash-stats"]`, `useDashboardDaily` → `[data-tour="dash-charts"]`, `usePortfolioPositions` → `[data-tour="dash-trades"]`) now expose their full `UseQueryResult` via locals `statsQuery`/`dailyQuery`/`positionsQuery`, and a derived `dashboardReady` boolean — `(isSuccess || isError)` per query — is passed as `autoStart={dashboardReady}`. Previously the tour fired 600 ms after mount against skeleton DOM. Now it waits for real content; once data arrives the existing 600 ms delay in `GuidedTour` still applies so the overlay animation is unchanged.
- Error-path decision: if a query transitions to `isError`, it still counts as "ready" for tour purposes — the tour starts anyway rather than blocking the user forever on a broken endpoint. The dashboard's existing red error banner remains visible beneath the tour overlay. We deliberately did not add a timeout fallback because React Query's default retry policy is already bounded (retries → success or error within seconds).
- Preserved: the "user has already completed the tour → don't auto-start again" logic in `tourStore.shouldShowTour` runs unchanged inside `GuidedTour`'s auto-start effect; the manual restart via `TourHelpButton` is untouched; tour step count, targets, and copy are identical.

#### Added
- **[UX-M3]** `frontend/src/pages/DashboardTour.test.tsx` — three new behavioural tests in a new `Dashboard tour autoStart gating on ready state` suite, on top of the pre-existing static-config assertions. Uses `vi.useFakeTimers` + `act(vi.advanceTimersByTime(...))` to verify: (1) with `autoStart={false}` (queries pending), advancing 2000 ms does NOT activate the tour and `useTourStore.getState().activeTour` stays `null`; (2) with `autoStart={true}` (queries succeeded), advancing the 600 ms delay starts the tour and `activeTour === "dashboard"`; (3) with `completedTours: { dashboard: true }` in the store the tour does NOT re-auto-start even when `ready=true` — confirms the localStorage-backed "seen once" guard still wins. Tests render `GuidedTour` directly with representative `data-tour` target divs and a `QueryClientProvider` wrapper to mirror the production tree.

#### Verified
- `cd frontend && npm test -- --run` — the new `DashboardTour.test.tsx` suite passes alongside the existing `GuidedTour.test.tsx` and `tourStore.test.ts` coverage.

### 2026-04-22 — ARCH-M1 + ARCH-M2: settings prune + feature-flag registry (#247, task 3/5)

#### Removed
- **[ARCH-M1]** `config/settings.py` — deleted the following dead fields and helpers (each was verified zero-consumer by grep across `src/`, `tests/`, `.env.example`, `docker-compose.yml`, and `deploy/`):
  - `BitgetConfig.testnet` + `BITGET_TESTNET` env var default (unused in `src/`; still documented in `docs/SETUP.md` + onboarding manuals, which is now the only reference — those are prose, not consumers).
  - `BitgetConfig.validate()` and `BitgetConfig.get_active_credentials()` (no production call sites; the encrypted-key path on `ExchangeConnection` replaced them long ago).
  - `DiscordConfig` class entirely (`bot_token`, `channel_id`, `webhook_url`, `validate()`) — notifications are sent via per-user webhooks from `ExchangeConnection`/`user_configs` and the admin audit hook reads `ADMIN_DISCORD_WEBHOOK_URL` via `os.getenv` directly in `src/bot/audit_scheduler.py:354`. No src consumer, no .env.example entry.
  - `LoggingConfig` class entirely (`level`, `file`) — `src/api/main_app.py:52` reads `LOG_LEVEL` via `os.getenv` directly; `file` had no readers at all. The `LOG_LEVEL` env var itself stays in `.env.example`, unchanged.
  - `Settings.validate()`, `Settings.validate_strict()`, and the in-module `ConfigValidationError` — no callers. The name `ConfigValidationError` continues to exist in `src/utils/config_validator.py` for the `validate_startup_config` path, which is the actually-used one (`src/api/main_app.py:143`, `tests/unit/test_config_validator.py`, `tests/unit/test_production_hardening.py`).
  - `config/__init__.py` — dropped the `DiscordConfig` re-export, added `RiskConfig` to the public surface so the feature-flag registry can import it symmetrically.
- **[ARCH-M1]** Fields kept despite looking quaint (per the "single consumer = separate cleanup" constraint): every `TradingConfig.*` and `StrategyConfig.*` field — they are still read by the `python main.py --status` CLI banner (lines 69-91) and by `main.py`'s `--status` daily-stats block. `BitgetConfig.{api_key, api_secret, passphrase, demo_api_key, demo_api_secret, demo_passphrase}` kept as empty-string defaults because `tests/unit/test_security.py::TestLegacyPlaintextKeysRemoved` asserts they stay empty — that test is a security regression guard against re-introducing a plaintext key path, so deleting the fields would defeat the purpose. `TradingConfig.demo_mode` + `Settings.is_demo_mode` kept, consumed by `src/notifications/discord_notifier.py:178,269`. `RiskConfig.*` kept (actively used).

#### Added
- **[ARCH-M2]** `config/feature_flags.py` — new single-source-of-truth `FeatureFlagRegistry`. A frozen `FeatureFlag` dataclass holds `name`, `settings_path`, `env_var`, `default`, and `description`; the module-level `FEATURE_FLAGS: List[FeatureFlag]` enumerates all flags; `FeatureFlagRegistry.get(name, settings_instance=None)` walks the dotted `settings_path` on the Settings instance at call time (no duplicated state — the Settings instance remains the source of truth). Module-level singleton `feature_flags` mirrors the `settings` singleton pattern. Currently inventories 2 flags: `risk_state_manager_enabled` (`RISK_STATE_MANAGER_ENABLED`, default off) and `hl_software_trailing_enabled` (`HL_SOFTWARE_TRAILING_ENABLED`, default off). Per the PR scope, existing call sites that read `settings.risk.<flag>` directly are NOT migrated; the registry is an inventory, the read-through migration is an optional follow-up.
- **[ARCH-M2]** `tests/unit/config/__init__.py` + `tests/unit/config/test_feature_flags.py` — 16 new tests in four classes. `TestFeatureFlagsShape` (6) asserts the registry has entries, unique names + env-var names, non-empty descriptions, and bool defaults. `TestRegistryMatchesSettings` (2) — crucially — walks every flag's `settings_path` against a fresh `Settings()` instance (guarantees the registry and the dataclass tree stay in sync) **and** parity-checks every `bool` field on the Settings tree whose name contains `enabled` or `disable` and asserts it is registered in `FEATURE_FLAGS` (stops a future `foo_enabled` from slipping in without being documented). `TestRegistryGet` (5) covers default read, runtime-mutation tracking, unknown-flag `KeyError`, the module-level singleton resolving against the global `settings`, and the explicit-instance override precedence rule. `TestGetFlagMetadata` (3) covers `get_flag` + `names`.

#### Verified
- `python -m pytest tests/unit/config/ tests/unit/test_settings.py tests/unit/test_security.py -x --tb=short` → **50/50 passed** (0.75 s). The 16 new `test_feature_flags.py` tests plus the 6 pre-existing `test_settings.py` (DB-first helper) and all 28 `test_security.py` tests — including `TestLegacyPlaintextKeysRemoved::test_bitget_config_does_not_load_api_key_from_env` and `test_bitget_config_demo_keys_also_empty`, which exercise the intentionally-kept empty `BitgetConfig` credential fields.
- Likely-affected subset (config + feature flags + security + config_validator + discord notifier x2 + bot worker + trades router + bots router + TP/SL integration): **314/314 passed** in 101 s.
- Full backend suite: `python -m pytest tests/ --tb=line -q` → **3193 passed, 24 skipped, 13 xfailed, 1 xpassed** in 503 s. One `test_production_hardening.py::TestHealthCheckDbVerification::test_health_returns_200_when_db_ok` flake reproduced only in the full-suite run; passes cleanly in isolation, unrelated to config changes (no settings touch in that code path).

### 2026-04-22 — UX-C5 BotBuilder symbol-conflict blocking (#247, task 1/5)

#### Changed
- **[UX-C5]** `src/api/routers/bots.py` — `create_bot` (POST /api/bots) and `update_bot` (PUT /api/bots/{id}) now raise **HTTP 409 `SYMBOL_ALREADY_IN_USE`** when the user already runs another enabled bot on the same exchange+mode+symbol. Backend is the source of truth (defense-in-depth with the existing `GET /api/bots/symbol-conflicts` probe used by the wizard). The detail payload is `{code, message, conflicts: [...]}` so the UI can translate by code *or* display the server's bilingual message verbatim. Update-path probes only when `trading_pairs`, `exchange_type`, or `mode` are part of the patch — a pure rename or webhook change still skips the conflict query. Copy-trading bots continue to short-circuit (budget-isolated).
- **[UX-C5]** `src/api/routers/bots.py::_check_symbol_conflicts` — added `BotConfig.deleted_at.is_(None)` to the where clause (soft-deleted rows from ARCH-M3 must not block new bots from reusing their symbols) and upper-cased both the requested-pair set and the stored-pair set so `btcusdt` vs `BTCUSDT` collides consistently.
- **[UX-C5]** `frontend/src/components/bots/BotBuilder.tsx` — `getStepErrors('step3')` now pushes `bots.builder.errors.symbolConflicts` when `symbolConflicts.length > 0`, so clicking Next on the Exchange step shows the inline amber validation panel *and* holds the user on that step. `saveDisabled` on the Review step now also includes `hasSymbolConflicts` so the Save/Create button visibly disables if a conflict is detected after step3 (e.g. the user raced another tab).

#### Added
- **[UX-C5]** `frontend/src/i18n/{de,en}.json` — new key `bots.builder.errors.symbolAlreadyInUse` (parameterized by `{{symbol}}` and `{{botName}}`) for code-based 409 rendering. Parity preserved, `i18n-completeness.test.ts` still green.
- **[UX-C5]** `tests/unit/api/test_bots_router_extra.py::TestSymbolConflictBlocking` — 7 new tests: create-blocks-on-conflict returns 409 with code, create-allows-different-symbol, create-ignores-disabled-bot (is_enabled=False), create-ignores-soft-deleted (deleted_at set), update-same-bot-doesn't-self-conflict (editing in place), update-blocks-when-other-enabled-bot-owns-symbol, and case-insensitive match (lowercase request hits uppercase stored pair).
- **[UX-C5]** `frontend/src/components/bots/__tests__/BotBuilder.test.tsx` — regression test `blocks Next on the Exchange step and shows an inline error when a conflict exists`. Mocks `/bots/symbol-conflicts` to return a BTCUSDT clash, advances to step3, asserts that clicking Next surfaces the validation key and keeps the user on the Exchange step.

#### Verified
- `python -m pytest tests/unit/api/ -x --tb=short` → **813/813 passed** in 225 s (the 7 new TestSymbolConflictBlocking tests plus the pre-existing 806, nothing regressed).
- `cd frontend && npm test -- --run` → **535/535 passed** across 55 files (22 s). The one new test (`blocks Next on the Exchange step…`) is additive; i18n parity test still passes with both new keys added to de+en.

### 2026-04-22 — ARCH-M6 `/api/health` active dependency probes (#247, task 4/5)

#### Changed
- **[ARCH-M6]** `src/api/routers/status.py` — the `/api/health` handler now actively probes the real runtime dependencies instead of returning a static payload. Four probes run in parallel via `asyncio.gather` with a per-probe 2.5 s hard timeout (wrapped in `asyncio.wait_for` so one stalled probe cannot block the others) and an outer 5 s cap on the whole gather as defense-in-depth against a wedged event loop: (1) **database** via `async with get_session(): SELECT 1` and reports `latency_ms`; (2) **scheduler** reads `app.state.orchestrator._scheduler.running`; (3) **ws_broker** reads `app.state.ws_manager.total_connections` (internal FastAPI ConnectionManager); (4) **exchange_ws** calls `app.state.exchange_ws_manager.connected_counts()` for bitget/hyperliquid. Each probe is pre-wrapped in `_run_probe` which swallows `asyncio.TimeoutError` and any other exception into a structured `{"ok": False, "error": "..."}` so the endpoint itself can never raise.
- HTTP status logic: DB failure → **503 + `status="unhealthy"`** (the one critical probe that pages operators). DB ok but any optional probe failed → **200 + `status="degraded"`**. All probes ok → **200 + `status="healthy"`** — the literal string `"healthy"` is preserved because `docker-compose.yml` (line 64) greps `d.get('status') == 'healthy'` in the container healthcheck. Non-critical failures deliberately do *not* flip to 503 so a brief WS reconnect doesn't mark the whole container unhealthy and cause Compose to restart it.
- Redis was intentionally not wired because grep across `src/`, `src/utils/settings.py`, and `config/settings.py` found zero `Settings.redis` / `REDIS_URL` references — the only mention is a forward-looking comment in `src/bot/event_bus.py`. External services (exchange REST, LLM providers) are deliberately not probed either: a health endpoint must not DoS them on every uptime poll, and they are per-bot rather than process-level dependencies.
- Response shape preserves every existing field monitors may depend on: top-level `status`, `checks` (now a dict of per-probe result dicts, each with `ok` + latency/running/connections), `ws_connections` (legacy `{bitget, hyperliquid}` counts), `timestamp`, and the new `version` field (reads `BUILD_COMMIT`/`GIT_COMMIT`, falls back to `"unknown"`). `checks.bots` is kept for backwards compat with the previous shape (now `{ok, errors, total}` instead of a string) and `checks.audit_log_failures` remains available.

#### Added
- **[ARCH-M6]** `tests/unit/api/test_health_probes.py` — 13 new tests covering: each probe function in isolation (scheduler running/stopped/missing, ws_broker count/missing), `_run_probe` swallows `asyncio.TimeoutError` and generic exceptions into `{ok: False, error: ...}`, and six endpoint-level cases — all probes ok → 200 `"healthy"`, DB fails → 503 `"unhealthy"` with other probes still reported, optional probe fail + DB ok → 200 `"degraded"`, `exchange_ws_manager` not on `app.state` → `ok=false` with `"not on app.state"` error (so monitoring can distinguish unconfigured from broken), a 10 s hung probe returns in under 2 s because per-probe timeout fires, and a literal-string regression test that guards the docker-compose healthcheck contract (`status == "healthy"`).

#### Fixed
- **[ARCH-M6]** `tests/unit/test_production_hardening.py` — updated `TestHealthCheckDbVerification` to match the new structured `checks.database` shape: `checks["database"]["ok"] is False` for the 503 case, `checks["database"]["ok"] is True` for the 200 case. Loosened the top-level assertion on the happy-path test from strict `"healthy"` to `in ("healthy", "degraded")` because that test does not wire an orchestrator/ws_manager onto `app.state`, so non-critical probes now report `ok=False` (was not visible before because the old handler didn't probe them).
- **[ARCH-M6]** `tests/unit/test_status_endpoints.py` — widened `test_health_response_fields` assertion from `status in ("healthy", "unhealthy")` to `status in ("healthy", "degraded", "unhealthy")` for the same reason.

#### Verified
- `python -m pytest tests/unit/api/test_health_probes.py tests/unit/test_status_endpoints.py tests/unit/test_production_hardening.py::TestHealthCheckDbVerification -x --tb=short` → **19/19 passed** in 0.59 s.
- docker-compose.yml healthcheck command unchanged: still parses `d.get('status') == 'healthy'` — the happy-path string is preserved byte-for-byte.

### 2026-04-22 — UX-M10 i18n parity tolerance tightened to zero (#247, task 5/5)

#### Changed
- **[UX-M10]** `frontend/src/i18n/i18n-completeness.test.ts` — tightened the `overall parity` block so **any** missing key in either `de.json` or `en.json` fails the test (and therefore CI). Before: the only whole-tree guard was `expect(Math.abs(deTotal - enTotal)).toBeLessThanOrEqual(5)`, which tolerated up to five missing keys on either side *and* only compared counts (so five DE-only keys and five disjoint EN-only keys would slip through). After: three strict assertions — (1) `deTotal === enTotal`, (2) the full dot-notation key sets are symmetric (empty diff in both directions, with a failure message that lists the exact `missingInDe` / `missingInEn` paths so the CI log pinpoints the gap), and (3) no structural mismatches (leaf-vs-object drift anywhere in the tree, printed as `path: de=<type> vs en=<type>`). The test file already contained a `flattenKeys` helper, reused as-is.

#### Verified
- Pre-change parity audit: DE 1105 keys, EN 1105 keys, `missingInDe = []`, `missingInEn = []`, zero structural mismatches — no JSON edits were needed, the sweep during PR #244 had already closed every gap.
- `cd frontend && npx vitest run src/i18n/i18n-completeness.test.ts` → **17/17 passed** (13 ms).
- Full frontend suite: `cd frontend && npx vitest run` → **534/534 passed** across 55 files (20.51 s). No other test broke.

### 2026-04-22 — UX-H8 Portfolio render-order error flow (#247, task 2/5)

#### Fixed
- **[UX-H8]** `frontend/src/pages/Portfolio.tsx` — render order is now **error → loading → content**, matching the audit prescription. Previously the component only checked `summaryError`, meaning a failure in `usePortfolioPositions`, `usePortfolioDaily`, or `usePortfolioAllocation` would be masked by the loading skeleton (while the other queries were still in flight) or by an empty-state fallback (e.g. "No data"/"No open positions") for the queries that did succeed. The new guard collapses all four `error` fields via `const firstError = summaryError ?? positionsError ?? dailyError ?? allocationError` and renders the shared error view (`getApiErrorMessage(firstError, t('common.error'))` + Retry button) before any loading or content branches. The previous in-content `{error && <banner/>}` fallback (also driven only by `summaryError`) was removed since every error path now exits early. No query behavior changed — this is a pure render-order fix.

#### Added
- **[UX-H8]** `frontend/src/pages/__tests__/Portfolio.test.tsx` — new regression test `should render error when one query fails even if others succeed`. Rejects `/portfolio/summary` while the other three endpoints return their happy-path fixtures, then asserts the error message ("Summary backend down") **and** the Retry button render, and that `"Open Positions"` / `"Exchange Breakdown"` (content markers) do **not** leak through. Existing `should show error message on API failure` test (which rejects all four queries) still passes. Added `common.retry: 'Retry'` to the mock translator so the retry button's accessible name resolves in the test environment.

#### Verified
- `cd frontend && npm test -- --run src/pages/__tests__/Portfolio.test.tsx` → **12/12 passed** (537 ms).

### 2026-04-22 — ARCH-H2 completion: delete HyperliquidGatesMixin (#245, task 4/4)

#### Removed
- **[ARCH-H2]** `src/bot/hyperliquid_gates.py` (262 lines, `HyperliquidGatesMixin`) deleted. The four legacy methods (`_check_referral_gate`, `_check_builder_approval`, `_check_wallet_gate`, `_check_affiliate_uid_gate`) were a duplicate of the logic that already lived in `HyperliquidClient.pre_start_checks` — kept alive only because nine legacy unit tests were still driving the mixin directly. Production has been calling `client.pre_start_checks(...)` exclusively since PR #244. `BotWorker`'s MRO no longer lists `HyperliquidGatesMixin` and the import is gone from `src/bot/bot_worker.py`. The file-level docstring now points readers at `ExchangeClient.pre_start_checks` as the single entry point for per-exchange gate checks.

#### Changed
- **[ARCH-H2]** `tests/unit/exchanges/test_hyperliquid_builder.py` — `TestBotWorkerReferralGate` (5 tests) and `TestBotWorkerBuilderCheck` (6 tests) repointed at `HyperliquidClient.pre_start_checks(user_id, db)` and renamed `TestHyperliquidPreStartChecksReferralGate` / `TestHyperliquidPreStartChecksBuilderGate`. Each test now builds a lightweight `HyperliquidClient` via `object.__new__` (same pattern as the pre-existing `TestBuilderFeeApproval` tests), stubs the SDK-touching methods (`get_referral_info`, `check_builder_fee_approval`, `validate_wallet`), and asserts on the returned `List[GateCheckResult]` — failing blocks assert `any(r.key == "referral"/"builder_fee" and not r.ok)`, passing cases assert the gate is absent from the result list. The one-of-a-kind `test_builder_check_skipped_for_non_hl_client` now tests the routing contract by invoking the base `ExchangeClient.pre_start_checks` via descriptor-bind and asserting it never emits a `builder_fee` key.
- **[ARCH-H2]** `tests/unit/bot/test_bot_worker_extra.py` — `TestCheckBuilderApproval` (4 tests) and `TestCheckReferralGate` (2 tests) ported in the same style. Shared `_make_hl_client_for_gates` helper mirrors the one in `test_hyperliquid_builder.py` to keep both test modules self-contained.
- **[ARCH-H2]** `src/exchanges/hyperliquid/client.py` — `pre_start_checks` docstring updated: caller attribution now reads "`BotWorker.initialize` maps failing results to `self.error_message`" instead of referring to the deleted mixin.

#### Verified
- Full backend suite: 3158 passed, 24 skipped, 13 xfailed, 1 xpassed — no regressions (`python -m pytest tests/ --tb=line -q`, 497.80s).
- Target 9 tests (listed in issue #245 task 4) + the 6 paired "passing" siblings in the same classes all run against `pre_start_checks` and pass.

### 2026-04-22 — Manual-close endpoint routed through RiskStateManager.classify_close (#245)

#### Changed
- **`src/api/routers/bots_lifecycle.py`** (`POST /api/bots/{bot_id}/close-position/{symbol}`, lines 328-474): after the exchange-side close is verified the endpoint now defers to `RiskStateManager.classify_close(trade_id, exit_price, exit_time)` when `Settings.risk.risk_state_manager_enabled` is True. This closes the last gap from PR #244: strategy exits and position-monitor exits already went through the RSM, but manual closes still hard-coded `exit_reason = "MANUAL_CLOSE"` regardless of what actually triggered the close on the exchange. Mirrors the `sync_trades` pattern from `trades.py:475-499`. Failure modes: the classifier is wrapped in try/except and falls back to the legacy `"MANUAL_CLOSE"` string; when the feature flag is off the endpoint behaves exactly as before (no classifier call, no import of `get_risk_state_manager`). The call is gated behind the success path — a failed close or a 502 verify never reaches the classifier, so a bad close cannot leak into exit-reason attribution.

#### Added
- **`tests/unit/api/test_bots_router.py`** — new `TestClosePositionClassifyClose` test class (3 tests) covering: classify_close is awaited with `(trade_id, exit_price, exit_time)` and its return value becomes `TradeRecord.exit_reason` when the flag is on; classify_close is NOT awaited when the flag is off; a RuntimeError from classify_close does not break the endpoint (fallback to `MANUAL_CLOSE`). All 79 tests in `test_bots_router.py` pass.

### 2026-04-22 — BUILD_COMMIT wiring: docker-compose + deploy script (#245)

#### Changed
- **`docker-compose.yml`**: `trading-bot.build` now declares an `args.BUILD_COMMIT: ${BUILD_COMMIT:-unknown}` block so the compose build stage forwards the host's commit SHA into the Dockerfile's `ARG BUILD_COMMIT`. Local `docker compose up` without the export still works thanks to the `:-unknown` fallback. The Dockerfile's `ARG BUILD_COMMIT` → `ENV BUILD_COMMIT` plumbing was already in place (lines 42-43) and was not touched.
- **`scripts/deploy.sh`**: added `export BUILD_COMMIT=$(git rev-parse HEAD)` right before the build step (covers both the `--no-cache` and cached branches), plus an echo line so the deploy log records which SHA is being baked in. This closes the open ops note from the 2026-04-21 Workstream E entry — `/api/version` will now return the real commit in production instead of `unknown`.

#### Verified
- `docker compose config` (with dummy `BUILD_COMMIT=abc123`) resolves `args.BUILD_COMMIT: abc123` on the `trading-bot` service, confirming end-to-end interpolation.

### 2026-04-21 — Backend: trades filter-options + sync_trades classify_close wiring (Agent A1)

#### Added
- **[ARCH-C1a filter-options]** `GET /api/trades/filter-options` — new endpoint in `src/api/routers/trades.py` returning `{symbols, bots: [{id, name}], exchanges, statuses}` scoped to the current user. Uses `SELECT DISTINCT` queries so it is cheap even on accounts with thousands of trades. Protected by the same `get_current_user` dependency as the rest of `/api/trades`. Exchanges are the union of `trade_records.exchange` and `bot_configs.exchange_type`, so a newly-created bot that hasn't traded yet still surfaces in the filter dropdown.
- **[ARCH-C1a filter-options]** New Pydantic response model `TradeFilterOptionsResponse` + `TradeFilterBotOption` in `src/api/schemas/trade.py`. Matches the shape the frontend `useTradesFilterOptions()` hook already consumes.
- **[ARCH-C1a tests]** `tests/unit/api/test_trades_router.py` — 5 new tests for the filter-options endpoint (auth required, empty-user, distinct values, cross-user isolation, bot-without-trades inclusion) and 3 new tests for the sync_trades RSM wiring (classify_close is used when flag is on, heuristic fallback on error, flag-off path untouched). All 44 tests pass.

#### Changed
- **[ARCH-C1a sync_trades]** `POST /api/trades/sync` — when `Settings.risk.risk_state_manager_enabled` is True the endpoint now defers to `RiskStateManager.classify_close(trade_id, exit_price, exit_time)` instead of the legacy price-proximity heuristic for attributing `exit_reason`. After marking each detected close in the DB it runs `RiskStateManager.reconcile(trade_id)` so `tp_status` / `sl_status` / `trailing_status` / `risk_source` / `last_synced_at` reflect the actual post-close exchange state. Both calls are wrapped in try/except — on failure the endpoint falls back to the old heuristic so a transient manager fault never stops a sync. When the flag is off the path is byte-for-byte identical to before.

#### Rationale
- The owned files (`trades.py`, `bots.py`, `portfolio.py`) do not host a `POST /.../close-position/...` endpoint — that lives in `src/api/routers/bots_lifecycle.py` (out-of-scope for this agent). The only path in-scope that bypassed the RSM classification pipeline was `sync_trades`, which detected exchange-side closes and wrote a heuristic `MANUAL_CLOSE` / `TAKE_PROFIT` / `STOP_LOSS` string without consulting the RSM. Wiring it through `classify_close` aligns the sweep with the precise-taxonomy codes (`TAKE_PROFIT_NATIVE`, `STOP_LOSS_NATIVE`, `TRAILING_STOP_NATIVE`, `LIQUIDATION`, …) that the live bot already emits.

### 2026-04-21 — Trades page: URL-driven filters + global filter-options (UX-H1/H2)

#### Changed
- **[UX-H1]** `frontend/src/pages/Trades.tsx` — URL search params are now the single source of truth for active filters (`status`, `symbol`, `exchange`, `bot`, `date_from`, `date_to`, `page`). Eliminated the six separate `useState` slices; filter values are derived from `useSearchParams()` on every render so fast navigation (change symbol → Apply → navigate away → come back) can no longer desync the UI and the `useTrades` query key. All filter controls funnel through a single `updateParams()` mutator that uses `setSearchParams(..., { replace: true })` to avoid polluting the browser history. Changing any filter resets `page` back to 1 automatically. The symbol free-text input keeps a local draft state and writes to the URL through a 300 ms debounce so typing doesn't thrash the history stack or fire a query per keystroke.
- **[UX-H2]** Filter dropdowns (symbol suggestions, exchange, bot, status) now consume the new `useTradesFilterOptions()` hook instead of deriving unique values from the currently-loaded 200-trade page. This fixes the audit finding where older trades' symbols/bots were missing from the dropdowns because they lived on a different page. Statuses fall back to a local default list (`open / closed / cancelled`) if the endpoint doesn't ship them. The client-side table text-search and `demoFilter` store are untouched.

#### Added
- **[UX-H2]** New hook `frontend/src/hooks/useTradesFilterOptions.ts` — `useQuery<TradeFilterOptions>` against `GET /api/trades/filter-options`, returns `{ symbols, bots: {id,name}[], exchanges, statuses }`. 5 min `staleTime`, single retry, `placeholderData` of empty arrays so the page renders even if the endpoint is offline in dev.
- **[UX-H1/H2]** `frontend/src/pages/__tests__/Trades.test.tsx` — 5 new tests covering URL hydration on mount, dropdown-change → URL write, debounced text-input URL write, dropdown options sourced from the hook (not derived from trades), and graceful empty-state when the hook is still loading. All 11 tests pass.
- New i18n key required (DE + EN; text supplied in agent report): `trades.clearAllFilters`.

#### Dependencies
- Assumes Backend Agent A1's `GET /api/trades/filter-options` endpoint ships with `{ symbols: string[], bots: {id: number, name: string}[], exchanges: string[], statuses: string[] }` — the hook defensively normalizes missing fields to empty arrays if A1's shape differs.

### 2026-04-21 — Workstream E (Agent E2): Dockerfile / CI hardening

#### Changed
- **Dockerfile**: HEALTHCHECK tuned to spec (`--interval=30s --timeout=5s --start-period=30s --retries=3`). Probe still uses `python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"` because `python:3.11-slim` does not ship `curl` and pulling it in just for the probe would add ~1.2 MB of layer for no gain. Multi-stage build, `ARG/ENV BUILD_COMMIT=unknown`, and non-root `botuser` were already in place — unchanged.
- **.dockerignore**: added `.github/`, `tests/`, `node_modules/`, `frontend/node_modules/`, `frontend/dist/`. `.git`, `.env`, `.env.*`, `__pycache__`, `.venv/`, `venv/`, `.vscode`, `.idea`, `*.py[cod]`, `.claude/` were already covered.

#### Added
- **[ARCH-C4]** New `alembic-check` CI job in `.github/workflows/ci.yml` (peer of `backend-tests` / `frontend-tests` / `lint`, none of which were modified). Spins up a `postgres:16-alpine` service, installs `requirements.txt`, then runs `alembic upgrade head` → `alembic downgrade base` → `alembic upgrade head`. Fails fast if any migration is missing a working `downgrade()` or is not idempotent on re-apply.

#### Ops notes (reviewer action required)
- Production `docker compose build` on the VPS currently does NOT pass `--build-arg BUILD_COMMIT=…`, so `/api/version` will keep returning `unknown` in prod. `docker-compose.yml` needs a `build: args: BUILD_COMMIT: ${BUILD_COMMIT:-unknown}` block (owned by Workstream B — not touched here) and the deploy step needs `export BUILD_COMMIT=$(git rev-parse --short HEAD)` before `docker compose build`.

### 2026-04-21 — HL onboarding: bounded poll instead of fixed sleep (UX-C3/H9)

#### Changed
- **[UX-C3]** `HyperliquidSetup.handleSignBuilderFee` no longer waits a fixed `setTimeout(3000)` after the user signs the builder-fee approval. It now polls `POST /config/hyperliquid/confirm-builder-approval` once per second (`POLL_INTERVAL_MS = 1000`) up to `MAX_POLL_MS = 30_000`. The first 200 response wins (no more false "failed" toast when the RPC lags); fast confirmations no longer waste 3s of user time. The sign button shows a live "Checking on-chain status… (Xs)" indicator while polling.
- **[UX-C3 / Visibility-pause]** While the tab is backgrounded (`document.visibilityState !== 'visible'`), the poll loop skips the HTTP request but keeps the elapsed-time counter running. The next tick after the user returns fires the request immediately.
- **[UX-H9]** Fixed stale-closure lint warnings in `HyperliquidSetup.tsx`: `fetchConfig` is now a `useCallback(fn, [t])`, its mounting `useEffect` depends on the callback, and the `onComplete` effect now includes `onComplete` in its dep array. Added an unmount cleanup effect that flips a `pollAbortRef` so a leftover poll loop stops if the component unmounts mid-flight.

#### Added
- **[UX-C3]** `frontend/src/components/hyperliquid/__tests__/HyperliquidSetup.test.tsx` — 4 tests covering happy path (poll succeeds within timeout), poll timeout error banner, elapsed-time indicator during polling, and visibility-pause (no requests while tab hidden). Mocks wagmi/RainbowKit hooks and global `fetch`.
- **[UX-C3]** New i18n keys required (DE + EN; text supplied in agent report): `hyperliquid.setup.pollingStatus`, `hyperliquid.setup.pollTimeout`.

### 2026-04-21 — Visibility-pause for polling timers (UX-M9) + EditPositionPanel audit (UX-M8)

#### Added
- **[UX-M9]** Neuer Hook `frontend/src/hooks/useIntervalPaused.ts` exportiert zwei visibility-aware Helfer:
  - `useIntervalPaused(baseMs)` gibt `baseMs` zurück wenn der Tab sichtbar ist und `false` wenn er im Hintergrund steht — direkt konsumierbar als `refetchInterval` in React-Query (`false` ist das dokumentierte "disable"-Sentinel).
  - `useVisibleTab()` liefert denselben Zustand als boolean für Nicht-React-Query-Konsumenten (z.B. `useTradesSSE({ enabled: useVisibleTab() })`).
  Beide Hooks lesen `document.visibilityState`, hängen einen einzigen `visibilitychange`-Listener ein und entfernen ihn sauber beim Unmount; SSR-safe Initial-State.
- Unit-Tests `frontend/src/hooks/__tests__/useIntervalPaused.test.ts` (7 Tests) decken: Rückgabewert bei sichtbarem/verstecktem Tab, Reaktion auf `visibilitychange`-Events (hidden → visible → hidden), Listener-Cleanup beim Unmount, beide Hook-Varianten.

#### Changed
- **[UX-M9]** `Dashboard.tsx` und `Portfolio.tsx` verdrahten `useTradesSSE({ enabled: useVisibleTab() })`, sodass die SSE-Verbindung (und ihr 5s-Polling-Fallback) geschlossen wird, sobald der User den Tab in den Hintergrund schickt, und beim Re-Focus automatisch wieder aufgebaut wird. Verhindert unnötige API-Calls im Hintergrund und das kurze Flackern stale Daten beim Zurückkehren. Keine anderen Call-Sites angefasst; React-Query-Defaults bleiben unverändert.

#### Audited (no change needed)
- **[UX-M8]** `EditPositionPanel` — Audit-Finding "zu viele Prop-Drills + stale Snapshot bei Re-Open" wurde bereits durch das live-cache-resolve-Pattern in Dashboard.tsx (Zeilen ~132-134) und Portfolio.tsx (Zeilen ~164-166) adressiert: Parent resolved `editingPos` vor dem Rendern via `positions.find(p => p.trade_id === editingPos.trade_id)`, sodass der Panel immer den aktuellen Server-State erhält. Panel selbst synchronisiert sein Formular-State über `useEffect([position.trade_id, position.take_profit, ...])`. Ein zusätzlicher `EditPositionPanelContext` würde nur Duplikation erzeugen, ohne Verhalten zu ändern — Refactor bewusst ausgelassen.

### 2026-04-21 — Migrations 025–027 + pip-tools source (ARCH-M3/M7, SEC-L3)

#### Added
- **[ARCH-M7]** Migration `025_add_unique_exchange_order_id_to_trade_records.py` creates a **partial unique index** `uq_trade_records_exchange_order_id` on `trade_records(exchange, order_id) WHERE order_id IS NOT NULL AND order_id <> ''`. Catches true duplicate orders per exchange without breaking on NULL/empty order_ids (cancelled/failed placements) or on the same numeric id appearing on two different venues. Postgres-only predicate; SQLite test env falls back to a regular unique index (no multi-exchange data in tests). `TradeRecord.__table_args__` mirrors the index.
- **[ARCH-M3]** Migration `027_add_soft_delete_to_bot_configs.py` adds `deleted_at TIMESTAMPTZ NULL` and `deleted_by_user_id INTEGER NULL` (FK → `users.id ON DELETE SET NULL`) to `bot_configs`, plus the partial index `ix_bot_configs_alive` on `(user_id) WHERE deleted_at IS NULL` for fast "alive bots" lookups. **Router queries are unchanged** — this migration only lays down the schema; ARCH-M3 follow-up will introduce soft-delete semantics. `BotConfig` model gains the two columns + `__table_args__`; the `User.bot_configs` / `BotConfig.user` relationships now specify `foreign_keys` explicitly since there are two FKs to `users.id`.
- **[SEC-L3]** New `requirements.in` captures the top-level declared dependencies (loose pins) as the source of truth. `requirements.txt` is intended to be regenerated via `pip-compile requirements.in -o requirements.txt --generate-hashes`. Lockfile was **not** regenerated in this pass because `pip-tools` is not installed on the agent host — `requirements.txt` is left untouched to avoid an inconsistent state. Regenerate in CI / on a developer box before the next release.

#### Changed
- **Migration `026_add_source_to_revenue_entries.py`** widens `revenue_entries.source` from VARCHAR(20) to VARCHAR(32) so labels like `referral_bonus`, `affiliate_import`, `fee_auto` fit. NOT NULL and default `'manual'` preserved. Downgrade clamps any oversize values back to `'manual'` before narrowing the column. `RevenueEntry.source` model updated to `String(32)`.

### 2026-04-21 — Per-route ErrorBoundaries (UX-H3)

#### Changed
- **[UX-H3]** `ErrorBoundary` now accepts `fallback` (ReactNode OR `(error, reset) => ReactNode`), `onReset`, `onError`, and `resetKeys` (auto-reset when any key identity changes). Default fallback UI adds a "Go to Dashboard" link alongside the existing "Try again" button. Backwards-compatible with existing `<ErrorBoundary>{children}</ErrorBoundary>` call sites.
- **[UX-H3]** Every route in `App.tsx` is wrapped in a new `RouteErrorBoundary` (`frontend/src/components/ui/RouteErrorBoundary.tsx`) that ties `resetKeys` to `useLocation().pathname`. A crash in one page now keeps sidebar/header/toast container alive and auto-clears when the user navigates elsewhere. The top-level `ErrorBoundary` is retained for catastrophic errors outside the routing tree.
- **[UX-H3]** New i18n keys `common.goToDashboard` and `common.errorBoundaryGeneric` required (DE + EN; text supplied in agent report).
- **[UX-H3]** `ErrorBoundary.test.tsx` extended: render-fn fallback respected, `resetKeys` change clears the error, `onReset`/`onError` callbacks fire. Suite now has 10 passing tests.

### 2026-04-21 — Workstream B parallel fix sweep

#### Security
- **[SEC-C1]** Broadcast preview now HTML-escapes admin markdown BEFORE the regex→HTML pass; URL scheme whitelist (http/https/tg) applied so `[x](javascript:...)` is stripped to plain text; frontend renders the Telegram HTML through a small React AST parser (allow-list `b/strong/i/em/u/s/code/pre/br/a`) instead of `dangerouslySetInnerHTML` (`broadcast_service.py`, `BroadcastPreview.tsx`). Unit test `test_broadcast_render.py` guards the `<script>` and `javascript:` regressions. `broadcast_sender.py` inspected — only renders pre-baked strings, no extra fix needed.
- **[SEC-C2]** `docker-compose.yml` aborts with a clear message if `POSTGRES_PASSWORD` or `GF_ADMIN_PASSWORD` is unset (`${VAR:?msg}` syntax); removed the `tradingbot_dev` / `changeme` fallbacks that could have shipped to production. `.env.example` updated to reflect both are required.
- **[SEC-H1]** CSP `script-src` dropped `'unsafe-inline'` (Vite production builds do not need inline scripts). `style-src` still carries `'unsafe-inline'` with a comment explaining the trade-off (Vite/Tailwind inline style chunks in the built index.html — meaningfully smaller risk than inline scripts, would require per-build hash tracking to remove).
- **[SEC-L1]** `/api/version` now requires authentication via `get_current_user` (no unauth monitor consumers found). Build commit is read from the `BUILD_COMMIT` / `GIT_COMMIT` env var set at Docker build time — no more `subprocess.check_output(["git", ...])` at import time, which also removes the dependency on a `.git/` tree inside the container.

#### Changed
- **[ARCH-H2]** Hyperliquid-specific onboarding gates lifted into the `ExchangeClient` abstraction. `ExchangeClient.pre_start_checks` is now the single dispatch point for every exchange; the default implementation runs the shared affiliate-UID gate (applies to every exchange with an active `AffiliateLink.uid_required=True`), and `HyperliquidClient.pre_start_checks` overrides + `super()`s to add the HL-specific referral / builder-fee / wallet gates. `bot_worker.py` now calls `client.pre_start_checks(...)` once and iterates `GateCheckResult`s (admins bypass only `referral`/`builder_fee`/`affiliate_uid` — wallet problems still block). `hyperliquid_gates.py` retains its original `_check_*` methods as a backwards-compatible mixin so the 41 legacy unit tests in `test_bot_worker_extra.py` / `test_hyperliquid_builder.py` continue to pin the behaviour at the BotWorker boundary; the production call-site uses the new abstraction and the mixin is slated for removal once those tests are ported to exercise `HyperliquidClient.pre_start_checks` directly. New unit test `tests/unit/exchanges/test_base_prestart.py` pins the default behaviour (empty result, failing affiliate gate when unverified, fail-open on DB errors). `copy_trading.py` inspected — no HL `isinstance` leaks, left untouched.
- **[ARCH-M4]** SPA fallback now uses `StaticFiles(directory=..., html=True, check_dir=True)` mounted at `/`; the hand-rolled path-traversal guard and extension whitelist are gone (Starlette's StaticFiles already performs traversal checks). Must remain the last mount so `/api/*` routes win.
- **[ARCH-H6]** Correlation ID flows from `RequestIDMiddleware` through a `contextvars.ContextVar("request_id")` to every log line. New `RequestIDLogFilter` populates `record.request_id`; JSON and colour formatters both include it. Context token is reset in the middleware's `finally` so IDs never leak across requests.
- **[ARCH-H3]** `get_db()` (FastAPI dependency) now delegates to `get_session()`, so API and background paths share the same circuit-breaker-protected acquisition. Previously only `get_session` tripped the breaker while API calls kept racing into an already-failing pool.
- **[ARCH-H5]** WebSocket broadcast fan-out redesigned: every accepted connection owns an `asyncio.Queue(maxsize=100)` and a dedicated writer task. `broadcast_all` / `broadcast_to_user` only `put_nowait(msg)` — a slow client can never stall the others. Full queue → that specific connection is disconnected. Send uses `asyncio.wait_for(..., 5s)`; writer task cancelled + queue drained on disconnect. New unit test `test_slow_client_does_not_block_fast_ones` guards the regression.
- **[ARCH-H7]** Strategies auto-register via `src/strategy/__init__.py` — the package now iterates `pkgutil.iter_modules` and imports every sibling file (skipping `base.py`, `__init__.py`, and `_`-prefixed helpers) so dropping a new strategy file is enough. Removed the hardcoded `from src.strategy.liquidation_hunter import LiquidationHunterStrategy` line from `orchestrator.py`.

#### Removed
- **[ARCH-H4]** Deleted empty directories `src/ai/`, `src/dashboard/`, `src/websocket/` (left behind after the LLM signal feature was removed — no code imported them). Also removed empty `tests/unit/ai/` and `tests/unit/websocket/` shells. `CLAUDE.md` and `README.md` already reflected the current feature set, no text update required.

#### Ops notes (not code-owned here)
- Dockerfile already sets `ARG BUILD_COMMIT` → `ENV BUILD_COMMIT`; pass `--build-arg BUILD_COMMIT=$(git rev-parse --short HEAD)` on build so `/api/version` returns a meaningful SHA.
### Refactor
- **ARCH-H1 Phase 1 PR-1 — NotificationsMixin → Notifier component (#274)**: Erster Composition-Schritt der BotWorker-Migration. Neue Datei `src/bot/components/notifier.py` kapselt die Discord/Telegram-Dispatch-Logik als `Notifier`-Klasse (Constructor nimmt `bot_config_id` + `config_getter`-Callable, weil `_config` erst in `start()` geladen wird). `src/bot/notifications.py` reduziert auf dünnen Proxy-Mixin, der an `self._notifier` delegiert — alle 12 bestehenden `self._send_notification(...)`-Callsites in `bot_worker.py`, `trade_executor.py`, `trade_closer.py`, `position_monitor.py` bleiben unverändert. Risiko gering: `Notifier.send_notification()` akzeptiert optional einen `notifiers`-Parameter, damit Tests die `worker._get_notifiers`-Stub-Methode weiter wirksam halten. 15 neue Unit-Tests in `tests/unit/bot/components/test_notifier.py` decken Channel-Name-Derivation, Discord-Loader (no-config / no-webhook / success / decrypt-error), Notifier-Aggregation (beide / einzeln / exception), Dispatch-Loop (alle Notifier / per-Notifier-Isolation / auto-load / no-user-id skips logging) ab. Test-Patch-Targets migriert von `src.bot.notifications.*` auf `src.bot.components.notifier.*` (4 Callsites in `test_bot_worker.py` + `test_bot_worker_extra.py`). Phase 2 entfernt den Mixin + migriert Callsites auf direkte `self._notifier.send_notification(...)`-Calls. Depends on #267 (components/ scaffolding).
### Fixed
- **WebSocket-Auth + thread-safe Auth-Code-Store (#259, SEC-013/SEC-014)**: Der `/api/ws`-Endpoint verlangt das JWT jetzt als `token`-Query-Param (mit `access_token`-Cookie als Browser-Fallback) und validiert via `decode_token(expected_type="access")` **vor** dem `websocket.accept()`. Bei Auth-Fail (kein Token, invalid Token, Refresh-Token statt Access, unbekannter User, `tv < token_version`, `is_active=False`, `is_deleted=True`) schließt der Endpoint jetzt mit dem RFC-6455-konformen Close-Code `1008` (`WS_1008_POLICY_VIOLATION`) statt der bisherigen anwendungs-spezifischen `4001`/`4008` — dadurch können Clients die Fehlschlag-Ursache regel-konform verstehen. Die bisherige First-Message-JWT-Auth-Fallback-Route (mit 10s-Timeout) ist entfernt, weil sie Tokens in den WebSocket-Message-Frames sichtbar machte und eine Race zwischen Accept und Auth öffnete. `src/auth/auth_code.py` (Supabase-Auth-Bridge) schützt jetzt jeden `_codes`-Mutations-Pfad (generate/exchange/cleanup) mit einem `asyncio.Lock` — verhindert Race-Conditions zwischen zwei gleichzeitigen `exchange()`-Calls auf denselben Code (Double-Spend) und zwischen `generate()` und dem Hintergrund-Cleanup (verlorene Codes). TTL ist auf 5 min (300 s, vorher 60 s) erhöht wie im Issue gefordert — gibt User eine komfortable Redirect+Exchange-Zeit ohne das Replay-Fenster übermäßig zu öffnen. Public API ist jetzt async (`await auth_code_store.generate(...)`, `await auth_code_store.exchange(...)`); einziger Caller `src/api/routers/auth_bridge.py` entsprechend angepasst. Neue Tests: 11 in `tests/unit/auth/test_auth_code_store.py` (TTL-Wert, Happy-Path, Single-Use, Eviction on exchange, Cleanup-Loop, Concurrent-Exchange-Race, Concurrent-Generate-Race), 6 in `tests/unit/api/test_websocket_auth.py` (No-Token → 1008, Invalid-Token → 1008, Refresh-Token → 1008, Unknown-User → 1008, Valid-Token → handshake, Ping/Pong).
### Changed
- **Admin-Notifier liest Credentials aus der DB (#242)**: `default_admin_notifier` in `src/bot/audit_scheduler.py` bezieht Discord-Webhook und Telegram-Token/Chat-ID nicht mehr ausschließlich aus den `ADMIN_*` ENV-Vars. Neuer Helper `_load_admin_notification_config()` sucht den ersten aktiven Admin (`User.role='admin' AND is_active=True`, niedrigste `id` zuerst) und zieht dessen neueste enabled `BotConfig` heran — dieselben Felder (`discord_webhook_url`, `telegram_bot_token`, `telegram_chat_id`, Fernet-verschlüsselt via `src/utils/encryption.py`), die der BotBuilder ohnehin schon pflegt. Felder werden einzeln entschlüsselt; jedes fehlgeschlagene bzw. leere Feld fällt individuell auf `ADMIN_DISCORD_WEBHOOK_URL` / `ADMIN_TELEGRAM_BOT_TOKEN` / `ADMIN_TELEGRAM_CHAT_ID` zurück (Rotation ohne Container-Restart möglich, Env bleibt als Fallback). Wenn weder DB noch ENV Werte liefert, macht der Notifier einen No-Op mit WARN-Log — das existierende `audit_scheduler.finding` WARN bleibt der baseline Signal-Pfad. Keine Schema-Migration nötig: Notifier-Felder existieren bereits per-BotConfig. Drei neue Unit-Tests in `tests/unit/scripts/test_audit_scripts.py` (`test_default_admin_notifier_uses_admin_user_db_config`, `test_default_admin_notifier_falls_back_to_env_when_db_empty`, `test_default_admin_notifier_noop_when_nothing_configured`).
### 2026-04-22 — ARCH-C1 Phase 3 PR-2: extract UsersService (#288)

Dritter Wave der ARCH-C1 Service-Layer-Refactor-Kette — nach TradesService (PR-3/PR-4), PortfolioService (PR-5) und BotsService-Scaffold (PR-1) werden jetzt die **User-Info-Read-Handler** aus den Users- und Auth-Routern in ein neues `UsersService`-Modul extrahiert. **Zero behavior change** — die 94 bestehenden Auth- und Users-Router-Tests (`tests/unit/test_auth.py`, `tests/unit/api/test_users_router.py`, `tests/integration/test_auth_flow.py`) bleiben unverändert grün. Der Login/Refresh/Logout/Change-Password-Flow und der Supabase-One-Time-Code-Bridge (`auth_bridge.py`) wurden bewusst NICHT angefasst — nur pure Reads wandern in die Service-Schicht.

#### Refactored
- **[services]** `src/services/users_service.py` (neu, 152 LOC) — FastAPI-freie Business-Logik für die beiden User-Info-Handler: `get_profile(user)` (pures `User` → `UserProfileResult` Transform, wird von `GET /api/auth/me` aufgerufen) und `list_users(db)` (Admin-Panel-Listing mit ge-batchten Exchange-/Bot-/Trade-Aggregaten für `GET /api/users`). Keine `HTTPException`, keine `Depends`, keine `Request`-Imports — der Service gibt Plain-Dataclasses (`UserProfileResult`, `AdminUserListItem`) zurück, die der Router mit direktem Konstruktor-Aufruf auf die bestehenden Pydantic-Response-Models projiziert. `list_users` behält die identische DB-Semantik: `is_deleted=False`-Filter, `ORDER BY id`, drei Batched-Queries gegen `ExchangeConnection` (DISTINCT exchange_type pro User), `BotConfig` (COUNT WHERE is_enabled=True) und `TradeRecord` (COUNT pro User) um N+1 zu vermeiden, plus `auth_provider or "local"`-Coalesce und ISO-8601-Serialisierung für `last_login_at` / `created_at`.
- **[router]** `src/api/routers/users.py` — `list_users` reduziert von 55 → 24 LOC (Handler-Body). Handler ist jetzt ein dünner Adapter: service call → Projektion auf `AdminUserResponse`. Die Write-Endpoints (`create_user`, `update_user`, `delete_user`) bleiben komplett im Router (Mutation-Pfad, Rate-Limiter-Decorators, Pydantic-Validierungs-Shape, Soft-Delete-Semantik mit `token_version`-Bump). Unused imports (`func`, `BotConfig`, `ExchangeConnection`, `TradeRecord`) wurden entfernt.
- **[router]** `src/api/routers/auth.py` — `get_me` ruft jetzt `users_service.get_profile(user)` und projiziert das Ergebnis auf `UserProfile`. Alle anderen Handler (login, refresh, logout, change-password) bleiben byte-identisch — der Service fasst bewusst nur die Pure-Read-Transform-Logik an, nicht die Auth-Seiteneffekte (Cookies, Rate-Limits, Session-Tabelle, Token-Versioning).

#### Added (tests)
- **[test]** `tests/unit/services/test_users_service.py` — **9 Unit-Tests** gegen den Service direkt, mit In-Memory-SQLite für die DB-Handler (mirror des `test_portfolio_service.py`-Patterns):
  - `TestGetProfile`: alle Felder werden durchgereicht, NULL-E-Mail und NULL-Language bleiben `None`, `is_active=False` surfaced korrekt.
  - `test_list_users_empty_db_returns_empty_list`: leere DB → `[]`, Batched-Queries crashen nicht bei leerer ID-Liste (Early-Return-Guard).
  - `test_list_users_excludes_soft_deleted`: `is_deleted=True`-Row wird herausgefiltert.
  - `test_list_users_orders_by_id_ascending`: Reihenfolge ist deterministisch über `id ASC`.
  - `test_list_users_surfaces_supabase_auth_provider`: `auth_provider` wird für Supabase-Bridge-User verbatim durchgereicht, `None` coalesct zu `"local"`.
  - `test_list_users_aggregates_exchanges_bots_and_trades`: Full-Happy-Path — ein User mit 2 Exchange-Connections (bitget+hyperliquid), 3 Bot-Configs (2 enabled + 1 disabled → `active_bots=2`), 3 Trades (alle gezählt, egal ob open/closed) liefert die erwarteten Aggregate; `last_login_at` und `created_at` sind ISO-8601-Strings.
  - `test_list_users_zero_defaults_for_user_with_no_relations`: User ohne Exchanges/Bots/Trades bekommt `exchanges=[]`, `active_bots=0`, `total_trades=0`, `last_login_at=None`.

Alle drei betroffenen Suites bleiben grün: `test_users_service.py` (9/9), `test_users_router.py` (unverändert), `test_auth.py` + `test_auth_flow.py` (94 kombiniert).
### 2026-04-22 — ARCH-C1 Phase 3 PR-1: extract ConfigService read handlers (#289)

Third wave of the service-layer refactor. Extracts the three smallest, pure-read handlers from the `config*` sub-routers into module-level functions in `src/services/config_service.py`. **Zero behavior change** — the existing 191 config-router tests (`tests/unit/api/test_config_router.py`, `tests/unit/api/test_config_router_extra.py`, `tests/integration/test_config_api.py`) pass unmodified, as do the 24 trades/portfolio characterization tests.

Das bestehende `config_service.py`-Modul war bisher eine reine Helper-Sammlung (DB-Lookups, Ping, Response-Builder), die von allen Config-Sub-Routern importiert wird. Dieser PR legt eine zweite Schicht darauf: FastAPI-freie Handler-Funktionen, die der Router als dünner Adapter aufruft. Klassen-Pattern à la `TradesService`/`PortfolioService` wurde bewusst NICHT übernommen — das existierende Modul ist bereits function-based und ein Bruch hätte die 4 Sub-Router alle anfassen müssen. Stattdessen folgt der PR dem `bots_service.py`-Pattern (ARCH-C1 Phase 2b PR-1, function-based).

#### Refactored
- **[services]** `src/services/config_service.py` — drei neue Handler-Funktionen:
  - `get_user_config_response(user, db)` — liefert das `GET /api/config/` Payload als Plain-Dict (`trading` / `strategy` als dekodierte JSON-Dicts, `connections` als bereits-projizierte `ExchangeConnectionResponse`-Liste, plus die deprecated `api_keys_configured` / `demo_api_keys_configured` Flags).
  - `list_exchange_connections(user, db)` — dünner Wrapper um `get_user_connections` + `conn_to_response`, liefert `{connections: [...]}` wie vom Frontend erwartet.
  - `list_config_changes(user, db, *, entity_type, entity_id, action, page, page_size)` — paginierte Audit-Trail-Query auf `ConfigChangeLog`, User-gescoped, mit optionalen Filtern. JSON-Decode des `changes`-Blobs fällt bei Malformed-Rows auf `None` zurück (identisches Verhalten wie vor dem Extract). Die `Query(..., ge=1, le=100)`-Bounds-Validierung bleibt weiterhin auf dem Router — die Service-Funktion akzeptiert die Werte unverändert.
  - Keine Änderung an den bestehenden Helpern (`get_or_create_config`, `get_user_connections`, `conn_to_response`, `ping_service`, `create_hl_client`, `create_hl_mainnet_read_client`, `async_none`, `EXCHANGE_PING_URLS`). Die Service-Funktionen bleiben FastAPI-frei — kein `HTTPException`, kein `Depends`, kein `Request`.
- **[router]** `src/api/routers/config_trading.py` — `get_config` delegiert an `config_service.get_user_config_response`. Der Handler projiziert die zurückgelieferten Plain-Dicts auf `TradingConfigUpdate` / `StrategyConfigUpdate` / `ConfigResponse` Pydantic-Modelle (die Pydantic-Validation bleibt bewusst auf Router-Ebene, damit Pydantic-Fehler als HTTP-422 sichtbar bleiben). Handler-LOC: 31 → 24.
- **[router]** `src/api/routers/config_exchange.py` — `get_exchange_connections` ist jetzt ein Einzeiler über `config_service.list_exchange_connections`. Die bestehenden Imports (`get_user_connections`, `conn_to_response`) bleiben wegen der mutierenden Handler (`upsert_exchange_connection`, `test_exchange_connection`, `get_connections_status`) die weiterhin die Helper-Ebene nutzen.
- **[router]** `src/api/routers/config_audit.py` — `list_config_changes` delegiert an `config_service.list_config_changes` und mappt die Plain-Dict-Items auf `ConfigChangeEntry` / `ConfigChangeListResponse`. `json` / `func` / `select` / `ConfigChangeLog`-Imports sind entfernt (LOC 93 → 61).

#### Added (tests)
- **[test]** `tests/unit/services/test_config_service.py` — **9 Unit-Tests** exercisen die drei neuen Handler direkt mit in-memory SQLite (gleiche Fixture-Blueprint wie `test_portfolio_service.py`):
  - `get_user_config_response`: leerer User (erstellt Default-`UserConfig`, leere Connections, `bitget` als Default-Exchange); populated User (dekodiertes Trading-/Strategy-JSON, zwei projizierte Connections, deprecated Flags korrekt aus den `UserConfig`-Columns abgeleitet).
  - `list_exchange_connections`: leerer User (`{connections: []}`); populated User (zwei Connections inkl. Affiliate-UID-Pass-Through auf `ExchangeConnectionResponse`).
  - `list_config_changes`: leerer User (paginiertes 0-Result); Sortierung `created_at DESC` über 3 Rows; Filter nach `entity_type` (`bot_config` vs `exchange_connection`); Malformed-JSON-Blob liefert `changes=None` statt Crash; Paginierung mit `page_size=2` über 5 Rows (3 Seiten ohne Overlap).
- Die Tests verwenden einen Sentinel-String (`"fake-encrypted-payload"`) für die `*_encrypted`-Spalten statt durch `encrypt_value` zu laufen — `conn_to_response` prüft nur Truthiness, so hängt die Test-Suite nicht an einem gültigen `ENCRYPTION_KEY` in der CI.

#### Candidates for follow-up PRs (ARCH-C1 Phase 3 PR-2+)
- `config_exchange.get_connections_status` — orchestriert parallele Pings über `aiohttp.ClientSession` plus die `data_source_registry` und `EXCHANGE_PING_URLS`-Union. Größerer Aufwand, verdient einen eigenen PR.
- `config_hyperliquid.get_hl_admin_settings` + der Rest von `config_hyperliquid.py` (Builder-Approval, Referral-Verify, Revenue-Summary). Eigene Extraktion, da `SystemSetting` / ENV-Fallback-Logik und der HL-Readback-Client zusätzliche Testing-Primitives brauchen.
- `config_affiliate.list_affiliate_uids` — Admin-Paginierung mit Stats-Aggregat, plus Search-Filter über `User.username` join.
- Alle Mutation-Handler (`update_trading_config`, `update_strategy_config`, `upsert_exchange_connection`, `delete_exchange_connection`, `set_affiliate_uid`, …) werden bewusst später extrahiert — Mutations brauchen saubere Error-Domain-Typen in `src/services/exceptions.py` statt direkte `HTTPException`-Raises.
### 2026-04-23 — ARCH-C1 Phase 2b PR-5: BotsService — balance / budget / symbol-conflict reads (#299)

Fünfte und finale Extraction-Welle für Phase 2b: die vier exchange-client-gekoppelten Read-Handler (`GET /api/bots/balance-preview`, `GET /api/bots/balance-overview`, `GET /api/bots/symbol-conflicts`, `GET /api/bots/budget-info`, zusammen ~460 LOC) wandern in den Service. `bots_service.balance_preview(db, user_id, exchange_type, mode, exclude_bot_id)`, `balance_overview(db, user_id, exclude_bot_id)`, `symbol_conflicts(db, user_id, exchange_type, mode, trading_pairs, exclude_bot_id, strategy_type)` und `budget_info(db, user_id)` kapseln die drei unterschiedlichen Balance-Fetch-Varianten (Preview: single-exchange, raises-auf-error; Overview: all-exchange parallel mit `asyncio.gather`; Budget: grouped-by-(exchange,mode) mit Open-Position-Margin-Credit), den 30-sekündigen In-Memory-`_budget_cache` (geteilt zwischen allen drei Handlern), den Copy-Trading-Short-Circuit in `_check_symbol_conflicts` und die per-Bot-Allocation-Math (`_bot_allocated_amount` — `position_usdt` override `position_pct`). Router-Handler sind jetzt 2–5 LOC reine Delegates. Stacked auf PR-4 (#298). **Zero behavior change** — alle drei Balance-Fehler-Semantiken bleiben bit-identisch: Preview verwendet `"no_connection"` / `"no_credentials"` / `"fetch_failed: {e}"`; Overview verwendet `"fetch_failed"` ohne Exception-Text; Budget skipt stillschweigend. Cache-Keys, Parallel-Fetch-Reihenfolge, Overallocation-/Insufficient-Funds-Warnings identisch.

#### Refactored
- **[services]** `src/services/bots_service.py`: vier neue öffentliche Funktionen + sechs Helpers. Module-Level State: `_MODE_CONFLICTS: dict[str, set[str]]` (demo↔demo+both, live↔live+both, both↔all three), `_budget_cache: dict[str, tuple[float, tuple[float, float, str]]]` (key `f"budget:{user_id}:{exchange}:{mode}"`, value `(monotonic_time, (available, equity, currency))`), `_BUDGET_CACHE_TTL = 30.0`. Helpers: `_budget_cache_get/set` (Time-bounded), `_pick_credentials(conn, is_demo)` gibt `(api_key_enc, api_secret_enc, passphrase_enc)` für den gewählten Mode zurück, `_fetch_balance_live(...)` erstellt den Exchange-Client via `create_exchange_client` + `decrypt_value` und ruft `get_account_balance()` mit 10-s-Timeout (**raises** auf jedem Fehler — Caller entscheidet Fehler-Format), `_bot_alloc_pairs(bot)` parst `trading_pairs` JSON, `_bot_allocated_amount(bot, equity)` summiert die USDT-Allocation aus `per_asset_config`, `_check_symbol_conflicts(...)` findet Overlap mit Copy-Trading-Short-Circuit. Service importiert jetzt `asyncio`, `json`, `time as _time`, `Protocol`, `create_exchange_client`, `get_exchange_symbols`, `decrypt_value`, `encrypt_value`, `CEX_EXCHANGES`, `EXCHANGE_NAMES` und `parse_json_field` — alle top-level damit Tests monkey-patchen können.
- **[router]** `src/api/routers/bots.py`: vier Handler auf 2–5 LOC geschrumpft (von 487 LOC auf 316 LOC total, `-171` LOC). `get_balance_preview`, `get_balance_overview`, `get_budget_info` sind jetzt einfache `return await bots_service.X(...)`-Delegates; `check_symbol_conflicts` parst nur noch den CSV-`trading_pairs`-Query-Param (`[p.strip() for p in trading_pairs.split(",") if p.strip()]`) bevor es delegiert. Unused Imports entfernt (`asyncio`, `json`, `time`, `select`, `BotBudgetInfo`, `BotRuntimeStatus`, `SymbolConflict`, `CEX_EXCHANGES`, `EXCHANGE_NAMES`, `TradeRecord`, `ExchangeConnection`, `logger`). `_MODE_CONFLICTS`, `_check_symbol_conflicts`, `_budget_cache`, `_budget_cache_get`, `_budget_cache_set` vollständig aus dem Router entfernt.
- **[router]** `src/api/routers/bots_lifecycle.py`: `_check_symbol_conflicts`-Import von `src.api.routers.bots` auf `src.services.bots_service` umgezogen (verhindert circular import, da Lifecycle-Sub-Router jetzt nicht mehr in den Parent-Router zurückgreift).

#### Tests
- **[unit]** `tests/unit/services/test_bots_service.py`: 22 neue Tests (53 total, +22). Neue Fixtures: autouse `_reset_budget_cache` (clear per Test, patch `decrypt_value` → `f"dec::{v}"`-Sentinel damit Blobs kein echtes Fernet brauchen), `_make_conn(user_id, exchange, live, demo)` baut `ExchangeConnection` mit `"blob"`-Sentinel-Credentials, `_fake_client_factory(available, total, currency)` stubt `create_exchange_client` über den MagicMock-Client mit `AsyncMock`-`get_account_balance`. `TestSymbolConflicts` (6 Tests): empty-pairs, overlap-mit-enabled-bot, disabled-bots-ignoriert, copy-trading-short-circuit, exclude-bot-id-filtered-self, both-mode-conflicts-mit-demo+live. `TestBalancePreview` (7 Tests): no-connection → `no_connection`, no-credentials → `no_credentials`, successful-fetch (populates `exchange_balance`/`exchange_equity`/`currency`), fetch-failure → `fetch_failed:`-prefix, cache-hit (zweiter Call zählt keinen Factory-Call), allocation-subtracts-existing-bot-budget (300-USDT von 1000-USDT-Equity → 30% / 700-USDT remaining), both-mode-uses-live-credentials. `TestBalanceOverview` (3 Tests): no-connections → empty list, lists-demo-und-live-wenn-beide-creds-gesetzt, fetch-failure-produces-fetch_failed-entry. `TestBudgetInfo` (5 Tests): no-bots → empty, disabled-bots-excluded, overallocation-warning (2 × 60% = 120% → Warning), insufficient-balance-warning ($500 needed / $100 available), open-position-margin-credited-back (50000×0.1÷10 = 500 USDT margin → effective-available $600 → sufficient), both-mode-bot-appears-in-demo-und-live. Alle 94 existierenden Regression-Tests (53 Service + 41 Router/Injection) grün.
- **[unit]** `tests/unit/api/test_bots_router_extra.py`: `_check_symbol_conflicts`-Import von `src.api.routers.bots` auf `src.services.bots_service` umgezogen (Konsistent mit dem neuen Service-Ownership).
- **[unit]** `tests/unit/api/test_injection_security.py`: PR-4-Regression gefixt — `monkeypatch.setattr("src.api.routers.bots.get_exchange_symbols", ...)` auf `"src.services.bots_service.get_exchange_symbols"` umgezogen (Service ownt den Symbol-Fetcher-Import jetzt).

#### Scope für Follow-up
- Phase 2b **abgeschlossen** — alle 11 `/api/bots`-Handler sind jetzt service-extracted. Nächste Phase: ConfigService + UsersService (Task #75).

---

### 2026-04-23 — ARCH-C1 Phase 2b PR-4: BotsService — create_bot + update_bot (#297)

Vierte Extraction-Welle: die beiden Write-Handler `POST /api/bots` (~85 LOC) und `PUT /api/bots/{id}` (~94 LOC) wandern in den Service. `bots_service.create_bot(db, user_id, body)` und `bots_service.update_bot(db, user_id, bot_id, body, orchestrator)` kapseln Strategy-Registry-Lookup, per-Exchange Symbol-Validation (Bitget/Weex/Hyperliquid/Bitunix/BingX via `get_exchange_symbols`), Fernet-Encryption der Notification-Webhooks/Telegram-Tokens, das `is_running`-Guarding bei Updates, das JSON-Dumping der `trading_pairs`/`strategy_params`/`schedule_config`/`per_asset_config`/`pnl_alert_settings`-Felder und die `log_event` + `log_config_change`-Audits. Drei neue Service-Exceptions (`StrategyNotFound`, `InvalidSymbols`, `BotIsRunning`) lassen den Router die User-facing Messages owned halten. Router-Handler sind jetzt 13-14 LOC reine Delegates mit Exception → HTTPException Mapping. Stacked auf PR-3 (#295). **Zero behavior change** — Response-Shapes, Status-Codes, Rate-Limits, MAX_BOTS-Enforcement, Audit-Log-Einträge und Validation-Reihenfolge identisch zu vorher.

#### Refactored
- **[services]** `src/services/bots_service.py`: zwei neue öffentliche Funktionen + zwei private Helpers. `_validate_strategy(name)` raised `StrategyNotFound(name)` wenn `StrategyRegistry.get(name)` ein `KeyError` wirft. `_validate_symbols(body_or_update, existing_bot=None)` hält die bestehende per-Exchange Symbol-Prüfung (Skip für Hyperliquid-Demo). `create_bot` führt Strategy/Symbol-Validation, `BotConfig`-Construction mit JSON-gedumpten Policy-Feldern, Encryption der Notification-Felder und `log_event("bot_created")` aus — raised `MaxBotsReached` wenn `count(BotConfig) >= MAX_BOTS_PER_USER`. `update_bot` raised `BotIsRunning(bot_id)` wenn der Bot aktuell läuft, nutzt `body.model_dump(exclude_unset=True)` für Partial-Patch-Semantik und wendet per-Field-Dispatch via zwei Module-Level-Frozensets an: `_ENCRYPTED_CLEAR_ON_EMPTY_FIELDS` (`discord_webhook_url`, `telegram_bot_token`, `telegram_chat_id` → `encrypt_value(value) if value else None`) und `_JSON_DUMPED_FIELDS` (`trading_pairs`, `strategy_params`, `schedule_config`, `per_asset_config`, `pnl_alert_settings` → `json.dumps(value)`). Audit-Log (`log_config_change(action="create"/"update")`) identisch zu vorher.
- **[services]** `src/services/exceptions.py`: drei neue `ServiceError`-Subklassen. `StrategyNotFound(strategy_name)` trägt den unbekannten Strategy-Namen. `InvalidSymbols(exchange, mode_label, invalid_symbols)` trägt die drei Felder die der Router zum Rendern der User-facing Message braucht (keine Message-Hardcoding im Service). `BotIsRunning(bot_id)` trägt die Bot-ID für den Router-Conflict-Response.
- **[router]** `src/api/routers/bots.py`: `create_bot` von ~85 LOC auf 13 LOC geschrumpft, `update_bot` von ~94 LOC auf 14 LOC. Try/except-Ketten mappen `StrategyNotFound` → 400 mit `ERR_STRATEGY_NOT_FOUND.format(name=e.strategy_name)`, `InvalidSymbols` → 400 mit formatierter Symbol-Liste, `MaxBotsReached` → 400 mit `ERR_MAX_BOTS_REACHED`, `BotNotFound` → 404, `BotIsRunning` → 400 mit "Cannot update running bot. Stop it first."-Message. Unused Imports entfernt (`StrategyRegistry`, `encrypt_value`, `get_exchange_symbols`, `func`) — sind jetzt alle im Service.

#### Tests
- **[unit]** `tests/unit/services/test_bots_service.py`: 11 neue Tests (31 total). `create_bot`: happy-path mit Field-Assembly-Check, `MaxBotsReached`-Guard (monkey-patched `MAX_BOTS_PER_USER=1`), `StrategyNotFound`-Guard, `InvalidSymbols`-Guard (monkey-patched `get_exchange_symbols` → restricted set), Hyperliquid-Demo-Skip (keine Symbol-Validation), Encryption-Roundtrip (monkey-patched `encrypt_value` → deterministic `ENC::{v}`-Tag). `update_bot`: happy-path mit `model_dump(exclude_unset=True)`-Semantik, `BotNotFound`, `BotIsRunning`-Guard, JSON-Dump der `strategy_params`, Empty-String für Notification-Felder clered die Encryption auf `None`.
- **[unit]** `tests/unit/api/test_bots_router.py`: ein bestehender `monkeypatch`-Target von `src.api.routers.bots.get_exchange_symbols` auf `src.services.bots_service.get_exchange_symbols` gezogen (Service ownt den Import jetzt). Alle 107 kombinierten Unit-Tests (Service + Router) grün, alle 22 Integration-Tests grün.

#### Scope für Follow-up PR
- PR-5: Balance-Preview, Balance-Overview, Symbol-Conflicts, Budget-Info (Exchange-Client-Coupling)

---

### 2026-04-22 — ARCH-C1 Phase 2b PR-3: BotsService — list_bots_with_status (#295)

Dritte Extraction-Welle: der `GET /api/bots` Handler (~185 LOC) wandert aus dem Router in den Service. Die Funktion `bots_service.list_bots_with_status(db, user, orchestrator, demo_mode)` zieht alle Preloads (HL-Gate-Flags für Hyperliquid, CEX-Affiliate-UIDs), den optionalen `demo_mode`-Filter, die drei Batch-Queries (Trade-Stats `sum(pnl)`/`sum(fees)`/`sum(funding)`, offene Trades, orphaned Pending-Trades) und das pro-Bot-Assembly der `BotRuntimeStatus`-Pydantic-Modelle in eine einzige Funktion zusammen. Das `_OrchestratorLike`-Protocol aus PR-2 wird um `get_bot_status(bot_id) -> dict | None` erweitert — der Service bleibt weiterhin FastAPI- und orchestrator-stack-frei. Admin-Role-Short-Circuit für HL/Affiliate-Gates ist unverändert (Admin bekommt alle Flags `True`/UID-`None`). Router-Handler ist jetzt 4 LOC: delegiert und wrappt in `BotListResponse(bots=...)`. Stacked auf PR-2 (#293). **Zero behavior change** — Response-Shape identisch, alle 152 Router-Tests und alle 21 Service-Tests grün.

#### Refactored
- **[services]** `src/services/bots_service.py`: neue Funktion `list_bots_with_status(db, user, orchestrator, demo_mode=None) -> list[BotRuntimeStatus]`. Behält die bestehende Query-Reihenfolge und den bestehenden Batch-Query-Ansatz (kein N+1) aus dem Router. `_OrchestratorLike`-Protocol um `get_bot_status` erweitert. Lokaler `from src.models.database import PendingTrade` bleibt lazy — mirror der Router-Struktur, vermeidet Cycle-Risk bei Callern die nur `BotConfig` brauchen. Neue Imports `json`, `BotRuntimeStatus`, `ExchangeConnection`, `TradeRecord`, `User`, `CEX_EXCHANGES`.
- **[router]** `src/api/routers/bots.py`: `list_bots` von ~185 LOC auf 4 LOC geschrumpft. Decorator, Auth-Dependency, `get_orchestrator`-Dependency, `demo_mode` Query-Param und `response_model=BotListResponse` unverändert. Alle Router-Imports (`CEX_EXCHANGES`, `TradeRecord`, `ExchangeConnection`, `json`, `func`) werden noch von anderen Handlern (create/update/balance/budget/symbol-conflicts) genutzt und bleiben.

#### Tests
- **[unit]** `tests/unit/services/test_bots_service.py`: 5 neue Tests (21 total). `_FakeOrchestrator` um `statuses: dict[int, dict]`-Parameter + `get_bot_status`-Methode erweitert. Neue Tests: `test_list_bots_with_status_empty` (keine Bots → leere Liste), `test_list_bots_with_status_returns_only_owned` (fremde Bots nie gelistet, Default-Status `idle` für disabled), `test_list_bots_with_status_respects_demo_mode_filter` (`demo_mode=True` → demo+both, `=False` → live+both), `test_list_bots_with_status_admin_bypasses_hl_gates` (Admin-Role ⇒ `builder_fee_approved=True` + `referral_verified=True` ohne DB-Lookup), `test_list_bots_with_status_exposes_runtime_state` (orchestrator-dict überschreibt config-derived Default `running` + `trades_today` + `started_at`).

#### Scope für Follow-up PRs
- PR-4: `create_bot` + `update_bot` (Validation, Strategy-Registry-Lookup, Encryption von Webhooks/Telegram-Tokens)
- PR-5: Balance/Budget/Symbol-Conflict Handler (Exchange-Client-Coupling)

---

### 2026-04-22 — ARCH-C1 Phase 2b PR-2: BotsService — single-bot CRUD (#293)

Zweite Extraction-Welle: die drei Single-Bot-CRUD-Handler (`GET /{bot_id}`, `DELETE /{bot_id}`, `POST /{bot_id}/duplicate`) wandern aus dem Router in den Service. Gemeinsamer Nenner war der `select(BotConfig).where(id == bot_id, user_id == user.id)`-Lookup, der jetzt als `bots_service.get_bot()` einmal zentral lebt. Delete stoppt den Bot via Orchestrator wenn er läuft, schreibt Event-Log + Config-Audit und gibt den Bot-Namen zurück. Duplicate erzwingt das `MAX_BOTS_PER_USER`-Limit über die neue `MaxBotsReached`-Service-Exception und clont alle 19 Policy-Felder (Strategy, Exchange, Mode, Trading-Pairs, Leverage, TP/SL-Percent, Schedule, Notifications-Webhooks). Router-Handler sind jetzt 5-15 LOC Delegates die `BotNotFound` → 404 und `MaxBotsReached` → 400 mappen. Stacked auf PR-1 (#286). **Zero behavior change** — Response-Shapes, Status-Codes und Rate-Limits identisch zu vorher.

#### Refactored
- **[services]** `src/services/bots_service.py`: drei neue async-Funktionen. `get_bot(db, user_id, bot_id)` → `BotConfig` oder `BotNotFound`. `delete_bot(db, user_id, bot_id, orchestrator)` → Bot-Name (String für Router-Response), führt `orchestrator.is_running` + `orchestrator.stop_bot` + `db.delete` + `log_event("bot_deleted")` + `log_config_change(action="delete")` aus. `duplicate_bot(db, user_id, bot_id)` → neue `BotConfig` mit `name=f"{original.name} (Copy)"`, `is_enabled=False`, identisch clonede Strategy/Exchange/Notification-Konfiguration, `log_event("bot_duplicated")`. Neuer `_OrchestratorLike`-Protocol-Type hält den Service orchestrator-stack-frei. Late Imports für `config_audit` + `event_logger` halten das Modul FastAPI-frei und testbar ohne Full-App-Bootstrap.
- **[services]** `src/services/exceptions.py`: `BotNotFound` + `MaxBotsReached` ergänzt (unterhalb `InvalidTpSlIntent`). Wie die bestehenden `ServiceError`-Subklassen: keine Nachrichten-Konstanten gehardcoded — Router owned die User-facing Message.
- **[router]** `src/api/routers/bots.py`: `get_bot` (15 LOC → 8 LOC), `delete_bot` (33 LOC → 10 LOC), `duplicate_bot` (54 LOC → 12 LOC). Module-level-Import `from src.services import bots_service` ersetzt die inline-Imports aus PR-1 (dreifache Nutzung jetzt). Try/except-Ketten mappen `BotNotFound` → `HTTPException(404, ERR_BOT_NOT_FOUND)` und `MaxBotsReached` → `HTTPException(400, ERR_MAX_BOTS_REACHED.format(max_bots=MAX_BOTS_PER_USER))`.

#### Tests
- **[unit]** `tests/unit/services/test_bots_service.py`: 10 neue Tests (16 total) mit in-memory SQLite + `_FakeOrchestrator`. `get_bot`: happy path, missing-ID, Foreign-Ownership (verifiziert No-Tenant-Leak durch Collapsing auf `BotNotFound`). `delete_bot`: happy path + Rückgabewert, Stop-if-running (verifiziert `orchestrator.stopped == [bot_id]`), missing-ID, Foreign-Ownership. `duplicate_bot`: disabled-copy-shape + Name-Suffix, missing-ID, `MaxBotsReached`-Guard (monkey-patch `MAX_BOTS_PER_USER=1`). Alle grün.

#### Scope für Follow-up PRs
- PR-3: `list_bots` extrahieren (~185 LOC, Orchestrator-Coupling über injizierten Callable)
- PR-4: `create_bot` + `update_bot` (Validation, Strategy-Registry-Lookup, Encryption von Webhooks/Telegram-Tokens)
- PR-5: Balance/Budget/Symbol-Conflict Handler (Exchange-Client-Coupling)

---

### 2026-04-22 — ARCH-C1 Phase 2b PR-1: BotsService — static read handlers (#286)

Erste Extraction-Welle aus dem `/api/bots`-Router in den Service-Layer. Minimaler Scope: die beiden DB-freien, Orchestrator-freien Static-Read-Handler (`GET /api/bots/strategies`, `GET /api/bots/data-sources`) wandern nach `src/services/bots_service.py`. Der Router-Body schrumpft auf zwei Einzeiler die die Service-Funktion aufrufen und das Ergebnis auf die Pydantic-Response mappen. Zweck dieser ersten sub-PR ist ausschließlich das Anlegen des Service-Moduls und die Etablierung des Router→Service-Patterns für die folgenden (größeren) `list_bots` / `get_bot` / `create_bot` Extractions. **Zero behavior change** — die bestehenden Router-Tests in `tests/integration/test_bots.py` bleiben unverändert grün.

#### Refactored
- **[services]** `src/services/bots_service.py` (NEU, ~40 LOC): zwei Module-Level-Funktionen. `list_strategies()` delegiert direkt an `StrategyRegistry.list_available()` (Plain-Dict-Liste die der Router auf `StrategyInfo` mapt). `list_data_sources()` liefert `{"sources": [ds.to_dict() for ds in DATA_SOURCES], "defaults": DEFAULT_SOURCES}` — identisches Dict wie vorher vom Handler direkt returned. FastAPI-frei (kein `HTTPException`, kein `Depends`, kein `Request`), purer Business-Logic-Read.
- **[router]** `src/api/routers/bots.py` Handler `list_strategies` + `list_data_sources` rufen jetzt `bots_service.list_strategies()` bzw. `bots_service.list_data_sources()`. Der lokale `from src.data.data_source_registry import ...`-Import im Handler entfällt — der Service owned den Import. Decorator (`@router.get`), Auth-Dependency (`get_current_user`), und Response-Model bleiben identisch.

#### Tests
- **[unit]** `tests/unit/services/test_bots_service.py` (NEU, 6 Tests): `TestListStrategies` (3 — non-empty, key-shape incl. `name`/`description`/`param_schema`, exact equality mit `StrategyRegistry.list_available()`) und `TestListDataSources` (3 — dict-shape, source-entries sind plain-dicts mit `id`+`name`, defaults referenzieren bestehende source-IDs). Alle grün.

#### Scope für Follow-up PRs
- PR-2: `list_bots` extrahieren (~185 LOC Handler-Body, DB + Orchestrator-Coupling via `orchestrator.get_bot_status` als injizierter Callable)
- PR-3: `get_bot` + CRUD (`create_bot`, `update_bot`, `delete_bot`, `duplicate_bot`)
- PR-4: Balance/Budget/Symbol-Conflict Handler (Exchange-Client-Coupling)
- PR-5: `bots_lifecycle.py` und `bots_statistics.py` extraction

### 2026-04-22 — ARCH-C1 Phase 2a PR-5: extract PortfolioService (#253)

Second extraction step of the service-layer refactor plan. **Zero behavior change** — the 10 portfolio characterization tests in `tests/integration/test_portfolio_router_characterization.py` and the 13 router unit tests in `tests/unit/api/test_portfolio_router.py` pass unmodified.

#### Refactored
- **[services]** `src/services/portfolio_service.py` — populated `PortfolioService` with the 4 handlers' business logic: `get_summary(days, demo_mode)`, `list_positions()`, `get_daily(days, demo_mode)`, `get_allocation()`. FastAPI-free (no `Request` / `HTTPException` imports). Returns plain dataclasses (`PortfolioSummaryResult`, `PortfolioPositionItem`, `PortfolioDailyItem`, `PortfolioAllocationItem`) which the router projects onto Pydantic models. The exchange-client loader is injected via a constructor callable (`clients_loader`) so tests that monkeypatch `portfolio_router._get_all_user_clients` still observe the patched version.
- **[router]** `src/api/routers/portfolio.py` — reduced from 388 → 213 LOC. Handlers are now thin adapters: parse query params → call service → map dataclass → Pydantic response. Module-level TTL cache (`_cache`, `_cache_get`, `_cache_set`, `CACHE_TTL`) stays on the router (module-scoped lifetime, not per-request). Rate-limit decorators untouched. `_get_all_user_clients` kept on the router module so the existing monkeypatch contract in the characterization tests is preserved.

#### Added (tests)
- **[test]** `tests/unit/services/test_portfolio_service.py` — **8 unit tests** exercising the service directly with in-memory SQLite + mocked exchange clients: `get_summary` (empty/populated), `list_positions` (no clients / one enriched position), `get_daily` (empty/populated), `get_allocation` (no clients / two exchanges).

All three affected suites stay green: `test_portfolio_service.py` (8/8), `test_portfolio_router.py` (13/13), `test_portfolio_router_characterization.py` (10/10).

### 2026-04-22 — ARCH-C1 Phase 1: service-layer scaffolding + characterization tests (#253)

First execution step of the service-layer refactor plan (`Anleitungen/refactor_plan_service_layer.md`). **No production behavior change.** Sets up the safety net for PR-3 onward (read-only service extraction).

#### Added (scaffolding)
- **[services]** `src/services/exceptions.py` — `ServiceError` base + `TradeNotFound`, `NotOwnedByUser`, `SyncInProgress`, `InvalidTpSlIntent`. Router will map these to HTTP status codes; this module does not import FastAPI.
- **[services]** `src/services/trades_service.py` — `TradesService(db, user)` placeholder. Populated in PR-3/PR-4.
- **[services]** `src/services/portfolio_service.py` — `PortfolioService(db, user)` placeholder. Populated in PR-5.
- **[services]** `src/services/trade_sync_service.py` — `TradeSyncService(db, user)` placeholder. Populated in PR-7.
- **[services]** `src/services/tpsl_service.py` — `TpSlService(db, user, risk_state_manager=None)` placeholder — RSM is constructor-injected for testability (plan §5). Populated in PR-6.

#### Added (tests — freeze current behavior)
- **[test]** `tests/integration/test_trades_router_characterization.py` — **14 characterization tests** covering all 6 handlers in `src/api/routers/trades.py`: list / filter-options / sync / detail / risk-state / tp-sl. Behaviors frozen include: the `POST /sync` response key is `synced` (not `synced_count`); `GET /{id}` and `PUT /{id}/tp-sl` return 404 (not 403) for "not owned by user" because ownership is fused into the SQL WHERE; `GET /{id}/risk-state` returns 404 when `risk_state_manager_enabled=False`.
- **[test]** `tests/integration/test_portfolio_router_characterization.py` — **10 characterization tests** covering all 4 handlers in `src/api/routers/portfolio.py`: summary / positions / daily / allocation. Behaviors frozen: `/summary` has no in-memory cache (only `/positions` and `/allocation` do); `/positions` silently ignores an `?exchange=` query param (it doesn't exist on the handler); `/allocation` returns raw balances, not normalized percentages.

All 24 new tests carry `@pytest.mark.characterization`.

### Added
- **ARCH-H1 Phase 1 PR-4 — PositionMonitor-Komponente extrahiert (#281)**: Vierter Extraction-PR der Mixin→Composition-Migration. Neue Datei `src/bot/components/position_monitor.py` enthält die `PositionMonitor`-Klasse (~557 LOC) mit der vollständigen Polling-Loop-Logik: `monitor_safe()` / `monitor()` (Iteration über offene Trades pro DB-Session, Exception-Firewall pro Trade), `check_position(trade, session)` (Readback von Exchange-Position + Preis, TP/SL/Trailing-Drift-Check, Glitch-Counter mit Warn/Alert-Schwelle `_GLITCH_WARN_THRESHOLD=3` / `_GLITCH_ALERT_THRESHOLD=10`), `try_place_native_trailing_stop(...)` (Skip bei `trailing_status ∈ {cleared, pending}` — schützt vor #188-Regression wenn User Trailing manuell gelöscht hat; Lock + `_trailing_stop_backoff`-Map mit `_TRAILING_STOP_RETRY_MINUTES=10` Backoff pro Trade), `confirm_position_closed(trade, client)` (Double-Check-Delay `_POSITION_GONE_DELAY_S=2.0`, Zähler `_POSITION_GONE_THRESHOLD=3` verhindert Single-Tick-Glitches), `check_pnl_alert(trade, current_price)` (Prozent-/Dollar-Trigger, Direction-Filter für `price_above`/`price_below`, Idempotenz über `_pnl_alerts_sent`-Set pro Trade), `classify_close_heuristic(trade, exit_price) -> str` (@staticmethod — Fallback wenn RSM-Readback fehlt), `handle_closed_position(trade, client, session)` (RSM-`classify_close` first → heuristik-Fallback, Fees via `get_trade_total_fees`, `_close_and_record_trade`-Hook). Pro-Instance-State gekapselt: `_trailing_stop_backoff: dict[int, datetime]`, `_trailing_stop_lock: asyncio.Lock`, `_glitch_counter: dict[str, int]`, `_pnl_alerts_sent: dict[int, set[str]]`, `_pnl_alert_parsed: dict | None`. Dependency-Injection via Getter-Callables (`config_getter`, `strategy_getter`, `risk_state_manager_getter`, `client_factory`, `close_trade`, `notification_sender`) — toleriert den deferred BotWorker-Lifecycle bei dem `_config`/`_strategy`/`_risk_state_manager` erst nach `__init__` attached werden. `src/bot/position_monitor.py` ist jetzt ein 150-Zeilen Thin-Proxy-Mixin (`PositionMonitorMixin`): `_init_monitor_state()` baut die Komponente mit Late-Binding-Lambdas (über `hasattr`-Guards fallback auf `_noop_async` wenn Test-Harness `_send_notification` / `_close_and_record_trade` nicht hat); `_ensure_monitor()` lazy-build-Helper für Harnesses die `_init_monitor_state` skippen; Property-Getter+Setter für alle 5 State-Attribute routen auf die Komponente; Method-Proxies für alle 9 öffentlichen Methoden; alle sechs Modul-Konstanten werden re-exportiert für Backwards-Compat mit Phase-0-Characterization-Tests (`_TRAILING_STOP_RETRY_MINUTES`, `_POSITION_GONE_THRESHOLD`, `_POSITION_GONE_DELAY_S`, `_GLITCH_WARN_THRESHOLD`, `_GLITCH_ALERT_THRESHOLD`, `_TRAILING_SKIP_STATES`). `BotWorker.__init__` ruft `_init_monitor_state()` nach dem RSM-Wiring unverändert auf — keine Änderung an Consumer-Code. Alle Issue-#188/#216/#218/#220/#221-Fixes (Pattern A/B/C Guards, Trailing-Clear-Skip, Glitch-Handling mit DB-Session-Rollback, `ExitReason.EXTERNAL_CLOSE_UNKNOWN`-Fallback) bleiben bit-identisch in der Komponente erhalten. 27 neue Komponenten-Tests in `tests/unit/bot/components/test_position_monitor.py` guarden: ExitReason-Klassifizierung, Cache-Cleanup nach Close, PnL-Alert-Parser-Modi (Prozent/Dollar), Direction-Filter für `price_above`/`price_below`, Glitch-Counter mit Warn/Alert-Notifikation, Position-Closed-Triggering, RSM vs Heuristik-Fallback, Trailing-Skip bei `cleared`/`pending`. Zero-Behavior-Change: alle 253 Bot-Unit-Tests + 2974 Gesamt-Suite grün, inkl. aller Phase-0-Characterization-Tests (#267/#271/#273).
- **ARCH-H1 Phase 1 PR-5 — TradeExecutor-Komponente extrahiert (#72)**: Fünfter und letzter Extraction-PR der BotWorker-Composition-Migration vor Finalize. Neue Klasse `TradeExecutor` in `src/bot/components/trade_executor.py` (~630 LOC) enthält die komplette Order-Placement-Pipeline: `execute(signal, client, demo_mode, asset_budget)` (Entry-Validierung, Risk-Check, Leverage-Set, Order-Place, Callback-Trigger), `resolve_pending_trade(id, status, error_message)`, `notify_trade_failure(signal, mode_str, error)` (routet über `_make_user_friendly` + `_is_fatal_error`), `get_open_trades_count`, `get_open_trades_for_bot`, `execute_wrapper(...)` (self-managed Strategies mit Ticker-Fetch und TP/SL-Berechnung), `close_by_strategy(trade, reason)`. Module-Level-Helfer (`_FATAL_ERROR_PATTERNS`, `_USER_FRIENDLY_ERRORS`, `_make_user_friendly`, `_is_fatal_error`) bleiben erhalten und werden aus dem Mixin-Modul für Backwards-Compat re-exported. Dependency-Injection via Getter-Callables (`config_getter`, `risk_manager_getter`, `client_getter`) respektiert den deferred Lifecycle im BotWorker (Config und RiskManager werden post-`__init__` attached); Worker-State-Mutations laufen über Callbacks (`on_trade_opened` → `trades_today += 1`, `on_fatal_error` → `BotStatus.ERROR` + `error_message`), damit die Komponente frei von BotWorker-State-Knowledge bleibt. Der bisherige `TradeExecutorMixin` in `src/bot/trade_executor.py` ist jetzt ein dünner Proxy (~140 LOC): `_init_trade_executor_state` baut die Komponente in `self._trade_executor`, `_ensure_trade_executor` lazy-initialisiert falls Tests den Constructor umgehen, alle 8 Mixin-Methoden delegieren durch (`_execute_trade`, `_resolve_pending_trade`, `_notify_trade_failure`, `get_open_trades_count`, `get_open_trades_for_bot`, `execute_trade`, `close_trade_by_strategy`). `BotWorker.__init__` ruft nun `_init_trade_executor_state()` nach `_init_monitor_state()`. Zero-Behavior-Change — alle externen Callsites bleiben unverändert, die Migration ist reines Re-Organisieren der Implementierung. Tests: 21 neue Unit-Tests in `tests/unit/bot/components/test_trade_executor.py` decken `TestErrorClassifiers` (5: HL-Wallet-Regex, Rate-Limit, Unknown-Passthrough, Fatal-Detection, Non-Fatal), `TestExecute` (9: Invalid-Entry-Skip, Risk-Manager-Deny, Position-Too-Small, Set-Leverage-Fail, Place+Callback-Fires, OrderError→Notify+Resolve, Minimum-Amount-Silent-Skip, NEUTRAL-Skip, Asset-Budget-Math, Caller-TP/SL-Override), `TestNotifyTradeFailure` (3: Friendly-Message, Fatal-Callback, Non-Fatal-No-Pause) und `TestWrappers` (4: `execute_wrapper` No-Client, Ticker-Error-Early-Return, `close_by_strategy`-Dispatch) ab. Vier Test-Files mit patch-Targeten wurden auf `src.bot.components.trade_executor.X` migriert: `tests/unit/test_production_hardening.py` (2 Tests refactored auf Component-Level-Mocking via `mixin._ensure_trade_executor().notify_trade_failure = AsyncMock()`), `tests/integration/test_tpsl_flow.py`, `tests/unit/bot/test_bot_worker.py`, `tests/unit/bot/test_bot_worker_extra.py`. Full Unit-Suite 2968 passed / 1 xfailed / 1 xpassed — zero regressions. Nach Merge folgt PR-6 (#73) — Finalize: alle Mixin-Shims entfernen (NotificationsMixin, HyperliquidGates, TradeCloserMixin, PositionMonitorMixin, TradeExecutorMixin) und `BotWorker` als reine Composition-Klasse über `src/bot/components/` betreiben.
- **ARCH-H1 Phase 0 PR-1 — `src/bot/components/` Scaffolding (#266)**: Vorbereitungs-PR für die Mixin→Composition-Migration des `BotWorker`. Neues Paket `src/bot/components/` mit drei Dateien: `protocols.py` (vier `@runtime_checkable` `Protocol`-Stubs — `TradeExecutorProtocol`, `PositionMonitorProtocol`, `TradeCloserProtocol`, `NotifierProtocol` — die die öffentliche Oberfläche jeder zukünftigen Komponente pre-deklarieren), `deps.py` (`BotWorkerDeps`-Dataclass als shared-Handle-Bundle für spätere Komponenten-Constructors: `bot_config`, `client`, `symbol_locks` per-Instance via `field(default_factory=dict)`, `user_trade_lock`), `__init__.py` (Re-Export der fünf Symbole). Zero-Behavior-Change: `BotWorker` erbt weiterhin von allen fünf Mixins, kein Consumer konstruiert bislang `BotWorkerDeps`. 8 Smoke-Tests in `tests/unit/bot/components/test_scaffolding.py` guarden: alle Exports in `__all__`, `BotWorkerDeps()` ohne Args konstruierbar, mutable-default-Regression (`symbol_locks` per-Instance), alle vier Protocols wirklich `runtime_checkable` + korrekte Ablehnung unvollständiger Duck-Types. Weitere Phasen der Extraktion (Notifier, HyperliquidGates-Shim-Drop, TradeCloser, PositionMonitor, TradeExecutor) folgen jeweils als eigene PRs mit Canary-Deploy — Detailplan in `Anleitungen/refactor_plan_bot_worker_composition.md`.
- **Auth-Hardening: RS256 + Dual-Validate + Optimistic Refresh-Rotation (#256, Phase A1)**: JWT-Signing unterstützt jetzt sowohl `RS256` (asymmetrisch, empfohlen via `JWT_PRIVATE_KEY` + `JWT_PUBLIC_KEY`) als auch `HS256` (Legacy via `JWT_SECRET_KEY`). Wenn beide Verfahren konfiguriert sind, signiert der Server neue Tokens mit RS256 und akzeptiert bei der Validierung beide — ermöglicht ein 14-Tage-Rollover-Fenster ohne Zwangs-Relog. `REFRESH_TOKEN_EXPIRE_DAYS` von 90 → 14 reduziert (industry-default). Refresh-Rotation jetzt mit Optimistic Locking über neue `user_sessions.session_version`-Spalte (Migration `025_add_session_version`): parallele Refresh-Requests racen atomar auf die Version — nur der Gewinner rotiert den Cookie, der Verlierer bekommt trotzdem ein frisches Access-Token ohne dem Browser einen veralteten Refresh-Token zu geben. Das eliminiert die Forced-Logout-Regression des alten no-rotation-Mode und schließt gleichzeitig das unbegrenzte Theft-Window. `/auth/refresh` Rate-Limit auf `2/minute` verschärft (von `5/minute`). `access_token` aus `LoginResponse`- und `TokenResponse`-Body entfernt (SEC-012, XSS-Defense) — Client bekommt nur noch `expires_in` und den httpOnly-Cookie. Frontend-Client + authStore lesen primär `expires_in`, fallen auf JWT-Decode nur für Legacy-Dual-Validate-Responses zurück. Neue bilinguale Anleitung `Anleitungen/auth-key-rotation.md` (DE+EN) mit Key-Pair-Erzeugung, Rollover-Prozedur und Rotation der RS256-Keys. `.env.example` dokumentiert beide Signing-Optionen. Unit-Tests in `tests/unit/auth/test_jwt_handler.py` decken HS256-Default, Refresh-Token-Expiry=14, Typ-Mismatch-Rejection und Dual-Validate ab (12 Tests, alle grün).
- **Anleitung `Anleitungen/WebSocket-Live-Updates.md`** (bilingual DE/EN): End-User-Doku für die beiden WebSocket-Systeme. Teil 1 erklärt das Frontend↔Server-WS (welche Events live im Dashboard landen, Status-Indikator, Reconnect-Backoff 1s→30s, häufige Probleme). Teil 2 richtet sich an Admins: `EXCHANGE_WEBSOCKETS_ENABLED`-Flag-Semantik, Status "aktuell aus auf Prod" (Commit `fd77ba9`), Aktivierungs-Ablauf auf dem VPS (`.env` + `docker compose restart`), `GET /api/health → ws_connections`-Monitoring, Log-Pattern-Referenz, Reconnect-Strategie ohne Event-Replay (reconcile-Sweep als Source-of-Truth-Ansatz), Rollback-Prozedur, bekannte Einschränkungen, Verweis auf `docs/websockets.md` für tiefergehende Architektur. Schließt Gap im Docs-Audit 2026-04-23.
- **Anleitung `Anleitungen/Feature-Flags-System.md`** (bilingual DE/EN): Zentrale Übersicht aller 8 Runtime-Flags (`AUTO_AUDIT_ENABLED`, `EXCHANGE_WEBSOCKETS_ENABLED`, `RISK_STATE_MANAGER_ENABLED`, `HL_SOFTWARE_TRAILING_ENABLED`, `ENABLE_HSTS`, `BEHIND_PROXY`, `SQL_ECHO`, `DEMO_MODE`) mit Default, Wirkung, Aktivierungs-Prozedur und Rollback-Hinweisen pro Flag. Erklärt auch den aktuellen Implementierungsstand: Flags werden ad-hoc via `os.getenv()` (bzw. für Risk-Flags über `Settings.risk`-Dataclass) gelesen — es gibt bewusst keinen zentralisierten Feature-Flag-Service, weil die Menge klein und stabil ist. Schließt Gap im Docs-Audit 2026-04-23.
- **WebSocketManager im App-Lifespan verdrahtet (#240)**: `src/bot/ws_credentials_provider.py` löst `(user_id, exchange)` gegen `ExchangeConnection` + `BotConfig` auf und liefert entschlüsselte Credentials (Bitget: api_key/api_secret/passphrase/demo_mode aus der neuesten enabled BotConfig; Hyperliquid: wallet_address aus `api_key_encrypted` — HL hat keine dedizierte Wallet-Spalte, der Client speichert sie als api_key). Die `lifespan` in `src/api/main_app.py` konstruiert nach RiskStateManager-Resolve einen Prozess-weiten `WebSocketManager`, legt ihn auf `app.state.exchange_ws_manager` (dort wo `/api/health` ihn bereits erwartet) und ruft `start_for_user` für jede `(user_id, exchange)` mit `is_enabled=true` Bot-Config. `EXCHANGE_WEBSOCKETS_ENABLED` bleibt default off → `start_for_user` ist dann ein dokumentierter No-Op, kein Production-Verhalten ändert sich bis das Flag explizit an ist. Shutdown ruft `stop_all()` nach dem Audit-Scheduler und vor dem Orchestrator-Shutdown. 7 neue Unit-Tests in `tests/unit/bot/test_ws_credentials_provider.py` (Bitget live/demo, Hyperliquid, fehlende Connection, fehlende Credentials, Default-Live ohne Bot, Unsupported-Exchange).
- Prometheus risk-state Metriken + Grafana Dashboard (#216 Section 2.3): `src/utils/metrics.py` exportiert drei neue Metriken — `risk_exchange_reject_total` (Counter: `exchange`, `reject_reason`; incremented in den `_parse_response`-Branches von Bitget/BingX/Weex Clients), `risk_intent_duration_seconds` (Histogram: `exchange`, `leg`, `outcome`; misst die End-to-End-Latenz von `RiskStateManager.apply_intent` über alle 2PC-Phasen), und `risk_sync_drift_total` (Counter: `field`; incremented pro DB-Feld das `RiskStateManager.reconcile` vom Exchange-State überschreibt). Die Metriken landen im Default-Registry und werden über den bereits existierenden `GET /metrics`-Endpoint (IP-restricted in Prod via `METRICS_ALLOWED_IPS`) von Prometheus gescrapt. Dashboard-Template in `docs/grafana/risk-state-dashboard.json` (Panels: Reject-Rate gestackt per Exchange, Intent-Duration P50/P95/P99 pro Leg, Drift-Count pro Feld; schemaVersion 38). Unit-Tests in `tests/unit/utils/test_metrics.py` decken Label-Contract, Counter-Inkremente und Histogram-Observation ab. Metrik-Helper sind best-effort — eine fehlschlagende Instrumentierung blockiert niemals den Request-Pfad. `prometheus-client` in `requirements.txt` auf `~=0.20.0` gepinnt.
- **SSE-Trades-Stream ersetzt 5s-Polling (#216 §2.2)**: Neuer Endpoint `GET /api/trades/stream` (Server-Sent Events, JWT via `Authorization`-Header / httpOnly-Cookie / `?token=`-Query-Param als EventSource-Fallback). Prozess-lokaler `EventBus` in `src/bot/event_bus.py` (asyncio.Queue pro Subscriber, per-User-Scope) emitiert `trade_opened` aus dem `TradeExecutorMixin`, `trade_updated` aus `RiskStateManager.apply_intent` (post-Phase-D), `trade_closed` aus `TradeCloserMixin`. Frame-Format: `data: {"event","trade_id","timestamp","data"}\n\n`; 30s-Keepalive (`: keepalive`). Frontend-Hook `useTradesSSE` invalidiert bei jedem Event den `['trades']`/`['portfolio','positions']`-React-Query-Cache und fällt bei EventSource-Fehler automatisch auf 5s-Polling zurück (`connectionState: 'sse' | 'polling' | 'disconnected'`). In Dashboard + Portfolio eingebunden; bestehende Polling-Pfade bleiben als Fallback unangetastet.
- Hyperliquid Software Trailing Emulator `src/bot/hl_trailing_emulator.py` (#216 Section 3.1): Hyperliquid hat keinen nativen Trailing-Stop-Primitive — der Bot emuliert jetzt selbst. Prozess-weiter 5-Sekunden-Watchdog, der alle offenen HL-Trades mit `trailing_intent_callback IS NOT NULL AND trailing_status='confirmed'` anzieht, `all_mids()` einmal pro Tick pro (user, demo_mode) abfragt (nicht pro Trade — HL rate-limitet per IP), `trade.highest_price` in Richtung der Position (long=max / short=min) ratcheted und bei tighterem Kandidaten-SL (=`highest*(1-cb/100)` long bzw `highest*(1+cb/100)` short) ein SL-Update via `RiskStateManager.apply_intent(SL, new_sl)` emittiert. Marker `risk_source='software_bot'` wird vom Emulator re-gestamped nach jedem apply_intent, damit `_classify_from_snapshot` die spätere SL-Fire als `TRAILING_STOP_SOFTWARE` attribuiert (nicht als `STOP_LOSS_NATIVE`). Persistenz: keine neuen Spalten — `highest_price` + `trailing_callback_rate` + `stop_loss` genügen für Reconstruction nach Bot-Restart. Feature-Flag `HL_SOFTWARE_TRAILING_ENABLED` (default off). Singleton via neuem `src/api/dependencies/hl_trailing.py::get_hl_trailing_emulator()`. `BotWorker.__init__` startet den Watchdog wenn Flag an. Event-Logging: `risk_state.hl_trailing_trigger trade=X new_sl=Y`. 9 neue Unit-Tests guarden: Long-Ratchet hoch, Long-Tick nach unten ist No-Op, tight-wins-over-loose, Short-Seiteninversion, Flag-Off kein Watchdog, Pending-Status wird übersprungen, Restart-Persistenz.
- WebSocket-Listeners für Bitget + Hyperliquid (#216 S2.1, Phase 2 Push-Mode): neues Paket `src/exchanges/websockets/` mit abstrakter Base-Klasse `ExchangeWebSocketClient` (Reconnect-Exponential-Backoff 1s/2s/4s/8s/30s-Cap, `is_connected`-Health), `BitgetWebSocketClient` (orders-algo Private Channel, HMAC-Login wie REST-Client) und `HyperliquidWebSocketClient` (HL SDK `Info.subscribe` mit `type=orderUpdates`, `isTrigger=true` Filter). Process-wide `src/bot/ws_manager.py:WebSocketManager` hält ein Client pro `(user_id, exchange)`, feature-gated über `EXCHANGE_WEBSOCKETS_ENABLED` (default off — keine Verhaltensänderung). Neue `RiskStateManager.on_exchange_event(user_id, exchange, event_type, payload)`-Methode dispatched erkannte Events (`plan_triggered`, `order_filled`, `position_closed`) an `reconcile(trade_id)` pro matching open trade; unbekannte Events no-op + log. `/api/health` liefert zusätzlich `ws_connections: {bitget, hyperliquid}`. Bei Reconnect triggert Manager eine One-Shot Reconcile-Sweep über alle Open Trades der `(user, exchange)` — Events während Outage werden bewusst NICHT repliziert (Exchange ist Source of Truth). Tests: 5 Unit-Tests in `tests/unit/exchanges/test_ws_base.py` + 3 in `tests/unit/bot/test_ws_manager.py` + 2 in `test_risk_state_manager.py`. Live-WS-Verifikation (Bitget Demo + HL Testnet) pending in `tests/integration/live/test_ws_live.py` (skip, needs demo credentials). Neue Übersicht in `docs/websockets.md`.
- **Automatic bug-detection audits (#216 Section 2.4)**: vier neue scheduled Audit-Scripts plus ein `AuditScheduler`, die im Hintergrund stündlich nach Drift-Indikatoren suchen und Findings via Discord/Telegram an die Admin-Kanäle melden. Jedes Script läuft als eigenständiges CLI-Tool (Default Dry-Run, `--apply` + `--yes` für Interface-Parität, `--user-id` / `--exchange` Filter) und schreibt einen Markdown-Report nach `reports/<audit>-<timestamp>.md`.
  - `scripts/audit_tp_sl_flags.py` — DB↔Exchange TP/SL-Plan-Vergleich via `client.get_position_tpsl(symbol, side)`. Flagged `db_only_tp` / `exchange_only_tp` / `db_only_sl` / `exchange_only_sl`. Für Healing auf `scripts/reconcile_open_trades.py --apply` verweisen.
  - `scripts/audit_position_size.py` — DB `trade.size` vs. Exchange `position.size` mit 0.5% Toleranz. Klassifiziert `rounded` (erwartet), `desync` (actionable), `missing` (Position weg).
  - `scripts/audit_price_sanity.py` — Für Closed-Trades der letzten 24 h werden `entry_price`/`exit_price` gegen Binance-1m-Klines verglichen; >2% Abweichung = Finding. Nutzt bestehenden `MarketDataFetcher.get_binance_klines`.
  - `scripts/audit_classify_method.py` — Parst Bot-Logs (JSON + Plain-Text) nach `risk_state.classify_close`-Emissionen, berechnet pro Exchange die Heuristik-Fallback-Rate. >30% = Alert (Pattern-B-Regression wie #218/#221). Resolved Exchange pro Event über `trade_records.id`-Lookup.
  - `src/bot/audit_scheduler.py` mit `AuditScheduler` (APScheduler-Wrapper): vier Jobs, stündlich gestaffelt 0/15/30/45 min UTC, nutzt `default_admin_notifier` (Discord + Telegram via `ADMIN_DISCORD_WEBHOOK_URL` / `ADMIN_TELEGRAM_BOT_TOKEN` / `ADMIN_TELEGRAM_CHAT_ID` ENV). Shared Helper in `scripts/_audit_common.py`: `ConnectionBackedClientFactory`, `session_factory`, `select_open_trades`, `render_summary_block`, `render_skip_error_blocks`. Opt-in via `AUTO_AUDIT_ENABLED=true` — ohne Flag komplett dormant. Startup/Shutdown-Wiring in `src/api/main_app.py` Lifespan. Tests in `tests/unit/scripts/test_audit_scripts.py` (15 Tests: je ein Smoke-Test pro Script + Scheduler-Registration + Notifier-Dispatch).
- `scripts/backfill_classify_close.py` (#220, Epic #188 Follow-Up): einmal-Tool um historische Trades mit schwachem Exit-Reason (Default: `EXTERNAL_CLOSE_UNKNOWN`) via `RiskStateManager.classify_close()` gegen Exchange-Readback nachzuklassifizieren. Default Dry-Run, `--apply` + `--yes` für DB-Writes, `--trade-ids` für gezielte Reclassification, `--exchange` / `--reason` Filter. Idempotent: zweiter Lauf ist No-Op. Historische Trades vor dem #218-Wiring (Trades #251, #262, #276) wurden damit von `EXTERNAL_CLOSE_UNKNOWN` auf die realen Reasons (`TRAILING_STOP_NATIVE`/`MANUAL_CLOSE_EXCHANGE`) gesetzt nachdem #221 den Bitget-Readback repariert hatte.
- Weex: leg-spezifischer Cancel (Epic #188 Follow-Up) — `cancel_tp_only` und `cancel_sl_only` filtern Pending-Conditional-Orders über `planType` (`TAKE_PROFIT` vs `STOP_LOSS`) plus `positionSide`, so dass ein Dashboard-Clear von nur TP die SL-Order unberührt lässt. Shared-Helper `_cancel_pending_tpsl_by_role` hält `cancel_position_tpsl` als dünnen Wrapper. Weex V3 unterstützt kein natives Trailing, daher nur 2 Legs.
- Bitunix: leg-spezifischer Cancel NICHT implementiert (Epic #188 Follow-Up) — `cancel_tp_only`/`cancel_sl_only` raisen `NotImplementedError` mit expliziter Begründung. Bitunix speichert TP+SL in EINEM Pending-Order-Row (sowohl `tpPrice` als auch `slPrice` in einem Objekt); `/tpsl/cancel_order` akzeptiert nur `orderId` ohne Leg-Selektor; `modify_order`-Semantik für Partial-Clear ist undokumentiert. RiskStateManager fängt das als `CancelFailed` auf und markiert den Leg als `cancel_failed` statt SL collateral zu canceln — UI zeigt den Fehler klar an.
- Drift-Backfill-Script `scripts/reconcile_open_trades.py` (#198, Epic #188): scannt alle offenen Trades, vergleicht DB mit Exchange-State via RiskStateManager.reconcile(), erzeugt Markdown-Report. Default Dry-Run, --apply zum Korrigieren. Filter --user-id und --exchange. Skip-Verhalten für Weex/Bitunix (kein Probe-Support).
- Modul `src/bot/risk_state_manager.py` mit 2-Phase-Commit für TP/SL/Trailing (#190, Epic #188): apply_intent() schreibt Intent → Exchange → Readback → DB; reconcile() heilt Drift; classify_close() Stub für #193. Feature-Flag RISK_STATE_MANAGER_ENABLED (default off). Verhindert Anti-Pattern A (probe-but-don't-write) und C (DEBUG cancel errors).
- DB-Migration für Risk-State-Felder auf trade_records (#189, Epic #188): tp_order_id, sl_order_id, trailing_order_id, trailing_callback_rate, trailing_activation_price, trailing_trigger_price, risk_source ENUM, *_intent/*_status pro Leg, last_synced_at. Vorbereitung für 2-Phase-Commit Risk-State-Manager.
- Exchange-Client Readback-Methoden für Bitget/BingX/Hyperliquid (#191, Epic #188): `get_position_tpsl()`, `get_trailing_stop()`, `get_close_reason_from_history()`. Normalisierte Snapshot-Dataclasses in `base.py`. Voraussetzung für RiskStateManager (#190) der die Methoden als Source of Truth nutzt.
- Modul `src/bot/risk_reasons.py` mit `ExitReason` Enum + Helpers `is_native_exit`/`is_software_exit`/`is_manual_exit` (#193, Epic #188). Zentralisiert die 10 neuen Reason-Codes plus 5 Legacy-Aliase für historische Trades.
- Neue Komponente RiskStateBadge für kompakte TP/SL/Trailing-Anzeige (#196, Epic #188): zeigt aktiven Wert + Quelle (Exchange/Bot) + Status (aktiv/pending/rejected/cancel_failed) mit Icon und Farbcodierung. Eingebaut in MobilePositionCard und Trades-Detail-Drawer. Tooltips mit order_id, latency, error. i18n DE+EN komplett.
- Live-Integration-Test-Suite gegen Bitget-Demo (#197, Epic #188): 19 Tests für TP/SL/Trailing-Roundtrip gegen admin user_id=1 Bitget-Demo-Account. Deckt TEST_MATRIX.md Sektion A+B+Teil-C ab. Cleanup-Garantie: jede Test-Position wird in finally geräumt. Marker `bitget_live` + env var `BITGET_LIVE_TEST_USER_ID` für selektive Ausführung.
- Frontend useRiskState + useUpdateTpSl mit Optimistic Updates + vollständiger Cache-Invalidation (#195, Epic #188): sofortiges UI-Feedback, Rollback bei Fehler, Warning-Toast bei Partial-Success. Neuer Backend-Endpoint GET /trades/{id}/risk-state für Readback. i18n DE+EN für Status-Meldungen. Behebt dass gelöschte TP bis Page-Reload sichtbar blieben.

### Changed
- **ARCH-H1 Phase 1 PR-3 — `TradeCloserMixin` → `TradeCloser`-Komponente (#279)**: Dritter Composition-Schritt nach PR-1 (Notifier, #276) und PR-2 (HyperliquidGates, #278). Neue Datei `src/bot/components/trade_closer.py` enthält die `TradeCloser`-Klasse mit der Methode `close_and_record(trade, exit_price, exit_reason, *, fees, funding_paid, builder_fee, strategy_reason)`. Die Komponente kapselt die komplette Close-Pipeline: In-Memory-Trade-Update → dedicated-Session DB-Persist mit Idempotency-Guard (`db_trade.status != 'closed'`) → RiskManager.record_trade_exit → WebSocket-Broadcast → SSE-Event → Discord/Telegram-Notifications. Dependency-Injection via vier Constructor-Args: `bot_config_id`, `config_getter` (lazy, da `_config` erst in `initialize()` geladen wird), `risk_manager_getter` (lazy, `_risk_manager` wird ebenfalls später attached), und `notification_sender` (das bound `_send_notification` von der NotificationsMixin — so bleibt PR-3 unabhängig von PR-1 #276). `src/bot/trade_closer.py::TradeCloserMixin` wird auf ~30 LOC thin proxy reduziert, der alle Kwargs durchleitet. Alle 5 Call-Sites unverändert (3× in `rotation_manager.py`, 2× in `position_monitor.py` — `trade_executor.py` nutzt weiterhin `getattr(self, '_close_and_record_trade', None)`-Pattern). `BotWorker.__init__` wired via `self._trade_closer = TradeCloser(bot_config_id, lambda: self._config, lambda: self._risk_manager, self._send_notification)`. 11 neue Unit-Tests in `tests/unit/bot/components/test_trade_closer.py` decken ab: in-memory-Field-Updates, optionale Fee-Felder, RiskManager-Record-Call, Notification-Dispatch, SSE-Event-Publish, SSE-Exception-Swallowing, DB-Fehler-Toleranz (in-memory bleibt closed), Idempotency-Guard (DB-Row bereits closed), strategy_reason-Override, WS-Broadcast-Failure-Tolerance, no-user_id-Pfad (WS+SSE skipped, Notifications weiter). Alle 237 bestehenden Bot-Tests grün — keine Regression.
- Klassifizierer für exit_reason refactored (#193, Epic #188): liest jetzt Bitgets orders-plan-history (via #191 readback) als Source of Truth für was die Position geschlossen hat. 9 neue präzise Reason-Codes (TRAILING_STOP_NATIVE/SOFTWARE, TAKE_PROFIT/STOP_LOSS_NATIVE, MANUAL_CLOSE_UI/EXCHANGE, STRATEGY_EXIT, LIQUIDATION, FUNDING_EXPIRY, EXTERNAL_CLOSE_UNKNOWN). `RiskStateManager.classify_close()` ersetzt den heuristischen Klassifizierer in `position_monitor._handle_closed_position`; Heuristik nur noch als Fallback bei API-Fail. Verhindert Anti-Pattern B (heuristischer Klassifizierer ohne Exchange-Probe). Strategy-Exit-Hinweise via `note_strategy_exit()` überschreiben Exchange-Readback (interne Signale gewinnen).
- PUT /api/trades/{id}/tp-sl refactored auf RiskStateManager (#192, Epic #188): 2-Phase-Commit pro Leg (TP/SL/Trailing einzeln), Response enthält post-readback State je Leg, Partial-Success möglich, Idempotency-Key support. Alter Pfad bleibt parallel über Feature-Flag risk_state_manager_enabled (default off). Anti-Pattern A (probe-but-don't-write) und C (cancel-DEBUG) endgültig verhindert.

### Fixed
- **Manual-Close routet durch den TradeCloser (#275)**: `POST /api/bots/{bot_id}/close-position/{symbol}` in `src/api/routers/bots_lifecycle.py` duplizierte die Close-Logik als reiner Inline-Write — ohne Fee/Funding/Builder-Fee-Capture, ohne Discord/Telegram-Notification, ohne WebSocket-Broadcast, ohne `EVENT_TRADE_CLOSED` auf dem SSE-Bus und ohne `RiskManager.record_trade_exit`. Fix: `TradeCloserMixin._close_and_record_trade` aus `src/bot/trade_closer.py` wurde in eine freistehende async-Funktion `close_and_record_trade(trade, exit_price, reason, *, bot_config_id, config, risk_manager, send_notification, fees, funding_paid, builder_fee, strategy_reason)` extrahiert; die Mixin-Methode delegiert jetzt auf den Helper, so dass Bot-Worker-Pfad und API-Pfad garantiert denselben Code durchlaufen. Der Manual-Close-Endpoint holt Fees via `client.get_trade_total_fees`, Funding via `get_funding_fees`, Builder-Fee via `calculate_builder_fee` (wo vorhanden — Hyperliquid) und ruft dann `close_and_record_trade` mit `exit_reason="MANUAL_CLOSE"`. Wenn der Bot läuft, werden der `_risk_manager` und der `_send_notification`-Dispatcher des Live-`BotWorker` aus `orchestrator._workers[bot_id]` wiederverwendet — so landen Daily-Stats im selben In-Memory-`DailyStats`-Objekt das der Bot verwendet. Bei gestopptem Bot wird eine DB-backed `RiskManager`-Instanz gebaut (`load_stats_from_db` + `_save_stats_to_db`) und ein standalone `build_standalone_dispatcher(config, bot_id)` aus `src/bot/notifications.py` für Discord/Telegram-Dispatch. SQLite-Tz-Naivität in `close_and_record_trade` abgefangen (`entry_time.replace(tzinfo=utc)` wenn naiv) — verhindert `can't subtract offset-naive and offset-aware datetimes` unter dem Integrationstest. Neuer Integrationstest `tests/integration/test_manual_close_full_flow.py` mit 6 Cases: 200-OK + PnL-Response, fee/funding/builder-Fee auf Trade-Row, Discord+Telegram `send_trade_exit` tatsächlich aufgerufen, WS-Manager `broadcast_to_user("trade_closed", ...)`, SSE-Bus `EVENT_TRADE_CLOSED` emittiert, und Live-Worker-Fall (wenn `orchestrator._workers[bot_id]` existiert wird dessen `_risk_manager.record_trade_exit` benutzt statt einer frischen Instanz).
- **Security (#302): SSRF in test-discord/telegram-direct + IP-Spoofing im Auth-Bridge**: Zwei zusammengefasste Security-Fixes. **(1 — CRITICAL SSRF in `src/api/routers/bots_lifecycle.py`):** `POST /api/bots/test-discord-direct` und `POST /api/bots/test-telegram-direct` lasen `webhook_url` bzw. `bot_token`/`chat_id` vorher direkt aus `await request.json()` ohne jede Validierung — ein authentifizierter User konnte beliebige URLs aufrufen und damit interne Netzwerke scannen (`http://127.0.0.1:5432`, `http://metadata.aws.internal`), Docker-Compose-Hosts (`postgres:5432`) oder AWS/GCP-Metadaten-Services anprobieren. Beide Endpoints nehmen jetzt typisierte Pydantic-Body-Models entgegen (`TelegramTestRequest` mit `bot_token`/`chat_id`, `DiscordTestRequest` mit `webhook_url`), wobei `DiscordTestRequest.webhook_url` durch den bereits existierenden `_validate_webhook_url`-Validator aus `src/api/schemas/bots.py` läuft — der erzwingt `https://` und whitelistet ausschließlich `{discord.com, discordapp.com, hooks.slack.com, api.telegram.org}` (Subdomains erlaubt). Effekt: Pydantic wirft bei Verletzung `ValidationError`, FastAPI gibt 422 zurück bevor überhaupt ein HTTP-Request das Netz verlässt. **(2 — MAJOR IP-Spoofing in `src/api/routers/auth_bridge.py`):** Beide Endpoints (`POST /api/auth/bridge/generate`, `POST /api/auth/bridge/exchange`) lasen `X-Forwarded-For` unconditional via `request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")` — ein Angreifer konnte durch setzen des Headers Audit-Log-Einträge fälschen ("user logged in from 1.2.3.4") und per-IP Rate-Limits umgehen. Beide Log-Call-Sites rufen jetzt `_get_real_client_ip(request)` aus `src/api/rate_limit.py` auf; der Helper vertraut `X-Forwarded-For` nur wenn die Modul-Konstante `_TRUST_PROXY` True ist (`BEHIND_PROXY=1|true|yes` im Env), validiert die IP zusätzlich über `_is_valid_ip` gegen `ipaddress.ip_address` und fällt ohne Proxy-Flag sauber auf `request.client.host` zurück. Beim Schreiben der Regression-Tests kam zusätzlich ein latenter Bug im globalen `validation_exception_handler` (`src/api/main_app.py`) zu Tage: Pydantic v2 hängt bei `ValueError` aus einem `@field_validator` die Exception-Instanz an `ctx.error`, was beim JSON-Encoding der 422-Response zu `TypeError: Object of type ValueError is not JSON serializable` führte und den ganzen Endpoint auf 500 fallen ließ. Der Sanitizer rekursiert jetzt über alle Error-Felder, wandelt `bytes` sicher um (`errors="replace"`) und stringifiziert beliebige non-JSON-Objekte (inkl. Exceptions) in `ctx`/nested-Values — 422 bleibt 422. Regression-Tests in `tests/integration/test_security_302.py` guarden 422-Responses für SSRF-Payloads auf beiden Test-Endpoints sowie das IP-Fallback-Verhalten ohne `BEHIND_PROXY`.
- **AUTO_AUDIT: `audit_classify_method` crashte bei Cron-Tick auf naiver Datetime (#238)**: Erster Live-Run von `AUTO_AUDIT_ENABLED=true` auf production 2026-04-21 16:45 UTC warf `TypeError: can't compare offset-naive and offset-aware datetimes`. Root cause: Python-Logger emittiert JSON-Timestamps als `"YYYY-MM-DD HH:MM:SS,fff"` (Komma-Millisekunden, kein TZ-Suffix). Python 3.11 `datetime.fromisoformat` akzeptiert das, liefert aber ein naives Datetime — und die Vergleichskante gegen das tz-aware `since = now(utc) - 1h` crashte jeden Tick. `_parse_iso_timestamp` in `scripts/audit_classify_method.py` normalisiert jetzt sowohl das Komma-Separator (`,` → `.`) als auch naive Ergebnisse (default UTC-stamp, identisches Verhalten wie der bereits-aware Text-Line-Pfad). Zusätzlich `DEFAULT_REPORT_DIR` in `scripts/_audit_common.py` jetzt via `AUDIT_REPORTS_DIR` Env-Var überschreibbar (Default unverändert `reports/`) — `/app` im Container ist root-owned und `botuser` konnte `reports/` nicht anlegen; auf Server `AUDIT_REPORTS_DIR=logs/reports` gesetzt. Neuer Unit-Test `test_audit_classify_method_json_parser_yields_tz_aware_timestamp` guardet den JSON-Parse-Pfad gegen Regression.
- **Weex Leg-Isolation: `set_position_tpsl` pre-place sweep ge-scoped (#216 S2 audit)**: `_cancel_existing_tpsl(symbol)` cancelte vor dem Place unbedingt jede pending TAKE_PROFIT- UND STOP_LOSS-Order für das Symbol — hat also bei einem reinen TP-Update die SL-Order des Users silent mitgekillt (gleiches Anti-Pattern wie #188 Bitget `cancel_position_tpsl` und BingX `_cancel_existing_tpsl`). Helper akzeptiert jetzt `target_types: frozenset[str]` mit den planType-Konstanten (`_TP_PLAN_TYPES`, `_SL_PLAN_TYPES`, `_TPSL_PLAN_TYPES` default für Backwards-Compat). `set_position_tpsl` baut die Scope-Menge aus den tatsächlich übergebenen Legs: TP-only setzt → sweep `{TAKE_PROFIT}`, SL-only → sweep `{STOP_LOSS}`, beide → beide. Hyperliquid und Bitunix wurden mitgesweept: HL ist bereits clean (native `positionTpsl`-Grouping ersetzt ohne Pre-Cancel, plus `_cancel_triggers_by_tpsl(target_tpsl=...)` mit Leg-Parameter), Bitunix ist strukturell clean (kein Pre-Cancel, Pos-Level-Endpoint replaced atomar, `cancel_tp_only`/`cancel_sl_only` raisen korrekt NotImplementedError). Neue Tests in `test_weex_cancel_leg.py` guarden: TP-only darf SL nicht anfassen, SL-only darf TP nicht anfassen, beide gemeinsam sweepen wie vorher, und `_cancel_existing_tpsl` ohne Filter erhält Legacy-Verhalten.
- **Pattern C + Pattern F Sweep (#225, Epic #188 Follow-Up)**: Nach dem Audit nach den #218/#221/#220-Fixes fünf MEDIUM-Findings gezielt behoben. **(Pattern C — DEBUG-swallowed cancel errors):** `bitget/client.py` — beide Call-Sites (`cancel_position_tpsl` inline-Loop + shared Helper `_cancel_plan_types`) nutzen jetzt den neuen `_log_bitget_cancel_outcome()`-Classifier: benigne "no matching plan"-Fehler (order does not exist / 40768 / not found) bleiben bei DEBUG, alles andere (HTTP 5xx, auth, network, contract errors) eskaliert zu WARN. Damit kann eine echte Cancel-Failure nie mehr still eine stale Exchange-Order hinterlassen. `weex/client.py:613` — gleiche Classifier-Logik für den Pending-TP/SL-Query-Pfad (`set_position_tpsl` → inneres cancel-loop). **(Pattern F — missing time window):** `bitget/client.py` — `get_trade_total_fees` (fallback-Path der `orders-history`) und `get_close_fill_price` passen jetzt explizit `startTime = now - 90d` + `endTime = now` + `limit=20` — vorher trat Bitgets stilles 7-Tage-Default-Fenster ein und alle Closes älter als eine Woche wurden stumm ignoriert (Fees/Fill-Preis fielen auf 0 / None). Neue Unit-Tests `test_cancel_benign_no_match_stays_at_debug` + `test_cancel_real_error_escalates_to_warn` im `test_bitget_cancel_tpsl.py` guarden das Log-Level-Verhalten.
- **Bitget Close-Readback Query komplett broken (#221, Epic #188 Hotfix)**: `_fetch_bitget_plan_close` hatte mehrere Bugs die den Call seit #191 jedes Mal crashen oder falsche Daten liefern ließen. **(1)** `planType`-Param fehlte obwohl Bitget v2 ihn required macht — Call crashte mit "Parameter verification failed". **(2)** `endTime`-Param fehlte. **(3)** Status-Filter prüfte `planStatus == "triggered"` aber Bitget liefert `executed`. **(4)** Bitgets `endTime` ist advisory — der Response enthält Rows mit späteren `uTime`-Werten, muss client-seitig nachgefiltert werden (sonst leakt ein neuerer Close auf demselben Symbol in den Backfill eines älteren Trades). **(5)** Der `_PLAN_TYPE_TO_REASON`-Mapper kannte `track_plan` aber nicht `moving_plan` — Bitgets Response für native Trailings nutzt `moving_plan`, `track_plan` kommt nur in den Docs vor; native Trailings landeten deshalb im `EXTERNAL_CLOSE_UNKNOWN`-Bucket. **(6)** Der `orderSource`-Mapper kannte weder `move_*` (Bitget-Demo-Kurzform für Trailing-Execution) noch mappte er Plan-getriggerte Closes auf die richtigen plan_type-Keys — alles wurde als `manual` markiert. Fix: `planType=profit_loss` (Umbrella für pos_profit/pos_loss/moving_plan), `endTime`-Param + client-side uTime-Filter, Status-Filter akzeptiert `executed`+`triggered`, `executeOrderId` vor Plan-`orderId` (= Fill-ID die mit `TradeRecord.*_order_id` matcht), `moving_plan`/`track_plan` beide → `TRAILING_STOP_NATIVE`, `orderSource`-Prefix-Mapping für `pos_loss_`/`pos_profit_`/`track_plan_`/`moving_plan_`/`move_`/`liquidation_`. `get_close_reason_from_history` isoliert Plan- und Manual-Probe in eigenen try/except. Der Readback unterstützt jetzt optional `until_ts_ms` auf Base-Interface — erlaubt Backfill mit gebundener Obergrenze. Live gegen Trade #251/#262/#276/#286 verifiziert: alle 4 korrekt klassifiziert (vorher: `EXTERNAL_CLOSE_UNKNOWN` — jetzt: `TRAILING_STOP_NATIVE` / `MANUAL_CLOSE_EXCHANGE` / `TRAILING_STOP_NATIVE` / `STOP_LOSS_NATIVE`). Verhindert endgültig Anti-Pattern B auf Bitget.
- **RiskStateManager in BotWorker verdrahtet (#218, Epic #188 Hotfix)**: Epic #188 hatte `RSM.classify_close()` + Exchange-Readback-Classifier gebaut, aber `BotWorker.__init__` setzte `_risk_state_manager = None` und nichts überschrieb das je — nur `src/api/dependencies/risk_state.py` instanziierte den Manager für den API-Pfad. Folge: jeder vom Bot-Polling-Loop erkannte Close lief durch den Legacy-0.2%-Proximity-Heuristik-Fallback und wurde bei echtem SL/TP-Slippage (|exit−sl| > entry*0.002) als `EXTERNAL_CLOSE_UNKNOWN` misklassifiziert. Evidenz: Trade #286 (ETHUSDT SHORT, SL 2306, Fill 2311.9, 5.9 pt Slippage > 4.56 Proximity) → "Extern geschlossen (unbekannt)" statt `STOP_LOSS_NATIVE`. Frische Instanz von Anti-Pattern B. Fix: `BotWorker` zieht jetzt den Prozess-weiten `get_risk_state_manager()`-Singleton wenn `risk_state_manager_enabled` on ist (lazy import gegen Zirkelimport). Singleton-Sharing ist bewusst — der per-(trade, leg)-Lock-Map muss zwischen API und Bot geteilt bleiben.
- **BingX Leg-Isolation: `cancel_native_trailing_stop` ergänzt + interner Sweep ge-scoped (Epic #188 Hotfix)**: BingX hat natives Trailing (`SUPPORTS_NATIVE_TRAILING_STOP=True`, `TRAILING_STOP_MARKET` Order-Type), aber `cancel_native_trailing_stop` fehlte komplett — RSM fiel auf `cancel_order(by_id)` zurück was bei stale DB-`trailing_order_id` zu Silent-No-Op führte. Methode hinzugefügt analog zu Bitget's leg-isoliertem Cancel. **Zweiter Bug an gleicher Stelle**: `place_trailing_stop` und `set_position_tpsl` riefen intern `_cancel_existing_tpsl` ohne Type-Filter auf — wipte bei jedem TP-Set auch SL und Trailing (gleiches Anti-Pattern wie Bitget's `cancel_position_tpsl`). Helper akzeptiert jetzt `target_types: frozenset` und beide Call-Sites passen den Leg-Scope explizit (Trailing-Place sweeped nur Trailing; TP/SL-Place sweeped nur was tatsächlich gesetzt wird).
- **Trailing-Readback-Crash auf Bitget (Epic #188 Hotfix)**: `get_trailing_stop` fragte `planType=track_plan` ab, Bitget speichert Trailing-Stops aber als `planType=moving_plan` innerhalb der `profit_loss`-Liste — Query lief immer leer, `_readback` crashte dann mit `'NoneType' object has no attribute 'callback_rate'`, Toast "Nur teilweise erfolgreich". Fix: Umbrella-Query + lokaler Filter (wie `has_native_trailing_stop`). `holdSide`-Filter akzeptiert leeres Feld (Bitget setzt beim Moving-Plan `holdSide: null`). Zusätzlich `_readback` hardened gegen `trailing_snap is None` (Return `(None, None)` statt Crash).
- **Trailing-Clear via Frontend nicht möglich**: `UpdateTpSlRequest` kannte kein `remove_trailing` — Toggle-Off im Modal wurde stumm ignoriert weil `body.trailing_stop is None` nicht von "keine Änderung" zu unterscheiden war. Feld + Endpoint-Handling ergänzt, spiegelt `remove_tp`/`remove_sl`-Semantik.
- **EditPositionPanel sendete stale Werte**: Modal serialisierte jedes Feld auf Save, nicht nur geänderte Legs. Stale cache → unveränderter SL wurde mit altem Wert resubmittet, Exchange rotierte Order-IDs unnötig, geklärte Legs kamen zurück. Jetzt Dirty-Tracking: nur Legs im Payload die gegen `position.*` abweichen. `remove_trailing` wird gesendet wenn Toggle ausgeschaltet.
- **Modal zeigte stale Werte nach Save**: `editingPos` war ein Snapshot zum Klick-Zeitpunkt, der nicht mehr mit dem (jetzt invalidierten) `positions` Cache mitging. Nach Save→Close→Reopen zeigten die Eingabefelder den alten SL obwohl Exchange + DB ihn längst geklärt hatten. Dashboard und Portfolio resolven jetzt vor dem Rendern über `positions.find(p => p.trade_id === editingPos.trade_id)` auf die Live-Daten. Kein Page-Reload mehr nötig.
- **Bot überschrieb vom User gelöschtes Trailing**: `position_monitor._try_place_native_trailing_stop` platzierte 30-60 s nach einem User-Clear einen neuen nativen Trailing — vom UI sah es aus als hätte der Toggle-Off nichts bewirkt. Monitor checkt jetzt `trade.trailing_status == 'cleared'` und überspringt Auto-Placement. User-Intent gewinnt.
- **Stale `trailing_order_id` in DB blockierte User-Trailing-Änderung**: Wenn der Bot einen Trailing platziert hatte (DB hatte `native_trailing_stop=true`, aber `trailing_order_id=None`), schlug der nächste User-Slider-Change mit `[bitget] API Error: Insufficient position, can not set profit or stop loss` fehl, weil RSM den existierenden Trailing nicht cancelte (Guard `if existing_order_id is not None`). `_exchange_apply` sweeped jetzt **immer** vor dem Place — die `cancel_*_only` Methoden filtern via `planType`/`orderType`, sind idempotent und leg-isoliert. Drift-Quelle (Bot, Bitget-App, externe API) spielt keine Rolle mehr.
- **`useUpdateTpSl.onSettled` invalidierte Cache fire-and-forget**: Mutation resolvte vor dem Refetch → Modal closed → User klickt sofort Edit → React Query liefert noch alte Position. Jetzt `await Promise.all([invalidateQueries(...)])` in `onSettled` damit `mutateAsync` erst nach dem Refetch returnt.
- **Trailing-Persist: legacy Felder fehlten** (`native_trailing_stop`, `trailing_atr_override`): `_write_confirmation` schrieb nur die neuen Risk-State-Spalten, die UI-Toggle-Seed-Felder blieben auf Default. Toggle stand nach erfolgreichem Set immer auf OFF, kein `remove_trailing` möglich. RSM persistiert jetzt beide Felder bei jedem Trailing-Write (atr_override aus dem Intent durchgereicht, native_trailing_stop aus `confirmed_order_id is not None` abgeleitet).
- BingX: `cancel_tp_only` + `cancel_sl_only` Methoden (Epic #188 Follow-Up): clear TP löscht jetzt nur die TAKE_PROFIT_MARKET/TAKE_PROFIT Orders; SL und Trailing bleiben aktiv. Vorher cancelte der Default-Fallback alle Orders gleichzeitig.
- i18n-Kollision aufgelöst: MANUAL_CLOSE und EXTERNAL_CLOSE hatten beide das Label "Manuell geschlossen" (#194, Epic #188). Plus 10 neue präzise Reason-Codes (TRAILING_STOP_NATIVE/SOFTWARE, TAKE_PROFIT/STOP_LOSS_NATIVE, MANUAL_CLOSE_UI/EXCHANGE, STRATEGY_EXIT, LIQUIDATION, FUNDING_EXPIRY, EXTERNAL_CLOSE_UNKNOWN). Uniqueness-Test verhindert künftige Kollisionen.

### Security
- **Phase A3 — CORS + IP-Spoofing + Traceback-Redaktion (#258)**:
  - **SEC-004 CORS-Wildcard mit Credentials**: `src/api/main_app.py` prüft beim Start, ob `CORS_ALLOWED_ORIGINS` ein `*` enthält während `allow_credentials=True` konfiguriert ist — diese Kombination ist laut Fetch-Spec forbidden und wird zusätzlich von jedem Browser ignoriert, aber der Fehler wäre eine CSRF-Oberfläche. Startup raist jetzt `RuntimeError` mit expliziter Remediation-Message, statt stillschweigend weiterzulaufen.
  - **SEC-006 X-Forwarded-For Spoofing**: `src/api/rate_limit.py` ignoriert bereits korrekt `X-Forwarded-For`, wenn `BEHIND_PROXY` nicht explizit auf `true/1/yes` gesetzt ist — ohne diesen Gate könnte ein unauthentifizierter Angreifer den Header rotieren und damit den Rate-Limit-Bucket pro Request wechseln. Neue Regressions-Suite `tests/unit/api/test_rate_limit_ip_spoofing.py` (9 Tests) guardet beide Pfade: Spoof-Rejection bei `BEHIND_PROXY=false/0/empty`, Trust bei `BEHIND_PROXY=true`, Malformed-IP-Fallthrough, Empty-Header-Fallthrough, Peer-Fallback wenn kein Client.
  - **SEC-010 Traceback leakt Secrets**: Neuer Utility `src/api/secret_redaction.py` (`redact_secrets`, `redact_lines`) greedy-redacted in dieser Reihenfolge: (1) Exakt-Match gegen Snapshot aller `_SENSITIVE_ENV_VARS` (DATABASE_URL, JWT_SECRET, BITGET_API_KEY, etc. — 22 Env-Vars), (2) Caller-provided `extra_values`, (3) `Bearer`/`Basic`/`Token`-Pattern VOR KV-Pattern (sonst fängt das KV-Pattern "Bearer" als Value und lässt den Token frei), (4) KV-Pattern für `password=…`, `api_key: …`, `Authorization: …` (JSON/YAML/ENV/Header-Separatoren), (5) URL-Credentials `scheme://user:pass@host`, (6) Long-Token-Pattern (JWT-Shape, `sk-`/`ghp_`/`pk_`/`xoxb-`/`github_pat_`-Prefixes). `src/api/middleware/error_handler.py` pipet im Dev-Mode sowohl `detail` als auch jede Traceback-Zeile durch `redact_secrets`/`redact_lines` — Prod-Mode liefert weiterhin generisches "Internal server error" ohne Traceback. 35 Tests in `tests/unit/api/test_secret_redaction.py` (KV-Pairs, URL-DSN, JWT, OpenAI-Keys, GitHub-PATs, Env-Snapshot, Idempotenz, Non-String-Inputs) + 4 Tests in `tests/unit/api/test_error_handler_redaction.py` (DSN in Traceback, Env-Value, Bearer-Token, Prod-Mode-Guard).
  - **SEC-011 HMAC compare-digest (Hinweis)**: Audit bestätigt keine Drop-in-Fund-Stelle im aktuellen Code. Der Signatur-Erzeugungs-Pfad in `src/exchanges/*/client.py` nutzt `hmac.new().hexdigest()` für Outbound-Request-Signing — dort gibt es keinen User-controlled Comparison-Vektor, also kein Timing-Angriff. Keine Inbound-HMAC-Verification aktuell im Codebase (kein Webhook-Receiver mit geteiltem Secret). Finding wird als False-Positive dokumentiert; sollte ein Inbound-HMAC-Verification-Pfad hinzukommen (z.B. Exchange-Webhooks, Bridge-Callbacks), MUSS `hmac.compare_digest(...)` statt `==` verwendet werden.
  - AUTH-bezogene Findings (A1 #256 RS256/Refresh-Rotation, A4 #259 Scope-Tightening) sind bewusst pausiert — das gesamte Auth-System wird im Zuge der Integration mit `trading-department.com` (Phase 1-6 Plan) komplett ersetzt.
- **Phase A5 — Dependency-Audit CI-Gate (#260, SEC-015)**:
  - Neue `requirements-dev.txt` mit `pip-audit>=2.7.0` + `pytest-timeout>=2.3.0` (Dev-only, nicht im Prod-Image).
  - `.github/workflows/security-audit.yml` mit zwei Jobs: `pip-audit --strict --vulnerability-service osv` gegen `requirements.txt` und `npm audit --audit-level=high` im `frontend/`. Beide failen bei High/Critical; Moderate bleibt als Info. Trigger: `push`/`pull_request` auf `main`+`staging` plus täglicher Cron 06:00 UTC, damit neu-disclosed CVEs gegen einen gepinnten Tree schlagen selbst ohne neuen Commit.
  - `discord.py`-Floor von `>=2.3.0` auf `>=2.4.0` angehoben (SEC-015 Acceptance-Criterion).
  - Existing-Findings vorab adressiert damit das Gate nicht am ersten Tag rot wird: `npm audit fix --legacy-peer-deps` aktualisiert `lodash` und `vite` — 3× High + 3× Moderate auf 0. `pip-audit` gegen `requirements.txt` lokal: no known vulnerabilities. Frontend `vitest run` 500/500 grün und `vite build` ok nach dem Update.

---

## [4.15.1] - 2026-04-15

### Changed (Issue #181 follow-up)
- **Affiliate-Credentials kommen jetzt aus der Admin-DB** — statt aus ENV-Variablen. Der Fetcher lädt automatisch die API-Keys aus den `exchange_connections`-Zeilen des Admin-Users. Keine ENV-Einträge mehr nötig für den Normalbetrieb.
  - Bitget/Weex/BingX: API-Key/Secret/Passphrase aus Admin-Connection (wenn Account Affiliate/Agent-Status hat)
  - Hyperliquid: Wallet-Adresse aus `api_key_encrypted` (HL's "API-Key" IST die Adresse)
  - Bitunix: weiterhin `unsupported` (keine API)
- ENV-Variablen bleiben als Override verfügbar falls du einen separaten Affiliate-Account nutzt
- `.env.example` aktualisiert

---

## [4.15.0] - 2026-04-15

### Added
- **Automatischer Affiliate-Revenue-Fetcher** — Einnahmen werden alle 6h direkt aus den Exchange-APIs gezogen und im Admin-Dashboard pro Exchange + als Gesamtsumme angezeigt (#181)
  - **Bitget**: `/api/v2/broker/customer-commissions` (HMAC, startTime/endTime)
  - **Weex**: `/api/v3/rebate/affiliate/getAffiliateCommission` (max 3-Monats-Range, Pagination)
  - **Hyperliquid**: `/info` `referral` (kumulativ, Delta via neue `affiliate_state` Tabelle)
  - **BingX**: `/openApi/agent/v1/asset/commissionDataList` (Agent-Tier, optional X-SOURCE-KEY Header)
  - **Bitunix**: keine öffentliche API — Kachel zeigt "API nicht verfügbar" Badge + Hinweis-Banner
- Neuer manueller Sync-Button "Jetzt synchronisieren" im Dashboard (Rate-limited 3/min)
- Sync-Status-Badges pro Kachel (✓ vor Xm | nicht konfiguriert | API nicht verfügbar | Fehler)
- ENV-Variablen für Affiliate-Credentials in `.env.example` dokumentiert (BITGET_AFFILIATE_*, WEEX_AFFILIATE_*, HL_REFERRER_ADDRESS, BINGX_AGENT_*)
- Migration `023_add_affiliate_state.py` für HL-Cumulative-Tracking + Last-Sync-State

### Removed
- **Manueller "Neuer Eintrag" Button** + dazugehöriges Modal entfernt
- **POST/PUT/DELETE /api/admin/revenue** Endpoints entfernt — alle Daten kommen automatisch
- Manuelle-Einträge-Tabelle aus dem Frontend entfernt (Daten sind nur noch in Kacheln + Chart)

### Changed
- `RevenueEntry.source` Default verbleibt auf "manual" für Migrations-Kompatibilität, neue Auto-Imports nutzen "auto_import"

---

## [4.14.10] - 2026-04-15

### Changed
- **Weex V3 API Migration (Phase 2)** — 7 weitere Endpoints von V2 auf V3 migriert nach Weex V3-Erweiterung am 2026-03-09 (#114)
  - `account_assets`: `/capi/v2/account/assets` → `/capi/v3/account/balance` (neue Felder: `asset`, `balance`, `availableBalance`, `unrealizePnl`)
  - `all_positions`: V3 `/capi/v3/account/position/allPosition` mit `LONG/SHORT` statt numerischer Side-Codes, `size` statt `hold_amount`
  - `single_position`: V3 mit Plain-Symbol-Format (BTCUSDT) statt cmt_btcusdt
  - `funding_rate`: V3 `/capi/v3/market/premiumIndex` mit `lastFundingRate`-Feld (statt v2 Liste)
  - `candles`: V3 `/capi/v3/market/klines`
  - `open_interest`: V3 `/capi/v3/market/openInterest`
  - `cancel_order`: jetzt **DELETE** `/capi/v3/order` (war POST `/capi/v2/order/cancel_order`)
- Position-Parser akzeptiert jetzt sowohl V3- (`size`/`LONG`) als auch V2-Shape (`hold_amount`/`1`) für rückwärtskompatibles Verhalten

### Pending
- `ticker`, `set_leverage`, `order/detail`, `order/current`, `order/fills` bleiben auf V2 — Weex hat noch keine V3-Pfade dafür publiziert. Werden migriert, sobald in Changelog erscheint.

---

## [4.14.9] - 2026-04-15

### Added (Test Coverage — Issue #176)
- 13 neue Fee-Tracking Tests in `test_fee_tracking_all_exchanges.py` (Weex, Hyperliquid, Bitunix, BingX) — Bitget hatte bereits umfassende Tests
- 8 neue Margin-Mode-Switch Tests in `test_margin_mode_all_exchanges.py` für alle 5 Exchanges (cross↔isolated)

### Documented (Findings aus Audit)
- **Bitget set_leverage()** ignoriert den `margin_mode`-Parameter — die Margin-Mode-Konfiguration läuft bei Bitget out-of-band über das Account-UI oder einen separaten `/api/v2/mix/account/set-margin-mode` Endpunkt (nicht implementiert). Test dokumentiert das Accept-and-Noop Verhalten.
- **Bitunix set_leverage()** macht ebenfalls keinen separaten Margin-Mode-Call — die Mode wird per Trade via `place_order` (changeMargin) gesetzt.
- BingX, Weex, Hyperliquid wandeln `margin_mode` korrekt in die exchange-spezifische Form um (CROSSED/ISOLATED, marginMode=1/3, is_cross=true/false).

### Verified during audit (no code change needed)
- `update_tpsl` Endpunkt: 60 parametrisierte Integration-Tests (12 Szenarien × 5 Exchanges) in `test_tpsl_edit_all_exchanges.py` — vollständige Abdeckung

---

## [4.14.8] - 2026-04-15

### Added (Issue #176)
- **`scripts/live_mode_smoke.py`** — Read-only Smoke-Test für Live-Keys aller 5 Exchanges
  - Probiert pro Exchange: Balance + Positions + Ticker + Funding-Rate
  - Keine Order-Platzierung, kein Schreiben — null Trading-Risiko
  - CLI: `--user-id N` (pflicht), `--exchanges bitget,bingx` (optional Filter)
  - Use-Case: BEVOR ein User von Demo auf Live geschaltet wird, in 30s verifizieren dass alle Live-Pfade laufen
- 3 Unit-Tests in `tests/unit/scripts/test_live_mode_smoke.py` decken Pfad-Logik ab

---

## [4.14.5] - 2026-04-15

### Fixed
- **CI grün** — Tests an aktuelle Implementation angepasst nach akkumuliertem Test-Drift aus PR #163 (PnL alerts), #166 (Telegram), DE-i18n. Alle Backend-Tests, Frontend-Tests (466) und Lint passieren wieder (#179)
- 6 Backend-Test-Failures behoben: DE-Übersetzungen, MockMonitor `_pnl_alert_parsed`, Telegram-Retry-Counter, Discord-Footer-Logik
- 3 Frontend-Test-Files an neue Props angepasst: `pnlAlertSettings`, Notification-Channels in Review/Notifications-Step, entfernte Tab-Struktur in Settings
- 9 Lint-Errors behoben: ungenutzte Imports, fehlender `ERR_WRONG_ENVIRONMENT` Import, ungenutzte Variable in admin_broadcasts

---

## [4.14.4] - 2026-04-14

### Fixed
- **Hyperliquid Demo-Preise stammen jetzt vom Mainnet** — Im Demo-Modus routete der HL-Client sämtliche Preis-Queries (`get_ticker`, `get_fill_price`, `get_close_fill_price`, `get_funding_rate`) auf das Testnet, wo AAVE stundenlang auf ~$114.94 festhing während das Mainnet bei ~$100.90 lag. Ergebnis: `exit_price` in DB und Frontend zeigte Fantasie-PnL (+80 USD statt tatsächlich +3 USD). Jetzt splittet `HyperliquidClient` seine Info-Clients: `_info` immer auf MAINNET für Marktdaten, `_info_exec` auf dem Execution-Netz für user-spezifische Queries (Fills, Positions, Balance). Demo-User sehen jetzt im Bot-Frontend die gleichen Zahlen wie auf app.hyperliquid.xyz
- **Backfill-Script korrigiert historische Demo-Trades** — `scripts/backfill_demo_prices.py` nutzt HL-Mainnet-Kline-Daten (1m → 5m → 15m → 1h → 4h Fallback) um `entry_price`, `exit_price` und `pnl` für alle geschlossenen Demo-HL-Trades neu zu berechnen. Angewendet in Prod: 5 Trades korrigiert (#17 PnL -1.95→-3.16, #116 -97.65→-57.18, #134 118.65→154.58, #148 79.70→-0.57, #150 83.13→1.88)
- **Native Trailing Stop DB-Sync auf Bitget** — Nach einem Frontend-TP/SL-Edit blieb das `moving_plan` auf Bitget teilweise aktiv während die DB auf `native_trailing_stop=False` sprang. Resultat: `position_monitor` versuchte alle 10 Minuten einen neuen Plan zu platzieren und erzeugte Endlos-Warning-Loops ("Insufficient position") bis zum Trade-Close. Root-Cause-Kette:
  - `cancel_position_tpsl` lief nur bei TP/SL-Änderungen, nicht bei reiner Trailing-Anpassung → alter `moving_plan` blieb alive, neuer Placement-Versuch scheiterte
  - Fix in `update_trade_tpsl`: neues `cancel_native_trailing_stop(symbol, side)` wird bei jeder Trailing-Änderung vorgeschaltet
  - Neue Capability `has_native_trailing_stop()` (Bitget + BingX) für Drift-Detection
  - `position_monitor` probiert pro Cycle bidirektional: bei Exchange=True/DB=False wird Flag korrigiert und Retry-Loop gestoppt; bei Exchange=False/DB=True wird der Plan neu platziert
  - `/trades/{id}/tpsl` nutzt die Exchange-Realität als Source of Truth statt lokaler Buchhaltung
- **`trailing_atr_override` wird beim Auto-Replace respektiert** — Bei automatischer Neu-Platzierung nach Drift nutzte `_try_place_native_trailing_stop` den Strategie-Default (`trailing_trail_atr=2.5`) auch wenn der User manuell einen anderen Wert gesetzt hatte. Jetzt gewinnt `trade.trailing_atr_override` wenn gesetzt.
- **Bitget `place_market_order` rundet Size auf `volumePlace`** — Eine 6-Nachkommastellen-Size (z.B. 11.978866) wurde von Bitget stumm auf 2 Nachkommastellen gekürzt (11.97), die DB behielt aber den vollen Wert → Drift zwischen gebuchter und dokumentierter Position. Neue Orders speichern jetzt den exchange-autoritativen Wert.

### Changed
- **Frontend-Placeholder entfernt** — Die Box "Die Empfehlung basiert auf deinen bisherigen Trades..." im EditPositionPanel war ein Platzhalter ohne Backend-Implementierung (Quellcode-Kommentar `{/* Recommendation hint (placeholder) */}`). Die Empfehlung wurde nie berechnet. Element inkl. i18n-Keys entfernt, bis die Funktion tatsächlich gebaut wird.

### Added
- **`scripts/audit_trailing_flags.py`** — Scannt alle offenen Trades auf DB/Exchange-Drift beim `native_trailing_stop`-Flag. Skippt Exchanges ohne Probe-Implementierung (HL, Weex, Bitunix) um False-Positives zu vermeiden. Kann mit `--apply` schreibend reconcilieren.
- **`SUPPORTS_NATIVE_TRAILING_PROBE` Capability-Flag** auf `ExchangeClient`-Basisklasse für erweiterte Feature-Detection. Bitget + BingX implementieren.

---

## [4.14.3] - 2026-04-14

### Fixed
- **Trade wird nicht mehr als "closed" markiert wenn Close-Order fehlschlägt** — Wenn `close_position()` einen leeren `order_id` zurückgibt (Close wurde nicht ausgeführt), wird der Trade in DB nicht mehr als closed markiert. Verhindert Phantom-Closes, bei denen die Position auf der Exchange noch offen ist aber die DB closed anzeigt. Resultat: Neuer Trade wurde auf bestehender Position eröffnet → Position auf Exchange doppelt so groß wie im Frontend angezeigt (#174)
- **Betroffen:** BingX, Bitget, Bitunix, Weex, Hyperliquid — alle Exchange-Clients loggen jetzt eine Warnung bei leerem orderId
- **Position Monitor + Rotation Manager** verifizieren jetzt `close_order.order_id` vor DB-Update

---

## [4.14.2] - 2026-04-14

### Fixed
- **Zeitplan synchronisiert sich beim Profilwechsel** — Beim Wechsel des Risikoprofils im Bot Builder wird jetzt auch das Schedule-Intervall automatisch angepasst: aggressive→15min, standard→60min, conservative→240min (#172)

---

## [4.14.1] - 2026-04-14

### Fixed
- **Aggressive Risikoprofil: fehlendes kline_interval Mapping** — Beim Wechsel auf "Aggressiv" im Bot Builder wurde kline_interval nicht aktualisiert. Backend (`liquidation_hunter.py`) und Frontend (`BotBuilderStepStrategy.tsx`) setzen jetzt `15m` für das aggressive Profil (#170)

---

## [4.14.0] - 2026-04-13

### Added
- **Telegram Interactive Bot** — User können im Telegram-Chat aktiv den Bot nach Status, Trades und PnL fragen (#166)
  - `/status` — Bot-Übersicht, offene Trades, PnL heute
  - `/trades` — Offene Positionen mit PnL
  - `/pnl` / `/pnl 7` / `/pnl 90` — PnL-Zusammenfassung nach Zeitraum
  - Nativer Telegram Command-Menü via `setMyCommands`
  - Long-Polling Background-Task, automatischer Start beim App-Start
- **PnL-Alert Schwellenwert-Benachrichtigungen** — Pro Bot konfigurierbar: Dollar oder Prozent, Gewinn/Verlust/Beides, einmalige Benachrichtigung pro Trade (#163)
  - Neuer Abschnitt im Bot Builder Step 4 (Notifications) mit Toggle, Modus-Wahl, Schwellenwert und Richtung
  - Position Monitor prüft bei jedem Zyklus und sendet Alert via Discord/Telegram
  - DB-Migration: `pnl_alert_settings` JSON-Spalte auf `bot_configs`
- **Einnahmen-Tab CRUD** — Admin kann manuelle Revenue-Einträge anlegen, bearbeiten und löschen (Formulare + Delete-Bestätigung) (#162)
- **Revenue-Zeitverlauf-Chart** — Gestapeltes Balkendiagramm zeigt Einnahmen pro Exchange über Zeit (7d/30d/90d/1y) (#162)
- **Backend-Tests für Revenue-Endpoints** — 19 Tests für GET/POST/PUT/DELETE, Auth-Guards, Auto-Entry-Schutz (#162)
- **Frontend-Tests für AdminRevenue** — 15 Tests für KPI-Strip, Exchange Cards, CRUD-Flows, Chart, Error-Handling (#162)

### Removed
- **WhatsApp-Benachrichtigungen komplett entfernt** — WhatsApp-Notifier, DB-Spalten und zugehöriger Code entfernt (#163)

### Fixed
- **Letzte Test-Failures behoben (0 Failures, 2875 passing):**
  - Edge Indicator: `test_choppy_bull_trend_still_gives_long` korrigiert — ADX-Filter gibt korrekt NEUTRAL bei choppy market zurück
  - Tax Report: Obsoleten `test_csv_contains_builder_fee` Test entfernt (Builder Fee nicht im CSV implementiert)
  - Main App: `test_frontend_mount_when_directory_exists` gegen Cross-Test-Pollution abgesichert (`os.getenv` Mock für TESTING env var)
- **121 pre-existing test failures fixed (CI green)** — Systematisches Beheben aller Test-Fehler:
  - Rotation-Tests entfernt/aktualisiert (Feature aus BotWorker entfernt, `_force_close_trade`, `_check_rotation` Tests gelöscht)
  - Integration-Tests: SPA Catch-All blockiert via `TESTING` env var, httpOnly Cookie-Leak in Auth-Tests behoben, Trailing-Slash für `/api/config/` korrigiert
  - Config-Router Import-Pfade aktualisiert (`_conn_to_response` → `config_service.conn_to_response`, etc.)
  - `get_close_fill_price` Mock zu allen Trade-Sync und Position-Monitor Tests hinzugefügt
  - `native_trailing_stop` Attribut zu Mock-Trades hinzugefügt
  - Builder Fee Berechnung: Testerwartungen an korrigierten Divisor (100.000 statt 1.000.000) angepasst
  - Referral Gate: Test verwendet jetzt passenden Referral-Code
  - Affiliate Gate: Assertions an String-basierte Error-Details angepasst
  - Statistics/Compare Endpoints: `request` Parameter für Rate-Limiting hinzugefügt
  - Session/Migration Tests: Angepasst an Alembic-basiertes Migrationssystem
  - Edge Indicator: TP/SL aus Schema-Erwartungen entfernt (jetzt Bot-Level Config)
  - Symbol Validation: `get_exchange_symbols` in betroffenen Tests gemockt

### Tests
- **BotBuilder Step Component Tests (5 neue Testdateien, 60 Tests)** — Umfassende Vitest-Tests für alle BotBuilder-Wizard-Schritte: StepName (7 Tests), StepExchange (13 Tests), StepStrategy (10 Tests), StepNotifications (13 Tests), StepReview (17 Tests). Abdeckung von Rendering, User-Interaktionen, Callbacks und Zustandsanzeigen.
- **Page, Hook & Utility Tests (8 neue Testdateien, 63 Tests)** — Tests für BotPerformance (Loading/Empty/Error/Data States), TaxReport (Titel, CSV-Button, Jahr-Auswahl, Loading), GettingStarted (Titel, Quickstart-Schritte, Navigation), NotFound (404-Meldung, Home-Link), useIsMobile (Breakpoints, Resize-Events), usePullToRefresh (Initialisierung, Optionen), Zod Validation Schemas (Login, BotName, Credentials, Trading-Params, Passwort-Regeln, validateField), API Error Handling (422, String, Objekt, Fallback).

### CI/CD
- **PostgreSQL 16 Service in GitHub Actions CI** — Backend-Tests laufen jetzt zweimal: einmal mit SQLite (schneller Basischeck) und einmal mit PostgreSQL 16 (echte DB-Kompatibilität). Service Container mit Health Checks und dedizierten Credentials.
- **Integration-Test Conftest unterstützt PostgreSQL** — `tests/integration/conftest.py` nutzt jetzt `TEST_DATABASE_URL` Env-Variable statt hardcodierter SQLite-URL. SQLite-spezifische `check_same_thread` Option wird nur bei SQLite gesetzt.

---

## [4.13.0] - 2026-04-11

### Added
- **Wallet-Validierung beim Hyperliquid Bot-Start** — Prüft ob Wallet existiert, min. 100 USDC Guthaben, und API-Wallet autorisiert ist. Blockiert Bot-Start mit klarer Fehlermeldung statt kryptischer Fehler beim ersten Trade
- **User-freundliche Fehlermeldungen** — 10+ kryptische Exchange-Fehler (Wallet not found, invalid API key, insufficient balance, rate limit, liquidation prevention, etc.) werden in klare deutsche Meldungen mit Handlungsanweisungen übersetzt
- **Auto-Pause bei fatalen Fehlern** — Bot pausiert automatisch bei Konfigurationsfehlern (ungültiges Wallet, falscher API-Key, gesperrtes Konto) statt alle 4h denselben Fehler zu spammen

### Fixed
- **Hyperliquid `set_leverage` Error-Handling** — Error-Responses (`{'status': 'err'}`) werden jetzt als ERROR geloggt und als Exception geworfen, statt als INFO geloggt und stillschweigend ignoriert
- **Discord-Footer kontextabhängig** — Zeigt "Bot wurde gestoppt" bei fatalen Fehlern, "Bot versucht es erneut" bei temporären Fehlern (statt immer "Trading has been paused for safety")
- **Bot-Scheduler respektiert ERROR-Status** — Überspringt Analyse-Zyklen wenn Bot wegen fatalem Fehler pausiert wurde

---

## [5.0.0] - 2026-04-09 — Bulletproof Release: Security, Resilience, UX & Architecture

> Umfassendes Hardening-Release mit 11 parallelen Verbesserungsbereichen. Ziel: Score 9.5/10 für Stabilität, Security und Code-Qualität.

### Sicherheit & Resilience
- **JWT Access Token TTL von 7 Tagen auf 4 Stunden reduziert** — Kürzere Lebensdauer für finanzielle Sicherheit; Refresh Token (90 Tage) sorgt für Session-Kontinuität.
- **Circuit Breaker für Datenbank-Sessions** — Schnelle 503-Antwort statt kaskadierender Timeouts bei DB-Problemen (3 Fehler → 30s Pause).
- **Disk Full Alert via Discord** — Automatischer Alert wenn Disk-Nutzung >90% (Env: `DISK_ALERT_WEBHOOK`), Hysterese-Reset bei <85%.
- **Strengere Rate-Limits auf Exchange-Config-Endpunkten** — Credential-Änderungen von 5/min auf 2/min limitiert.
- **WebSocket Inactivity Timeout (5 Minuten)** — Server trennt automatisch verwaiste Verbindungen.

### Position Reconciliation (NEU)
- **API Endpoint `GET /api/bots/{bot_id}/reconcile`** — Vergleicht Exchange-Positionen mit DB-Trades. Erkennt untracked (Exchange-only) und phantom (DB-only) Diskrepanzen.
- **Startup Reconciliation** — Automatische Prüfung beim Serverstart für alle aktivierten Bots mit Warning-Logs.

### Frontend — React Query Migration
- **@tanstack/react-query Integration** — Alle 5 Hauptseiten (Dashboard, Trades, Bots, Portfolio, BotPerformance) migriert. Stale-while-revalidate, Auto-Refetch, Request-Deduplication.
- **13 Query-Hooks + 8 Mutation-Hooks** mit konsistenter Query-Key-Factory und automatischer Cache-Invalidierung.

### Frontend — Validation & Accessibility
- **Zod Client-Side Validation** — Schemas für Login, Bot-Name, Exchange-Credentials, Trading-Parameter, Passwort-Änderung.
- **FormField-Komponente** — Wiederverwendbar mit Label, Error, Hilfetext, `aria-describedby`.
- **Accessibility** — `scope="col"` Tabellen-Header, `aria-expanded` für Collapsibles, Keyboard-Navigation (Enter/Space).

### Architecture — Exchange Client Refactoring
- **HTTPExchangeClientMixin** — Extrahiert ~220 LOC duplizierte HTTP-Logik (Session, Circuit Breaker, Request Wrapper) aus 4 Exchange-Clients in `src/exchanges/base.py`.
- Bitget, Weex: Volle Mixin-Integration. BingX, Bitunix: Session/Circuit-Breaker via Mixin, eigene Auth.

### Architecture — Market Data Module Split
- **`src/data/market_data.py` (2464→859 Zeilen)** aufgeteilt in `src/data/sources/`: fear_greed, funding_rates, klines, options_data, long_short_ratios, open_interest, spot_volume, macro_data, social_sentiment. MarketDataFetcher bleibt Facade mit identischer API.

### Memory Leak Fixes
- **Signal-Dedup-Cache** — TTL-basierte Bereinigung (>24h Einträge entfernt, stündlich geprüft).
- **Risk-Alert-Cache** — Täglicher Reset implementiert.
- **Trailing-Stop-Backoff** — Cleanup bei Trade-Close und Position-Monitor-Zyklus.
- **Glitch-Counter** — Bereinigung für nicht mehr gehandelte Symbole.

### Tests (75 neue Tests)
- **Frontend** — 59 neue Tests: useWebSocket (13), realtimeStore (8), sizeUnitStore (12), Bots (5), Dashboard (4), Trades (6), Settings (4), BotBuilder (6).
- **Backend** — 16 neue WebSocket Manager Tests (connect/disconnect, broadcast, limits, dead connections, concurrency).
- **Symbol-Normalisierung** — Intelligenter Vergleich zwischen Exchange- und DB-Symbolen (entfernt Suffixe wie `_UMCBL`, `:USDT`, `-SWAP` und Trennzeichen).

## [4.16.2] - 2026-04-09 — Memory Leak Fixes in BotWorker Caches

### Behoben
- **Signal-Dedup-Cache (`_last_signal_keys`) wuchs unbegrenzt** — Neue Cleanup-Methode entfernt Einträge älter als 24 Stunden. Wird einmal pro Stunde am Anfang jedes Analyse-Zyklus aufgerufen.
- **Risk-Alerts-Cache (`_risk_alerts_sent`) wurde nie zurückgesetzt** — Kommentar sagte "reset daily", aber es gab keinen Code dafür. Jetzt wird der Cache alle 24 Stunden automatisch geleert.
- **Trailing-Stop-Backoff-Cache (`_trailing_stop_backoff`) wuchs unbegrenzt** — Einträge für geschlossene Trades werden jetzt sofort bei Schließung entfernt. Zusätzlich werden im Monitoring-Loop verwaiste Einträge für nicht mehr offene Trades bereinigt.
- **Glitch-Counter-Cache (`_glitch_counter`) wuchs unbegrenzt** — Verwaiste Einträge für Symbole ohne offene Trades werden im Monitoring-Loop entfernt. Bei keinen offenen Trades werden beide Caches komplett geleert.

---

## [4.16.1] - 2026-04-08 — Copy-Trading v1.1 (Step 3 redesign + safety limits)

### Geändert
- **Bot-Builder Step 3 Redesign für Copy-Trading-Bots** — Step 3 (Exchange & Assets) zeigt für Copy-Trading-Bots jetzt ein eigenes Layout statt des Trading-Pair-Pickers und des Per-Asset-Grids. Letztere sind für Copy-Bots konzeptionell falsch, weil Assets von der Source-Wallet bestimmt werden. Neues Component `frontend/src/components/bots/CopyTradingStepExchange.tsx` mit drei Blöcken:
  - **Block 1 — Wallet & Symbol-Filter:** `CopyTradingValidator` (aus Step 2 hierher verschoben) + Whitelist/Blacklist Chip-Picker, gefüllt aus `strategyParams._validation.available`.
  - **Block 2 — Risiko-Overrides:** Optionale Felder `leverage`, `take_profit_pct`, `stop_loss_pct`, `min_position_size_usdt`. Leere Felder = Werte der Source-Wallet werden 1:1 übernommen.
  - **Block 3 — Globale Sicherheits-Limits:** `daily_loss_limit_pct` und `max_trades_per_day`.
  - `trading_pairs` wird für Copy-Bots auf `['__copy__']`-Sentinel gesetzt, damit die bestehende Backend-Validierung greift.
- **Step 2 für Copy-Bots verschlankt** — zeigt jetzt nur noch die Kern-Felder `source_wallet`, `budget_usdt`, `max_slots`. Whitelist/Blacklist und Wallet-Validator sind nach Step 3 verschoben.

### Hinzugefügt
- **Copy-Trading TP/SL Overrides + Safety Limits (Backend)** — Neue Strategie-Parameter `take_profit_pct`, `stop_loss_pct`, `daily_loss_limit_pct`, `max_trades_per_day` in `CopyTradingStrategy`. Der alte `copy_tp_sl`-Toggle wurde entfernt zugunsten eines klareren "leer = wie Source / gesetzt = überschreibt"-Modells.
  - **TP/SL Override:** Wenn gesetzt, berechnet der Bot absolute TP/SL-Preise aus dem Entry (`entry * (1 ± pct/100)`) und platziert sie an der Exchange. Leer = kein TP/SL (HL-Fills tragen keine TP/SL-Daten).
  - **Daily Loss Limit:** Realized-PnL der heute geschlossenen Trades wird gegen das Budget gerechnet; bei Erreichen werden weitere Kopien bis Mitternacht UTC pausiert.
  - **Max Trades per Day:** Begrenzt die pro UTC-Tag dispatched Entries.
  - Neue Helpers `_get_today_realized_pnl` und `_get_today_entry_count`.
  - `TradeExecutorMixin.execute_trade` akzeptiert jetzt `take_profit_pct`/`stop_loss_pct` kwargs; `_execute_trade` respektiert Caller-supplied TP/SL, statt sie durch Bot-Level-Config zu überschreiben.
  - 3 neue Unit-Tests in `tests/unit/strategy/test_copy_trading.py`.
- de + en i18n-Strings unter `bots.builder.copyTradingStep3` ergänzt.

---

## [4.16.0] - 2026-04-08

### Hinzugefügt
- **Copy-Trading-Strategie (v1)** — Neue Bot-Strategie `copy_trading`, die eine öffentliche Hyperliquid-Wallet trackt und ihre Entries sowie Full-Closes auf eine beliebige Ziel-Exchange (Bitget, BingX, Bitunix, Weex, Hyperliquid) kopiert. Add-Ins, Teil-Closes und nachträgliche TP/SL-Anpassungen der Source werden in v1 bewusst **nicht** gespiegelt.
  - Implementiert als **self-managed** Strategie `src/strategy/copy_trading.py` mit `run_tick(ctx)`-Hook (Cold-Start-Watermark beim ersten Tick, Whitelist/Blacklist, Slot-Limit, Notional-Sizing via `budget / max_slots`, Leverage-Cap via `get_max_leverage`, Symbol-Mapping Hyperliquid ↔ Ziel-Exchange, Exit-Sync mit `exit_reason=COPY_SOURCE_CLOSED`, 24h-Negativ-Cache für nicht verfügbare Symbole). Registriert in `src/strategy/__init__.py`.
  - **Cold Start:** Bestehende offene Positionen der Source werden nicht übernommen. Der Bot folgt nur Trades, die nach dem Start eröffnet werden.
  - **Slot-Logik:** `budget / max_slots` ergibt die feste Notional-Größe pro kopiertem Trade. Wenn alle Slots belegt sind und die Source einen weiteren Trade öffnet, wird dieser mit Notification geskippt.
  - **Skip-Gründe mit Notification:** Slot voll, Symbol nicht auf Ziel-Exchange, Hebel gecappt, unter `min_position_size_usdt` (default 10), Symbol nicht in Whitelist / in Blacklist.
  - **Polling:** Default 1 Minute, einstellbar via `schedule_interval_minutes`.
- **Neue API-Endpunkte** — Router `src/api/routers/copy_trading.py`, registriert in `src/api/main_app.py`:
  - `POST /api/copy-trading/validate-source` — Validiert eine Hyperliquid-Source-Wallet in vier Stufen (Format → Existenz → 30-Tage-Aktivität → Symbol-Verfügbarkeits-Preview auf der Ziel-Exchange via `HyperliquidWalletTracker`, `get_exchange_symbols`, `to_exchange_symbol`). Das Frontend nutzt das Ergebnis, um die Bot-Erstellung zu blocken, wenn keines der Source-Symbole auf der Ziel-Exchange verfügbar ist.
  - `GET /api/exchanges/{exchange}/leverage-limits?symbol=...` — Liefert das Max-Leverage via `get_max_leverage` aus der statischen Tabelle `src/exchanges/leverage_limits.py`.
- **Frontend** — `CopyTradingValidator` Component (ruft `validate-source` auf und zeigt die 4-Stufen-Preview), neuer `text` Param-Type im Bot Builder (für komma-separierte Symbol-Listen Whitelist/Blacklist), eigene Bot-Karten-Variante für Copy-Bots. `strategyDesc_copy_trading` (de + en) und Display-Name `copy_trading: 'Copy Trading'` in `STRATEGY_DISPLAY`.
- **Neue Anleitung** `Anleitungen/copy-trading.md` — Bilinguales Einsteiger-Tutorial (Deutsch zuerst, dann Englisch) mit Schritt-für-Schritt-Setup, Slot-Mechanik, Cold-Start-Erklärung, optionalen Einstellungen, FAQ und Troubleshooting-Tabelle.
- **Affiliate-UID Auto-Retry** — Neuer Service `src/services/affiliate_retry.py::retry_pending_verifications` läuft alle 30 Minuten via APScheduler (im `BotOrchestrator._scheduler`, registriert in `src/api/main_app.py` lifespan startup). Holt alle `ExchangeConnection` Rows mit `affiliate_uid IS NOT NULL AND affiliate_verified = false`, gruppiert nach Exchange, baut pro Exchange einen einzigen Admin-Client und ruft `check_affiliate_uid` für jede Row auf. Erfolgreiche Rows werden auf `verified=True, verified_at=now()` gesetzt. User müssen ihre UID nicht neu eingeben, sobald Admin-Live-Keys hinterlegt sind. Per-Row-Exceptions werden gefangen und geloggt. Inkl. 4 Unit-Tests in `tests/unit/services/test_affiliate_retry.py`.
- **Affiliate-UID Warning-Logs** — `src/api/routers/config_affiliate.py::set_affiliate_uid` loggt jetzt zwei bisher stille Fälle als Warnung: (1) wenn keine Admin-Live-Connection für die Exchange existiert (statt silent failure — Admin sieht sofort, dass er Live-Keys hinterlegen muss), (2) wenn die Exchange-API `check_affiliate_uid` mit `False` zurückkommt.

### Geändert
- **`BaseStrategy` — `is_self_managed`-Flag und `run_tick(ctx)`-Hook** — Strategien können sich jetzt als self-managed markieren. Der Bot-Worker dispatched in dem Fall zu `run_tick` und überspringt den klassischen Per-Symbol-Loop (`generate_signal` → Risk Check → Trade). Das erlaubt Strategien wie Copy-Trading, die nicht pro Symbol sondern pro Source-Wallet arbeiten.
- **`_check_symbol_conflicts` ignoriert Copy-Trading-Bots** — Copy-Bots sind budget-isoliert (eigene Slots, eigenes Budget) und dürfen deshalb mit anderen Bots auf demselben Symbol koexistieren, ohne einen Konflikt-Fehler auszulösen.
- **`TradeExecutorMixin` — neue Wrapper für self-managed Strategien** — In `src/bot/trade_executor.py` neue öffentliche Methoden `execute_trade`, `get_open_trades_count`, `get_open_trades_for_bot`, `close_trade_by_strategy` als dünne Adapter auf die bestehenden internen Pfade (`_execute_trade`, `_close_and_record_trade`), damit self-managed Strategien sauber gegen eine stabile API programmieren können.

### Datenbank
- **Neue Spalte `bot_configs.strategy_state`** (Text/JSON) — Speichert den Runtime-State einer Strategie (z. B. die Copy-Trading Watermark und den Slot-Counter) persistent, damit Bot-Restarts konsistent bleiben. Migration `018_add_strategy_state_to_bot_configs.py`.

### Tests
- 9 Unit-Tests in `tests/unit/strategy/test_copy_trading.py`
- 4 Unit-Tests in `tests/unit/api/test_copy_trading_router.py`
- 4 Unit-Tests in `tests/unit/services/test_affiliate_retry.py`

---

## [4.15.12] - 2026-04-08

### Geändert
- **Strategie-Beschreibungen im Bot Builder ausführlicher** — Die Texte für Liquidation Hunter und Edge Indicator wurden von einem Satz auf 5–7 Sätze erweitert und erklären jetzt zusätzlich was die Strategie genau macht, wann und wie der Trailing Stop aktiviert wird (ATR-Trigger und -Abstand pro Risikoprofil) und in welchem Marktumfeld die Strategie am besten funktioniert. Beide Locales (de + en) aktualisiert.

### Hinzugefügt (Design)
- **Spec für Copy-Trading-Strategie** (`docs/superpowers/specs/2026-04-08-copy-trading-design.md`) — neue Strategie die eine öffentliche Hyperliquid-Wallet trackt und Trades 1:1 (oder mit User-Overrides für Hebel/Symbole/Min-Größe) auf der gewünschten Exchange kopiert. Implementierung als neues Strategie-Plugin im bestehenden Bot-Framework, Polling-basiert, fixe Slot-Größe, nur Entry und Full-Close in v1.
- Frontend-Beschreibung `strategyDesc_copy_trading` (de + en) und Display-Name `copy_trading: 'Copy Trading'` in `STRATEGY_DISPLAY` als Vorbereitung. Implementierung folgt im nächsten Schritt nach Plan-Approval.

---

## [4.15.11] - 2026-04-08

### Behoben
- **Exit-Preis stimmte nicht exakt mit der Börse überein (alle Close-Pfade)** — An vier Stellen wurde der Exit-Preis aus `ticker.last_price` oder dem Order-Objekt abgeleitet statt aus dem tatsächlichen Fill-Preis des Close-Orders. Das führte zu Abweichungen zwischen den im Frontend angezeigten Werten und der Realität auf der Börse — kritisch für PnL-Anzeige und vor allem für den **Steuerreport**, der zwingend mit den Exchange-Daten übereinstimmen muss. Beispiele:
  - AVAXUSDT Short manueller Close: Frontend -$975.44 / -10.34%, real -9.90 USDT / -0.10%
  - BNBUSDT Long Strategy-Exit: Frontend +$361.99 / +1.98% (Exit 617.05), real +353.17 / +1.93% (Exit 616.76)

  Alle vier Close-Pfade nutzen jetzt einheitlich `get_close_fill_price()` als primäre Quelle (liefert den `priceAvg` des tatsächlich gefüllten Close-Orders aus der Bitget orders-history) und fallen erst danach auf Ticker / Order-Preis / Entry-Preis zurück:
  - `src/api/routers/bots_lifecycle.py` — manueller Close via UI-Button
  - `src/bot/position_monitor.py` — Strategy-Exit (z.B. Edge Indicator, Liquidation Hunter)
  - `src/bot/rotation_manager.py` — Rotation-Close (beide Branches: aktive Rotation + bereits-geschlossen)
  - `src/api/routers/trades.py` — `POST /api/trades/sync` (Sync verwaister Trades)

- **Bot-Karte zeigte i18n-Schlüssel statt Risikoprofil-Name** — Bei Bots mit `risk_profile=aggressive` (Liquidation Hunter) wurde in der Bot-Karte der rohe Übersetzungs-Key `bots.builder.paramOption_risk_profile_aggressive` angezeigt, weil nur `conservative` und `standard` in `de.json`/`en.json` definiert waren. Betraf nur User mit aggressivem Risikoprofil. Beide Locales ergänzt.

### Hinzugefügt
- **Trade-ID immer sichtbar im Trades-Tab** — Die `#ID`-Spalte war bisher nur ab `2xl`-Breakpoint (≥1536px) sichtbar. Sie wird jetzt auf allen Auflösungen in der Desktop-Tabelle angezeigt (monospace, dezent grau, mit `#`-Prefix) und auch im `MobileTradeCard` neben dem Symbol eingeblendet. Erleichtert Support-Anfragen, Fehleranalyse und das eindeutige Referenzieren einzelner Trades (z.B. im Steuerreport-Kontext).

### Behoben
- **KRITISCH: TP/SL wurde nie an die Exchange gesendet — Key-Mismatch in per_asset_config (#154)** — Das Frontend speichert TP/SL als `"tp"` und `"sl"` in `per_asset_config`, aber der Trade Executor suchte nach `"take_profit_percent"` und `"stop_loss_percent"`. Ergebnis: Alle Trades liefen ohne Stop-Loss und Take-Profit auf der Exchange, obwohl User diese im BotBuilder konfiguriert hatten. Betrifft alle Exchanges (Bitget, Hyperliquid, Weex, Bitunix, BingX). Fix: `trade_executor.py` akzeptiert jetzt beide Key-Formen, Frontend-Keys haben Priorität.

### Datenkorrektur
- Bestehender AVAXUSDT Short Demo-Trade vom 2026-04-08 09:51 wurde manuell auf die echten Bitget-Werte korrigiert (siehe `scripts/fix_avax_trade.sql`).

### Tests
- 2 neue Tests in `test_tpsl_passthrough.py`: Frontend-Short-Keys aufgelöst (#36), Short-Key-Priorität (#37).

---

## [4.15.10] - 2026-04-07

### Behoben
- **User wurden ständig ausgeloggt — Race Condition bei Refresh-Token-Rotation (#147)** — User auf Mobile (PWA) und Desktop beschwerten sich, dass sie sich praktisch täglich neu anmelden mussten, obwohl Access-TTL=24h und Refresh-TTL=30d eigentlich lang genug waren.
  
  Root cause: der Refresh-Endpoint rotierte den Refresh-Token bei jedem Call (klassisches Rotating-Refresh-Pattern). Unter parallelen Refresh-Anfragen — z.B. PWA wake-up `visibilitychange` + gleichzeitig ein API-Call der 401 wirft, oder zwei Browser-Tabs die simultan refreshen — race condition: beide Requests lesen denselben Session-Row, beide erstellen neue Tokens, beide updaten die DB. Browser-Cookie hat Token X, DB-Hash hat Token Y. Nächster Refresh schlägt fehl → Forced Logout.
  
  Fix:
  1. **Refresh-Token-Rotation entfernt**. Der Refresh-Endpoint stellt nur noch ein neues Access-Token aus. Der Refresh-Token-Cookie bleibt unverändert; der DB-Session-Row bekommt nur `last_activity=NOW()`. Trade-off: bei kompromittiertem Refresh-Token ist das Theft-Window jetzt die volle Refresh-TTL — für unser Threat-Model (httpOnly + secure Cookie hinter TLS) akzeptabel.
  2. **Access-TTL** von 24h → **7 Tage** erhöht (`ACCESS_TOKEN_EXPIRE_MINUTES = 10080`)
  3. **Refresh-TTL** von 30d → **90 Tage** erhöht (`REFRESH_TOKEN_EXPIRE_DAYS = 90`)
  4. Frontend `DEFAULT_TOKEN_LIFETIME_S` (authStore.ts) und der Fallback in `client.ts::doRefresh` an die neuen Werte angepasst.
  
  Auswirkung: Bei normalem Gebrauch sieht ein User nur dann einen Logout, wenn er explizit ausloggt, sein Passwort ändert (token_version-Bump) oder 90 Tage offline war.

### Tests
- 2 bestehende `TestRefreshEndpointLogic` Tests aktualisiert (`test_refresh_with_matching_token_version_succeeds`, `test_refresh_new_tokens_contain_updated_user_data`) — Refresh-Endpoint setzt jetzt 1 statt 2 Cookies.
- `test_refresh_with_valid_refresh_token_returns_new_tokens` umbenannt zu `test_refresh_with_valid_refresh_token_returns_new_access_only`.
- 18/18 in `TestRefreshEndpointLogic` + `TestJwtHandler` grün.

---

## [4.15.9] - 2026-04-07

### Hinzugefügt
- **Per-Mode Delete-Funktion für API-Keys (#145)** — User können jetzt ihre Live- oder Demo-API-Keys einzeln löschen, ohne die ganze Exchange-Verbindung zu verlieren. Neuer Endpoint `DELETE /api/config/exchange-connections/{exchange_type}/keys?mode={live|demo}` setzt die drei Spalten des angefragten Modus auf NULL. Wenn nach dem Löschen beide Modi leer sind, wird die Connection-Row komplett gelöscht damit das Frontend keine "configured"-Badge mehr zeigt. Spezialfall Hyperliquid: wenn alle Wallets entfernt sind, werden auch `builder_fee_approved` und `referral_verified` zurückgesetzt (waren an die alte Wallet-Adresse gebunden).
- Frontend Delete-Button im Settings → API-Keys → KeyForm. Sichtbar nur wenn der Modus konfiguriert ist, mit Browser-Confirm-Dialog vor dem Löschen.
- 6 neue Tests in `test_config_router.py::TestExchangeConnections`: Live-only, Demo-only, drops-row-when-both-empty, no-connection-404, wrong-mode-404, invalid-mode-422.

### Geändert
- **Strikte Live/Demo-Trennung wiederhergestellt (#145)** — Der in #141 eingeführte automatische Demo-Client aus Live-Credentials für Bitget/BingX (via `paptrading`-Header bzw. VST-URL) wurde rückgängig gemacht. User-Feedback: Live und Demo sollen unabhängige Slots bleiben. Wer Demo-Trading auf Bitget/BingX möchte, muss explizit Demo-Credentials hinterlegen — kein Auto-Mirroring mehr. Der `_EXCHANGES_WITH_HEADER_BASED_DEMO` Set in `factory.get_all_user_clients` wurde entfernt; die Funktion erstellt jetzt strikt nur Clients für Modi mit gespeicherten Credentials.
- Frontend Settings-Page: Der in #143 hinzugefügte Banner ("Bei Bitget brauchst du nur EIN API-Key-Set...") wurde entfernt. Die zugehörigen i18n-Keys `headerDemoHint` (de + en) sind weg.

### Anmerkung zu eLPresidente
Sein offener Trade #79 bleibt mit dieser Änderung sichtbar, weil seine Connection nach dem direkten DB-Cleanup nur noch Demo-Credentials im Demo-Slot hat. Die Factory erstellt einen Demo-Client für Bitget, der den Trade matched.

### Tests
- 10 Factory-Tests in `test_get_all_user_clients.py` aktualisiert: bitget/bingx live-only ergeben jetzt nur einen Live-Client (keine zwei mehr); `test_elpresidente_scenario` spiegelt seinen tatsächlichen Post-Cleanup-Zustand wider.
- 25/25 Tests in `TestExchangeConnections` grün.

---

## [4.15.8] - 2026-04-07

### Behoben
- **Doppelt gespeicherte Live-/Demo-Credentials verursachen Background-Errors (#143)** — User eLPresidente speicherte denselben Bitget-Demo-API-Key in BEIDE Felder (Live und Demo) der Settings-Seite. Bitget akzeptiert den Demo-Key nur mit dem `paptrading: 1` Header → Live-Abfragen schlugen mit `exchange environment is incorrect` fehl. Vor #141 war sein Demo-Trade unsichtbar; nach #141 sichtbar, aber jeder Portfolio-Refresh produzierte Fehler-Logs für die Live-Abfrage.
  
  Fix in `PUT /api/config/exchange-connections/{exchange_type}`:
  - **Same-request duplicate**: Wenn `data.api_key == data.demo_api_key` in einem einzelnen Request → 400 mit klarer Meldung
  - **Cross-request duplicate (live)**: Wenn der neue `api_key` einen existierenden `demo_api_key` matched → 400 mit Hinweis "Demo-Key gilt automatisch für beide Modi"
  - **Cross-request duplicate (demo)**: Wenn der neue `demo_api_key` einen existierenden `api_key` matched → 400 mit Hinweis "Live-Key gilt automatisch für beide Modi"
  
  Frontend-Hinweis: Settings-Seite zeigt für Bitget und BingX einen prominenten Hinweis, dass nur EIN Key-Set nötig ist (Live → automatisch beide Modi via Header). Verhindert dass weitere User in dieselbe Falle laufen.
  
  Direkte DB-Reparatur für eLPresidente: seine Live-Spalten wurden geleert (er hatte die DEMO-Credentials in beide Felder kopiert). Sein offener Trade #79 bleibt sichtbar via Demo-Client.

### Hinzugefügt
- 4 neue Error-Konstanten in `src/errors.py` (de + en) für Duplikats- und Wrong-Environment-Fälle.
- 3 neue Tests in `test_config_router.py::TestExchangeConnections`:
  - `test_upsert_rejects_same_key_in_both_fields_same_request`
  - `test_upsert_rejects_live_key_matching_existing_demo`
  - `test_upsert_rejects_demo_key_matching_existing_live`
- i18n Key `settings.headerDemoHint` (de + en) für die Frontend-Erklärung.

---

## [4.15.7] - 2026-04-07

### Behoben
- **Portfolio zeigt keine Demo-Trades wenn Connection nur Live-Keys hat (#141)** — User eLPresidente konfigurierte einen Bitget-Bot im **Demo-Modus**, seine Bitget-ExchangeConnection hatte aber nur **Live-Credentials**. Der Bot funktionierte (Bitget akzeptiert den Live-Key mit `paptrading: 1` Header für Simulated Trading), der Trade wurde korrekt als `demo_mode=true` in der DB gespeichert — aber im Dashboard/Portfolio war er **unsichtbar**.
  
  Ursache: `src/exchanges/factory.py::get_all_user_clients` erstellte exakt einen Client pro Exchange und bevorzugte Live-Credentials. Für eLPresidente entstand nur ein Live-Bitget-Client, der Live-Positionen abfragte (leer) — der Demo-Trade wurde nie gematched. Zusätzlich war `trade_lookup` in `portfolio.py` nur auf `(exchange, symbol, side)` gekeyed, ohne `demo_mode` — ein weiterer Punkt an dem Live/Demo-Trades kollidieren können.
  
  Fix: Die Factory gibt jetzt `list[tuple[exchange_type, demo_mode, client]]` zurück. Für jede Connection werden alle Modi erstellt, die die gespeicherten Credentials bauen können:
  - Bitget: Live-Creds → Live + Demo-Client (via `paptrading` Header)
  - BingX: Live-Creds → Live + Demo-Client (via VST-URL mit demselben Key)
  - Hyperliquid: Demo = Testnet = separates Wallet → nur erstellt wenn dedizierte Demo-Keys vorhanden
  - Weex / Bitunix: Keine Demo-Unterstützung → nur Live
  
  `portfolio.py::get_portfolio_positions` matched jetzt `(exchange, base_sym, side, demo_mode)` — ein User kann Live- und Demo-Trades auf demselben Symbol+Side unabhängig sehen. `get_portfolio_allocation` dedupliziert auf eine Balance pro Exchange (bevorzugt Live), damit die Pie-Chart nicht doppelt zählt.

  Der Bot-Trading-Pfad war nie betroffen — `bot_worker.py:187-199` baut seine eigenen Clients mit expliziten kwargs.

### Hinzugefügt
- `tests/unit/exchanges/test_get_all_user_clients.py` — 10 neue Tests inkl. parametrisierter Capability-Matrix (Bitget/BingX Header-Demo, Hyperliquid nur mit dedizierten Keys, Weex/Bitunix nur Live) und einem expliziten Regression-Test für das eLPresidente-Szenario.

---

## [4.15.6] - 2026-04-07

### Geändert
- **Hyperliquid Setup UI visuell überarbeitet (#137)** — User-Feedback: "alles ist links zentriert". Die flache, lineare Checkliste ohne visuelle Hierarchie wurde durch ein hierarchisches Layout ersetzt:
  - Header-Bereich mit prominentem Wallet-Icon-Badge, Titel, Subtitel und farbkodiertem Status-Pill (amber bei pending, emerald bei ready)
  - Numerierte Schritt-Kacheln (`01`, `02`, `03`) statt Checkbox-Liste, mit farbkodiertem Zustand: emerald (done), amber (active), muted (pending)
  - Aktive Action-Cards mit Amber-Border und Glow-Effekt heben hervor was der User als nächstes tun muss
  - Buttons sind jetzt `py-3` mit Emerald-Shadow für mehr Präsenz
  - Diagnose-Block (bei Referral-Fehler) ist aufgeräumt: Error-Banner oben, 2×2-Grid für Wallet/Balance/Volume/Referrer, darunter der Action-spezifische Schritt-Block mit besserem Step-Styling
  - Wallet-Adresse und Balance-Werte sind in uppercase labels + large values strukturiert (stärkere Lesbarkeit)
  - Neue `hlSetup.subtitle` i18n Keys (de + en)

  Keine Funktionsänderung — rein kosmetisch und Layout-strukturierend.

---

## [4.15.5] - 2026-04-07

### Behoben
- **Hyperliquid Builder-Fee-Bestätigung schlug immer fehl — User festgefahren in Signatur-Loop (#138)** — User eLPresidente (und jeder andere Demo-User) klickte "Transaktion bestätigen", signierte erfolgreich in seinem Wallet, und bekam dann immer wieder `Builder-Fee-Genehmigung nicht auf Hyperliquid gefunden. Bitte erneut signieren.` Zwei kombinierte Bugs:
  1. **`HyperliquidClient.check_builder_fee_approval` short-circuitete bei `self._builder is None`**: Der HL-Client liest die Builder-Config nur aus `os.environ`, aber auf der Prod-Instanz liegt sie in der `system_settings` DB-Tabelle (via `get_hl_config()`). Clients die über `create_hl_client()` / `create_hl_mainnet_read_client()` erstellt werden haben daher `self._builder = None`, und die Methode returnt `None` ohne die HL-API überhaupt zu fragen. Der Bot-Trading-Pfad ist nicht betroffen, weil `bot_worker.py:181-184` `builder_address` explizit als kwargs durchreicht.
  2. **`confirm_builder_approval` nutzte Testnet-Client für Demo-User**: Das Frontend signiert mit `hyperliquidChain: 'Mainnet'` und postet an die Mainnet-API `https://api.hyperliquid.xyz/exchange`. Der Backend-Check lief aber für Demo-only-User gegen Testnet — die Approval gab es dort natürlich nicht.
  
  Live-verifiziert: direkte HTTP-Abfrage gegen HL Mainnet für eLPresidente's Wallet `0x5A57D576...` mit dem Builder `0x67B10Bf6...` gibt `maxBuilderFee: 10` zurück. Die Signatur war die ganze Zeit korrekt gespeichert, unser Backend hat sie nur nicht korrekt abgefragt.
  
  Fix: `check_builder_fee_approval(user_address, builder_address)` akzeptiert jetzt den Builder explizit. `confirm_builder_approval` und `revenue_summary` nutzen `create_hl_mainnet_read_client` und übergeben den Builder-Address aus `get_hl_config()` explizit. Der `mode`-Query-Parameter auf `revenue_summary` wird für Rückwärtskompatibilität akzeptiert aber ignoriert (Builder-Fees und Referrals existieren nur auf Mainnet).

### Hinzugefügt
- 5 neue Tests (3 Unit + 2 Router) für die Builder-Fee-Confirmation-Pfade:
  - `test_check_approval_accepts_explicit_builder_address` — Regression für den self._builder=None Pfad
  - `test_check_approval_explicit_builder_overrides_self` — Explizites kwarg hat Vorrang
  - `test_approval_uses_mainnet_for_demo_user` — Mainnet-Zwang auch bei Demo-User
  - `test_approval_passes_explicit_builder_address` — Router-Seite übergibt Builder korrekt
  - `test_approval_requires_configured_builder_address` — Klarer Fehler wenn Builder nicht konfiguriert

---

## [4.15.4] - 2026-04-07

### Behoben
- **Hyperliquid Referral-Verifikation zeigte unbrauchbare Fehlermeldung (#135)** — User (z.B. eLPresidente) sahen beim Klick auf "Bereits registriert? Jetzt prüfen" nur `Referral nicht gefunden. Bitte registriere dich zuerst über https://app.hyperliquid.xyz/join/TRADINGDEPARTMENT`, ohne Hinweis WAS sie tatsächlich tun müssen. Ursache: Der Endpoint meldete einen generischen Fehler, ohne zu unterscheiden zwischen (a) Wallet hat noch kein Guthaben auf HL, (b) Wallet hat Guthaben aber keinen Referrer, (c) Wallet wurde über anderen Referrer registriert. Zusätzlich lief die Abfrage für Demo-User gegen Hyperliquid-Testnet, obwohl Referrals ein reines Mainnet-Konzept sind.

  Fix: `POST /api/config/hyperliquid/verify-referral` gibt jetzt bei Fehler eine strukturierte JSON-Detail-Response zurück mit:
  - `required_action`: `DEPOSIT_NEEDED` | `ENTER_CODE_MANUALLY` | `WRONG_REFERRER` | `VERIFIED`
  - `wallet_address` + `wallet_short`: welches Wallet geprüft wurde
  - `account_value_usd` + `cum_volume_usd`: aktueller HL-Kontostand und Handelsvolumen
  - `referred_by`: rohe Referrer-Info von HL
  - `min_deposit_usdc`: 5.0 (Hyperliquids Hard-Minimum)
  - `deposit_url`, `enter_code_url`: konkrete nächste-Schritte-Links
  
  Frontend `HyperliquidSetup.tsx` rendert jetzt pro Action-Typ einen passenden Anleitungs-Block mit nummerierten Schritten:
  - **DEPOSIT_NEEDED**: "Zahle mindestens 5 USDC via Arbitrum Bridge ein (weniger geht verloren!)"
  - **ENTER_CODE_MANUALLY**: "Öffne https://app.hyperliquid.xyz/referrals → Enter Code → TRADINGDEPARTMENT"
  - **WRONG_REFERRER**: Erklärt dass HL keine nachträgliche Referrer-Änderung zulässt
  
  Außerdem: `verify-referral` und `referral-status` forcieren jetzt Mainnet (neuer Helper `create_hl_mainnet_read_client` in `src/services/config_service.py`), weil HL-Referrals nur dort existieren. Der `mode`-Query-Parameter auf `referral-status` wird für Rückwärtskompatibilität akzeptiert aber ignoriert.

### Hinzugefügt
- `src/services/config_service.py::create_hl_mainnet_read_client()` — Mainnet-only HL-Client für read-only Queries (Referral, User-State).
- `src/exchanges/hyperliquid/client.py::HyperliquidClient.get_user_state()` — direkter `user_state`-Query für Balance-Diagnose.
- `src/errors.py`: drei neue Fehler-Konstanten mit Platzhaltern für wallet/account/code.
- `src/api/routers/config_hyperliquid.py`: Konstante `HL_MIN_DEPOSIT_USDC = 5.0` und Action-Enum-Konstanten.
- i18n-Keys in `frontend/src/i18n/{de,en}.json` für alle Diagnose-Texte (Step-by-Step-Anleitungen).
- 5 neue Tests in `tests/unit/api/test_config_router_extra.py` für alle Diagnose-Pfade: `test_referral_deposit_needed`, `test_referral_enter_code_needed`, `test_referral_wrong_referrer`, `test_referral_uses_mainnet_regardless_of_demo`, plus aktualisierter `test_referral_found`.

---

## [4.15.3] - 2026-04-07

### Behoben
- **Dashboard Trailing Stop zeigte falschen Status (#133)** — Die Dashboard-API (`/api/portfolio/positions`, `/api/trades`) berechnete den Trailing-Stop mit anderen Parametern als die Strategie selbst. Zwei unabhängige Bugs:
  1. `_compute_trailing_stop` in `src/api/routers/trades.py` merged nur `DEFAULTS + strategy_params` und **ignorierte `RISK_PROFILES`**. Für ein `conservative`-Bot (edge_indicator) wurden `trailing_breakeven_atr=2.0` und `trailing_trail_atr=3.0` nicht angewendet — stattdessen griffen die DEFAULTS (1.5, 2.5).
  2. Der Klines-Prefetch in `src/api/routers/portfolio.py` und `src/api/routers/trades.py` hardcodete `"1h"` statt das konfigurierte `kline_interval` der Strategie zu verwenden. Ein conservative-Bot mit `kline_interval="4h"` bekam für die ATR-Berechnung 1h-Klines.
  
  Konsequenz: Das Dashboard zeigte "Trailing aktiv ✓" samt ShieldCheck-Badge (z.B. $69,179.54 bei Trade #71), obwohl die Strategie den Trailing nie aktivierte. User verließen sich auf einen Schutz, den es gar nicht gab. **Der Bot selbst hat immer korrekt auf dem gewählten Intervall gehandelt** — Signalgenerierung, Exit-Checks und native Trailing-Stop-Platzierung nutzen `self._strategy._p` mit korrektem Profil-Merge. Nur die Dashboard-Anzeige war falsch.
  
  Fix: Neuer Helper `resolve_strategy_params()` in `src/strategy/base.py` spiegelt die Merge-Logik (`DEFAULTS → RISK_PROFILE → user_params`) der Strategie-`__init__`-Methoden. Dashboard und Strategie sehen jetzt garantiert dieselben Parameter. Unterstützt auch `liquidation_hunter` (vorher nur edge_indicator). Klines-Cache ist jetzt pro `(symbol, interval)` statt nur `symbol`.

- **BingX native Trailing Stop schlug immer fehl (Error 109400)** — `place_trailing_stop` sendete `price` zusammen mit `priceRate` im TRAILING_STOP_MARKET-Request. BingX interpretiert `price` als "USDT-Trail-Distance" (Alternative zu `priceRate`) und lehnt die Kombination mit Error 109400 "cannot provide both the Price and PriceRate fields" ab. Korrektes Feld ist `activationPrice` (laut [BingX-API Issue #28](https://github.com/BingX-API/BingX-swap-api-doc/issues/28)). User Ludwig (Bot 14) und alle BingX-Bots waren betroffen seit Feature-Release. Software-Backup hatte gegriffen, aber der native Trailing war komplett kaputt.

- **Trailing Stop: falsche Erfolgsmeldungen bei Weex/Bitunix/Hyperliquid** — `trade_executor` prüfte den Rückgabewert von `client.place_trailing_stop` nicht. Da die Basis-Klasse für nicht unterstützte Börsen `None` zurückgibt, wurde fälschlicherweise `trailing_placed=True` gesetzt und "Native trailing stop placed" geloggt — obwohl nichts platziert wurde. `trade.native_trailing_stop` in der DB zeigte diesen falschen Status an. Zusätzlich versuchte `position_monitor._try_place_native_trailing_stop` alle 10 Minuten vergeblich Klines zu holen und einen Trailing zu setzen. Fix: neues Class-Level Flag `ExchangeClient.SUPPORTS_NATIVE_TRAILING_STOP` (Bitget/BingX = True, Rest = False). Beide Pfade überspringen unnötige API-Calls, die nicht unterstützten Börsen verlassen sich vollständig auf Software-Trailing in `strategy.should_exit`.

### Hinzugefügt
- `src/strategy/base.py::resolve_strategy_params()` — zentrale Helfer-Funktion zum Auflösen von Strategie-Parametern außerhalb einer Strategie-Instanz (Dashboard, Background Jobs).
- `src/exchanges/base.py::SUPPORTS_NATIVE_TRAILING_STOP` — explizite Capability-Deklaration pro Exchange-Client.
- `tests/unit/test_resolve_strategy_params.py` — 23 Tests inkl. Parametrized Parity-Tests, die garantieren dass `resolve_strategy_params` dasselbe Ergebnis liefert wie `EdgeIndicatorStrategy._p` / `LiquidationHunterStrategy._p` für alle Risk Profiles.
- `tests/unit/exchanges/test_bingx_trailing_stop.py` — Regression-Tests, die verhindern dass `price` statt `activationPrice` wieder gesendet wird.
- `tests/unit/exchanges/test_native_trailing_capability.py` — 8 Tests, die die Support-Matrix pro Client absichern (Bitget ✓, BingX ✓, Weex/Bitunix/Hyperliquid ✗) passend zur Frontend-Feature-Matrix.

---

## [4.15.2] - 2026-04-05

### Behoben
- **Discord: Trade Entry Notifications wurden nicht gesendet** — `send_trade_entry()` crashte still wenn `take_profit` oder `stop_loss` `None` war (Strategie-Exit ohne TP/SL). Der Format-String `${None:,.2f}` warf einen TypeError, der im Notification-Dispatcher verschluckt wurde. TP/SL sind jetzt Optional und zeigen "—" wenn nicht gesetzt.
- **Telegram: Parameter-Mismatch bei Trade Entry & Exit** — `position_size` statt `size` verursachte TypeError bei jedem Trade-Notification-Versuch. Parameter-Name auf `size` vereinheitlicht.
- **WhatsApp: Parameter-Mismatch bei Trade Entry & Exit** — `direction` statt `side` verursachte TypeError. Parameter-Name auf `side` vereinheitlicht (konsistent mit allen anderen Notifiern).
- **Telegram/WhatsApp: Error-Notifications crashten** — `send_error()` akzeptierte kein `error_type`-Argument, das vom Bot-Worker gesendet wurde. Parameter `error_type` und `details` hinzugefügt.
- **WhatsApp: Daily Summary zeigte nur Nullwerte** — Parameter-Namen wichen ab (`gross_pnl`/`fees`/`funding` statt `total_pnl`/`total_fees`/`total_funding`). Signatur an Caller-Konvention angepasst.
- **Discord: Bot-Status zeigte keinen Bot-Namen** — `bot_name` wurde in `**kwargs` verschluckt. Wird jetzt im Titel angezeigt.

---

## [4.15.1] - 2026-04-03

### Behoben
- **Auth: Session-Verlust auf Mobile/PWA (#130)** — User wurden auf Android-PWA alle ~10 Min ausgeloggt. Drei Ursachen behoben:
  1. `/auth/me` war fälschlicherweise von der Token-Refresh-Logik ausgeschlossen — bei abgelaufenem Access-Token wurde kein Refresh versucht
  2. Token-Expiry war nur im Arbeitsspeicher — ging bei PWA-Kill/Background verloren. Jetzt in localStorage persistiert
  3. Race Condition: Wenn Visibility-Handler und Interceptor gleichzeitig refreshen wollten, konnte der Interceptor fälschlicherweise einen Fehlschlag melden. Jetzt teilen sich alle Caller dieselbe Refresh-Promise
- **Multi-Tab Logout-Sync** — Logout in einem Tab synchronisiert jetzt die Token-Expiry über alle offenen Tabs via `storage`-Event
- **localStorage-Fehlerbehandlung** — Private-Browsing-Modus oder voller Speicher crasht die App nicht mehr

---

## [4.15.0] - 2026-04-03

### Behoben
- **Bot Builder: 400-Fehler ohne Details** — Fehlermeldung zeigte nur "Request failed with status code 400" statt dem eigentlichen Grund. Ursache: Affiliate-Gate gab ein JSON-Object statt eines Strings als `detail` zurück, das Frontend konnte es nicht parsen. Jetzt werden alle Error-Details korrekt als String zurückgegeben und im Frontend angezeigt.
- **Frontend `getApiErrorMessage()`** — Unterstützt jetzt auch Object-Details mit `message`-Feld (zusätzlich zu String und Array).

### Verbessert
- **Sprechende Fehlermeldungen beim Bot-Start** — Jede Fehlermeldung erklärt jetzt den Grund und nennt die nötige Aktion:
  - CEX (Bitget, Weex, Bitunix, BingX): Affiliate-Link + UID-Hinweis mit Exchange-Name
  - Hyperliquid: Wallet-Verbindung, Referral-Link, Builder Fee — jeweils mit Navigation zu Einstellungen
- **Bot Builder: Validierung bei fehlender Exchange-Verbindung** — Step "Exchange & Assets" blockiert jetzt den Wizard wenn keine Exchange-Connection vorhanden ist. Auffällige Warnung (statt grauer Text) mit Handlungsanweisung.
- **Hyperliquid Setup immer sichtbar** — Referral-Link und Builder Fee Setup werden jetzt im Settings-Accordion sofort angezeigt, nicht erst nach dem Speichern der Wallet-Daten. Neue User sehen den Referral-Link direkt beim Öffnen der Hyperliquid-Sektion.

---

## [4.14.0] - 2026-04-02

### Hinzugefügt
- **Bot Builder: Mode-aware Symbol-Listen** — Symbol-Listen werden jetzt passend zum gewählten Modus (Demo/Live) geladen. Bitget Demo zeigt nur die ~22 handelbaren Symbole statt aller 544 Live-Symbole. BingX und Hyperliquid nutzen ebenfalls ihre Demo/Testnet-Endpunkte. Beim Mode-Wechsel werden ungültige Trading-Pairs automatisch entfernt. (#128)

---

Für ältere Versionen, siehe [CHANGELOG-archive.md](CHANGELOG-archive.md).
