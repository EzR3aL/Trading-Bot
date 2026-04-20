# Audit-Skripte (#216 Section 2.4)

Vier Skripte im Ordner `scripts/` suchen automatisch nach Bugs und Drift
zwischen Bot-DB und Börsen-Realität. Sie laufen **stündlich** im
Hintergrund (wenn der `AuditScheduler` aktiv ist) und können **manuell**
für gezielte Checks ausgeführt werden.

## Die vier Skripte

| Skript | Was wird geprüft? |
|---|---|
| `audit_tp_sl_flags.py` | DB-TP/SL-Felder vs. Börsen-Plan-State (via `get_position_tpsl`) |
| `audit_position_size.py` | DB `trade.size` vs. Exchange `position.size` (0.5% Toleranz) |
| `audit_price_sanity.py` | Geschlossene Trades: `entry_price`/`exit_price` vs. Binance-Kline (>2% flag) |
| `audit_classify_method.py` | Log-Scan: wie oft wurde Heuristik-Fallback genutzt? (Pattern-B-Alarm) |

## Manuell ausführen — Dry-Run (nur lesen)

```bash
# TP/SL-Vergleich für alle offenen Trades
docker exec bitget-trading-bot \
    python /app/scripts/audit_tp_sl_flags.py

# Nur einen User / eine Börse prüfen
docker exec bitget-trading-bot \
    python /app/scripts/audit_position_size.py --user-id 4 --exchange bitget

# Preis-Sanity mit 48-Stunden-Fenster
docker exec bitget-trading-bot \
    python /app/scripts/audit_price_sanity.py --hours 48

# Classify-Method mit 24-Stunden-Fenster
docker exec bitget-trading-bot \
    python /app/scripts/audit_classify_method.py --hours 24
```

Jedes Skript schreibt einen Markdown-Report nach
`reports/<skriptname>-YYYY-MM-DD-HHMM.md`.

## Manuell ausführen — Apply-Modus

> **Wichtig:** `audit_tp_sl_flags.py` und `audit_price_sanity.py` schreiben
> **niemals** in die DB, auch nicht mit `--apply`. Für echte Korrekturen
> immer `scripts/reconcile_open_trades.py --apply` nutzen (das ist das
> autoritative Healing-Tool aus #198).

Der `--apply`-Flag existiert zur Interface-Parität; Skripte bestätigen
nur via interaktivem Prompt, dass du den Modus bewusst aktivieren willst:

```bash
docker exec -it bitget-trading-bot \
    python /app/scripts/audit_position_size.py --apply
# → "WARNING: --apply will write corrections to the DB. Continue? [y/N]:"

# Ohne interaktiven Prompt (für CI / Scripts):
docker exec bitget-trading-bot \
    python /app/scripts/audit_position_size.py --apply --yes
```

## Automatischer Hintergrund-Scheduler

Der `AuditScheduler` startet mit der App, **wenn** die ENV-Variable
`AUTO_AUDIT_ENABLED=true` gesetzt ist:

```bash
# .env (oder docker-compose.yml environment)
AUTO_AUDIT_ENABLED=true

# Admin-Notifications (optional; fehlen → nur Log-Warnung)
ADMIN_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
ADMIN_TELEGRAM_BOT_TOKEN=...
ADMIN_TELEGRAM_CHAT_ID=...
```

Wenn aktiv laufen die vier Audits in diesem stündlichen Takt:

| Minute (UTC) | Audit |
|---|---|
| `:00` | `audit_tp_sl_flags` |
| `:15` | `audit_position_size` |
| `:30` | `audit_price_sanity` (letzte 24 h) |
| `:45` | `audit_classify_method` (letzte 1 h) |

Bei einem Finding (Mismatch, Desync, Preis-Abweichung oder Fallback-Spike)
schickt der Scheduler eine kompakte Zusammenfassung an Discord und/oder
Telegram. Saubere Läufe erzeugen **keine** Notification — nur das
Logfile-Marker `audit_scheduler.run clean job=...`.

## Reports lesen

```bash
ls -lt reports/ | head
cat reports/audit-position-size-2026-04-20-1315.md
```

Jeder Report startet mit `## Summary`, gefolgt von einer Findings-Tabelle
(falls welche gefunden wurden) und optional `## Skipped` / `## Errors`.
