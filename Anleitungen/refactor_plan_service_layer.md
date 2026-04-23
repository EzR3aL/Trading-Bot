# Refactor-Plan: Service-Layer-Extraktion aus `routers/trades.py` (ARCH-C1)

> **Status:** Planung · **Risiko:** Hoch (Live-Trading-Pfad) · **Scope:** Backend · **Abhängigkeiten:** keine offenen

---

## 1. Problem

`src/api/routers/trades.py` ist auf 1350 Zeilen gewachsen und mischt drei Verantwortungen in einer Datei:

| Schicht | Aufgabe | Beispiel |
|---------|---------|----------|
| HTTP-Adapter | Request parsen, Auth prüfen, Response shapen | `Depends(get_current_user)`, Pydantic-Modelle |
| Business-Logik | Trade-Synchronisation, Risk-Readback, Filter-Aggregation | `POST /sync`, Portfolio-Aggregation |
| Persistenz | DB-Queries mit Joins, Exchange-Client-Aufrufe | `select(TradeRecord).where(...)` direkt im Handler |

Konsequenzen, die uns messbar Zeit kosten:

1. **Testing:** Jeder Handler muss über `httpx.AsyncClient` + `FakeDB` getestet werden. Unit-Tests für die Business-Rules sind unmöglich, ohne einen FastAPI-Stack hochzuziehen.
2. **Coverage-Gap:** Die kritische `POST /api/trades/sync`-Route (~250 LOC Handler) hat keinen direkten Business-Logik-Test — nur einen End-to-End-Happy-Path.
3. **Single Responsibility:** Änderungen am Risk-Readback erzwingen Änderungen am Router-File; Merge-Konflikte bei parallelem Arbeiten garantiert.
4. **Kopplung zu RiskStateManager:** Drei Routen (`POST /sync`, `PUT /{id}/tp-sl`, neue Manual-Close-Wiring) duplizieren RSM-Integration statt einen gemeinsamen Service-Shim zu nutzen.

---

## 2. Zielarchitektur

```
src/
├── api/
│   └── routers/
│       └── trades.py            # ~300 LOC — nur Adapter
└── services/                    # neu
    ├── __init__.py
    ├── trades_service.py        # Trade-CRUD, Filter, Pagination, Export
    ├── portfolio_service.py     # Positions-Aggregation, PnL, Exposure
    ├── trade_sync_service.py    # POST /sync-Pipeline (Exchange → DB-Reconciliation)
    └── tpsl_service.py          # TP/SL/Trailing-Intent-Dispatch (thin wrapper um RiskStateManager)
```

**Trennschnitte:**

- Jeder Service ist eine Python-Klasse mit `__init__(self, db: AsyncSession, user: User)` (oder `user_id` wenn sauberer).
- Keine `HTTPException` in Services — Services werfen Domain-Exceptions (`TradeNotFound`, `NotOwnedByUser`, `SyncInProgress`), der Router mappt sie auf HTTP-Status.
- Services kennen **keine** FastAPI-Primitiven (`Request`, `Response`, `BackgroundTasks`). Async-Effekte (z.B. SSE-Emit) gehen als Callback-Parameter rein.
- Response-Dataclasses im Service-Modul, Pydantic-Modelle bleiben im Router.

**Begründung gegen Alternativen:**

- *Ein grosser `TradeService`:* nein — 1350 LOC in einer Klasse ist derselbe Smell wie 1350 LOC in einem Router.
- *Repository + Use-Case-Pattern (DDD):* zu schwer für unseren Skalierungspunkt. Wir bleiben bei Service = Use-Case-Gruppe.

---

## 3. Call-Site-Inventar

Rohdaten aus `grep '^@router\.' src/api/routers/trades.py` (mit Ziel-Service):

| Endpoint | LOC (ca.) | Ziel-Service | Methoden-Name |
|----------|-----------|--------------|---------------|
| `GET /api/trades` (Line 158) | 140 | `TradesService` | `list_trades(filters, pagination) -> TradeListResult` |
| `GET /api/trades/filter-options` (Line 303) | 70 | `TradesService` | `get_filter_options() -> FilterOptions` |
| `POST /api/trades/sync` (Line 377) | 250 | `TradeSyncService` | `sync_user_trades(user_id, exchange, since) -> SyncReport` |
| `GET /api/trades/{trade_id}` (Line 631) | 240 | `TradesService` + `PortfolioService` | `get_trade_detail(trade_id)`, `enrich_with_live_state(trade)` |
| `GET /api/trades/{trade_id}/risk-state` (Line 870) | 190 | `TpSlService` | `get_risk_state(trade_id) -> RiskStateSnapshot` |
| `PUT /api/trades/{trade_id}/tp-sl` (Line 1062) | 290 | `TpSlService` | `apply_tpsl_intent(trade_id, intent) -> PartialResult` |
| `GET /api/trades/stream` (SSE) | 40 | `TradesService` | `subscribe_events(user_id) -> AsyncIterator[Event]` |

**Portfolio/Positions (`routers/portfolio.py`, 14921 bytes)** folgt derselben Logik und bekommt `PortfolioService` — separater Call-Site-Schnitt, aber gleicher Plan.

**Bots-Router (`routers/bots.py`, 47598 bytes)** hat eigene Business-Logik (Lifecycle, Rotation) — außerhalb dieser Extraktion, Folge-Refactor.

---

## 4. Migrations-Reihenfolge (small PRs)

**Regel:** Jeder Schritt ist ein eigener Commit mit grüner Test-Suite, und jeder PR ist einzeln deploybar. Kein Big-Bang.

### Phase 1 — Vorbereitung (risikoarm)
**PR-1:** `src/services/__init__.py` + leere Service-Module + Domain-Exceptions (`src/services/exceptions.py` mit `TradeNotFound`, `NotOwnedByUser`, `SyncInProgress`, `InvalidTpSlIntent`).
- Keine Verhaltensänderung. CI muss grün sein.

**PR-2:** Characterization-Tests für die existierenden Handler.
- Pro Route: 2–4 Tests (Happy-Path + 1–2 Fehlerfälle) die das aktuelle Verhalten einfrieren.
- Quelle: existierende Integration-Tests durchforsten; Lücken füllen.
- **Blocker:** Wenn hier Lücken zu gross sind, extrahieren wir nicht — Coverage muss >80% auf jedem Handler sein BEVOR wir ihn anfassen.

### Phase 2 — Read-only Services (geringes Risiko)
**PR-3:** `TradesService.list_trades` + `get_filter_options` extrahieren.
- Handler wird Dünnschicht: Filter parsen → `service.list_trades(...)` → Response mappen.
- Tests aus PR-2 müssen ohne Änderung grün sein.
- Neue Unit-Tests für den Service selbst (ohne FastAPI-Stack).

**PR-4:** `TradesService.get_trade_detail` + `subscribe_events`.

**PR-5:** `PortfolioService.get_positions` + `get_exposure` (aus `routers/portfolio.py`).

### Phase 3 — Write-Services (mittleres Risiko)
**PR-6:** `TpSlService.get_risk_state` + `apply_tpsl_intent`.
- `TpSlService` hält als einzige Klasse einen `RiskStateManager`-Ref — kein anderer Service nutzt RSM direkt.
- Neue Unit-Tests mit gemocktem `RiskStateManager` (protokollbasiert, nicht Struktur-Mock).
- **Rollout:** Feature-Flag `SERVICE_LAYER_TPSL_ENABLED` (default off) — Router schaltet dynamisch um. Nach einer Woche Prod-Beobachtung entfernen wir den alten Pfad.

### Phase 4 — Sync-Pipeline (höchstes Risiko)
**PR-7:** `TradeSyncService.sync_user_trades`.
- Die `POST /sync`-Route ist der grösste Block (~250 LOC, ruft 3 Exchange-Clients, updated `TradeRecord.fees_total`, normalisiert Fills).
- **Aufteilung:** extrahieren in 3 Submethoden: `_fetch_remote_trades`, `_merge_into_local`, `_recompute_aggregates`.
- Erste Extraktion mit 1:1-Übersetzung. Refactoring der Submethoden erst nach grünem PR-7 in einem separaten PR-8.
- **Rollout:** Feature-Flag `SERVICE_LAYER_SYNC_ENABLED` (default off). Auf dem VPS zuerst für `user_id=1` (Admin-Account) aktivieren, zwei Trade-Cycles beobachten, dann flächendeckend.

### Phase 5 — Cleanup
**PR-9:** Feature-Flags entfernen, tote Router-Pfade löschen.
**PR-10:** `routers/trades.py` muss `<350 LOC` sein. Wenn nicht, ist die Extraktion unvollständig — nachbessern.

---

## 5. Test-Strategie

**Vor jedem Extract:** Characterization-Test schreibt den aktuellen Output 1:1 fest.

**Nach jedem Extract:** Zwei Test-Ebenen:

1. **Service-Unit-Test** (schnell, kein FastAPI, kein HTTP):
   ```python
   async def test_list_trades_filters_by_symbol(session: AsyncSession, fixture_trades):
       svc = TradesService(db=session, user=fixture_trades.owner)
       result = await svc.list_trades(TradeFilters(symbol="BTCUSDT"))
       assert len(result.items) == 3
       assert all(t.symbol == "BTCUSDT" for t in result.items)
   ```

2. **Router-Integration-Test** (der alte Characterization-Test aus PR-2 bleibt erhalten).

**Mock-Strategie für RSM:** `TpSlService` bekommt `risk_state_manager` als Constructor-Arg; Tests injizieren Fake. Protokoll-basiert:
```python
class _FakeRsm:
    async def apply_intent(self, trade_id, leg, **kwargs):
        self.calls.append((trade_id, leg, kwargs))
        return FakeApplyResult(status="confirmed", order_id="x-123")
```

**Coverage-Ziel:** 85%+ pro Service-Klasse. Router bleibt bei existierender Coverage.

---

## 6. Risiken

| Risiko | Wahrscheinlichkeit | Impact | Mitigation |
|--------|-------------------|--------|------------|
| Session-Leak: Service hält DB-Session länger als Request | mittel | Background-Task crasht still | Service-Instanz ist per-Request, Constructor nimmt bestehende Session, kein eigenes `AsyncSessionMaker` |
| Circular Import: Services importieren aus `bot/`, `bot/` importiert aus `services/` | mittel | App startet nicht | TYPE_CHECKING-Imports für Type-Hints; keine Laufzeit-Imports von `src.bot` in `src.services` außer als Callable-Dependency |
| Lock-Reihenfolge ändert sich | niedrig | Race zwischen Bot-Worker und API | RSM-Locks bleiben bei RSM; Service ruft RSM, fügt keine neuen Locks hinzu |
| SSE-Stream bricht während Extract | mittel | Frontend fällt auf 5s-Polling zurück (schon gebaut) | Stream-Extraktion zuletzt; dedizierter Test in PR-4 |
| Performance-Regression durch zusätzliche Methoden-Aufrufe | niedrig | <1ms pro Request | Nicht proaktiv optimieren, messen nach PR-5 im Staging |
| Partial-Rollback: Feature-Flag an, Bug, Zurückschalten | hoch erwartet | Zwei Pfade temporär live | Flag wird jeweils nur eine PR lang genutzt; nicht dauerhaft |

---

## 7. Rollback-Punkte

Jede Phase hat einen klaren Rollback:

- **Phase 1–2:** `git revert <PR-SHA>` genügt, keine DB-Änderungen.
- **Phase 3–4:** Feature-Flag auf `false` zurücksetzen in ENV, Rollback ohne Redeploy. Wenn auch der alte Pfad kaputt geht: vollständiger Revert + neuer Build.
- **Phase 5:** erst starten wenn Phase 3+4 zwei Wochen grün waren. Wenn dann zurück, ist der alte Pfad bereits gelöscht — Vollständiger Revert auf Tag vor Phase 5.

---

## 8. Definition-of-Done

- [ ] `routers/trades.py` < 350 LOC
- [ ] `routers/portfolio.py` < 250 LOC
- [ ] `src/services/` enthält 4 Service-Module mit jeweils eigener Test-Datei
- [ ] Service-Coverage > 85%
- [ ] Alle Feature-Flags entfernt
- [ ] Keine Regression in den E2E-Tests
- [ ] Prometheus-Metriken (`risk_intent_duration_seconds`, `trade_sync_duration_seconds` neu) zeigen keine Erhöhung der p95-Latenz über 10 %

---

## 9. Nicht in diesem Scope

- `routers/bots.py` (47598 bytes) — eigener Bot-Lifecycle-Service, separater Plan
- Auth / Users — wird demnächst in anderes Repo migriert, anfassen wäre verlorene Arbeit
- Broadcast/Notification-Pfade — klein genug, bleiben in ihren Routern
- `BotWorker`-Mixin-Decomposition — siehe `refactor_plan_bot_worker_composition.md`

---

## 10. Verwandte Arbeit

- RiskStateManager 2-Phase-Commit (#190) — Services bauen darauf auf
- Audit Scheduler (#216 §2.4) — läuft eigenständig, nicht betroffen
- WebSocket Manager (#240) — eigenständig, Services emittieren in den EventBus (`src/bot/event_bus.py`), nicht direkt ins WS

---

# Refactor Plan: Service Layer Extraction from `routers/trades.py` (ARCH-C1)

> **Status:** Planning · **Risk:** High (live-trading path) · **Scope:** Backend · **Blockers:** none

---

## 1. Problem

`src/api/routers/trades.py` has grown to 1350 lines and mixes three concerns in a single file:

| Layer | Responsibility | Example |
|-------|----------------|---------|
| HTTP adapter | Parse request, check auth, shape response | `Depends(get_current_user)`, Pydantic models |
| Business logic | Trade sync, risk readback, filter aggregation | `POST /sync`, portfolio aggregation |
| Persistence | DB queries with joins, exchange client calls | `select(TradeRecord).where(...)` inline |

Concrete consequences we pay for every week:

1. **Testing:** Every handler has to be tested through `httpx.AsyncClient` + `FakeDB`. Unit-testing business rules without booting FastAPI is impossible.
2. **Coverage gap:** The critical `POST /api/trades/sync` handler (~250 LOC) has no direct business-logic test — only one happy-path E2E.
3. **Single responsibility:** Changes to risk-readback force edits in the router file; merge conflicts during parallel work are guaranteed.
4. **RiskStateManager coupling:** Three routes duplicate RSM integration instead of sharing a single service shim.

---

## 2. Target Architecture

```
src/
├── api/
│   └── routers/
│       └── trades.py            # ~300 LOC — adapters only
└── services/                    # new
    ├── __init__.py
    ├── trades_service.py        # trade CRUD, filters, pagination, export
    ├── portfolio_service.py     # position aggregation, PnL, exposure
    ├── trade_sync_service.py    # POST /sync pipeline
    └── tpsl_service.py          # TP/SL/trailing intent dispatch (thin RSM wrapper)
```

**Cut rules:**

- Every service is a class with `__init__(self, db: AsyncSession, user: User)` (or `user_id` if cleaner).
- No `HTTPException` in services — services raise domain exceptions (`TradeNotFound`, `NotOwnedByUser`, `SyncInProgress`), router maps them to HTTP status codes.
- Services know **no** FastAPI primitives (`Request`, `Response`, `BackgroundTasks`). Async effects (e.g., SSE emit) come in as callback parameters.
- Response dataclasses live in the service module, Pydantic models stay in the router.

**Why not the alternatives:**

- *One big `TradeService`:* same 1350-LOC smell, different file.
- *Repository + Use-Case pattern (DDD):* overkill at our scale. Service = use-case group is enough.

---

## 3. Call-Site Inventory

| Endpoint | LOC (approx.) | Target service | Method |
|----------|--------------|----------------|--------|
| `GET /api/trades` (line 158) | 140 | `TradesService` | `list_trades(filters, pagination) -> TradeListResult` |
| `GET /api/trades/filter-options` (line 303) | 70 | `TradesService` | `get_filter_options() -> FilterOptions` |
| `POST /api/trades/sync` (line 377) | 250 | `TradeSyncService` | `sync_user_trades(user_id, exchange, since) -> SyncReport` |
| `GET /api/trades/{trade_id}` (line 631) | 240 | `TradesService` + `PortfolioService` | `get_trade_detail`, `enrich_with_live_state` |
| `GET /api/trades/{trade_id}/risk-state` (line 870) | 190 | `TpSlService` | `get_risk_state(trade_id) -> RiskStateSnapshot` |
| `PUT /api/trades/{trade_id}/tp-sl` (line 1062) | 290 | `TpSlService` | `apply_tpsl_intent(trade_id, intent) -> PartialResult` |
| `GET /api/trades/stream` (SSE) | 40 | `TradesService` | `subscribe_events(user_id) -> AsyncIterator[Event]` |

`routers/portfolio.py` follows the same pattern and gets `PortfolioService`. `routers/bots.py` has its own bot-lifecycle logic — scoped to a follow-up refactor.

---

## 4. Migration Order (small PRs)

**Rule:** every step is a standalone commit with green tests and is individually deployable. No big-bang.

### Phase 1 — Preparation (low risk)
**PR-1:** Create `src/services/__init__.py`, empty service modules, `src/services/exceptions.py` with `TradeNotFound`, `NotOwnedByUser`, `SyncInProgress`, `InvalidTpSlIntent`.
- No behavior change. CI must be green.

**PR-2:** Characterization tests for existing handlers.
- Per route: 2–4 tests (happy path + 1–2 error cases) that freeze current behavior.
- **Blocker:** if gaps are too large here, do NOT extract — coverage must exceed 80% on each handler before we touch it.

### Phase 2 — Read-only services (low risk)
**PR-3:** Extract `TradesService.list_trades` + `get_filter_options`.
**PR-4:** Extract `TradesService.get_trade_detail` + `subscribe_events`.
**PR-5:** Extract `PortfolioService.get_positions` + `get_exposure` from `routers/portfolio.py`.

### Phase 3 — Write services (medium risk)
**PR-6:** Extract `TpSlService.get_risk_state` + `apply_tpsl_intent`.
- **Rollout:** feature flag `SERVICE_LAYER_TPSL_ENABLED` (default off). Router dispatches conditionally. Remove old path after one clean week in prod.

### Phase 4 — Sync pipeline (highest risk)
**PR-7:** Extract `TradeSyncService.sync_user_trades`.
- Split into `_fetch_remote_trades`, `_merge_into_local`, `_recompute_aggregates` — first extraction is 1:1, further refactoring in a separate PR-8.
- **Rollout:** feature flag `SERVICE_LAYER_SYNC_ENABLED` (default off). Enable for `user_id=1` on the VPS, observe two trade cycles, then enable globally.

### Phase 5 — Cleanup
**PR-9:** Remove feature flags, delete dead router paths.
**PR-10:** Enforce `routers/trades.py` < 350 LOC; if not, continue extraction.

---

## 5. Test Strategy

**Before every extract:** characterization tests freeze current output 1:1.

**After every extract:** two test levels:

1. **Service unit test** (fast, no FastAPI, no HTTP).
2. **Router integration test** (the characterization test from PR-2 stays).

**Mock strategy for RSM:** `TpSlService` takes `risk_state_manager` as a constructor arg; tests inject a fake that captures calls.

**Coverage target:** 85%+ per service class. Router coverage stays as-is.

---

## 6. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Session leak — service outlives request | medium | background task crash | service is per-request, constructor takes existing session |
| Circular import — services ↔ bot | medium | app won't boot | TYPE_CHECKING imports; `src.services` never imports `src.bot` at runtime |
| Lock ordering changes | low | race between bot worker and API | RSM locks stay in RSM; services add no new locks |
| SSE stream breaks during extract | medium | frontend falls back to 5s polling (already built) | extract stream last; dedicated test in PR-4 |
| Perf regression from extra call overhead | low | <1ms per request | measure after PR-5 in staging, don't pre-optimize |
| Partial rollback — flag on, bug, flip off | expected | two paths live briefly | flag used for one PR only |

---

## 7. Rollback Points

- **Phase 1–2:** `git revert <PR-SHA>` is enough, no DB changes.
- **Phase 3–4:** flip feature flag to `false` in ENV, no redeploy needed. If old path is also broken: full revert + new build.
- **Phase 5:** only start after Phase 3+4 have been green for two weeks. If rollback is needed after Phase 5, revert to the tag before Phase 5.

---

## 8. Definition of Done

- [ ] `routers/trades.py` < 350 LOC
- [ ] `routers/portfolio.py` < 250 LOC
- [ ] `src/services/` has 4 service modules with their own test files
- [ ] Service coverage > 85%
- [ ] All feature flags removed
- [ ] No E2E regression
- [ ] Prometheus p95 latency does not increase by more than 10%

---

## 9. Out of Scope

- `routers/bots.py` — separate bot-lifecycle-service plan
- Auth / users — being migrated to another repo, touching it wastes work
- Broadcast/notification paths — small enough to stay in their routers
- `BotWorker` mixin decomposition — see `refactor_plan_bot_worker_composition.md`

---

## 10. Related Work

- RiskStateManager 2-phase commit (#190) — services build on this
- Audit scheduler (#216 §2.4) — runs independently, not affected
- WebSocket manager (#240) — independent; services emit into the `EventBus` (`src/bot/event_bus.py`), not directly into WS
