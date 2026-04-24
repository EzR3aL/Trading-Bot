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

### Status — was noch fehlt

Vollständiges Setup mit Prometheus-Scraper, Docker-Compose-Snippet und
Grafana-Dashboards folgt in **PR-5 von #327**. Dieser Stub dokumentiert
nur den PR-1-Scope.

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

### Status — what is still missing

The full setup with a Prometheus scraper, Docker-Compose snippet and
Grafana dashboards arrives in **PR-5 of #327**. This stub only
documents the PR-1 scope.
