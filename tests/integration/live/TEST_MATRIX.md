# Risk-State Integration Test Matrix

Diese Matrix ist die verbindliche Test-Spec für Issue #197 + Live-Run auf Bitget-Demo (admin user_id=1, connection #1). Jede Zeile = ein Test-Case. Jeder MUSS nach Phase-1-Deploy grün sein.

Spalten:
- **Trigger** = wo startet die Aktion (UI, Backend-internal, direkt Exchange)
- **Sync-Richtung** = Frontend→Exchange (F→E), Exchange→Frontend (E→F), DB-Drift-Reconcile (DB⇄E)
- **Vorzustand** = welche Legs sind bei Test-Start aktiv
- **Aktion** = was wird gemacht
- **Erwartet DB** / **Erwartet Exchange** / **Erwartet Frontend** = die drei Wahrheits-Ziele

---

## A. Frontend → Exchange Roundtrip (UI-initiiert)

| # | Vorzustand | Aktion | Erwartet DB | Erwartet Bitget | Erwartet UI |
|---|------------|--------|-------------|-----------------|-------------|
| A01 | leer | Set TP=80000 auf LONG | tp=80000, tp_status=confirmed, tp_order_id set | 1× `pos_profit` plan aktiv @ 80000 | Badge "TP $80000 (Exchange)" < 3s |
| A02 | leer | Set SL=72000 auf LONG | sl=72000, sl_status=confirmed, sl_order_id set | 1× `pos_loss` plan aktiv @ 72000 | Badge "SL $72000 (Exchange)" < 3s |
| A03 | leer | Set TP=80000 + SL=72000 atomic | beide confirmed mit je 1 order_id | 1× `pos_profit` + 1× `pos_loss` | beide Badges sichtbar |
| A04 | TP=80000 | Modify TP auf 82000 | tp=82000, alte order_id ersetzt | alter plan gecancelt, neuer @ 82000 | Badge zeigt 82000 < 3s |
| A05 | TP=80000 + SL=72000 | Clear TP only (remove_tp=true) | tp=NULL, tp_status=cleared, sl bleibt | nur `pos_loss` aktiv | TP-Badge weg < 500ms optimistic |
| A06 | TP=80000 + SL=72000 | Clear SL only | sl=NULL, tp bleibt | nur `pos_profit` aktiv | SL-Badge weg < 500ms |
| A07 | leer | Set Trailing callback=1.4 ATR | trailing_order_id set, trailing_callback_rate, native_trailing_stop=True, risk_source=native_exchange | 1× `track_plan` aktiv | Badge "Trailing 1.4× ATR (Exchange)" |
| A08 | Trailing 1.4 | Modify Trailing auf 2.0 ATR | trailing_callback_rate=2.0 neuer | alter track_plan gecancelt, neuer | Badge zeigt 2.0× |
| A09 | Trailing 1.4 | Clear Trailing | trailing_status=cleared, trailing_order_id=NULL | kein track_plan | Badge weg < 500ms |
| A10 | TP+SL+Trailing | Clear alle 3 | alle 3 status=cleared | keine Pläne aktiv | alle Badges weg |
| A11 | leer | Set Trailing + TP (combined) | beide confirmed | `track_plan` + `pos_profit` aktiv | beide Badges |

## B. Partial-Success (Bitget lehnt einen Leg ab)

| # | Vorzustand | Aktion | Erwartet DB | Erwartet Bitget | Erwartet UI |
|---|------------|--------|-------------|-----------------|-------------|
| B01 | leer | Set TP=200000 (weit über Markt) — Bitget rejected TP | tp_status=rejected mit Fehler | kein `pos_profit` | TP-Badge rot mit Tooltip "Trigger invalid" |
| B02 | leer | Set TP=80000 + SL=200000 — TP ok, SL rejected | tp_status=confirmed, sl_status=rejected | 1× `pos_profit` aktiv | TP-Badge grün, SL-Badge rot |
| B03 | leer | Set Trailing callback=0.05% (unter Minimum) | trailing_status=rejected | kein `track_plan` | Badge rot, Fehler "callback too small" |
| B04 | TP=80000 | Modify TP auf 200000 — rejected | tp bleibt 80000 (original), status bleibt confirmed (nicht pending) | alter `pos_profit` noch aktiv | Badge unverändert + Toast "Fehler" |
| B05 | Trailing aktiv | Modify mit activation price < market | trailing_status=rejected | alter track_plan noch aktiv | Toast-Fehler, alter Wert bleibt |

## C. Cancel-Failure-Pfad (früher DEBUG-verschluckt)

| # | Szenario | Erwartet |
|---|----------|----------|
| C01 | TP=80000, cancel TP simuliert mit transient error (respx mock) | Retry 1×, dann Fehler-Log WARN mit status=cancel_failed, keine neue Order |
| C02 | Trailing aktiv, Bitget gibt auf cancel 404 zurück | Behandelt als "already gone" → status=cleared, OK |
| C03 | Trailing aktiv, Bitget gibt 500 auf cancel | status=cancel_failed, neue Trailing-Order wird NICHT platziert, Alert an user |

## D. Exchange → Frontend Sync (E→F)

| # | Vorzustand | Exchange-seitige Aktion | Erwartet DB | Erwartet UI |
|---|------------|-------------------------|-------------|-------------|
| D01 | TP=80000 in DB+Exchange | User schließt TP-Plan direkt auf Bitget-App | Reconciler (Poll 30s oder WS) setzt tp_status=cleared, tp=NULL | Badge verschwindet nach Poll/WS < 30s (WS: < 2s) |
| D02 | leer | User setzt TP direkt auf Bitget-App auf 80000 | Reconciler erkennt neuen Plan, schreibt tp=80000, tp_order_id, risk_source=native_exchange | Badge taucht auf |
| D03 | Trailing aktiv | Bitget triggert Trailing (market fill) | Position wird closed, exit_reason=TRAILING_STOP_NATIVE mit korrektem closed_by_order_id | Exit-Badge "Trailing Stop (Exchange)" |
| D04 | TP=80000 aktiv | Position triggert TP (market fill) | exit_reason=TAKE_PROFIT_NATIVE, close_order_id gesetzt | Badge "Take Profit (Exchange)" |
| D05 | leer | User schließt Position manuell auf Exchange | exit_reason=MANUAL_CLOSE_EXCHANGE | Badge "Manuell geschlossen (Exchange)" |
| D06 | Liquidation-nahe Position | Bitget liquidiert | exit_reason=LIQUIDATION | Badge "Liquidation" rot |

## E. Sync-Drift-Reconciliation (DB⇄E)

| # | Drift-Szenario | Erwartet |
|---|----------------|----------|
| E01 | DB sagt tp=80000, Exchange hat keinen Plan (silent cancel) | Reconcile setzt tp=NULL, WARN log |
| E02 | DB sagt kein trailing, Exchange hat track_plan aktiv | Reconcile setzt trailing_order_id + trailing_callback_rate + native_trailing_stop=True |
| E03 | DB sagt tp=80000 order_id=A, Exchange hat tp=80000 order_id=B | Reconcile aktualisiert order_id=B (kein TP-Value-Change aber ID-Update) |
| E04 | DB sagt trailing callback=1.4, Exchange sagt 2.0 | Reconcile: Exchange ist authority, DB wird 2.0 |
| E05 | Bot-Start nach Crash, 4 offene Trades | `reconcile_open_trades.py --apply` fixt alle Drifts in einem Durchgang |

## F. Close-Klassifizierung (`RiskStateManager.classify_close`)

| # | Close-Kontext | Erwarteter exit_reason |
|---|---------------|------------------------|
| F01 | closed_by_order_id == trade.trailing_order_id (native track_plan getriggert) | TRAILING_STOP_NATIVE |
| F02 | closed_by_order_id == trade.tp_order_id | TAKE_PROFIT_NATIVE |
| F03 | closed_by_order_id == trade.sl_order_id | STOP_LOSS_NATIVE |
| F04 | closed_by_plan_type=track_plan aber kein order_id Match (Plan wurde modifiziert) | TRAILING_STOP_NATIVE |
| F05 | closed via Bitget UI manual-close (orderType=market, reduceOnly) | MANUAL_CLOSE_EXCHANGE |
| F06 | closed via unser POST /trades/{id}/close Endpoint | MANUAL_CLOSE_UI |
| F07 | closed mit Reason aus strategy.should_exit() | STRATEGY_EXIT |
| F08 | closed mit liquidation-Flag in Bitget-History | LIQUIDATION |
| F09 | Software-Trailing (HL) Watchdog hat modify gemacht und SL-Trigger fired | TRAILING_STOP_SOFTWARE |
| F10 | Exchange-API fail beim Klassifizieren | EXTERNAL_CLOSE_UNKNOWN + Heuristik-Fallback mit WARN |

## G. UI-Reaktivität (Frontend-Only, Mock-Backend)

| # | Aktion | Erwartet |
|---|--------|----------|
| G01 | User klickt "Set TP" | Spinner < 100ms, Optimistic-Wert sichtbar |
| G02 | Server bestätigt | Spinner weg, Value solid, Source-Icon (🔗 native) < 3s |
| G03 | Server reject | Rollback auf vorherigen Wert, roter Toast mit Server-Fehler |
| G04 | User klickt "Clear TP" | Badge verschwindet < 500ms (optimistic) |
| G05 | Server reject Clear | Rollback: Badge wieder da |
| G06 | SSE-Event trade_updated reinkommt | Cache per setQueryData aktualisiert, UI rerendert ohne flicker |
| G07 | SSE-Connection verloren | Fallback-Polling 5s aktiviert, Banner "Verbindung verloren" |
| G08 | 3× hintereinander Modify TP | letzter Call gewinnt (nicht race-condition), Spinner stacked |

## H. i18n + Badge-Rendering

| # | Test | Erwartet |
|---|------|----------|
| H01 | Alle 10 neuen Reason-Codes in DE haben unique Label | PASS (Uniqueness-Test) |
| H02 | Alle 10 neuen Reason-Codes in EN haben unique Label | PASS |
| H03 | Legacy-Codes (MANUAL_CLOSE, EXTERNAL_CLOSE) rendern differenziert | "Manuell geschlossen (Legacy)" vs "Manuell geschlossen (Exchange)" |
| H04 | RiskStateBadge für state {tp:80000, source:native} | Server-Icon + blau |
| H05 | RiskStateBadge für state {trailing:1.4, source:software} | Cpu-Icon + hellblau |
| H06 | RiskStateBadge pending | Animated dotted border |
| H07 | RiskStateBadge rejected | Roter Hintergrund + Tooltip mit Error |

## I. Multi-Exchange

| # | Exchange | Test | Erwartet |
|---|----------|------|----------|
| I01 | Bitget | A01-A11 grün | PASS |
| I02 | BingX | A01-A09 grün (kein trailing-modify-in-place, cancel+replace) | PASS |
| I03 | Hyperliquid | A01-A06 grün, A07-A11 NUR als `software_bot` | PASS mit TRAILING_STOP_SOFTWARE |
| I04 | Weex / Bitunix | NotImplementedError beim Readback | 400 mit klarer Fehlermeldung |

## J. Race-Conditions

| # | Szenario | Erwartet |
|---|----------|----------|
| J01 | User-Klick und Position-Monitor reconcile gleichzeitig | Lock verhindert Race, nur ein Update landet |
| J02 | 2 User-Klicks sofort nacheinander (Modify TP twice) | Zweiter wartet auf Lock, beide DB-Writes sehen konsistenten Zustand |
| J03 | Bot-Worker öffnet neuen Trade während reconcile läuft | Reconcile überspringt neuen Trade (last_synced_at < now) |

## K. Observability

| # | Test | Erwartet |
|---|------|----------|
| K01 | Ein apply_intent emittiert `risk_intent_duration_seconds` Histogram | PASS |
| K02 | Ein Reject emittiert `risk_exchange_reject_total{reason_code}` counter | PASS |
| K03 | Reconcile findet Drift → `risk_sync_drift_total{leg}` counter | PASS |
| K04 | classify_close emittiert `risk_classify_close_method{outcome=history_match}` oder `heuristic_fallback` | PASS |
| K05 | Bitget WS down → `ws_connection_state{exchange=bitget}=0` | PASS |

---

## Execution-Plan

### Phase 1 (nach Welle 4 Code fertig)
- [ ] A01-A11 via `pytest tests/integration/live/test_risk_state_bitget_demo.py` (admin user_id=1, live Bitget-Demo)
- [ ] B01-B05 analog
- [ ] C01-C03 via respx-Mocks + Live-Run
- [ ] D01-D06 manuell mit Browser + Bitget-Demo-UI (separate Checklist)
- [ ] E01-E05 via `reconcile_open_trades.py` gegen 4 aktuelle offene Trades
- [ ] F01-F10 via Unit-Tests mit gemockten Snapshots (Teil von #193)
- [ ] G01-G08 via Playwright-E2E (Phase-3, #205)
- [ ] H01-H07 via Vitest + Snapshots (Teil von #194, schon fertig)
- [ ] I01-I04 Matrix wie Phase 1, pro Exchange
- [ ] J01-J03 via Concurrency-Tests mit asyncio.gather
- [ ] K01-K05 via Prometheus-Scrape während Last-Test

### Exit-Kriterium
Alle I01 (Bitget) und H01-H07 + F01-F10 müssen PASS sein bevor Phase 1 als deploy-ready gilt. I02, I03, D01-D06, G01-G08 dürfen nachträglich grün werden — aber ohne Blocker-Bugs.

---

## Bug-Hunt-Heuristiken

Beim Durchlauf explizit suchen nach diesen 4 Anti-Patterns aus Epic #188:
1. **Probe ohne write**: `grep -n "exchange_has\|await client.get_\|probe" src/bot/risk_state_manager.py` — jede match muss in einem DB-update enden.
2. **Heuristischer Klassifizierer**: Default-Reason != EXTERNAL_CLOSE_UNKNOWN ohne Exchange-Probe-Versuch.
3. **Cancel-Error-DEBUG**: `grep -rn "cancel.*except" src/` — kein logger.debug bei Cancel-Fails.
4. **i18n-Kollision**: `Object.values(de.trades.exitReasons)` muss alle unique sein.
