# Changelog

Alle wichtigen Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

> **Hinweis:** Dieser Changelog wird automatisch bei jeder Änderung aktualisiert.

---

## [Unreleased]

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

### Added
- **ARCH-H1 Phase 0 PR-1 — `src/bot/components/` Scaffolding (#266)**: Vorbereitungs-PR für die Mixin→Composition-Migration des `BotWorker`. Neues Paket `src/bot/components/` mit drei Dateien: `protocols.py` (vier `@runtime_checkable` `Protocol`-Stubs — `TradeExecutorProtocol`, `PositionMonitorProtocol`, `TradeCloserProtocol`, `NotifierProtocol` — die die öffentliche Oberfläche jeder zukünftigen Komponente pre-deklarieren), `deps.py` (`BotWorkerDeps`-Dataclass als shared-Handle-Bundle für spätere Komponenten-Constructors: `bot_config`, `client`, `symbol_locks` per-Instance via `field(default_factory=dict)`, `user_trade_lock`), `__init__.py` (Re-Export der fünf Symbole). Zero-Behavior-Change: `BotWorker` erbt weiterhin von allen fünf Mixins, kein Consumer konstruiert bislang `BotWorkerDeps`. 8 Smoke-Tests in `tests/unit/bot/components/test_scaffolding.py` guarden: alle Exports in `__all__`, `BotWorkerDeps()` ohne Args konstruierbar, mutable-default-Regression (`symbol_locks` per-Instance), alle vier Protocols wirklich `runtime_checkable` + korrekte Ablehnung unvollständiger Duck-Types. Weitere Phasen der Extraktion (Notifier, HyperliquidGates-Shim-Drop, TradeCloser, PositionMonitor, TradeExecutor) folgen jeweils als eigene PRs mit Canary-Deploy — Detailplan in `Anleitungen/refactor_plan_bot_worker_composition.md`.
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
- Klassifizierer für exit_reason refactored (#193, Epic #188): liest jetzt Bitgets orders-plan-history (via #191 readback) als Source of Truth für was die Position geschlossen hat. 9 neue präzise Reason-Codes (TRAILING_STOP_NATIVE/SOFTWARE, TAKE_PROFIT/STOP_LOSS_NATIVE, MANUAL_CLOSE_UI/EXCHANGE, STRATEGY_EXIT, LIQUIDATION, FUNDING_EXPIRY, EXTERNAL_CLOSE_UNKNOWN). `RiskStateManager.classify_close()` ersetzt den heuristischen Klassifizierer in `position_monitor._handle_closed_position`; Heuristik nur noch als Fallback bei API-Fail. Verhindert Anti-Pattern B (heuristischer Klassifizierer ohne Exchange-Probe). Strategy-Exit-Hinweise via `note_strategy_exit()` überschreiben Exchange-Readback (interne Signale gewinnen).
- PUT /api/trades/{id}/tp-sl refactored auf RiskStateManager (#192, Epic #188): 2-Phase-Commit pro Leg (TP/SL/Trailing einzeln), Response enthält post-readback State je Leg, Partial-Success möglich, Idempotency-Key support. Alter Pfad bleibt parallel über Feature-Flag risk_state_manager_enabled (default off). Anti-Pattern A (probe-but-don't-write) und C (cancel-DEBUG) endgültig verhindert.

### Fixed
- **Manual-Close routet durch den TradeCloser (#275)**: `POST /api/bots/{bot_id}/close-position/{symbol}` in `src/api/routers/bots_lifecycle.py` duplizierte die Close-Logik als reiner Inline-Write — ohne Fee/Funding/Builder-Fee-Capture, ohne Discord/Telegram-Notification, ohne WebSocket-Broadcast, ohne `EVENT_TRADE_CLOSED` auf dem SSE-Bus und ohne `RiskManager.record_trade_exit`. Fix: `TradeCloserMixin._close_and_record_trade` aus `src/bot/trade_closer.py` wurde in eine freistehende async-Funktion `close_and_record_trade(trade, exit_price, reason, *, bot_config_id, config, risk_manager, send_notification, fees, funding_paid, builder_fee, strategy_reason)` extrahiert; die Mixin-Methode delegiert jetzt auf den Helper, so dass Bot-Worker-Pfad und API-Pfad garantiert denselben Code durchlaufen. Der Manual-Close-Endpoint holt Fees via `client.get_trade_total_fees`, Funding via `get_funding_fees`, Builder-Fee via `calculate_builder_fee` (wo vorhanden — Hyperliquid) und ruft dann `close_and_record_trade` mit `exit_reason="MANUAL_CLOSE"`. Wenn der Bot läuft, werden der `_risk_manager` und der `_send_notification`-Dispatcher des Live-`BotWorker` aus `orchestrator._workers[bot_id]` wiederverwendet — so landen Daily-Stats im selben In-Memory-`DailyStats`-Objekt das der Bot verwendet. Bei gestopptem Bot wird eine DB-backed `RiskManager`-Instanz gebaut (`load_stats_from_db` + `_save_stats_to_db`) und ein standalone `build_standalone_dispatcher(config, bot_id)` aus `src/bot/notifications.py` für Discord/Telegram-Dispatch. SQLite-Tz-Naivität in `close_and_record_trade` abgefangen (`entry_time.replace(tzinfo=utc)` wenn naiv) — verhindert `can't subtract offset-naive and offset-aware datetimes` unter dem Integrationstest. Neuer Integrationstest `tests/integration/test_manual_close_full_flow.py` mit 6 Cases: 200-OK + PnL-Response, fee/funding/builder-Fee auf Trade-Row, Discord+Telegram `send_trade_exit` tatsächlich aufgerufen, WS-Manager `broadcast_to_user("trade_closed", ...)`, SSE-Bus `EVENT_TRADE_CLOSED` emittiert, und Live-Worker-Fall (wenn `orchestrator._workers[bot_id]` existiert wird dessen `_risk_manager.record_trade_exit` benutzt statt einer frischen Instanz).
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
