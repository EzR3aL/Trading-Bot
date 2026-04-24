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

**Legacy-Middleware:**
`src/monitoring/middleware.py` existiert weiterhin, nutzt aber die
alte Default-Registry aus `src/monitoring/metrics.py`. Sie wird in
einem Folge-PR entfernt, sobald kein Code sie mehr importiert —
siehe CHANGELOG-Eintrag zu PR-2 von #327.

### Bot Metrics (PR-3 von #327)

Mit PR-3 emittieren die Bot-Komponenten (BotWorker, TradeExecutor,
PositionMonitor) + der `collect_bot_metrics`-Sammler folgende Metriken
in die Observability-Registry:

| Metrik | Typ | Labels | Call-Site |
|--------|-----|--------|-----------|
| `bot_signals_generated_total` | Counter | `bot_id`, `exchange`, `strategy`, `side` | `BotWorker._analyze_symbol_locked` nach `generate_signal()` |
| `bot_trades_executed_total` | Counter | `bot_id`, `exchange`, `mode`, `result` | `TradeExecutor.execute` um `place_market_order` |
| `bot_trade_execution_duration_seconds` | Histogram | `exchange` | `TradeExecutor.execute` submit-to-ack |
| `bot_position_monitor_tick_duration_seconds` | Histogram | `bot_id` | `PositionMonitor.monitor` pro Tick |
| `bot_open_positions` | Gauge | `bot_id`, `exchange` | `_collect_observability_bot_gauges` (alle 15s) |
| `bot_daily_pnl` | Gauge | `bot_id`, `exchange` | `_collect_observability_bot_gauges` (alle 15s) |
| `app_build_commit` | Gauge (Info) | `commit` | `lifespan` bei App-Start — Wert konstant 1, Commit aus `BUILD_COMMIT` env var |

**Werte der Labels:**

- `side ∈ {long, short}` — neutrale Signale werden **nicht** gezählt.
- `mode ∈ {demo, live}` — reflektiert `demo_mode` beim Order-Submit.
- `result ∈ {success, rejected, failed}` — `success` wenn die Exchange
  eine Order zurückgibt, `rejected` wenn sie `None` zurückgibt (z.B.
  Mindestgröße nicht erreicht ohne Exception), `failed` wenn
  `place_market_order` eine Exception wirft.
- `bot_id` ist der `BotConfig.id` als String (Grafana-freundlich).
- `exchange` ist `BotConfig.exchange_type` (`bitget`, `hyperliquid`,
  etc.); die Sammler-Gauges fallen auf `"unknown"` zurück, wenn der
  Worker noch keinen Config hat.

**Gating:** Die Call-Sites laufen **immer** — `.inc()` / `.observe()`
sind atomar und günstig, ein zusätzlicher Flag-Check pro Trade kostet
mehr als der Write selbst. Die Registry selbst wird nur dann serviert,
wenn `PROMETHEUS_ENABLED=true` gesetzt ist (der Endpoint gibt sonst
404 zurück). Jede Metric-Emission ist in `try/except` gekapselt —
Observability darf Trading niemals brechen.

**Legacy-Parallelität:** Der alte Sammler in `src/monitoring/collectors.py`
speist weiterhin `bots_running_total`, `bot_consecutive_errors`, etc.
in die alte Default-Registry (`src/monitoring/metrics.py`). PR-3
erweitert ihn, um parallel die neuen observability-Gauges
(`bot_open_positions`, `bot_daily_pnl`) zu füllen. Die alte Registry
wird erst in einem Folge-PR entfernt, sobald keine Dashboards sie mehr
referenzieren.

### Status — was noch fehlt

Instrumentierung des RiskStateManagers + Exchange-Adapter (PR-4) und
vollständiges Setup mit Prometheus-Scraper, Docker-Compose-Snippet
und Grafana-Dashboards folgen in **PR-4/PR-5 von #327**.

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

**Legacy middleware:**
`src/monitoring/middleware.py` still exists but uses the old default
registry from `src/monitoring/metrics.py`. It will be removed in a
follow-up PR once no code imports it — see the PR-2 CHANGELOG entry
for #327.

### Bot metrics (PR-3 of #327)

PR-3 wires six bot-level metrics plus the `app_build_commit` info
gauge. They are emitted from the BotWorker / TradeExecutor /
PositionMonitor call sites and from the `collect_bot_metrics`
collector:

| Metric | Type | Labels | Call site |
|--------|------|--------|-----------|
| `bot_signals_generated_total` | Counter | `bot_id`, `exchange`, `strategy`, `side` | `BotWorker._analyze_symbol_locked` after `generate_signal()` |
| `bot_trades_executed_total` | Counter | `bot_id`, `exchange`, `mode`, `result` | `TradeExecutor.execute` around `place_market_order` |
| `bot_trade_execution_duration_seconds` | Histogram | `exchange` | `TradeExecutor.execute` submit-to-ack |
| `bot_position_monitor_tick_duration_seconds` | Histogram | `bot_id` | `PositionMonitor.monitor` per tick |
| `bot_open_positions` | Gauge | `bot_id`, `exchange` | `_collect_observability_bot_gauges` (every 15 s) |
| `bot_daily_pnl` | Gauge | `bot_id`, `exchange` | `_collect_observability_bot_gauges` (every 15 s) |
| `app_build_commit` | Gauge (info) | `commit` | `lifespan` at app start — value always 1, commit from `BUILD_COMMIT` env var |

**Label values:**

- `side ∈ {long, short}` — neutral signals are **not** counted.
- `mode ∈ {demo, live}` — reflects the `demo_mode` flag at order submit.
- `result ∈ {success, rejected, failed}` — `success` when the exchange
  returns an order object, `rejected` when it returns `None` (e.g.
  below minimum size, without raising), `failed` when
  `place_market_order` raises.
- `bot_id` is `BotConfig.id` as a string (Grafana-friendly).
- `exchange` is `BotConfig.exchange_type` (`bitget`, `hyperliquid`,
  etc.); the collector gauges fall back to `"unknown"` when the worker
  has no config attached yet.

**Gating:** Call sites always run — `.inc()` / `.observe()` are atomic
and cheap, so the per-write flag check would cost more than the write
itself. The registry itself is only served when `PROMETHEUS_ENABLED=true`
(the endpoint returns 404 otherwise). Every metric emission is wrapped
in `try/except` — observability must never break trading.

**Legacy parallelism:** The pre-existing collector in
`src/monitoring/collectors.py` keeps populating `bots_running_total`,
`bot_consecutive_errors`, etc. on the old default registry
(`src/monitoring/metrics.py`). PR-3 extends it so the new observability
gauges (`bot_open_positions`, `bot_daily_pnl`) are populated in
parallel. The old registry will be removed in a follow-up PR once no
dashboards reference it.

### Status — what is still missing

Instrumentation of the RiskStateManager + exchange adapters (PR-4)
and the full setup with a Prometheus scraper, Docker-Compose snippet
and Grafana dashboards arrive in **PR-4 / PR-5 of #327**.
