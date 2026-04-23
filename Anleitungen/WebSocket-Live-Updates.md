# WebSocket Live Updates

## Übersicht

Die Plattform nutzt zwei unabhängige WebSocket-Systeme:

1. **Frontend ↔ Server** — Live-Updates im Dashboard (Trades, Bot-Status). **Immer aktiv.**
2. **Server ↔ Exchange** — Push-Modus für Order-Events von Bitget/Hyperliquid. **Admin-Flag, Standard: aus.**

Diese Anleitung erklärt beide Systeme: was du als Nutzer im UI siehst und wie Admins den Exchange-Push-Modus aktivieren.

---

## Teil 1: Frontend-Updates (für alle Nutzer)

### Was wird live aktualisiert?

Solange der Browser-Tab offen ist, pusht der Server folgende Events:

| Event              | Wirkung im UI                                           |
|--------------------|---------------------------------------------------------|
| `bot_started`      | Bot-Status-Badge wechselt auf „Running"                 |
| `bot_stopped`      | Bot-Status-Badge wechselt auf „Stopped"                 |
| `trade_opened`     | Neue Zeile in der Trades-Tabelle                        |
| `trade_closed`     | PnL-Update, Statistik-Kacheln werden aktualisiert       |

Ohne WebSocket müsste die Seite neu geladen werden, um Änderungen zu sehen.

### Verbindungsstatus

Im Dashboard zeigt ein kleiner Indikator den WS-Zustand:

- **`connected`** — alles gut, Updates kommen in Echtzeit
- **`connecting`** — Verbindung wird aufgebaut (kurz beim Login oder nach Tab-Wechsel)
- **`disconnected`** — Verbindung unterbrochen, automatischer Reconnect läuft
- **`failed`** — nach 10 Fehlversuchen aufgegeben; Seite neu laden

### Reconnect-Verhalten

Der Frontend-Hook versucht automatisch neu zu verbinden:

- Exponentieller Backoff: 1 s → 2 s → 4 s → 8 s → ... (max. 30 s)
- Maximal 10 Versuche, dann Status `failed`
- Sofortiger Reconnect, wenn der Tab wieder sichtbar wird (Tab-Wechsel)
- Keep-Alive-Ping alle 30 s

### Authentifizierung

Die Verbindung nutzt dein Login-Cookie (httpOnly `access_token`) — es gibt keinen separaten Login-Schritt. Bei abgelaufenem Cookie wird die Verbindung geschlossen; ein Seiten-Reload loggt dich erneut ein.

### Häufige Probleme

**„disconnected" bleibt bestehen**
- Netzwerk prüfen (z. B. Firewall oder Proxy blockiert WebSocket)
- Browser-Tab neu laden

**„failed" nach längerer Inaktivität**
- Nach 10 fehlgeschlagenen Versuchen gibt der Client auf
- Tab neu laden reicht

**Updates kommen zeitverzögert (30+ s)**
- Meist hat sich der Tab in den Hintergrund begeben; Browser drosselt inaktive WS-Verbindungen
- Fokus zurück auf den Tab → sofortiger Reconnect

---

## Teil 2: Exchange-Push-Modus (nur Admins)

### Was macht der Flag?

Normalerweise fragt der Bot alle ~30 s per REST-Polling bei Bitget/Hyperliquid ab, ob sich Trade-Zustände geändert haben (Order gefüllt, TP/SL ausgelöst, Position geschlossen). Mit dem Flag `EXCHANGE_WEBSOCKETS_ENABLED=true` abonniert der Server stattdessen private WebSocket-Channels der Börsen und reagiert **sofort** auf Events.

**Vorteile:**
- Reaktionslatenz sinkt von ~15 s (halbes Poll-Intervall) auf < 1 s
- Weniger REST-Last auf die Exchange-Quotas

**Was sich NICHT ändert:**
- Die Trade-Logik bleibt identisch (`RiskStateManager.reconcile` ist dieselbe Funktion)
- Bei Verbindungsabbruch übernimmt automatisch der Polling-Fallback

### Status: aktuell deaktiviert auf Produktion

Der Flag ist auf dem Live-Server `46.101.130.50` aktuell **aus**. Grund: der Code ist
infrastrukturell fertig (Commit `fd77ba9`) und mit Mocks getestet, aber noch nicht
gegen Live-Bitget-Demo / HL-Testnet verifiziert. Siehe `tests/integration/live/test_ws_live.py`.

### Unterstützte Exchanges

| Exchange     | Channel                        | Deckt ab                                |
|--------------|--------------------------------|------------------------------------------|
| Bitget       | `orders-algo` (instId=default) | alle USDT-M Futures eines Users          |
| Hyperliquid  | `orderUpdates`                 | alle Trigger-Orders einer Wallet         |
| Weex         | —                              | nicht unterstützt (nur Polling)          |
| BingX        | —                              | nicht unterstützt (nur Polling)          |
| Bitunix      | —                              | nicht unterstützt (nur Polling)          |

### Aktivierung

Auf dem VPS (`46.101.130.50`):

```bash
# 1. Flag in .env setzen
ssh trading-bot
cd /root/Trading-Bot
echo "EXCHANGE_WEBSOCKETS_ENABLED=true" >> .env

# 2. Container neu starten (Container liest .env nur beim Start)
docker compose restart bitget-trading-bot

# 3. Verifizieren
curl -s http://127.0.0.1:8000/api/health | jq '.ws_connections'
# Erwartete Ausgabe (sobald mindestens ein Bot läuft):
# { "bitget": N, "hyperliquid": M }
```

### Monitoring

**`GET /api/health` → `ws_connections`**

Zeigt die Anzahl aktiver Exchange-WS-Verbindungen pro Börse. Wenn ein Bot läuft und
der Zähler `0` ist, ist der Flag entweder aus, oder die WS-Verbindung ist
unterbrochen (der Reconnect-Loop versucht es alle 1 s → 30 s weiter).

**Log-Zeilen** (in `docker logs bitget-trading-bot`):

| Log                                              | Bedeutung                                         |
|--------------------------------------------------|---------------------------------------------------|
| `ws_manager: started (user=X, exchange=bitget)`  | Neue Verbindung aufgebaut                         |
| `ws_manager: reconnect scheduled in Ns`          | Backoff läuft, siehe Wert von N                   |
| `ws_manager: on_reconnect → reconcile sweep`     | Reconnect erfolgreich, alle offenen Trades geprüft |
| `ws_manager: unknown event_type dropped`         | Unbekanntes Event (z. B. manueller Trade in App), kein Fehler |

### Reconnect-Strategie

- Backoff: `1 s, 2 s, 4 s, 8 s, 30 s (cap, wiederholt)` — **gibt niemals auf**
- Kein Replay verpasster Events — stattdessen läuft nach jedem Reconnect ein
  `reconcile`-Sweep über alle offenen Trades des betroffenen Users. Die Exchange
  ist „source of truth", `reconcile` ist idempotent → einfacher und korrekter
  als Event-Buffering.

### Rollback

Falls etwas schiefgeht: Flag entfernen oder `false` setzen, Container neu starten.
Der Code fällt automatisch auf das REST-Polling zurück (kein Daten- oder
Funktionsverlust).

```bash
sed -i '/^EXCHANGE_WEBSOCKETS_ENABLED=/d' .env
docker compose restart bitget-trading-bot
```

### Bekannte Einschränkungen

1. **Noch nicht live-verifiziert** — Unit-Tests mocken Bitgets `orders-algo`-Payloads.
   Vor Aktivierung auf Prod sollte `tests/integration/live/test_ws_live.py` gegen
   ein Demo-Konto laufen.
2. **Keine Drop/Latenz-Metriken** — nur Connected-Count über Health-Endpoint.
3. **Ein Abonnement pro User pro Exchange** — kein Subaccount-Scoping.
4. **Pro Docker-Replika eine Verbindung** — bei Multi-Replika-Deployment öffnet
   jede Replika ihre eigene WS. Duplicate Events sind harmlos (reconcile ist
   idempotent), aber der Health-Counter ist pro-Replika.

### Entwickler-Referenz

Tiefergehende Architektur-Doku: `docs/websockets.md` im Repo-Root.

---

# WebSocket Live Updates (English)

## Overview

The platform uses two independent WebSocket systems:

1. **Frontend ↔ Server** — live updates in the dashboard (trades, bot status). **Always active.**
2. **Server ↔ Exchange** — push mode for Bitget/Hyperliquid order events. **Admin flag, default off.**

This guide covers both: what end users see in the UI, and how admins enable the exchange push mode.

---

## Part 1: Frontend Updates (for all users)

### What is updated live?

As long as the browser tab is open, the server pushes these events:

| Event              | UI effect                                               |
|--------------------|---------------------------------------------------------|
| `bot_started`      | Bot status badge flips to "Running"                     |
| `bot_stopped`      | Bot status badge flips to "Stopped"                     |
| `trade_opened`     | New row appears in the trades table                     |
| `trade_closed`     | PnL updates, statistics tiles recalculated              |

Without WebSocket, you would have to reload the page to see changes.

### Connection status

A small indicator in the dashboard shows the WS state:

- **`connected`** — all good, updates arrive in real time
- **`connecting`** — connection being established (brief on login or tab focus)
- **`disconnected`** — connection dropped, automatic reconnect running
- **`failed`** — gave up after 10 attempts; reload the page

### Reconnect behavior

The frontend hook reconnects automatically:

- Exponential backoff: 1s → 2s → 4s → 8s → ... (max 30s)
- Up to 10 attempts, then `failed`
- Immediate reconnect when the tab becomes visible again
- Keep-alive ping every 30s

### Authentication

The connection uses your login cookie (httpOnly `access_token`) — no separate
auth step. If the cookie expires, the connection closes; a page reload re-authenticates.

### Common issues

**"disconnected" persists**
- Check network (firewall or proxy may block WebSocket)
- Reload the browser tab

**"failed" after long inactivity**
- After 10 failed attempts, the client gives up
- Reloading the tab is enough

**Updates lag by 30+ seconds**
- Usually the tab went to background; browsers throttle inactive WS
- Focus the tab → immediate reconnect

---

## Part 2: Exchange Push Mode (admins only)

### What the flag does

By default, the bot polls Bitget/Hyperliquid every ~30s via REST to check for
trade state changes (order filled, TP/SL triggered, position closed). With
`EXCHANGE_WEBSOCKETS_ENABLED=true`, the server subscribes to private WebSocket
channels and reacts **immediately** to events instead.

**Benefits:**
- Reaction latency drops from ~15s (half the poll interval) to < 1s
- Lower REST load against exchange quotas

**What does NOT change:**
- Trade logic is identical (`RiskStateManager.reconcile` is the same function)
- On a WS drop, the polling fallback takes over automatically

### Status: currently disabled in production

The flag is **off** on the live server `46.101.130.50`. Reason: the code is
infrastructurally complete (commit `fd77ba9`) and mock-tested, but not yet
verified against live Bitget-demo / HL-testnet. See
`tests/integration/live/test_ws_live.py`.

### Supported exchanges

| Exchange     | Channel                        | Coverage                                 |
|--------------|--------------------------------|------------------------------------------|
| Bitget       | `orders-algo` (instId=default) | all USDT-M futures for a user            |
| Hyperliquid  | `orderUpdates`                 | all trigger orders for a wallet          |
| Weex         | —                              | not supported (polling only)             |
| BingX        | —                              | not supported (polling only)             |
| Bitunix      | —                              | not supported (polling only)             |

### Enabling

On the VPS (`46.101.130.50`):

```bash
# 1. Set the flag in .env
ssh trading-bot
cd /root/Trading-Bot
echo "EXCHANGE_WEBSOCKETS_ENABLED=true" >> .env

# 2. Restart the container (.env is only read at startup)
docker compose restart bitget-trading-bot

# 3. Verify
curl -s http://127.0.0.1:8000/api/health | jq '.ws_connections'
# Expected output (once at least one bot is running):
# { "bitget": N, "hyperliquid": M }
```

### Monitoring

**`GET /api/health` → `ws_connections`**

Shows the count of active exchange-WS connections per exchange. If a bot is running
and the counter is `0`, the flag is either off or the connection dropped
(the reconnect loop keeps retrying at 1s → 30s).

**Log lines** (from `docker logs bitget-trading-bot`):

| Log                                              | Meaning                                            |
|--------------------------------------------------|----------------------------------------------------|
| `ws_manager: started (user=X, exchange=bitget)`  | New connection established                         |
| `ws_manager: reconnect scheduled in Ns`          | Backoff active, see value of N                     |
| `ws_manager: on_reconnect → reconcile sweep`     | Reconnect OK, all open trades re-checked           |
| `ws_manager: unknown event_type dropped`         | Unknown event (e.g. manual trade in app), not an error |

### Reconnect strategy

- Backoff: `1s, 2s, 4s, 8s, 30s (cap, repeats)` — **never gives up**
- No replay of missed events — after every reconnect a `reconcile` sweep runs
  across all open trades of the affected user. The exchange is source of truth,
  `reconcile` is idempotent → simpler and more correct than event buffering.

### Rollback

If something goes wrong: remove or set the flag to `false`, restart the container.
The code falls back to REST polling automatically (no data or feature loss).

```bash
sed -i '/^EXCHANGE_WEBSOCKETS_ENABLED=/d' .env
docker compose restart bitget-trading-bot
```

### Known limitations

1. **Not yet live-verified** — unit tests mock Bitget's `orders-algo` payloads.
   Before enabling on prod, run `tests/integration/live/test_ws_live.py` against
   a demo account.
2. **No drop/latency metrics** — only connected-count via the health endpoint.
3. **One subscription per user per exchange** — no subaccount scoping.
4. **One connection per Docker replica** — in a multi-replica deployment, each
   replica opens its own WS. Duplicate events are harmless (reconcile is
   idempotent), but the health counter is per-replica.

### Developer reference

Deeper architecture doc: `docs/websockets.md` in the repo root.
