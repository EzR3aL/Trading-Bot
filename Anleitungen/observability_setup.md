# Observability Setup (Prometheus Metrics)

> Deutsch zuerst, English below.

---

## Deutsch

### Kurzüberblick (PR-1 von #327)

Issue [#327](https://github.com/EzR3aL/Trading-Bot/issues/327) führt eine
Prometheus-basierte Observability-Schicht ein. PR-1 landet **nur die
Infrastruktur**: zentrale Metric-Registry, Metric-Definitionen und einen
geschützten `/metrics`-Endpoint. Instrumentierung der HTTP-Middleware,
BotWorker-Komponenten, RiskStateManager und Exchange-Adapter folgt in
PR-2 bis PR-4. Grafana-Dashboards kommen in PR-5.

### Endpoint aktivieren

Der Endpoint ist per Default **aus**. Drei Environment-Variablen werden
benötigt:

```env
PROMETHEUS_ENABLED=true
METRICS_BASIC_AUTH_USER=prom-scraper
METRICS_BASIC_AUTH_PASSWORD=<starkes-random-passwort>
```

Nach dem Setzen der Variablen den Bot neu starten. Der Endpoint ist
danach unter `https://<deine-domain>/metrics` erreichbar — mit
HTTP-Basic-Auth.

### Verhalten

| Flag | Auth | Status |
|------|------|--------|
| `PROMETHEUS_ENABLED=false` (oder nicht gesetzt) | — | **404** — die Existenz des Endpoints wird bewusst nicht geleakt. |
| `PROMETHEUS_ENABLED=true` | kein `Authorization`-Header | **401** mit `WWW-Authenticate: Basic`. |
| `PROMETHEUS_ENABLED=true` | falsche Credentials | **401**. |
| `PROMETHEUS_ENABLED=true` | korrekte Credentials | **200** mit Prometheus-Text-Exposition-Format. |

### Sicherheitshinweise

- Passwort-Vergleich ist timing-safe (`secrets.compare_digest`).
- `/metrics` **muss** hinter HTTPS stehen — Basic-Auth über Plain-HTTP
  leakt die Credentials.
- Für zusätzliche Härtung empfiehlt sich eine IP-Allowlist auf der
  Nginx/Traefik-Ebene. Basic-Auth ist die letzte Verteidigungslinie,
  nicht die einzige.
- Labels enthalten bewusst keine User-E-Mails, Wallet-Adressen oder
  API-Keys — nur `bot_id` und `exchange` (Issue #327, Security-Erwägungen).

### HTTP-Metrics (PR-2 von #327)

Mit PR-2 werden drei HTTP-Metriken automatisch befüllt, sobald der
`PROMETHEUS_ENABLED`-Flag **an** ist:

| Metrik | Typ | Labels |
|--------|-----|--------|
| `http_requests_total` | Counter | `method`, `path`, `status` |
| `http_request_duration_seconds` | Histogram | `method`, `path` |
| `http_requests_in_flight` | Gauge | `method`, `path` |

Die Middleware `src/api/middleware/metrics.py` läuft als äußerste
Schicht des Middleware-Stacks, damit das Histogramm auch die Zeit
aller anderen Middlewares (Auth, Rate-Limit, Security-Header) erfasst.
Sie ist als reine ASGI-Middleware geschrieben, weil sie den
matched-Route-Template **vor** dem Handler-Aufruf auflösen muss
(über `Route.matches(scope)`), damit der In-Flight-Counter denselben
Label-Wert für `inc()` und `dec()` sieht.

**Template-Path-Collapsing (Kardinalitätsschutz):**
`GET /api/bots/42`, `GET /api/bots/17`, `GET /api/bots/999` landen
**alle** unter `path="/api/bots/{bot_id}"`. Ohne diese Normalisierung
würde die Prometheus-Zeitreihenzahl mit jeder Bot-ID wachsen —
`http_requests_total` hätte dann Millionen Serien statt Dutzenden.
Requests, die auf **keine** Route matchen (404), werden unter dem
Sentinel `path="<unmatched>"` gezählt, nie mit dem rohen Request-Pfad.

**`/metrics` ist selbst nicht instrumentiert:**
Prometheus scraped den Endpoint alle 15 s — Self-Observation würde
nur konstantes Hintergrundrauschen ohne operativen Wert produzieren.
Die Middleware macht einen Early-Return, sobald der Request-Pfad mit
`/metrics` beginnt.

**Legacy-Middleware entfernt (#337):**
Die alte `src/monitoring/middleware.py` (die HTTP-Metriken gegen die
Default-Registry geschrieben hat) wurde in #337 entfernt. Einziger
HTTP-Metrics-Pfad ist jetzt `src/api/middleware/metrics.py` gegen die
dedizierte `OBSERVABILITY_REGISTRY`.

### Grafana-Dashboards + lokaler Stack (PR-5 von #327)

PR-5 liefert drei Grafana-Dashboards, die Auto-Provisioning-Konfiguration
und einen optionalen standalone Monitoring-Stack.

#### Voraussetzungen

- Docker + Docker Compose v2 (`docker compose version`).
- Ports **9090** (Prometheus) und **3000** (Grafana) frei auf `127.0.0.1`.
- `/metrics`-Endpoint der App ist bereits aktiv (PR-1 + PR-2 Setup,
  siehe oben: `PROMETHEUS_ENABLED=true`, Basic-Auth gesetzt).

#### Setup-Schritte (integrierter Stack im Haupt-Compose)

Die Haupt-`docker-compose.yml` am Repo-Root hat Prometheus + Grafana
bereits als Services — für die meisten Setups ist nichts Zusätzliches
zu tun:

```bash
# im Repo-Root
cp .env.example .env  # falls noch nicht vorhanden
# In .env setzen:
#   PROMETHEUS_ENABLED=true
#   METRICS_BASIC_AUTH_USER=prom-scraper
#   METRICS_BASIC_AUTH_PASSWORD=<starkes-passwort>
#   GF_ADMIN_PASSWORD=<starkes-admin-passwort>
docker compose up -d
```

Grafana ist dann unter `http://127.0.0.1:3000` erreichbar.

#### Setup-Schritte (standalone Stack, App läuft außerhalb Compose)

Für Setups, bei denen die Trading-Bot-API **nicht** im Compose läuft
(z.B. bare-metal oder separater Compose-Stack), gibt es
`monitoring/docker-compose.monitoring.yml`:

```bash
# Externes Netzwerk einmalig anlegen
docker network create trading-bot-net

# App-Container mit diesem Netzwerk verbinden
# (je nach Setup: docker run --network trading-bot-net ..., oder
#  in der Haupt-Compose das external network referenzieren)

cd monitoring
GF_ADMIN_PASSWORD='<starkes-passwort>' docker compose \
  -f docker-compose.monitoring.yml up -d
```

Services:

| Service | Port | Volume | Zweck |
|---------|------|--------|-------|
| `prometheus` | 9090 | `prometheus_data` | Scraper, TSDB, 15 d Retention |
| `grafana` | 3000 | `grafana_data` | UI + Dashboard-Rendering |

Grafana-Credentials: default `admin`/`admin` → **unmittelbar nach dem
ersten Login auf ein eigenes Passwort ändern** (oder vorher per
`GF_ADMIN_PASSWORD`-Env-Var überschreiben).

#### Auto-Provisioning

Beim Start liest Grafana automatisch:

- `monitoring/grafana/provisioning/datasources/datasources.yml`
  → legt die Prometheus-Datasource (und im Haupt-Stack auch Postgres) an.
- `monitoring/grafana/provisioning/dashboards/dashboards.yml`
  → lädt alle JSON-Dashboards aus `/var/lib/grafana/dashboards`.

Aktuell enthalten:

| Dashboard (UID) | Datei | Fokus |
|-----------------|-------|-------|
| `trading-bot-overview` | `trading-bot-overview.json` | Top-Level: HTTP, Signals, Trades, Risk, Exchange Errors |
| `trading-bot-detail` | `bot-detail.json` | Drill-Down pro `bot_id` (Template-Variable) |
| `trading-bot-exchange-health` | `exchange-health.json` | Exchange-Layer: API rate, Latenz, WebSocket-Status |
| `admin-support` | `admin-support.json` | Legacy Admin-Tabellen (Postgres-Queries) |

#### Neue Metrics hinzufügen (Dev-Workflow)

1. Metric-Definition ergänzen in `src/observability/metrics.py`
   (z.B. neuer `Counter` mit klarer Label-Liste, max 3-4 Labels, keine
   high-cardinality Felder wie `user_id` / `symbol` ohne Aggregation).
2. Instrumentieren an der Call-Site: `METRIC.labels(...).inc()` /
   `.observe()` / `.set()`.
3. Unit-Test in `tests/unit/observability/` — mindestens ein
   Happy-Path-Case, der den Registry-Zustand nach dem Call prüft.
4. Dashboard-Panel in der passenden JSON-Datei hinzufügen
   (PromQL, `rate(...)`-Window = 5m, p95 per `histogram_quantile`).
5. CHANGELOG-Eintrag unter `## [Unreleased]` → `### Added`.

#### Troubleshooting

| Symptom | Ursache / Fix |
|---------|---------------|
| Prometheus-Target `DOWN` | `/metrics` nicht erreichbar. Check: `curl -u $USER:$PASS http://<api>:8000/metrics`. Wenn 404 → `PROMETHEUS_ENABLED=false`. Wenn 401 → Basic-Auth stimmt nicht. |
| Grafana Panel "No data" | Entweder Metric noch nie gesampelt (PR-3/4 noch nicht live) oder Label-Wert in PromQL passt nicht (z.B. `exchange="hyperliquid"` aber Adapter schreibt `HYPERLIQUID`). |
| `scrape_configs` ändert sich nicht | Prometheus muss gereloaded werden: `docker compose restart prometheus` oder `curl -X POST http://localhost:9090/-/reload`. |
| Dashboard nicht sichtbar | Prüfen ob JSON valide ist (`python -c "import json; json.load(open('monitoring/grafana/dashboards/<file>.json'))"`). Grafana-Logs: `docker logs tradingbot-grafana \| grep -i provisioning`. |
| Basic-Auth klappt im Browser, nicht in Prometheus | Prometheus `basic_auth` erwartet **unquoted** Strings in `prometheus.yml`. Env-Var-Interpolation wie `${METRICS_BASIC_AUTH_USER}` wird von Prometheus **nicht** nativ expandiert → entweder hart reinschreiben oder per `envsubst` rendern. |

#### Security-Hinweise

- `/metrics` **niemals** public exposed lassen — weder ohne Auth noch
  ohne HTTPS. Selbst mit Basic-Auth leakt Plain-HTTP die Credentials.
- Basic-Auth-Credentials regelmäßig rotieren (Quartal-Rhythmus
  empfohlen). Passwort ≥ 32 Zeichen, per `openssl rand -base64 32`.
- Grafana-Admin-Passwort ebenfalls rotieren. `GF_USERS_ALLOW_SIGN_UP=false`
  ist gesetzt — kein Self-Service-Signup.
- Prometheus + Grafana sind im Compose-Setup an `127.0.0.1` gebunden,
  **nicht** an `0.0.0.0`. Zugriff nur per SSH-Port-Forward:
  `ssh -L 3000:127.0.0.1:3000 trading-bot`.
- Labels enthalten bewusst **keine** PII (siehe PR-1 Security-Notes).

---

## English

### Overview (PR-1 of #327)

Issue [#327](https://github.com/EzR3aL/Trading-Bot/issues/327) introduces
a Prometheus-based observability layer. PR-1 lands the **infrastructure
only**: the central metric registry, metric definitions and a protected
`/metrics` endpoint. Instrumentation of the HTTP middleware, BotWorker
components, RiskStateManager and exchange adapters arrives in PR-2
through PR-4. Grafana dashboards follow in PR-5.

### Enabling the endpoint

The endpoint is **off by default**. Three environment variables are
required:

```env
PROMETHEUS_ENABLED=true
METRICS_BASIC_AUTH_USER=prom-scraper
METRICS_BASIC_AUTH_PASSWORD=<strong-random-password>
```

Restart the bot after setting the variables. The endpoint is then
reachable at `https://<your-domain>/metrics` with HTTP Basic-Auth.

### Behaviour

| Flag | Auth | Status |
|------|------|--------|
| `PROMETHEUS_ENABLED=false` (or unset) | — | **404** — the endpoint's existence is intentionally not leaked. |
| `PROMETHEUS_ENABLED=true` | no `Authorization` header | **401** with `WWW-Authenticate: Basic`. |
| `PROMETHEUS_ENABLED=true` | wrong credentials | **401**. |
| `PROMETHEUS_ENABLED=true` | correct credentials | **200** with Prometheus text exposition format. |

### Security notes

- Password comparison is timing-safe (`secrets.compare_digest`).
- `/metrics` **must** sit behind HTTPS — Basic-Auth over plain HTTP
  leaks the credentials.
- For additional hardening, add an IP allowlist on the Nginx / Traefik
  layer. Basic-Auth is the last line of defence, not the only one.
- Labels deliberately never carry user emails, wallet addresses or API
  keys — only `bot_id` and `exchange` (#327 security notes).

### HTTP metrics (PR-2 of #327)

PR-2 wires three HTTP metrics that are populated automatically as
soon as `PROMETHEUS_ENABLED` is **on**:

| Metric | Type | Labels |
|--------|------|--------|
| `http_requests_total` | Counter | `method`, `path`, `status` |
| `http_request_duration_seconds` | Histogram | `method`, `path` |
| `http_requests_in_flight` | Gauge | `method`, `path` |

The middleware `src/api/middleware/metrics.py` is registered as the
outermost layer of the middleware stack so the histogram captures
the wall-clock cost of every other middleware (auth, rate limit,
security headers). It is implemented as a pure ASGI middleware
because it must resolve the matched route template **before** the
downstream handler runs (via `Route.matches(scope)`), so that the
in-flight gauge sees the same label value on `inc()` and `dec()`.

**Template-path collapsing (cardinality control):**
`GET /api/bots/42`, `GET /api/bots/17`, `GET /api/bots/999` are
**all** recorded under `path="/api/bots/{bot_id}"`. Without this
normalisation the Prometheus series count would grow linearly with
each bot ID — `http_requests_total` would balloon to millions of
series instead of dozens. Requests that match **no** route (404) are
counted under the sentinel `path="<unmatched>"`, never with the raw
request path.

**`/metrics` itself is not instrumented:**
Prometheus scrapes the endpoint every 15 s — self-observation would
produce a constant background of noise without any operational
value. The middleware short-circuits as soon as the request path
starts with `/metrics`.

**Legacy middleware removed (#337):**
The old `src/monitoring/middleware.py` (which wrote HTTP metrics to
the default registry) was removed in #337. The only HTTP metrics
path is now `src/api/middleware/metrics.py` against the dedicated
`OBSERVABILITY_REGISTRY`.

### Grafana dashboards + local stack (PR-5 of #327)

PR-5 delivers three Grafana dashboards, the auto-provisioning config
and an optional standalone monitoring stack.

#### Prerequisites

- Docker + Docker Compose v2 (`docker compose version`).
- Ports **9090** (Prometheus) and **3000** (Grafana) free on `127.0.0.1`.
- The app's `/metrics` endpoint is already live (PR-1 + PR-2 setup —
  see above: `PROMETHEUS_ENABLED=true`, basic-auth configured).

#### Setup steps (integrated stack inside main compose)

The root-level `docker-compose.yml` ships Prometheus + Grafana as
services — for most setups nothing else needs to be done:

```bash
# at the repo root
cp .env.example .env  # if not yet present
# Set inside .env:
#   PROMETHEUS_ENABLED=true
#   METRICS_BASIC_AUTH_USER=prom-scraper
#   METRICS_BASIC_AUTH_PASSWORD=<strong-password>
#   GF_ADMIN_PASSWORD=<strong-admin-password>
docker compose up -d
```

Grafana then listens on `http://127.0.0.1:3000`.

#### Setup steps (standalone stack, app runs outside compose)

For setups where the Trading-Bot API does **not** run in this compose
(bare-metal or a separate compose stack) use
`monitoring/docker-compose.monitoring.yml`:

```bash
# create the shared external network once
docker network create trading-bot-net

# join the app container to that network
# (depending on your setup: docker run --network trading-bot-net ...,
#  or reference the external network from your app's compose)

cd monitoring
GF_ADMIN_PASSWORD='<strong-password>' docker compose \
  -f docker-compose.monitoring.yml up -d
```

Services:

| Service | Port | Volume | Purpose |
|---------|------|--------|---------|
| `prometheus` | 9090 | `prometheus_data` | Scraper, TSDB, 15 d retention |
| `grafana` | 3000 | `grafana_data` | UI + dashboard rendering |

Grafana credentials: default `admin`/`admin` → **change immediately
after the first login** (or override via `GF_ADMIN_PASSWORD` before
`docker compose up`).

#### Auto-provisioning

On startup Grafana automatically reads:

- `monitoring/grafana/provisioning/datasources/datasources.yml`
  → registers the Prometheus datasource (plus Postgres in the main stack).
- `monitoring/grafana/provisioning/dashboards/dashboards.yml`
  → loads every JSON dashboard from `/var/lib/grafana/dashboards`.

Currently shipped:

| Dashboard (UID) | File | Focus |
|-----------------|------|-------|
| `trading-bot-overview` | `trading-bot-overview.json` | Top-level: HTTP, signals, trades, risk, exchange errors |
| `trading-bot-detail` | `bot-detail.json` | Per-`bot_id` drill-down (template variable) |
| `trading-bot-exchange-health` | `exchange-health.json` | Exchange layer: API rate, latency, WebSocket status |
| `admin-support` | `admin-support.json` | Legacy admin tables (Postgres queries) |

#### Adding new metrics (dev workflow)

1. Declare the metric in `src/observability/metrics.py` (a fresh
   `Counter` with a tight label set — max 3-4 labels, no high-cardinality
   values like `user_id` / `symbol` without aggregation).
2. Instrument the call site: `METRIC.labels(...).inc()` / `.observe()` /
   `.set()`.
3. Write a unit test in `tests/unit/observability/` — at minimum a
   happy-path case that asserts the registry state after the call.
4. Add a panel to the matching dashboard JSON (PromQL, `rate(...)`
   window = 5m, p95 via `histogram_quantile`).
5. Add a CHANGELOG entry under `## [Unreleased]` → `### Added`.

#### Troubleshooting

| Symptom | Root cause / fix |
|---------|------------------|
| Prometheus target `DOWN` | `/metrics` unreachable. Check: `curl -u $USER:$PASS http://<api>:8000/metrics`. 404 → `PROMETHEUS_ENABLED=false`. 401 → wrong basic-auth credentials. |
| Grafana panel "No data" | Either the metric was never sampled (PR-3/4 not yet shipped) or the label value in PromQL does not match (e.g. `exchange="hyperliquid"` but the adapter writes `HYPERLIQUID`). |
| `scrape_configs` changes do not apply | Reload Prometheus: `docker compose restart prometheus` or `curl -X POST http://localhost:9090/-/reload`. |
| Dashboard not visible | Validate the JSON first (`python -c "import json; json.load(open('monitoring/grafana/dashboards/<file>.json'))"`). Grafana logs: `docker logs tradingbot-grafana \| grep -i provisioning`. |
| Basic-auth works in the browser but not in Prometheus | Prometheus `basic_auth` expects **unquoted** strings in `prometheus.yml`. Env-var interpolation like `${METRICS_BASIC_AUTH_USER}` is **not** expanded natively → either hard-code or render via `envsubst` before startup. |

#### Security notes

- `/metrics` must **never** be publicly exposed — neither without auth
  nor without HTTPS. Basic-auth over plain HTTP leaks the credentials.
- Rotate basic-auth credentials regularly (quarterly recommended).
  Password ≥ 32 chars, generated with `openssl rand -base64 32`.
- Rotate the Grafana admin password too. `GF_USERS_ALLOW_SIGN_UP=false`
  is set — no self-service sign-up.
- In the compose setup Prometheus + Grafana bind to `127.0.0.1`, not
  `0.0.0.0`. Access only via SSH port forwarding:
  `ssh -L 3000:127.0.0.1:3000 trading-bot`.
- Labels deliberately carry **no** PII (see PR-1 security notes).
