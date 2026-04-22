# Refactor-Plan: BotWorker Mixin → Composition (ARCH-H1)

> **Status:** Planung · **Risiko:** Sehr hoch (läuft im Prod-Trade-Loop) · **Scope:** `src/bot/` · **Vorbedingung:** ARCH-H2 (HL-Lift) eingeflossen

---

## 1. Problem

`src/bot/bot_worker.py` (977 LOC) ist die Klasse `BotWorker`, die fünf Mixins erbt:

```python
class BotWorker(TradeExecutorMixin, PositionMonitorMixin, TradeCloserMixin,
                HyperliquidGatesMixin, NotificationsMixin):
```

LOC-Aufteilung (aktueller Stand):

| Mixin | LOC | Verantwortung |
|-------|-----|---------------|
| `trade_executor.py` | 757 | Signal → Order-Placement, Idempotency, Fee-Tracking |
| `position_monitor.py` | 744 | Offene Positions pollen, TP/SL-Fires erkennen, Close-Klassifikation |
| `trade_closer.py` | 189 | Manual-Close, Strategy-Exit |
| `hyperliquid_gates.py` | 138 | HL-Onboarding (nach ARCH-H2 nur noch Shim-Dummy) |
| `notifications.py` | 94 | Discord/Telegram-Emit |
| `bot_worker.py` | 977 | Lifecycle + Scheduling + Lock-Map + `self.bot_config` |

**Problem 1: Shared State via `self`.**
Jedes Mixin liest/schreibt `self.bot_config_id`, `self.status`, `self.error_message`, `self._config`, `self._client`, `self._db_session_factory`, `self._last_signal_ts`. Niemand kann sehen, *welches Attribut welches Mixin ownt* — sie alle sind im selben Namespace. Eine vermeintlich triviale Änderung in `TradeExecutorMixin` kann `PositionMonitorMixin` kaputtmachen, weil beide auf dasselbe Attribut schreiben.

**Problem 2: MRO-Fallen.**
Wenn zwei Mixins eine gemeinsame Methode überschreiben (z.B. `async def _on_error(self, exc)`), gewinnt die Reihenfolge der Klassenbasen. Python erlaubt die Definition, aber der Effekt ist unsichtbar in der einzelnen Mixin-Datei.

**Problem 3: Testbarkeit.**
Ein Unit-Test für `TradeExecutorMixin` muss heute einen vollständigen `BotWorker` konstruieren (inkl. Scheduler, Lock, DB-Session-Factory). Es gibt keinen Weg, nur den `TradeExecutor` isoliert zu testen. Die Test-Suite (`tests/unit/bot/`) spiegelt das wider — fast alle Tests sind "BotWorker + Mocks drumherum", nicht "eine Komponente in Ruhe".

**Problem 4: Kopplung HL-Gates.**
Obwohl ARCH-H2 bereits die HL-Onboarding-Logik in `HyperliquidClient.pre_start_checks` verschoben hat, bleibt der Mixin als Shim weil Legacy-Tests direkt `BotWorker._check_referral_gate` aufrufen. Composition würde den Shim überflüssig machen.

---

## 2. Zielarchitektur

Composition statt Inheritance: `BotWorker` hält seine Komponenten als Attribute, keine Mehrfachvererbung.

```
class BotWorker:
    def __init__(self, config: BotConfig, deps: BotWorkerDeps):
        self._config = config
        self._deps = deps

        # Components
        self.executor      = TradeExecutor(config, deps)
        self.monitor       = PositionMonitor(config, deps)
        self.closer        = TradeCloser(config, deps)
        self.notifier      = Notifier(config, deps)

    async def tick(self):
        """Scheduler tick: Signal → Execute → Monitor → Close if needed."""
        signal = await self._deps.strategy.generate_signal(...)
        if signal.is_entry():
            trade = await self.executor.open(signal)
            await self.notifier.on_trade_opened(trade)

        await self.monitor.poll_positions()
        await self.closer.run_due_exits()
```

**Schnittstellen (Protocols):**

```python
# src/bot/components/protocols.py

class TradeExecutorProtocol(Protocol):
    async def open(self, signal: Signal) -> TradeRecord: ...
    async def cancel_pending(self, trade_id: int) -> None: ...

class PositionMonitorProtocol(Protocol):
    async def poll_positions(self) -> list[PositionUpdate]: ...
    async def on_closed(self, trade: TradeRecord, fill: ExchangeFill) -> None: ...

class TradeCloserProtocol(Protocol):
    async def close_manual(self, trade_id: int, reason: ExitReason) -> TradeRecord: ...
    async def run_due_exits(self) -> None: ...

class NotifierProtocol(Protocol):
    async def on_trade_opened(self, trade: TradeRecord) -> None: ...
    async def on_trade_closed(self, trade: TradeRecord) -> None: ...
    async def on_error(self, exc: Exception) -> None: ...
```

**`BotWorkerDeps`** — alle geteilten Ressourcen in einem Dataclass:

```python
@dataclass
class BotWorkerDeps:
    client: ExchangeClient
    db_session_factory: AsyncSessionFactory
    risk_state_manager: RiskStateManager
    strategy: StrategyProtocol
    event_bus: EventBus
    admin_notifier: AdminNotifier
    lock_map: LockMap  # per-symbol / per-user locks
    clock: Clock       # injectable for tests
```

Jede Komponente bekommt `deps` im Constructor und nutzt nur die Referenzen, die sie braucht. Keine Komponente mutiert `self.bot_config.*` oder `self.status` — Zustand (`running`, `error`, `error_message`) bleibt ausschließlich im `BotWorker`.

---

## 3. State-Ownership-Matrix

| State | Aktuell (Mixin-Wirklichkeit) | Ziel (Composition) |
|-------|------------------------------|--------------------|
| `bot_config_id` | Alle Mixins lesen | `BotWorker` (read-only für Komponenten via `config`) |
| `status`, `error_message` | Alle Mixins schreiben | `BotWorker` (Komponenten raisen `ComponentFailure`, Worker setzt Status) |
| `_last_signal_ts` | `TradeExecutor` schreibt, `PositionMonitor` liest | `TradeExecutor.last_signal_ts` (@property) |
| `_open_trade_cache` | `TradeExecutor` und `PositionMonitor` mutieren | `PositionMonitor.open_trades` (Single Owner), `TradeExecutor` fragt via Methode ab |
| `_db_session_factory` | Alle | `deps.db_session_factory` |
| `_client` (Exchange) | Alle | `deps.client` |
| `_lock` (per-Symbol) | `TradeExecutor`, `TradeCloser` | `deps.lock_map.acquire(symbol)` |
| `_notifier_state` (rate-limit für Admin-Alerts) | `Notifications` | `Notifier` selbst, privat |

---

## 4. Extraktions-Reihenfolge

Von einfach nach riskant. Jeder Schritt ist ein eigener PR mit grüner Suite. **Nie zwei Komponenten gleichzeitig extrahieren.**

### Phase 0 — Vorbereitung
**PR-1:** `src/bot/components/` + `protocols.py` + `BotWorkerDeps` Dataclass. Keine Logik, keine Verhaltensänderung. Neue Unit-Test-Datei `tests/unit/bot/components/` (leer, nur Smoke-Import).

**PR-2:** Characterization-Tests für `BotWorker` — gesamten Lifecycle, je 2 Tests pro Mixin-Ober-Methode. Ziel: Baseline-Verhalten eingefroren. Ohne >85% Coverage auf dem Worker brechen wir ab — ARCH-H1 erfordert dieses Sicherheitsnetz.

### Phase 1 — `Notifier` (einfachster Start)
**PR-3:** `NotificationsMixin` → `Notifier`-Klasse in `src/bot/components/notifier.py`.
- Mixin löschen nur wenn keine Tests ihn direkt nutzen (grep zeigt alle Call-Sites).
- `BotWorker.__init__` setzt `self.notifier = Notifier(config, deps)`.
- Alle bisherigen `self.notify_*()`-Call-Sites im Worker zu `self.notifier.*` umschreiben.
- **Canary-Deploy:** 1 Bot auf Admin-Account, 24 h beobachten. Discord/Telegram-Output muss exakt wie vorher aussehen (Diff-Check auf Message-Text).
- Rollback: `git revert` + Redeploy.

### Phase 2 — `HyperliquidGates` (ARCH-H2 Abschluss)
**PR-4:** `HyperliquidGatesMixin`-Shim löschen.
- Voraussetzung: Legacy-Tests (`test_bot_worker_extra.py::TestCheckBuilderApproval`) auf `client.pre_start_checks(...)` umgeschrieben.
- `BotWorker` ruft `self._deps.client.pre_start_checks(...)` direkt.
- Keine Prod-Verhaltensänderung (der Shim war bereits leer).

### Phase 3 — `TradeCloser`
**PR-5:** `TradeCloserMixin` → `TradeCloser`-Klasse.
- Nur 189 LOC — gut abgrenzbare Methoden (`close_manual`, `run_due_exits`).
- `TradeCloser` hält Referenz auf `RiskStateManager` und `EventBus`.
- Worker nutzt `self.closer.close_manual(...)` und `self.closer.run_due_exits()`.

### Phase 4 — `PositionMonitor` (mittleres Risiko)
**PR-6:** `PositionMonitorMixin` → `PositionMonitor`-Klasse.
- 744 LOC, enthält die Polling-Loop und Close-Klassifikation.
- Klare Schnittstelle zum `TradeCloser` (übergibt `TradeRecord` + `ExchangeFill`).
- `PositionMonitor.open_trades` wird Single Owner des Caches.
- **Canary:** 1 Bot auf Admin-Account für 48 h. Audit-Script `scripts/audit_tp_sl_flags.py` muss stündlich grün sein.
- Rollback-Trigger: jede Desync-Klassifikation oder mehr als zwei Audit-Findings in 24 h.

### Phase 5 — `TradeExecutor` (höchstes Risiko)
**PR-7:** `TradeExecutorMixin` → `TradeExecutor`-Klasse.
- 757 LOC, berührt Order-Placement und Idempotency.
- **Voraussetzung:** PR-3 bis PR-6 laufen seit mindestens einer Woche auf Prod ohne Incidents.
- **Canary:** 1 Bot, 72 h beobachten. Jede Order muss auf dem Exchange exakt gleich erscheinen wie vor dem Refactor (gleiches Size-Rounding, gleiche Fee-Attribution).
- Rollback-Trigger: jede Order-Placement-Failure mit unerwarteter Exception, jede `client_order_id`-Kollision, jede Fee-Diskrepanz > 0.1 %.

### Phase 6 — Cleanup
**PR-8:** Alle fünf `*_mixin.py`-Dateien entfernen. Klassenbasis von `BotWorker` ist nur noch `object`. Import-Graph aufräumen. CI muss grün sein.

---

## 5. Test-Strategie

**Vor jedem Extract:** Characterization-Test friert Worker-Verhalten auf Pfad der Komponente ein.

**Pro Komponente (neu):**
1. **Unit-Tests ohne BotWorker.** Komponente mit gemockten `BotWorkerDeps` instanziieren. Alle öffentlichen Methoden einzeln testen.
2. **Contract-Test gegen Protocol.** `isinstance(comp, TradeExecutorProtocol)` = True. Schützt vor Signatur-Drift.
3. **Integration-Test** mit echtem `BotWorker`: prüft das Zusammenspiel über den Lifecycle. Der alte Characterization-Test läuft weiter, bis er identisch verhält.

**Coverage-Ziele:**
- Jede Komponente: 90 % (höher als Service-Layer, weil Trade-Loop kritisch)
- `BotWorker` (Lifecycle-Glue): 80 %

**Fake-Klassen:**
```python
class FakeClient:
    """In-memory Exchange-Client. Speichert Orders, gibt deterministische Fills."""

class FakeStrategy:
    """Emittiert fest skriptierte Signale."""

class FakeClock:
    """Controllable time — ermöglicht schnelle Tests von Poll-Loops."""
```

**Golden-Path-Test nach jeder Extraktion:**
```python
async def test_full_cycle_entry_to_exit(fake_deps):
    worker = BotWorker(config, fake_deps)
    fake_deps.strategy.queue_signal(entry_long())
    await worker.tick()  # opens position
    fake_deps.client.simulate_tp_hit()
    await worker.tick()  # detects close + classifies
    trade = await fake_deps.db.get(1)
    assert trade.exit_reason == ExitReason.TAKE_PROFIT_NATIVE
```

---

## 6. Risiken und Mitigationen

| Risiko | Wahrscheinlichkeit | Impact | Mitigation |
|--------|--------------------|--------|------------|
| Komponente mutiert State, den der Worker ebenfalls schreibt | hoch | Race zwischen Worker-Loop und Komponente | State-Ownership-Matrix strikt einhalten; Code-Review prüft jeden `self._config.xxx = ...` |
| MRO-Wegfall zerstört Override-Reihenfolge | mittel | Silent behavior change | Phase 0 — grep auf `super()` in allen Mixins; keine Mixin nutzt super() produktiv → MRO-Risiko entfällt |
| Canary-Bot läuft grün, Prod-Flotte nicht | mittel | Silent Drift in seltenen Signalen | Jede Phase Canary-Dauer ≥ 48 h. Audit-Scheduler (#216 §2.4) überwacht Drift |
| Refactor bricht Order-Idempotency | niedrig | Doppelte Orders | `TradeExecutor.client_order_id` Generator-Logik IDENTISCH behalten. Test: identischer Signal-Hash → identischer client_order_id |
| Deploy-Fenster fällt in aktive Trading-Session | mittel | Bot pausiert während Deploy | Deploy-Fenster weit weg von HTPmVC-Session (02:00–04:00 UTC). Orchestrator zieht im Restart sanft an — kein hard kill |
| Orchestrator spawnt Worker mit neuer + alter Signatur parallel | niedrig | Deserialisierungs-Fehler beim Pickle | Worker-Instanzen sind prozesslokal, kein Pickle. `Orchestrator.reload()` startet alle Worker neu nach Deploy |
| Lock-Map-Contention neu | niedrig | Latency-Spike | `deps.lock_map` derselbe Singleton wie vorher; keine neuen Locks |
| Tests grün, aber Fee-Attribution in Prod abweichend | mittel | Stille PnL-Fehler | Fee-Reconcile-Audit (`audit_price_sanity.py`) stündlich, Alert bei > 0.5 % Drift |

---

## 7. Rollback-Punkte

| Phase | Rollback-Methode | Maximale Wiederherstellungszeit |
|-------|------------------|-------------------------------|
| 0–1 | `git revert` + Redeploy | 5 min |
| 2 | `git revert` + Redeploy + alte Tests anlegen | 15 min |
| 3–4 | `git revert` + Redeploy | 10 min |
| 5 | `git revert` + Redeploy + Datenabgleich (offene Trades gegen Exchange) | 30 min |
| 6 | `git revert` nicht möglich (Mixin-Dateien weg). Tag vor Phase 6 als Rollback-Ziel. | 45 min |

Nach Phase 6 gibt es keinen einfachen Rückweg. Deshalb: Phase 3–5 mindestens **zwei Wochen** grün in Prod laufen lassen, bevor Phase 6 merged wird.

---

## 8. Definition-of-Done

- [ ] `src/bot/bot_worker.py` enthält **keine** `Mixin`-Klassenbasen
- [ ] `src/bot/*_mixin.py`-Dateien gelöscht (trade_executor.py, position_monitor.py, trade_closer.py, hyperliquid_gates.py, notifications.py)
- [ ] `src/bot/components/` enthält fünf Komponenten + Protocol-Modul
- [ ] Pro Komponente eine eigene Test-Datei, Coverage > 90 %
- [ ] `BotWorker` Coverage > 80 %
- [ ] Kein `isinstance(client, HyperliquidClient)` in `src/bot/`
- [ ] Alle Audit-Scripts grün auf Prod über 7 Tage Canary → Flotte
- [ ] Prometheus: keine Regression in `risk_intent_duration_seconds` p95

---

## 9. Nicht in diesem Scope

- `Orchestrator` (`src/bot/orchestrator.py`) — eigenes Lifecycle-Refactor, separater Plan
- `RiskStateManager` — bleibt wie er ist, Komponente konsumiert ihn
- `AuditScheduler` — unabhängig
- Strategien (`src/strategy/`) — konsumieren keine Mixins
- Frontend — keine direkten Auswirkungen

---

## 10. Verwandte Arbeit

- ARCH-H2 (HL-Lift) muss vor Phase 2 gemerged sein
- Service-Layer-Refactor (ARCH-C1) — läuft parallel in `src/services/`, keine Überschneidung
- RiskStateManager 2PC (#190) — bleibt Singleton, Komponenten teilen ihn

---

# Refactor Plan: BotWorker Mixin → Composition (ARCH-H1)

> **Status:** Planning · **Risk:** Very high (runs in prod trade loop) · **Scope:** `src/bot/` · **Blocker:** ARCH-H2 landed

---

## 1. Problem

`src/bot/bot_worker.py` (977 LOC) is the class `BotWorker`, which inherits from five mixins:

```python
class BotWorker(TradeExecutorMixin, PositionMonitorMixin, TradeCloserMixin,
                HyperliquidGatesMixin, NotificationsMixin):
```

Current LOC split:

| Mixin | LOC | Responsibility |
|-------|-----|----------------|
| `trade_executor.py` | 757 | Signal → order placement, idempotency, fee tracking |
| `position_monitor.py` | 744 | Poll open positions, detect TP/SL fires, classify closes |
| `trade_closer.py` | 189 | Manual close, strategy exit |
| `hyperliquid_gates.py` | 138 | HL onboarding (post-H2, just a shim) |
| `notifications.py` | 94 | Discord/Telegram emit |
| `bot_worker.py` | 977 | Lifecycle + scheduling + lock map + `self.bot_config` |

**Problem 1: shared state via `self`.** Every mixin reads/writes `self.bot_config_id`, `self.status`, `self.error_message`, `self._config`, `self._client`, `self._db_session_factory`, `self._last_signal_ts`. There's no way to see *which attribute belongs to which mixin* — they all share one namespace. A seemingly trivial change in `TradeExecutorMixin` can break `PositionMonitorMixin`.

**Problem 2: MRO traps.** If two mixins override the same method (e.g. `async def _on_error(self, exc)`), class base order wins. Python accepts the definition, but the effect is invisible in the individual mixin file.

**Problem 3: testability.** A unit test for `TradeExecutorMixin` today has to construct a full `BotWorker` (with scheduler, lock, DB session factory). There is no way to test the executor in isolation.

**Problem 4: HL coupling.** Even after ARCH-H2 moved HL onboarding into `HyperliquidClient.pre_start_checks`, the mixin remains as a shim because legacy tests still call `BotWorker._check_referral_gate` directly. Composition eliminates the shim.

---

## 2. Target Architecture

Composition over inheritance: `BotWorker` holds components as attributes, no multiple inheritance.

```python
class BotWorker:
    def __init__(self, config: BotConfig, deps: BotWorkerDeps):
        self._config = config
        self._deps = deps
        self.executor = TradeExecutor(config, deps)
        self.monitor  = PositionMonitor(config, deps)
        self.closer   = TradeCloser(config, deps)
        self.notifier = Notifier(config, deps)

    async def tick(self):
        signal = await self._deps.strategy.generate_signal(...)
        if signal.is_entry():
            trade = await self.executor.open(signal)
            await self.notifier.on_trade_opened(trade)
        await self.monitor.poll_positions()
        await self.closer.run_due_exits()
```

**Protocols:**

```python
class TradeExecutorProtocol(Protocol):
    async def open(self, signal: Signal) -> TradeRecord: ...
    async def cancel_pending(self, trade_id: int) -> None: ...

class PositionMonitorProtocol(Protocol):
    async def poll_positions(self) -> list[PositionUpdate]: ...
    async def on_closed(self, trade: TradeRecord, fill: ExchangeFill) -> None: ...

class TradeCloserProtocol(Protocol):
    async def close_manual(self, trade_id: int, reason: ExitReason) -> TradeRecord: ...
    async def run_due_exits(self) -> None: ...

class NotifierProtocol(Protocol):
    async def on_trade_opened(self, trade: TradeRecord) -> None: ...
    async def on_trade_closed(self, trade: TradeRecord) -> None: ...
    async def on_error(self, exc: Exception) -> None: ...
```

**`BotWorkerDeps`** — all shared resources in one dataclass: `client`, `db_session_factory`, `risk_state_manager`, `strategy`, `event_bus`, `admin_notifier`, `lock_map`, `clock`.

---

## 3. State Ownership Matrix

| State | Current (mixin reality) | Target (composition) |
|-------|------------------------|---------------------|
| `bot_config_id` | All mixins read | `BotWorker` (read-only for components via `config`) |
| `status`, `error_message` | All mixins write | `BotWorker` (components raise `ComponentFailure`, worker sets status) |
| `_last_signal_ts` | Executor writes, monitor reads | `TradeExecutor.last_signal_ts` (@property) |
| `_open_trade_cache` | Executor and monitor mutate | `PositionMonitor.open_trades` (single owner) |
| `_db_session_factory` | All | `deps.db_session_factory` |
| `_client` | All | `deps.client` |
| `_lock` (per-symbol) | Executor, closer | `deps.lock_map.acquire(symbol)` |
| `_notifier_state` | Notifications | `Notifier` privately |

---

## 4. Extraction Order

Easy → risky. Each step is its own PR with a green suite. **Never extract two components at once.**

### Phase 0 — Preparation
**PR-1:** `src/bot/components/` + `protocols.py` + `BotWorkerDeps` dataclass. No logic, no behavior change.
**PR-2:** Characterization tests for `BotWorker` lifecycle — 2 tests per mixin's top-level method. Require >85% coverage before touching the worker.

### Phase 1 — `Notifier` (simplest)
**PR-3:** `NotificationsMixin` → `Notifier` class in `src/bot/components/notifier.py`.
- Canary: 1 bot on admin account, 24 h. Discord/Telegram output must match exactly.
- Rollback: `git revert` + redeploy.

### Phase 2 — `HyperliquidGates` (ARCH-H2 finish)
**PR-4:** Delete the `HyperliquidGatesMixin` shim. Legacy tests repointed to `client.pre_start_checks(...)`.

### Phase 3 — `TradeCloser`
**PR-5:** `TradeCloserMixin` → `TradeCloser` class.

### Phase 4 — `PositionMonitor` (medium risk)
**PR-6:** `PositionMonitorMixin` → `PositionMonitor` class.
- Canary: 1 bot for 48 h. Audit script `scripts/audit_tp_sl_flags.py` must be green hourly.
- Rollback trigger: any desync classification or >2 audit findings in 24 h.

### Phase 5 — `TradeExecutor` (highest risk)
**PR-7:** `TradeExecutorMixin` → `TradeExecutor` class.
- Prerequisite: PR-3..PR-6 running in prod for at least one week without incidents.
- Canary: 1 bot, 72 h. Every order must land on the exchange identical to pre-refactor (size rounding, fee attribution, idempotency).
- Rollback triggers: any placement failure, `client_order_id` collision, fee discrepancy > 0.1 %.

### Phase 6 — Cleanup
**PR-8:** Delete all five `*_mixin.py` files. `BotWorker` inherits only from `object`. CI must be green.

---

## 5. Test Strategy

Per component (new):
1. **Unit tests without BotWorker** — instantiate with mocked `BotWorkerDeps`.
2. **Contract test against Protocol** — `isinstance(comp, TradeExecutorProtocol)`.
3. **Integration test** with real `BotWorker` — covers the glue.

Coverage: 90% per component (trade loop is critical), 80% for the worker glue.

**Fake classes:** `FakeClient` (in-memory exchange with deterministic fills), `FakeStrategy` (scripted signals), `FakeClock` (controllable time).

**Golden-path test after every extraction:**
```python
async def test_full_cycle_entry_to_exit(fake_deps):
    worker = BotWorker(config, fake_deps)
    fake_deps.strategy.queue_signal(entry_long())
    await worker.tick()
    fake_deps.client.simulate_tp_hit()
    await worker.tick()
    trade = await fake_deps.db.get(1)
    assert trade.exit_reason == ExitReason.TAKE_PROFIT_NATIVE
```

---

## 6. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Component mutates state the worker also writes | high | race between worker loop and component | Strict state-ownership matrix; code review checks every `self._config.xxx = ...` |
| MRO disappearance destroys override order | medium | silent behavior change | Phase 0 greps all mixins for `super()`; none use it productively → MRO risk removed |
| Canary bot clean, full fleet isn't | medium | silent drift on rare signals | Canary duration ≥ 48 h per phase. Audit scheduler monitors drift |
| Refactor breaks order idempotency | low | duplicate orders | Keep `TradeExecutor.client_order_id` generator byte-identical. Test: same signal hash → same `client_order_id` |
| Deploy window hits active trading session | medium | bot pauses mid-session | Deploy at 02:00–04:00 UTC. Orchestrator does a soft restart |
| Orchestrator spawns mixed-signature workers | low | pickle error | Workers are process-local; orchestrator `reload()` restarts all workers after deploy |
| New lock-map contention | low | latency spike | `deps.lock_map` is the same singleton; no new locks |
| Tests green, fee attribution drifts in prod | medium | silent PnL errors | `audit_price_sanity.py` hourly, alert on > 0.5 % drift |

---

## 7. Rollback Points

| Phase | Rollback method | Max restore time |
|-------|-----------------|------------------|
| 0–1 | `git revert` + redeploy | 5 min |
| 2 | `git revert` + redeploy + restore legacy tests | 15 min |
| 3–4 | `git revert` + redeploy | 10 min |
| 5 | `git revert` + redeploy + reconcile open trades | 30 min |
| 6 | Tag-before-phase-6 restore (mixin files gone) | 45 min |

Phase 3–5 must be green in prod for **at least two weeks** before Phase 6 merges.

---

## 8. Definition of Done

- [ ] `BotWorker` has no mixin bases
- [ ] Five `*_mixin.py` files deleted
- [ ] `src/bot/components/` has five components + protocols module
- [ ] Per component: own test file, coverage > 90 %
- [ ] `BotWorker` coverage > 80 %
- [ ] No `isinstance(client, HyperliquidClient)` in `src/bot/`
- [ ] All audit scripts green on prod over 7-day canary-to-fleet
- [ ] Prometheus: no regression in `risk_intent_duration_seconds` p95

---

## 9. Out of Scope

- `Orchestrator` — separate lifecycle refactor
- `RiskStateManager` — stays, components consume it
- `AuditScheduler` — independent
- Strategies — don't use mixins
- Frontend — no direct impact

---

## 10. Related Work

- ARCH-H2 (HL lift) must land before Phase 2
- Service-layer refactor (ARCH-C1) — runs in parallel in `src/services/`, no overlap
- RiskStateManager 2PC (#190) — remains a singleton, components share it
