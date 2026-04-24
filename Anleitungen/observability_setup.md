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

### Risk-Metrics (PR-4 von #327)

PR-4 instrumentiert die Risk-Trade-Gate-Entscheidung in
`src/risk/risk_manager.py`. Jeder Aufruf von `RiskManager.can_trade()`
emittiert genau eine Observation auf dem Counter
`risk_trade_gate_decisions_total` — eine pro Branch:

| Metrik | Typ | Labels | Kardinalität |
|--------|-----|--------|--------------|
| `risk_trade_gate_decisions_total` | Counter | `bot_id`, `decision` | `bot_id` × 8 Decisions |

Das Label `decision` hat einen festen Wertebereich:

| Wert | Bedeutung |
|------|-----------|
| `allow` | Trading erlaubt (Happy Path). |
| `block_max_trades` | Globales Trade-Limit erreicht. |
| `block_daily_loss` | Globales Daily-Loss-Limit erreicht (löst auch `_halt_trading` aus). |
| `block_max_trades_symbol` | Per-Symbol Trade-Limit erreicht. |
| `block_daily_loss_symbol` | Per-Symbol Loss-Limit erreicht (Eager-Pfad im Gate). |
| `block_global_halted` | Das Gate wurde aufgerufen, während der Bot schon global angehalten ist. |
| `block_symbol_halted` | Das Gate wurde aufgerufen, während das Symbol bereits angehalten ist. |
| `block_uninitialized` | `initialize_day()` wurde nicht aufgerufen — Konfig-Fehler. |

**Per-Symbol Loss-Limit — nur ein Pfad wird gezählt:**
Das Per-Symbol Loss-Limit kann an zwei Stellen kippen: eager im Gate
(`can_trade` — instrumentiert mit `block_daily_loss_symbol`) und lazy
nach einem verlorenen Exit (`record_trade_exit` — **nicht**
instrumentiert). Nur der Gate-Pfad zählt als "Trade-Gate-Decision" —
der Exit-Flip halbiert sich den Zustand, es wird aber kein Trade
gegated. Doppel-Zählung wäre irreführend.

**Alert-Emission bleibt ausstehend:**
Die Metrik `risk_alerts_emitted_total` wird in PR-4 **nicht** befüllt.
Die Alert-Logik lebt aktuell auf dem `BotWorker` und kollidiert mit
dem parallelen PR-3 (BotWorker-Instrumentation). Der AlertThrottler
wird im Rahmen von [Issue #326](https://github.com/EzR3aL/Trading-Bot/issues/326)
Phase 1 aus dem BotWorker extrahiert; die Alert-Instrumentation
landet dann zusammen mit dieser Extraktion.

### Exchange-Metrics (PR-4 von #327)

PR-4 instrumentiert auch die Exchange-Adapter:

| Metrik | Typ | Labels |
|--------|-----|--------|
| `exchange_api_requests_total` | Counter | `exchange`, `endpoint`, `status` |
| `exchange_api_request_duration_seconds` | Histogram | `exchange`, `endpoint` |
| `exchange_websocket_connected` | Gauge | `exchange` |

**Zentrale Einstiegspunkte:**
- REST-Clients routen alle durch `HTTPExchangeClientMixin._request`
  (Bitget, Weex, BingX, Bitunix). Eine einzige Stelle, eine einzige
  Emission pro API-Call.
- Hyperliquid verwendet das offizielle Python-SDK; die Instrumentation
  sitzt in `HyperliquidClient._cb_call`. `endpoint` ist dort der
  SDK-Methodenname (`market_open`, `user_state`, `cancel` …) — stabil
  und kardinal-sicher.
- Der WebSocket-Gauge wird in `ExchangeWebSocketClient.connect/
  disconnect` (neue Hierarchie, `src/exchanges/websockets/base.py`)
  sowie in den Connect/Disconnect-Methoden der legacy
  `ExchangeWebSocket`-Subklassen (Bitget, BingX, Weex, Bitunix,
  Hyperliquid) gesetzt.

**Status-Label-Werte:**

| Wert | Bedeutung |
|------|-----------|
| `ok` | HTTP/SDK-Call ohne Exception zurückgekehrt. |
| `error` | Irgendeine Exception (Netzwerk, 4xx, 5xx, Parsing). |
| `circuit_open` | Der Circuit-Breaker hat den Call abgelehnt, bevor er ausgeführt wurde. |

**Endpoint-Kardinalitätsschutz:**
`_collapse_endpoint` in `src/exchanges/base.py` faltet numerische IDs
(`/orders/1234567890`), Hex-Blobs und UUIDs im Endpoint-Pfad zu `{id}`.
Query-Strings werden abgeschnitten. Die heutigen Adapter bauen zwar
bereits template-artige Pfade, aber die Collapse-Regel ist eine
Defence-in-Depth — falls ein künftiger Adapter eine Order-ID in den
Pfad legt, explodiert die Prometheus-Serienzahl nicht.

### Status — was noch fehlt

Alert-Instrumentation (`risk_alerts_emitted_total`) zusammen mit
AlertThrottler-Extraktion in #326 Phase 1. Vollständiges Setup mit
Prometheus-Scraper, Docker-Compose-Snippet und Grafana-Dashboards
folgt in **PR-5 von #327**.

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

### Risk metrics (PR-4 of #327)

PR-4 instruments the risk trade-gate decision in
`src/risk/risk_manager.py`. Every call to `RiskManager.can_trade()`
emits exactly one observation on the counter
`risk_trade_gate_decisions_total` — one per branch:

| Metric | Type | Labels | Cardinality |
|--------|------|--------|-------------|
| `risk_trade_gate_decisions_total` | Counter | `bot_id`, `decision` | `bot_id` × 8 decisions |

The `decision` label is drawn from a fixed set:

| Value | Meaning |
|-------|---------|
| `allow` | Trade permitted (happy path). |
| `block_max_trades` | Global trade-count limit reached. |
| `block_daily_loss` | Global daily-loss limit reached (also triggers `_halt_trading`). |
| `block_max_trades_symbol` | Per-symbol trade-count limit reached. |
| `block_daily_loss_symbol` | Per-symbol loss limit reached (eager gate path). |
| `block_global_halted` | Gate called while the bot is already globally halted. |
| `block_symbol_halted` | Gate called while this symbol is already halted. |
| `block_uninitialized` | `initialize_day()` was never called — config bug. |

**Per-symbol loss limit — one path only:**
The per-symbol loss limit can flip at two sites: eagerly inside the
gate (`can_trade` — instrumented with `block_daily_loss_symbol`) and
lazily after a losing exit (`record_trade_exit` — **not**
instrumented). Only the gate path is counted as a "trade-gate
decision"; the exit-time flip changes state but gates no trade.
Counting both would double-count a single halt event across two
semantically different moments.

**Alert emission deferred:**
The metric `risk_alerts_emitted_total` is **not** populated in PR-4.
The alert logic currently lives on `BotWorker` and overlaps with the
parallel PR-3 (BotWorker instrumentation). The AlertThrottler is
being extracted from BotWorker as part of
[issue #326](https://github.com/EzR3aL/Trading-Bot/issues/326)
phase 1; alert instrumentation will land together with that extraction.

### Exchange metrics (PR-4 of #327)

PR-4 also instruments the exchange adapters:

| Metric | Type | Labels |
|--------|------|--------|
| `exchange_api_requests_total` | Counter | `exchange`, `endpoint`, `status` |
| `exchange_api_request_duration_seconds` | Histogram | `exchange`, `endpoint` |
| `exchange_websocket_connected` | Gauge | `exchange` |

**Central entry points:**
- REST clients all route through `HTTPExchangeClientMixin._request`
  (Bitget, Weex, BingX, Bitunix). One site, one emission per API call.
- Hyperliquid uses the official Python SDK; instrumentation lives in
  `HyperliquidClient._cb_call`. Here `endpoint` is the SDK method
  name (`market_open`, `user_state`, `cancel` …) — stable and
  cardinality-safe.
- The WebSocket gauge is set from `ExchangeWebSocketClient.connect/
  disconnect` (new hierarchy, `src/exchanges/websockets/base.py`)
  and from the connect/disconnect methods of the legacy
  `ExchangeWebSocket` subclasses (Bitget, BingX, Weex, Bitunix,
  Hyperliquid).

**Status label values:**

| Value | Meaning |
|-------|---------|
| `ok` | HTTP/SDK call returned without raising. |
| `error` | Any exception (network, 4xx, 5xx, parsing). |
| `circuit_open` | The circuit breaker refused the call before it executed. |

**Endpoint cardinality guard:**
`_collapse_endpoint` in `src/exchanges/base.py` folds numeric IDs
(`/orders/1234567890`), hex blobs and UUIDs in endpoint paths to
`{id}`. Query strings are stripped. The current adapters already use
template-shaped paths, but the collapse rule is defence in depth — if
a future adapter embeds an order ID in the URL, the Prometheus series
count does not explode.

### Status — what is still missing

Alert instrumentation (`risk_alerts_emitted_total`) lands with the
AlertThrottler extraction in #326 phase 1. The full setup with a
Prometheus scraper, Docker-Compose snippet and Grafana dashboards
arrives in **PR-5 of #327**.
