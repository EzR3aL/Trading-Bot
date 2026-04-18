# Live Integration Tests (Bitget Demo)

This directory holds the **live** integration test suite for Issue #197 / Epic #188.
Unlike the unit tests under `tests/unit/` or the in-memory integration tests
under `tests/integration/`, these tests talk to the **real Bitget demo API**
and mutate state on the admin account (`user_id=1`, Bitget-Demo-Connection #1).

## Scope

| Section | Tests | Status |
|---------|-------|--------|
| A — Frontend → Exchange Roundtrip | A01–A11 (11 tests) | ✅ implemented |
| B — Partial-Success / Reject     | B01–B05 (5 tests)  | ✅ implemented |
| C — Cancel-Failure (respx mocks) | C01, C03 (2 tests) | ✅ implemented |
| I01 — Bitget multi-exchange row  | Sum of A + B + C   | ✅ covered     |

The full test matrix lives in [`TEST_MATRIX.md`](./TEST_MATRIX.md).

## Voraussetzungen

- SSH-Zugang zum Legacy-Server `46.101.130.50` (oder lokale DB mit admin
  credentials, falls der Bitget-Demo-Account lokal provisioniert ist).
- Environment variable `BITGET_LIVE_TEST_USER_ID` gesetzt auf den User, der
  die Bitget-Demo-Connection hält (default `1` = admin auf dem Legacy-Server).
- Running Postgres mit dem vollen Schema (Alembic-Migrationen applied).
- Encryption-Key, der die im DB gespeicherten Demo-Credentials entschlüsseln
  kann (`ENCRYPTION_KEY` env var).

## Ausführen

### Auf dem Server (empfohlen)

```bash
docker exec bitget-trading-bot \
    bash -c "BITGET_LIVE_TEST_USER_ID=1 pytest tests/integration/live/ \
             -v -m bitget_live --tb=short"
```

Der Marker `-m bitget_live` ist erforderlich — ohne ihn werden die Tests
standardmässig übersprungen (das ist Absicht, damit ein regulärer
`pytest`-Lauf die Live-Bitget-API nicht berührt).

### Lokal (falls DB und Credentials verfügbar)

```bash
export BITGET_LIVE_TEST_USER_ID=1
export DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/tradingbot"
export ENCRYPTION_KEY="<base64 encryption key>"
export JWT_SECRET_KEY="<any string>"

pytest tests/integration/live/ -v -m bitget_live --tb=short
```

Wenn lokal keine Admin-Credentials verfügbar sind, skipt die `admin_bitget_client`
Fixture alle Tests mit der Meldung `No Bitget demo client configured for user_id=1`.
Das ist OK — die Tests sind dafür gebaut, primär auf dem Server zu laufen.

### Selektiv

```bash
# Nur Section A
pytest tests/integration/live/test_risk_state_bitget_demo.py::test_A01_set_tp_only_on_long_position -v

# Nur Reject-Pfade
pytest tests/integration/live/ -v -m bitget_live -k "test_B"

# Nur die mock-basierten C-Tests
pytest tests/integration/live/ -v -m bitget_live -k "test_C"
```

## Default Behavior (Safety)

```bash
pytest tests/        # → skipt alle bitget_live Tests, sicher
pytest tests/integration/   # → skipt alle bitget_live Tests, sicher
```

## Laufzeit

- A01–A11 (11 Tests): jeweils ~8–10s (1× Position öffnen + schliessen pro Test).
- B01–B05 (5 Tests): jeweils ~8–10s.
- C01, C03 (2 Tests): jeweils ~8s (Position öffnen + DB-Setup + Mock-Stub).
- **Total: ~2.5–3 Minuten für 18 Tests bei sauberem Durchlauf.**

## Cleanup-Garantie

Jede Test-Position wird in einem `finally`-Block geräumt:

```python
@pytest_asyncio.fixture
async def demo_long_position(admin_bitget_client):
    ...
    try:
        trade_info = await _open_position(...)
        yield trade_info
    finally:
        if trade_info is not None:
            await _teardown_trade(admin_bitget_client, trade_info)
```

`_teardown_trade` ruft zwei Bitget-Endpoints (best-effort, Fehler werden
geschluckt), damit der nächste Test sauber startet:

1. `close_position(symbol, side)` — schliesst die Demo-Position via
   Flash-Close-Endpoint.
2. `cancel_position_tpsl(symbol, side)` — cancelt jeden `pos_profit`,
   `pos_loss`, `moving_plan`, `profit_plan`, `loss_plan` auf dem Symbol.

## Idempotenz

Die Tests sind so gebaut, dass zweimaliges Laufen nacheinander das gleiche
Ergebnis liefert: jeder Test öffnet eine frische Position mit eigenem
`trade_id`, und die Cleanup-Logik räumt am Ende aller offenen Plan-Orders.

## Expected Outcomes

Bei einem sauberen Durchlauf sollten alle 18 Tests grün sein.

Wenn Tests rot sind, prüfe in dieser Reihenfolge:

1. **Bitget-Demo-Outage**: `scripts/live_mode_smoke.py --user-id 1 --exchanges bitget`
   liefert `get_open_positions` + `get_ticker`? Wenn nicht, ist Bitget down.
2. **Min-Size-Verletzung**: Bitget-Demo hat manchmal eigene Min-Size-Grenzen.
   `LIVE_TEST_SIZE = 0.001` in `conftest.py` muss oberhalb der aktuellen
   Bitget-Min-Size für BTCUSDT liegen.
3. **Rate-Limit**: falls Tests zu schnell hintereinander laufen (parallele
   pytest-workers), kann Bitget 429 liefern. Den Suite **immer seriell**
   laufen lassen (`pytest -n0` oder ohne `xdist`).
4. **Drift-Probleme**: falls eine frühere Test-Run-Reste auf dem Account
   hat, kann das nächste Test-Open fehlschlagen. Einmal manuell das Konto
   räumen:

   ```bash
   docker exec bitget-trading-bot python -c "
   import asyncio
   from scripts.reconcile_open_trades import main
   asyncio.run(main(user_id=1, exchange='bitget', apply=True))
   "
   ```

## Bug-Hunt-Heuristiken

Siehe [`TEST_MATRIX.md`](./TEST_MATRIX.md) Sektion "Bug-Hunt-Heuristiken".
Bei roten Tests immer prüfen, ob eines der 4 Anti-Patterns aus Epic #188
zurückgekehrt ist:

1. Probe ohne write (Pattern A).
2. Heuristischer Klassifizierer ohne Probe (Pattern B).
3. Cancel-Error-DEBUG (Pattern C).
4. i18n-Kollision bei neuen Reason-Codes.

## CI Integration

**Diese Tests laufen NICHT in PR-CI** — die erforderlichen Bitget-Credentials
fehlen dort bewusst. Ausführung erfolgt ausschliesslich manuell auf dem
Legacy-Server oder lokal mit explizit gesetzten Credentials.

## Matrix Coverage

Aus [`TEST_MATRIX.md`](./TEST_MATRIX.md):

- **Sektion A komplett** (11 Tests) — implementiert als `test_A01`..`test_A11`.
- **Sektion B komplett** (5 Tests) — implementiert als `test_B01`..`test_B05`.
- **Sektion C01 + C03** (2 Tests) — implementiert als `test_C01_tp_cancel_transient_error_no_place`
  und `test_C03_trailing_cancel_500_no_new_order`.
- **Sektion C02** ("already gone" auf cancel 404): nicht live testbar ohne
  race-condition, wird separat als Unit-Test in `tests/unit/bot/test_risk_state_manager.py`
  abgedeckt (Teil von #190).
- **Sektion I01** (Bitget Multi-Exchange Row): automatisch erfüllt durch
  grüne A+B+C-Tests gegen Bitget.
