# Monitoring-Alerts einrichten (Alertmanager + Prometheus)

> Deutsch zuerst, English below.

> **Scope:** Diese Anleitung deckt die **Infrastruktur-Alerts** ab
> (Prometheus Alertmanager, Discord/Telegram-Webhooks, `alert_rules.yml`).
> Für **In-App-Alerts** (Price / Strategy / Portfolio) siehe
> [`Alerts-einrichten.md`](./Alerts-einrichten.md). Für den Prometheus/
> Grafana-Basis-Setup siehe [`observability_setup.md`](./observability_setup.md).

---

## Deutsch

### Kurzüberblick

Die Trading-Bot-Infrastruktur wird von Prometheus überwacht. 16 Alert-Regeln
in `monitoring/alert_rules.yml` decken Health, Fehler-Raten, Ressourcen,
Trade-Failures und Backup ab. Alertmanager (`monitoring/alertmanager.yml`)
route diese Alerts an konfigurierte Receiver — standardmäßig an den
internen App-Webhook, optional zusätzlich an Discord oder Telegram.

### Voraussetzungen

- `/metrics`-Endpoint ist live (`PROMETHEUS_ENABLED=true`, Basic-Auth
  gesetzt — siehe `observability_setup.md`).
- Prometheus + Grafana laufen (integrierter Compose-Stack oder
  `monitoring/docker-compose.monitoring.yml`).
- Optional: Discord-Server mit Rechten, Webhooks zu erstellen.
- Optional: Telegram-Bot-Token + Chat-ID (oder Webhook-Proxy).

### Schritt 1 — Verifizieren, dass Prometheus die Regeln geladen hat

Nach dem Deploy prüfen, ob Prometheus die 16 Regeln aus `alert_rules.yml`
kennt:

```bash
# Über SSH-Port-Forward von lokal:
ssh -L 9090:127.0.0.1:9090 trading-bot
# Dann im Browser: http://localhost:9090/alerts
```

Erwartet: 16 Regeln in Status **Inactive** (grün) oder **Firing** (rot).
Wenn die Seite leer ist → `prometheus.yml` lädt `alert_rules.yml` nicht.
Fix: Prometheus-Logs prüfen (`docker logs trading-bot-prometheus`) — meist
ein YAML-Syntaxfehler oder ein falsch gemounteter Pfad.

### Schritt 2 — Alertmanager-Service ergänzen (falls nicht vorhanden)

Die `monitoring/docker-compose.monitoring.yml` enthält aktuell nur
Prometheus + Grafana. Alertmanager muss einmalig ergänzt werden:

```yaml
  alertmanager:
    image: prom/alertmanager:v0.27.0
    container_name: trading-bot-alertmanager
    restart: unless-stopped
    ports:
      - "127.0.0.1:9093:9093"
    volumes:
      - ./alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro
      - alertmanager_data:/alertmanager
    networks:
      - trading-bot-net
    deploy:
      resources:
        limits:
          memory: 128M
```

Volume-Block am Ende der Datei ergänzen:

```yaml
volumes:
  prometheus_data:
  grafana_data:
  alertmanager_data:   # neu
```

Starten:

```bash
cd monitoring
docker compose -f docker-compose.monitoring.yml up -d alertmanager
```

Alertmanager-UI: `http://127.0.0.1:9093` (nur per SSH-Port-Forward
erreichbar — bewusst an `127.0.0.1` gebunden).

### Schritt 3 — Discord-Webhook einrichten

1. In deinem Discord-Server → **Servereinstellungen → Integrationen →
   Webhooks**.
2. **Neuer Webhook** → Kanal auswählen (empfohlen: eigener `#bot-alerts`
   Kanal) → **Webhook-URL kopieren**.
3. In `monitoring/alertmanager.yml` die auskommentierten Discord-Zeilen
   im `critical` Receiver aktivieren:

```yaml
  - name: "critical"
    webhook_configs:
      - url: "http://trading-bot:8000/api/webhooks/alertmanager"
        send_resolved: true
      - url: "https://discord.com/api/webhooks/DEINE_WEBHOOK_ID/DEIN_WEBHOOK_TOKEN"
        send_resolved: true
```

4. Optional auch im `default` Receiver (für Warnings), falls du **alle**
   Alerts in Discord sehen willst — oder nur `critical` (empfohlen, um
   Rauschen zu vermeiden).
5. Alertmanager neu laden:

```bash
docker compose -f docker-compose.monitoring.yml restart alertmanager
```

### Schritt 4 — Webhook testen

Einen manuellen Test-Alert feuern, um den Pfad zu verifizieren:

```bash
curl -XPOST http://127.0.0.1:9093/api/v2/alerts -H 'Content-Type: application/json' -d '[
  {
    "labels": {"alertname": "TestAlert", "severity": "critical"},
    "annotations": {"summary": "Test von Alertmanager", "description": "Wenn das in Discord ankommt, funktioniert das Routing."},
    "startsAt": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"
  }
]'
```

In Discord sollte innerhalb von 30 s eine Nachricht erscheinen (wegen
`group_wait: 30s` in `alertmanager.yml`). Wenn nichts ankommt: Logs prüfen:

```bash
docker logs trading-bot-alertmanager 2>&1 | tail -50
```

Häufige Fehler:

- **`dial tcp: lookup trading-bot`** → der App-Container ist nicht im
  `trading-bot-net` Netzwerk. Prüfen mit
  `docker network inspect trading-bot-net`.
- **`401 Unauthorized`** (Discord) → Webhook-URL ist ungültig oder wurde
  gelöscht. Neuen Webhook erstellen.
- **`http: read on closed response body`** → Firewall blockt ausgehende
  Verbindungen zu `discord.com`. `iptables` / Cloud-Firewall prüfen.

### Schritt 5 — Telegram einrichten (optional, alternativ zu Discord)

Alertmanager hat **keinen** nativen Telegram-Support — man braucht einen
Webhook-Proxy. Zwei Optionen:

**Option A — `alertmanager-telegram`** (einfach, empfohlen):

```yaml
# docker-compose.monitoring.yml ergänzen:
  telegram-proxy:
    image: inCaller/alertmanager-telegram
    container_name: trading-bot-alertmanager-telegram
    restart: unless-stopped
    environment:
      - TELEGRAM_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
    ports:
      - "127.0.0.1:9087:9087"
    networks:
      - trading-bot-net
```

Dann in `alertmanager.yml`:

```yaml
      - url: "http://telegram-proxy:9087/alert"
        send_resolved: true
```

**Option B — App-Webhook wiederverwenden:** Da der Bot bereits Telegram
sendet (siehe `Telegram Benachrichtigungen einrichten.md`), reicht der
interne Webhook `http://trading-bot:8000/api/webhooks/alertmanager` —
dieser leitet Alerts an die App-Notification-Pipeline weiter, die dann
Discord + Telegram gemäß User-Einstellungen bedient. **Nachteil:** wenn
der Bot down ist, kommen keine Alerts an. Deshalb ist ein **externer**
Kanal (Discord-Webhook direkt) immer zusätzlich empfohlen.

### Schritt 6 — Alert-Regeln verstehen

Die 16 Regeln in `alert_rules.yml` im Überblick:

| Alert | Severity | Typischer Fix |
|-------|----------|---------------|
| `HealthCheckFailing` | critical | App/DB down → `docker compose logs trading-bot`, SSH auf VPS. |
| `HighErrorRate` (5xx > 5%) | warning | Neues Deploy kaputt? → Rollback oder Logs. |
| `NoBotsRunning` | warning | Alle Bots gestoppt → absichtlich? Sonst Orchestrator-Status prüfen. |
| `BotInErrorState` | critical | Spezifischer Bot im Error → `GET /api/bots/{id}/status` + Logs. |
| `BotConsecutiveErrors` > 5 | critical | Wiederholte Fails → Exchange-Creds oder Rate-Limit. |
| `HighRequestLatency` (p95 > 2s) | warning | DB-Slow-Query? External API langsam? → Grafana `exchange-health`. |
| `SlowDatabaseQueries` (p95 > 1s) | warning | Index fehlt, `EXPLAIN ANALYZE` der betroffenen Query. |
| `HighWebSocketConnections` > 100 | warning | Potenzieller Abuse → Rate-Limit prüfen. |
| `HighRateLimitHits` (429/s > 1) | warning | Abuse oder ein User im Dauerfeuer → `/api/audit-logs`. |
| `HighMemoryUsage` > 768 MB | warning | Memory-Leak? → APScheduler-Jobs, Bot-Count. |
| `HighDiskUsage` > 85% | warning | Backup-Directory? Postgres-WAL? → `du -sh /var/lib/*`. |
| `CriticalDiskUsage` > 95% | critical | Sofort-Handlung: alte Backups/Logs löschen. |
| `TradeExecutionFailures` > 0.1/s | critical | Exchange-Auth-Fehler oder Insufficient-Balance. |
| `DatabasePoolExhaustion` > 80% | critical | `DB_POOL_SIZE` erhöhen oder Queries profilen. |
| `ExchangeCircuitBreakerOpen` | critical | Exchange-API down → `https://status.bitget.com/`. |
| `BackupJobFailed` > 25 h | critical | `/root/Trading-Bot/backups/` prüfen, Cron-Job-Logs. |
| `DailyLossLimitTriggered` | critical | Bot wurde geschützt gestoppt — manueller Review erforderlich. |

### Schritt 7 — Troubleshooting

| Symptom | Ursache / Fix |
|---------|---------------|
| Prometheus-UI zeigt 0 Regeln | `alert_rules.yml` nicht gemountet oder Syntax-Fehler. Logs: `docker logs trading-bot-prometheus`. |
| Alertmanager-UI zeigt Alert als `firing`, aber keine Nachricht in Discord | Receiver-Config falsch zugeordnet. `alertmanager.yml` → `route.routes` prüfen. Alertmanager-Logs zeigen HTTP-Status des Webhooks. |
| Alert bleibt `firing` auch nach Fix | `repeat_interval` (4h default) → einmal noch, dann auto-resolved. Oder: der zugrunde liegende Metric-Wert ist weiterhin über Schwelle. |
| Alerts kommen doppelt | Mehrere Receiver für selben Alert. Oder Alertmanager läuft in mehreren Instanzen ohne `--cluster.listen-address`. |
| App-Webhook liefert HTTP 500 | `/api/webhooks/alertmanager` Handler kaputt — App-Logs prüfen. Discord-Fallback greift dann nicht automatisch — deshalb ist externer Kanal wichtig. |
| `FiringAlerts` explodiert beim Start | Erwartet: Nach Cold-Start zeigen Gauges wie `bots_running_total=0` kurzzeitig einen Alert-Zustand. Die `for: 5m`-Klausel filtert das normalerweise weg — wenn nicht, Start-Grace im Orchestrator verlängern. |

### Checkliste

```
✓ Prometheus zeigt 16 Regeln unter /alerts
✓ Alertmanager läuft (UI erreichbar via SSH-Forward)
✓ Discord-Webhook erstellt und in alertmanager.yml eingetragen
✓ Test-Alert kommt in Discord an (Schritt 4)
✓ Alertmanager-UI zeigt aktuelle Aktivität (Silences, Routes)
✓ Mindestens ein externer Kanal konfiguriert (nicht nur App-Webhook)
✓ Webhook-Credentials im .env, nicht im Repo
```

### Sicherheitshinweise

- Discord-Webhook-URLs sind **Secrets** — niemals committen. Besser: per
  `envsubst` aus `.env` rendern.
- Alertmanager-Port `9093` nur an `127.0.0.1` binden (default in der
  Compose-Datei). Kein öffentlicher Zugriff.
- `send_resolved: true` ist bewusst aktiv, damit das Team Entwarnung
  bekommt. Wenn das zu viel Noise erzeugt, für spezifische Alerts auf
  `false` setzen.

---

## English

### Overview

The Trading-Bot infrastructure is monitored by Prometheus. 16 alert
rules in `monitoring/alert_rules.yml` cover health, error rates,
resources, trade failures and backups. Alertmanager
(`monitoring/alertmanager.yml`) routes these alerts to configured
receivers — by default to the internal app webhook, optionally also
to Discord or Telegram.

### Prerequisites

- `/metrics` endpoint is live (`PROMETHEUS_ENABLED=true`, basic-auth
  configured — see `observability_setup.md`).
- Prometheus + Grafana are running (integrated compose stack or
  `monitoring/docker-compose.monitoring.yml`).
- Optional: Discord server with permission to create webhooks.
- Optional: Telegram bot token + chat ID (or webhook proxy).

### Step 1 — Verify that Prometheus loaded the rules

After deploy, check that Prometheus knows all 16 rules from
`alert_rules.yml`:

```bash
# Via SSH port-forward from local:
ssh -L 9090:127.0.0.1:9090 trading-bot
# Then in the browser: http://localhost:9090/alerts
```

Expected: 16 rules in status **Inactive** (green) or **Firing** (red).
If the page is empty → `prometheus.yml` isn't loading `alert_rules.yml`.
Fix: check Prometheus logs (`docker logs trading-bot-prometheus`) — usually
a YAML syntax error or a wrongly mounted path.

### Step 2 — Add the Alertmanager service (if missing)

`monitoring/docker-compose.monitoring.yml` currently only contains
Prometheus + Grafana. Alertmanager must be added once:

```yaml
  alertmanager:
    image: prom/alertmanager:v0.27.0
    container_name: trading-bot-alertmanager
    restart: unless-stopped
    ports:
      - "127.0.0.1:9093:9093"
    volumes:
      - ./alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro
      - alertmanager_data:/alertmanager
    networks:
      - trading-bot-net
    deploy:
      resources:
        limits:
          memory: 128M
```

Extend the volumes block at the bottom of the file:

```yaml
volumes:
  prometheus_data:
  grafana_data:
  alertmanager_data:   # new
```

Start it:

```bash
cd monitoring
docker compose -f docker-compose.monitoring.yml up -d alertmanager
```

Alertmanager UI: `http://127.0.0.1:9093` (only reachable via SSH
port-forward — bound to `127.0.0.1` on purpose).

### Step 3 — Configure a Discord webhook

1. In your Discord server → **Server Settings → Integrations →
   Webhooks**.
2. **New Webhook** → pick a channel (recommended: a dedicated
   `#bot-alerts` channel) → **Copy Webhook URL**.
3. In `monitoring/alertmanager.yml` uncomment the Discord lines in the
   `critical` receiver:

```yaml
  - name: "critical"
    webhook_configs:
      - url: "http://trading-bot:8000/api/webhooks/alertmanager"
        send_resolved: true
      - url: "https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN"
        send_resolved: true
```

4. Optionally also in the `default` receiver (for warnings) if you want
   **every** alert in Discord — or just `critical` (recommended, to
   avoid noise).
5. Reload Alertmanager:

```bash
docker compose -f docker-compose.monitoring.yml restart alertmanager
```

### Step 4 — Test the webhook

Fire a manual test alert to verify the end-to-end path:

```bash
curl -XPOST http://127.0.0.1:9093/api/v2/alerts -H 'Content-Type: application/json' -d '[
  {
    "labels": {"alertname": "TestAlert", "severity": "critical"},
    "annotations": {"summary": "Test from Alertmanager", "description": "If this arrives in Discord, routing works."},
    "startsAt": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"
  }
]'
```

A message should appear in Discord within 30 s (because of
`group_wait: 30s` in `alertmanager.yml`). If nothing arrives, check logs:

```bash
docker logs trading-bot-alertmanager 2>&1 | tail -50
```

Common errors:

- **`dial tcp: lookup trading-bot`** → the app container is not on the
  `trading-bot-net` network. Check with
  `docker network inspect trading-bot-net`.
- **`401 Unauthorized`** (Discord) → the webhook URL is invalid or was
  deleted. Create a new webhook.
- **`http: read on closed response body`** → firewall blocks outbound
  connections to `discord.com`. Check `iptables` / cloud firewall.

### Step 5 — Telegram (optional, instead of Discord)

Alertmanager has **no** native Telegram support — you need a webhook
proxy. Two options:

**Option A — `alertmanager-telegram`** (simple, recommended):

```yaml
# add to docker-compose.monitoring.yml:
  telegram-proxy:
    image: inCaller/alertmanager-telegram
    container_name: trading-bot-alertmanager-telegram
    restart: unless-stopped
    environment:
      - TELEGRAM_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
    ports:
      - "127.0.0.1:9087:9087"
    networks:
      - trading-bot-net
```

Then in `alertmanager.yml`:

```yaml
      - url: "http://telegram-proxy:9087/alert"
        send_resolved: true
```

**Option B — reuse the app webhook:** because the bot already sends
Telegram messages (see `Telegram Benachrichtigungen einrichten.md`),
the internal webhook `http://trading-bot:8000/api/webhooks/alertmanager`
is enough — it forwards alerts into the app's notification pipeline
which then dispatches Discord + Telegram based on user settings.
**Downside:** if the bot is down, no alerts arrive. That's why an
**external** channel (direct Discord webhook) is always recommended in
addition.

### Step 6 — Understand the alert rules

The 16 rules in `alert_rules.yml` at a glance:

| Alert | Severity | Typical fix |
|-------|----------|-------------|
| `HealthCheckFailing` | critical | App/DB down → `docker compose logs trading-bot`, SSH onto VPS. |
| `HighErrorRate` (5xx > 5%) | warning | Bad deploy? → rollback or check logs. |
| `NoBotsRunning` | warning | All bots stopped → intentional? Otherwise check orchestrator status. |
| `BotInErrorState` | critical | Specific bot in error → `GET /api/bots/{id}/status` + logs. |
| `BotConsecutiveErrors` > 5 | critical | Repeated failures → exchange creds or rate limit. |
| `HighRequestLatency` (p95 > 2s) | warning | DB slow query? External API slow? → Grafana `exchange-health`. |
| `SlowDatabaseQueries` (p95 > 1s) | warning | Missing index → `EXPLAIN ANALYZE` the culprit query. |
| `HighWebSocketConnections` > 100 | warning | Potential abuse → check rate limits. |
| `HighRateLimitHits` (429/s > 1) | warning | Abuse or single user hammering → `/api/audit-logs`. |
| `HighMemoryUsage` > 768 MB | warning | Memory leak? → APScheduler jobs, bot count. |
| `HighDiskUsage` > 85% | warning | Backup directory? Postgres WAL? → `du -sh /var/lib/*`. |
| `CriticalDiskUsage` > 95% | critical | Immediate action: delete old backups/logs. |
| `TradeExecutionFailures` > 0.1/s | critical | Exchange auth error or insufficient balance. |
| `DatabasePoolExhaustion` > 80% | critical | Raise `DB_POOL_SIZE` or profile queries. |
| `ExchangeCircuitBreakerOpen` | critical | Exchange API down → `https://status.bitget.com/`. |
| `BackupJobFailed` > 25 h | critical | Check `/root/Trading-Bot/backups/`, cron job logs. |
| `DailyLossLimitTriggered` | critical | Bot was safely halted — manual review required. |

### Step 7 — Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Prometheus UI shows 0 rules | `alert_rules.yml` not mounted or syntax error. Logs: `docker logs trading-bot-prometheus`. |
| Alertmanager shows alert as `firing`, but no message in Discord | Receiver config misrouted. Check `alertmanager.yml` → `route.routes`. Alertmanager logs show the HTTP status of the webhook call. |
| Alert stays `firing` even after fix | `repeat_interval` (4h default) → one more, then auto-resolves. Or: underlying metric value is still above threshold. |
| Alerts arrive twice | Multiple receivers for the same alert. Or Alertmanager running in multiple instances without `--cluster.listen-address`. |
| App webhook returns HTTP 500 | `/api/webhooks/alertmanager` handler broken — check app logs. Discord fallback won't kick in automatically — that's why an external channel matters. |
| `FiringAlerts` spikes at startup | Expected: after a cold start, gauges like `bots_running_total=0` briefly trigger alerts. The `for: 5m` clause usually filters this — if not, increase startup grace in the orchestrator. |

### Checklist

```
✓ Prometheus shows 16 rules under /alerts
✓ Alertmanager is running (UI reachable via SSH forward)
✓ Discord webhook created and entered in alertmanager.yml
✓ Test alert arrives in Discord (step 4)
✓ Alertmanager UI shows current activity (silences, routes)
✓ At least one external channel configured (not just the app webhook)
✓ Webhook credentials in .env, not in the repo
```

### Security notes

- Discord webhook URLs are **secrets** — never commit them. Better:
  render via `envsubst` from `.env`.
- Bind Alertmanager port `9093` to `127.0.0.1` only (default in the
  compose file). No public access.
- `send_resolved: true` is intentionally on so the team gets the
  all-clear. If this is too noisy, set it to `false` for specific
  alerts.
