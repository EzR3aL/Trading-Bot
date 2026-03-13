# Debug: ETH Trailing Stop nicht ausgelöst

## Deutsch

### Hintergrund
Der ETH Edge Bot (ETHUSDT LONG, Entry $2,126.16) war zuvor deutlich im Plus, aber der Trailing Stop hat den Trade nicht geschlossen. Auf Bitget zeigt Trailing TP/SL "--".

### Schritt 1: Server-Logs prüfen

```bash
# SSH auf den Server
ssh root@46.101.130.50

# Logs der letzten 24h filtern nach ETHUSDT und Trailing
docker logs bitget-trading-bot --since 24h 2>&1 | grep -i -E "trailing|ETHUSDT" | tail -80

# Speziell nach Fehlern suchen
docker logs bitget-trading-bot --since 24h 2>&1 | grep -i -E "Failed to place|exit check error|Monitor error|trailing stop placed" | tail -30

# Bot-Restarts prüfen
docker logs bitget-trading-bot --since 24h 2>&1 | grep -i -E "startup|lifespan|shutdown|restart|scheduler" | tail -20
```

### Schritt 2: Datenbank prüfen

```bash
# Trade-Record anschauen (highest_price ist entscheidend)
docker exec tradingbot-postgres psql -U trading -d tradingbot -c "
SELECT id, symbol, side, entry_price, highest_price, native_trailing_stop,
       take_profit, stop_loss, status, entry_time, bot_config_id
FROM trade_records
WHERE symbol='ETHUSDT' AND status='open'
ORDER BY id DESC LIMIT 5;
"

# Session-Tabelle: War der Bot-Worker aktiv?
docker exec tradingbot-postgres psql -U trading -d tradingbot -c "
SELECT id, name, strategy, is_active, updated_at
FROM bot_configs
WHERE name ILIKE '%ETH%Edge%'
ORDER BY id DESC LIMIT 5;
"
```

### Schritt 3: Ergebnisse interpretieren

| Feld | Erwartung | Problem wenn... |
|------|-----------|-----------------|
| `highest_price` | Deutlich über entry_price | = entry_price → Tracking kaputt |
| `native_trailing_stop` | `true` | `false` → Bitget-Platzierung fehlgeschlagen |
| Logs: "trailing stop placed" | Vorhanden | Fehlt → Wurde nie versucht |
| Logs: "Failed to place" | Nicht vorhanden | Vorhanden → API-Fehler |
| Logs: "Monitor error" | Nicht vorhanden | Vorhanden → Monitor-Loop kaputt |
| Logs: "startup" | 1x (beim Deploy) | Mehrfach → Bot hat neugestartet |

### Schritt 4: Ergebnisse an Claude übergeben

Kopiere die Ausgaben der Befehle und gib sie in der nächsten Claude-Session ein. Claude hat das Thema in Memory gespeichert und wird dort weitermachen.

---

## English

### Background
The ETH Edge Bot (ETHUSDT LONG, entry $2,126.16) was significantly profitable earlier, but the trailing stop did not close the trade. Bitget shows Trailing TP/SL as "--".

### Step 1: Check server logs

```bash
ssh root@46.101.130.50

# Filter last 24h logs for ETHUSDT and trailing
docker logs bitget-trading-bot --since 24h 2>&1 | grep -i -E "trailing|ETHUSDT" | tail -80

# Search for errors specifically
docker logs bitget-trading-bot --since 24h 2>&1 | grep -i -E "Failed to place|exit check error|Monitor error|trailing stop placed" | tail -30

# Check for bot restarts
docker logs bitget-trading-bot --since 24h 2>&1 | grep -i -E "startup|lifespan|shutdown|restart|scheduler" | tail -20
```

### Step 2: Check database

```bash
docker exec tradingbot-postgres psql -U trading -d tradingbot -c "
SELECT id, symbol, side, entry_price, highest_price, native_trailing_stop,
       take_profit, stop_loss, status, entry_time, bot_config_id
FROM trade_records
WHERE symbol='ETHUSDT' AND status='open'
ORDER BY id DESC LIMIT 5;
"
```

### Step 3: Share results with Claude

Copy the command outputs and paste them in the next Claude session. The investigation context is saved in Claude's memory.
