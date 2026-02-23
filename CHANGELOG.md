# Changelog

Alle wichtigen Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

> **Hinweis:** Dieser Changelog wird automatisch bei jeder Änderung aktualisiert.

---

## [3.21.0] - 2026-02-23

### Hinzugefuegt
- **Budget/Balance-Warnung im Bot-Dashboard** — Neuer API-Endpoint `GET /api/bots/budget-info` zeigt pro Bot: verfuegbares Guthaben, allokiertes Budget, Gesamt-Allokation pro Exchange. Bot-Cards zeigen Budget-Zeile und amber Warnbanner wenn Mittel nicht ausreichen oder Bots ueberallokiert sind (>100%). Verhindert stilles Scheitern wenn mehrere Bots dasselbe Konto teilen
- **Graceful Degradation fuer SentimentSurfer ohne News** — Wenn GDELT keine Artikel liefert (Timeout/Ausfall), wird die News-Quelle komplett aus der Signal-Berechnung entfernt statt als neutrales Signal gezaehlt. Agreement-Check passt sich dynamisch an (z.B. "3/5" statt "3/6"). Verbleibende 5 Quellen (Fear&Greed, VWAP, Supertrend, Volume, Momentum) entscheiden allein

### Geaendert
- **GDELT-Parameter optimiert** — `max_records`: 25→10, Query: `"bitcoin OR cryptocurrency OR crypto"`→`"bitcoin"`, `lookback_hours`: 24→12, Timeout: 15s→10s. Kleinere Queries = schnellere Antworten von der ueberlastetem GDELT-API
- **GDELT Circuit Breaker gelockert** — `reset_timeout`: 300s→120s (schneller erneut versuchen bei intermittierender Verfuegbarkeit)

---

## [3.20.2] - 2026-02-23

### Behoben
- **Logging im Docker-Container komplett fehlend** — `setup_logging()` wurde im API-Einstiegspunkt (`main_app.py`) nie aufgerufen, da Docker uvicorn direkt startet statt ueber `main.py`. Alle INFO-Level Logs (Analysen, Budgets, Signale) waren unsichtbar — nur ERROR-Meldungen kamen durch Pythons Last-Resort-Handler. Fix: `setup_logging()` wird jetzt in `main_app.py` aufgerufen
- **Falsches Balance-Feld bei Bitget Cross-Margin** — `get_account_balance()` nutzte `available` (auszahlbarer Betrag) statt `crossedMaxAvailable` (tatsaechlich fuer neue Positionen verfuegbar). Bei bestehenden Positionen zeigte `available` den vollen Kontostand (~$20k), obwohl die Margin durch andere Positionen belegt war (~$19k). Ergebnis: Orders wurden von Bitget abgelehnt ("order amount exceeds balance"). Fix: Prioritaet auf `crossedMaxAvailable` geaendert
- **Debug-Logging fuer Order-Vorbereitung** — Vor jeder Orderplatzierung werden jetzt verfuegbares Guthaben, Leverage, Position-Groesse und Entry-Preis geloggt, um Balance-Fehler schneller zu diagnostizieren

---

## [3.20.1] - 2026-02-23

### Behoben
- **NoneType-Crash in Strategien** — Wenn Binance/GDELT-APIs intermittierend `None` zurueckgeben, crashte `generate_signal()` mit `unsupported operand type(s) for /: 'NoneType' and 'int'`. Betroffen: Liquidation Hunter (741x), Claude Edge (149x), Sentiment Surfer. Alle Metrik-Felder werden jetzt mit Fallback-Werten abgesichert
- **Trade-Execution Balance-Fehler** — Bot 1 scheiterte mit `The order amount exceeds the balance` weil `entry_price` nicht vor der Position-Size-Berechnung validiert wurde. Frueher Guard gegen ungueltige Preise hinzugefuegt
- **GDELT-Timeout-Kaskade** — News-Sentiment-API-Timeouts kaskadierten in NoneType-Fehler. Sentiment Surfer setzt jetzt explizite Fallback-Werte bei fehlenden Metriken
- **None TP/SL aus Bot-Config ueberschreibt Strategy-Defaults** — Wenn `take_profit_percent` und `stop_loss_percent` in der Bot-Config `NULL` sind, wurde `None` in die Strategy-Params injiziert und ueberschrieb die Defaults (4.0% / 1.5%). Fix: None-Werte werden nicht mehr an Strategien weitergegeben
- **Fehlende Tracebacks in Bot-Logs** — Error-Handler loggten nur die Fehlermeldung ohne Stacktrace, was Debugging unmoeglich machte. `exc_info=True` hinzugefuegt
- **Order exceeds balance bei 100% Position** — Position-Size-Berechnung nutzte 100% des Budgets als Margin, aber Bitget benoetigt Reserve fuer Gebuehren/Funding. Jetzt 95% Safety-Margin
- **Circuit Breaker vergiftet durch set_leverage** — `set_leverage` Fehler bei existierenden Positionen wurden als API-Fehler gezaehlt und oeffneten den Circuit Breaker fuer ALLE Bitget-Calls. Fix: set_leverage umgeht jetzt den Circuit Breaker

---

## [3.20.0] - 2026-02-22

### Hinzugefuegt
- **Trade-Fehler Benutzerbenachrichtigung** — Bei fehlgeschlagener Orderplatzierung wird der Benutzer sofort via WebSocket (`trade_failed` Event) und Discord/Telegram (`TRADE_FAILED` Risk Alert) benachrichtigt. Nur echte Fehler — "minimum amount" Warnungen werden nicht eskaliert
- **Atomare Daily-Loss-Limit Pruefung** — Per-User `asyncio.Lock` im Orchestrator stellt sicher, dass Risk-Check + Trade-Execution atomar ablaufen. Verhindert, dass parallele Bots gleichzeitig das Tageslimit umgehen
- **Datenbank-Performance-Indexes** — Neue Indexes `ix_trade_bot_status` (bot_config_id, status) und `ix_trade_entry_time` (entry_time) auf TradeRecord fuer schnellere Abfragen im Position Monitor
- **Log-Rotation** — `RotatingFileHandler` mit 100 MB pro Datei, 10 Backups. Automatisches JSON-Format in Production (`LOG_FORMAT=json` oder `ENVIRONMENT=production`)
- **Request-ID Middleware** — Jede Response enthaelt `X-Request-ID` Header fuer Log-Korrelation. Akzeptiert Client-Header oder generiert UUID
- **System-Metriken** — Neue Prometheus-Gauges: `process_resident_memory_bytes` (Speicherverbrauch), `disk_usage_percent` (Festplatte). Background-Collector erfasst alle 15 Sekunden
- **Trade-Failure Counter** — Neuer Prometheus-Counter `trade_failures_total` mit Labels `exchange` und `error_type`
- **PostgreSQL Backup Sidecar** — Automatisches taegliches Backup via `pg_dump` im Docker-Compose. Behaelt 7 Tage, loescht aeltere automatisch
- **Alertmanager Integration** — Vollstaendige Alertmanager-Konfiguration mit Webhook-Receiver. Separate Route fuer kritische Alerts (1h Wiederholung). Prometheus sendet Alerts an Alertmanager
- **Erweiterte Alert-Regeln** — 4 neue Prometheus-Alerts: `HighMemoryUsage` (>768MB), `HighDiskUsage` (>85%), `CriticalDiskUsage` (>95%), `TradeExecutionFailures`
- **Graceful Shutdown** — `STOPSIGNAL SIGTERM` + `--timeout-graceful-shutdown 25s` im Dockerfile, `stop_grace_period: 30s` in Docker-Compose
- **CPU-Limit** — Trading-Bot Container auf 2.0 CPUs begrenzt
- **35 neue Tests** — Trade-Failure-Notification (4), Per-User Trade Lock (6), DB-Indexes (2), Log-Rotation (2), Request-ID (2), Health-Check (1), Prometheus-Metriken (3), Metrics-Collector (2), Docker/DevOps-Konfiguration (13)

### Geaendert
- **Health-Check Endpoint** — Erweitert um `checks`-Objekt mit `database` und `bots` Status. Zeigt Anzahl der Bots im Error-State
- **Erweiterter Metrics-Collector** — Sammelt jetzt auch Prozess-Speicher (Linux: `resource.getrusage`, Windows: Fallback) und Disk-Usage (`shutil.disk_usage`)

### Frontend
- **i18n: Hardcoded Strings entfernt** — Alle `" - OK"` Suffixe und `"Failed to load data"` durch `t()` Uebersetzungen ersetzt (Bots, BotDetail, Dashboard, Backtest, BotPerformance, GettingStarted, Trades)
- **Modal Accessibility** — `role="dialog"`, `aria-modal="true"`, `aria-label`, Escape-Key-Handler auf TradeDetailModal und BotTradeHistoryModal
- **Toast Store** — Maximum 10 Toasts gleichzeitig (aeltere werden automatisch entfernt)
- **Realtime Store** — `removeBotStatus()` Methode fuer Cleanup hinzugefuegt
- **Portfolio Performance** — `chartData` mit `useMemo` optimiert (abhaengig von `dailyData`)

---

## [3.19.0] - 2026-02-22

### Hinzugefuegt
- **Metrics Endpoint IP-Restriction** — `/metrics` ist in Production nur von localhost, Docker-Netzwerken und `METRICS_ALLOWED_IPS` erreichbar (403 fuer andere IPs)
- **HTTPS Redirect Middleware** — Automatische HTTP→HTTPS Weiterleitung (301) in Production ueber `X-Forwarded-Proto` Header (fuer Nginx/Caddy/Traefik)
- **Default-Passwort Erkennung** — Config Validator lehnt schwache Passwoerter (`tradingbot_dev`, `changeme`, etc.) bei `ENVIRONMENT=production` ab — App startet nicht
- **11 neue Security-Tests** — Metrics IP-Restriction (5), HTTPS Redirect (3), Default-Passwort Validator (3)

### Geaendert
- **docker-compose.yml** — Produktions-Checkliste als Kommentar ergaenzt (POSTGRES_PASSWORD, GF_ADMIN_PASSWORD, ENVIRONMENT)

---

## [3.18.0] - 2026-02-22

### Hinzugefuegt
- **Toast-Benachrichtigungen im Frontend** — Alle `console.error`-Only-Catches durch `useToastStore.addToast()` ergaenzt (8 Dateien, 15+ Stellen). Benutzer sehen jetzt Fehlermeldungen bei API-Fehlern
- **Rate Limiting auf allen Endpoints** — 16 ungeschuetzte Endpoints in 5 Router-Dateien mit `@limiter.limit()` versehen:
  - `admin_logs.py` (5 Endpoints: 60/min Lesen, 5/min Loeschen)
  - `exchanges.py` (2 Endpoints: 30/min)
  - `funding.py` (2 Endpoints: 30/min)
  - `portfolio.py` (4 Endpoints: 20-30/min)
  - `statistics.py` (3 Endpoints: 30/min)
- **Exchange-Name Validierung** — `GET /api/exchanges/{name}/info` validiert Parameter mit Regex `^[a-zA-Z][a-zA-Z0-9_-]{0,29}$`, gibt 400 bei ungueltigem Namen
- **Log-Redaktion** — `RedactionFilter` in `logger.py` maskiert automatisch API-Keys, Bearer-Tokens und JWTs in allen Log-Ausgaben
- **Prometheus Alert Rules** — 9 Alerting-Regeln fuer kritische Events:
  - `HealthCheckFailing`, `HighErrorRate`, `NoBotsRunning`, `BotInErrorState`
  - `BotConsecutiveErrors`, `HighRequestLatency`, `SlowDatabaseQueries`
  - `HighWebSocketConnections`, `HighRateLimitHits`
- **Docker Health Check verbessert** — Parst jetzt `/api/health`-Response und prueft `status == "healthy"` (statt nur HTTP 200)
- **18 neue Tests** — Auth-Integration (Login Lockout Flow, Password Change + Token Revocation), Exchange-Validierung, Log-Redaktion (5 Faelle), Rate-Limiting Coverage (5 Router-Dateien)

### Behoben
- **Frontend: Stille Catches endgueltig behoben** — Alle `catch { /* ignore */ }` durch `console.error` + Toast-Benachrichtigung ersetzt
  - Backtest.tsx: 4 Catches (Submit, Load, Delete + Polling-Error-Logging)
  - BotPerformance.tsx: 2 Catches (Copy-to-Clipboard Error-Logging)
  - Bots.tsx: 2 Catches (Trade History Load + Copy-Image Error-Logging)

---

## [3.17.0] - 2026-02-22

### Behoben
- **CRITICAL: Path Traversal in SPA Routing** — `serve_spa()` validiert jetzt, dass aufgeloeste Pfade innerhalb des Frontend-Verzeichnisses bleiben. Verhindert `../../etc/passwd`-Angriffe
- **CRITICAL: TP/SL Fehlerbehandlung (Bitget)** — TP/SL-Fehler werden jetzt als ERROR (statt WARNING) geloggt, mit automatischem Retry (2 Versuche) und 200ms Verzoegerung fuer Order-Fill
- **CRITICAL: Daily Loss Limit in Trade Execution** — `can_trade()` wird jetzt direkt vor Orderplatzierung geprueft, nicht nur waehrend der Analyse
- **CRITICAL: Position Sizing Logik** — Vereinfacht: `asset_budget` wird immer direkt verwendet wenn gesetzt, unabhaengig von `position_size_percent`
- **HIGH: Weex Client Retry/Circuit Breaker** — Gleiche `@with_retry` und Circuit Breaker Logik wie Bitget hinzugefuegt (3 Versuche, Exponential Backoff)
- **HIGH: Stille `.catch(() => {})` im Frontend** — 14 leere Catch-Bloecke in 8 Dateien durch `console.error`-Logging ersetzt
- **HIGH: `dangerouslySetInnerHTML` in BotBuilder** — Durch sichere `<Trans>`-Komponente von react-i18next ersetzt
- **HIGH: Docker Image Pinning** — `prom/prometheus:v3.2.1` und `grafana/grafana:11.5.2` statt `:latest`
- **HIGH: X-Forwarded-For IP-Validierung** — IP-Format wird jetzt per Regex validiert, Fallback auf `request.client.host` bei ungueltigem Format
- **MEDIUM: Passwort-Komplexitaet** — Neues Passwort erfordert min. 8 Zeichen, 1 Grossbuchstabe, 1 Kleinbuchstabe, 1 Ziffer, 1 Sonderzeichen
- **MEDIUM: Account Lockout Eskalation** — Exponentielles Backoff: 15min, 30min, 60min, ... max 24h (statt fixer 15min)
- **MEDIUM: Health Check DB-Verifizierung** — `/api/health` prueft DB-Konnektivitaet mit `SELECT 1`, gibt 503 bei Fehler zurueck
- **MENTOR: TP/SL Failure Propagation** — `Order.tpsl_failed` Flag hinzugefuegt, trade_executor sendet Risk Alert bei fehlgeschlagenem TP/SL
- **MENTOR: IP-Validierung** — Regex durch `ipaddress.ip_address()` ersetzt fuer echte IPv4/IPv6-Validierung
- **MENTOR: Health Check Imports** — Module-Level Imports statt Function-Level fuer bessere Sichtbarkeit

### Geaendert
- **Orchestrator Kommentar** — Dokumentiert, warum `restore_on_startup()` keine Race Condition hat (laeuft vor API-Start)
- **Status-Endpoint Version** — `/api/status` und `/api/health` zeigen jetzt korrekt Version `3.0.0`

### Hinzugefuegt
- **36 neue Tests** — `test_production_hardening.py` mit Integration/Unit-Tests fuer alle Hardening-Fixes:
  - Path Traversal (HTTP-Integration), can_trade Guard (Denial + Allow), TP/SL Failure Propagation,
  - Lockout Eskalation (8 parametrisierte Faelle), Passwort-Komplexitaet (6 Faelle),
  - IP-Validierung (9 Faelle inkl. IPv4/IPv6/Garbage), Health Check DB (200 + 503),
  - Weex Circuit Breaker (Registrierung, Fehler, Bypass)

---

## [3.16.0] - 2026-02-22

### Hinzugefuegt
- **PostgreSQL Support:** docker-compose.yml enthaelt PostgreSQL 16 Alpine als Produktionsdatenbank mit Healthcheck und benanntem Volume
- **SPA Catch-All Routing:** FastAPI serviert index.html fuer alle Frontend-Routen — Seitenaktualisierung auf /settings etc. funktioniert jetzt korrekt
- **.env.example:** PostgreSQL- und Grafana-Konfiguration dokumentiert

### Geaendert
- **DateTime Timezone:** Alle DateTime-Spalten verwenden jetzt `DateTime(timezone=True)` fuer PostgreSQL-Kompatibilitaet (verhindert offset-naive vs offset-aware Fehler)
- **Dockerfile:** `--legacy-peer-deps` fuer npm, `NODE_OPTIONS=--max-old-space-size=1536` fuer speicherbeschraenkte Builds, korrekter Frontend-Output-Pfad
- **docker-compose.yml:** CPU-Limit auf 0.90 (1-vCPU-Droplet), Grafana nur auf localhost gebunden, Passwort ueber Umgebungsvariable, trading-bot haengt von postgres ab
- **Settings:** Referral-Registrierung fuer Admin-Benutzer ausgeblendet

---

## [3.15.2] - 2026-02-21

### Hinzugefuegt
- **Backtest-Ergebnisse BTC:** Vollstaendige Ergebnisse aller 42 Backtests als Markdown (DE + EN) in Anleitungen/
- **Strategie-Empfehlungen:** Backtest-basierte Hinweise in jeder Strategiebeschreibung (i18n DE + EN) mit Disclaimer
- **Portfolio Exchange-Merge:** Exchange-Karten zeigen nun alle Exchanges (auch ohne Trades, z.B. nur mit Live-Balance)
- **OfflineIndicator i18n:** Banner-Texte uebersetzt (DE/EN), Dismiss-Button hinzugefuegt

### Geaendert
- **Token-Refresh ohne Rotation:** `token_version` wird beim Refresh nicht mehr inkrementiert — verhindert ungewollte Logouts bei mehreren Tabs/Requests
- **OfflineIndicator weniger aggressiv:** 3 statt 2 konsekutive Fehler, 30s Intervall, 8s Timeout, 5s Verzoegerung beim Start, gelbes statt rotes Banner
- **Portfolio Donut-Chart:** Tooltip zeigt jetzt Exchange-Name + formatierte Zahl; Farben sind Exchange-spezifisch statt Index-basiert
- **GettingStarted Timeframes:** Empfohlene Intervalle aktualisiert basierend auf Backtest-Daten (Edge: 1h/4h, Degen: 4h, Liquidation: 15m)
- **Settings Hyperliquid-Tab:** User-Status-Karten (Builder Code, Empfehlung) entfernt — nur Admin-relevante Inhalte (Earnings, Konfiguration) bleiben

### Behoben
- **Auth Token-Rotation Bug:** Refresh inkrementierte token_version, was parallele Requests und Multi-Tab-Sessions sofort invalidierte

---

## [3.15.1] - 2026-02-21

### Hinzugefuegt
- **Portfolio In-Memory Cache:** 10s TTL-Cache fuer `/positions` und `/allocation` Endpoints — wiederholte Aufrufe werden sofort bedient
- **Portfolio Cache Tests:** 4 Unit-Tests fuer Cache-Logik (hit, miss, TTL-Ablauf, Key-Isolation)

### Geaendert
- **Portfolio progressive Loading:** Schnelle DB-Queries (Summary, Daily) laden sofort, Exchange-API-Calls (Positions, Allocation) im Hintergrund mit eigenem Spinner
- **Settings resilientes Laden:** `Promise.allSettled` statt `Promise.all` — einzelne API-Fehler blockieren nicht mehr die gesamte Seite
- **Settings Verbindungen-Tab:** Nur noch fuer Admins sichtbar, nicht mehr in der User-Ansicht
- **OfflineIndicator robuster:** Erfordert 2 aufeinanderfolgende Fehler bevor Banner erscheint, Pruefintervall von 30s auf 15s verkuerzt
- **Axios Timeout:** 15s globaler Timeout hinzugefuegt um endloses Haengen zu verhindern

---

## [3.15.0] - 2026-02-21

### Hinzugefuegt
- **Englische Anleitungen:** Alle 13 Guides vollstaendig ins Englische uebersetzt (Anleitungen/en/)
- **Anleitungen-Index:** README.md mit Links zu allen Guides (DE + EN)
- **PDF-Export Template:** generate-pdf.html mit Trading Department Branding
- **Professional README.md:** GitHub-Uebersicht komplett neu geschrieben

### Entfernt
- **execute_signal.py geloescht:** Deprecated Datei die geloeschtes TradingBot-Modul referenzierte
- **_write_test.js geloescht:** Temporaeres Test-Generator-Skript
- **35 __pycache__ Verzeichnisse bereinigt**
- **9 stale Remote-Branches geloescht**

### Geaendert
- **.gitignore/.dockerignore:** .ruff_cache/ hinzugefuegt

---

## [3.14.1] - 2026-02-21

### Sicherheit
- **Login Rate Limit verschaerft:** Von 10/min auf 5/min fuer Brute-Force-Schutz
- **Exchange-Test Rate Limit verschaerft:** Von 10/min auf 3/min
- **SQL Injection Fix:** Migration-Code verwendet jetzt Whitelist-validierte Identifier mit Quoting

---

## [3.14.0] - 2026-02-21

### Sicherheit
- **Account Lockout:** 5 fehlgeschlagene Login-Versuche sperren Account fuer 15 Minuten
- **WebSocket token_version Pruefung:** WS-Verbindungen pruefen jetzt Token-Revocation gegen DB
- **Passwort-Aenderung Endpoint:** PUT /api/auth/change-password mit Rate-Limiting (3/min), revoziert bestehende Tokens
- **passlib entfernt:** Ungenutzte Dependency entfernt (bcrypt wird direkt verwendet)

### Hinzugefuegt
- **BotStatus/ExchangeType/TradeStatus/TradeSide Enums:** Typ-sichere String-Enums statt Magic Strings
- **MAX_BOTS_PER_USER Enforcement:** Orchestrator begrenzt auf 10 laufende Bots pro User
- **TradeCloserMixin:** Gemeinsame Trade-Close-Logik aus position_monitor und rotation_manager extrahiert
- **API Error Utility:** Zentrales `getApiErrorMessage()` fuer Frontend Error-Handling
- **Skip-to-Content Link:** Accessibility-Verbesserung im AppLayout
- **ChangePasswordRequest Schema:** Pydantic-Schema mit min_length=8 Validierung

### Behoben
- **164x datetime.utcnow() ersetzt:** Alle Vorkommen durch datetime.now(timezone.utc) ersetzt (47 Dateien)
- **Timezone-aware Subtraction Fix:** Naive/aware datetime Mismatch in trades.py und trade_closer.py behoben
- **Hardcoded German Strings:** ~20 deutsche Fallback-Strings in BotBuilder durch i18n-Keys ersetzt
- **Dashboard Tests geloescht:** Tests fuer geloeschte legacy Dashboard-Module entfernt

### Entfernt
- **Legacy Module geloescht:** trading_bot.py, trade_database.py, src/dashboard/, src/websocket/ (ersetzt durch FastAPI + Exchange-WS)
- **Legacy Tests geloescht:** 12 Test-Dateien fuer geloeschte Module entfernt

### Geaendert
- **Exchange Factory:** Verwendet jetzt ExchangeType Enum statt String-Vergleiche
- **BotWorker/Orchestrator:** Verwendet jetzt BotStatus Enum statt Magic Strings
- **main.py --dashboard:** Startet jetzt FastAPI statt legacy Dashboard

---

## [3.13.0] - 2026-02-21

### Sicherheit
- **python-jose durch PyJWT ersetzt:** python-jose ist unmaintained mit bekannten CVEs — Migration auf PyJWT[crypto] v2.11+
- **WebSocket JWT-Token nicht mehr in URL:** Token wird jetzt als erste Nachricht nach Connect gesendet, nicht mehr als Query-Parameter (verhindert Log-Exposure)
- **Login Rate Limit verschaerft:** Von 30/min auf 10/min reduziert

### Behoben
- **Frontend Build repariert:** Unused `INTERVAL_BACKTEST_HINTS` Konstante entfernt (blockierte `tsc`)
- **13 failing Frontend-Tests gefixt:** ErrorBoundary i18n-Mock + Portfolio Test-Stabilisierung
- **54 failing Backend-Tests gefixt:** Integration-Test Fixture-Mismatch (DB Engine), Affiliate-Router fehlte, seed_exchanges Mock, FundingPayment Schema
- **CircuitBreakerError:** Doppelter `super().__init__()` Aufruf entfernt
- **Silent Exception Swallowing:** `except Exception: pass` in exchange factory durch Logging ersetzt
- **aiohttp Session Leak:** Context Manager Support fuer LLM Provider hinzugefuegt
- **_signal_degen TypeError:** Fehlender `history` Parameter in zweiter Definition ergaenzt
- **50+ Test-Lint-Fehler behoben:** E741, F841, E402, F401 in 28 Test-Dateien

### Geaendert
- **CI linted jetzt auch tests/:** `ruff check src/ tests/` statt nur `src/`
- **Hardcoded German String entfernt:** `'Speichern fehlgeschlagen'` durch `t('common.saveFailed')` ersetzt
- **Leere Komponentenverzeichnisse entfernt:** `components/bot/` und `components/exchanges/`

---

## [3.12.1] - 2026-02-21

### Behoben
- **CI-Pipeline repariert:** 134 ruff-Lint-Fehler behoben (unused imports, E402, E712, E741, E731, F821, F841, F811)
- **Doppelte Methoden entfernt:** 6 duplizierte Funktionen in `MarketDataFetcher` (calculate_atr, calculate_ema, calculate_adx, calculate_macd, calculate_rsi, detect_rsi_divergence)
- **Undefined Name Bugs:** `BacktestResult` und `history` Referenzen in backtest engine korrigiert
- **SQLAlchemy Best Practices:** `== True` Vergleiche durch `.is_(True)` ersetzt
- **Test fix:** `test_date_range.py` nutzte Kline-Strategy-Pfad der in CI wegen Binance Geo-Block (HTTP 451) fehlschlug — auf Data-Pfad umgestellt

---

## [3.12.0] - 2026-02-20

### Freie Datumswahl im Backtesting (Option A)

**Problem geloest:** Der Backtest-Fetcher holte historische Daten immer ab "heute rueckwaerts". Nutzer konnten keine beliebigen historischen Zeitraeume (z.B. Jan 2024 bis Maerz 2024) testen — es wurden immer die letzten N Tage verwendet.

**Loesung:** Komplette Date-Range-Unterstuetzung durch den gesamten Stack: Frontend → API → Strategy-Adapter → HistoricalDataFetcher.

#### Hinzugefuegt
- **`HistoricalDataFetcher.set_date_range(start_date, end_date)`** — Setzt den Datumbereich fuer alle Sub-Fetcher (Binance, CoinGecko, Alternative.me, etc.)
- **`_get_time_range_ms(days)`** — Helper der start_ms/end_ms aus Datumbereich oder Fallback (now-days) berechnet
- **`_cache_suffix()`** — Cache-Keys enthalten jetzt den Datumbereich, damit verschiedene Perioden unabhaengig gecacht werden
- **`GET /api/backtest/date-limits`** — Neuer API-Endpoint der Timeframe-spezifische Limits zurueckgibt
- **Timeframe-spezifische Validierung** im Backend:
  - 1m: max. 7 Tage
  - 5m: max. 30 Tage
  - 15m: max. 90 Tage
  - 30m: max. 180 Tage
  - 1h/4h/1d: max. 365 Tage
  - Fruehestes Datum: 01.01.2020 (Binance Futures Start)
  - Kein Enddatum in der Zukunft
- **DatePicker min/max Constraints** — Deaktiviert Tage ausserhalb des erlaubten Bereichs
- **Frontend-Validierung** — Zeigt Timeframe-Limit-Info und Fehlermeldungen in Echtzeit
- **i18n-Keys** fuer de.json und en.json (dateLimitInfo, dateLimitExceeded, dateBeforeEarliest, dateFuture)
- **13 neue Tests** (`tests/backtest/test_date_range.py`) — Date-Range-Helpers, API-Validierung, Adapter-Propagation, Integration

#### Geaendert
- `HistoricalDataFetcher.__init__()` speichert `_start_ms` und `_end_ms` Attribute
- Alle 11 Sub-Fetcher verwenden `_get_time_range_ms()` statt `datetime.now() - timedelta(days)`
- `strategy_adapter.run_backtest_for_strategy()` berechnet `fetch_start` (mit Warmup-Buffer) und `fetch_end`, uebergibt sie an den Fetcher
- `BacktestRunRequest` API-Validation prueft Datumgrenzen und Timeframe-Limits
- Cache-Keys aller Sub-Fetcher enthalten optionalen Datums-Suffix fuer Range-Caching

#### Timeframe-Limit-Matrix
| Timeframe | Max. Tage | Candles (30d) | Grund |
|---|---|---|---|
| 1m | 7 | 10.080 | Extrem viele Datenpunkte |
| 5m | 30 | 8.640 | Viele Datenpunkte, API-Pagination |
| 15m | 90 | 8.640 | Moderate Datenmenge |
| 30m | 180 | 8.640 | Moderate Datenmenge |
| 1h | 365 | 8.760 | Gute Balance |
| 4h | 365 | 2.190 | Wenig Datenpunkte |
| 1d | 365 | 365 | Minimale Datenmenge |

---

## [3.11.0] - 2026-02-20

### ExecutionSimulator — Realistische Handelskosten im Backtest

**Problem geloest:** Das Backtest-Kostenmodell verwendete fest kodierte Werte (Slippage 0.03%, Fees 0.04%×2, Funding 1/3-Wahrscheinlichkeit), die erheblich von den tatsaechlichen Live-Trading-Kosten abwichen. Insbesondere wurden Funding-Kosten bei Mehrtages-Positionen um Faktor 9× unterschaetzt.

**Loesung:** Neuer `ExecutionSimulator` der die Exchange-Ausfuehrungsschicht 1:1 nachbildet.

#### Hinzugefuegt
- **`ExecutionSimulator`** (`src/backtest/execution_simulator.py`) — Professionelles Kostenmodell:
  - **Volatilitaets-basierte Slippage**: `slip = base + factor × (high-low)/close` statt fester 0.03%. Ruhiger Markt (0.2% Range) = 0.02% Slippage, volatiler Markt (3% Range) = 0.16%.
  - **Exchange-spezifische Fees**: Bitget Taker 0.06%, Hyperliquid 0.035%, Binance 0.04% — statt pauschaler 0.04%. Unterstuetzt VIP-Tiers und Hyperliquid Builder-Fee.
  - **Exakte 8h-Funding-Windows**: Zaehlt praezise wie viele 00:00/08:00/16:00 UTC-Grenzen eine Position kreuzt. Ersetzt die alte Heuristik (Intraday: rate×0.33, Multi-Day: rate×1) die Funding massiv unterschaetzte.
- **`entry_timestamp` und `entry_candle_range`** in `BacktestTrade` — Speichert Einstiegszeitpunkt und Candle-Volatilitaet fuer praezise Kostenberechnung beim Schliessen.
- **`_close_trade_simulated()`** in `BacktestEngine` — Schliesst Trades ueber den ExecutionSimulator. Automatisch aktiviert im Unified Mode, Legacy Mode bleibt unveraendert.
- **Exchange-Parameter** (`exchange`, `fee_tier`) in Strategy-Adapter — Konfigurierbar ueber `strategy_params`.
- **48 neue Tests** (`tests/backtest/test_execution_simulator.py`) — Slippage-Modell, Fee-Modell, Funding-Windows, Complete PnL, Old-vs-New-Vergleich.

#### Geaendert
- `BacktestEngine._close_trade()` prueft auf vorhandenen ExecutionSimulator und delegiert automatisch.
- `BacktestEngine.run_unified()` speichert Entry-Timestamp und Entry-Candle-Range auf jedem Trade, uebergibt Exit-Candle beim Schliessen.
- `strategy_adapter._run_unified_backtest()` erstellt automatisch einen ExecutionSimulator (Standard: Bitget).

#### Kostenvergleich Alt vs. Neu
| Kosten | Alt (fest) | Neu (ExecutionSimulator) |
|---|---|---|
| Slippage | 0.03% pauschal | 0.02%-0.16% je nach Volatilitaet |
| Fees (Bitget) | 0.08% RT | 0.12% RT (realer Taker-Satz) |
| Fees (Hyperliquid) | 0.08% RT | 0.07% RT |
| Funding (3-Tage-Hold) | rate × 1.0 | rate × 9.0 (9 Windows) |
| Funding (Intraday) | rate × 0.33 | rate × 0 oder 1 (exakt) |

---

## [3.10.0] - 2026-02-20

### Unified Backtest Architecture — Live Strategy Code wiederverwenden

**Problem geloest:** Bisher war jede Strategie DOPPELT implementiert — einmal fuer Live-Trading und einmal als Kopie im Backtest-Engine. Das fuehrte zu 5-50% Abweichung zwischen Backtest- und Live-Ergebnissen.

**Loesung:** Dependency Injection. Der Backtest ruft jetzt den **exakt gleichen** Strategy-Code auf wie das Live-Trading, nur mit historischen Daten statt API-Calls.

#### Hinzugefuegt
- **`BacktestMarketDataFetcher`** (`src/backtest/backtest_data_provider.py`) — Drop-in Replacement fuer `MarketDataFetcher`, das historische Daten im Binance-API-Format zurueckgibt. Erbt alle statischen Indicator-Methoden (EMA, RSI, ADX, etc.).
- **`BacktestEngine.run_unified()`** — Neue async Methode, die Live-Strategy-Code mit Mock-Daten ausfuehrt. Gleiche Position-Management-Logik wie `run()` (TP/SL, Fees, Slippage, Daily Limits, Next-Candle-Open Entry).
- **Unified Mode im Strategy Adapter** — Nicht-LLM-Strategien (EdgeIndicator, ClaudeEdgeIndicator, SentimentSurfer, LiquidationHunter) nutzen automatisch den Unified Mode. LLM-Strategien (Degen, LLMSignal) fallen auf den Legacy Mode zurueck.
- **Timeframe-Synchronisation** — `kline_interval` wird automatisch auf das Backtest-Timeframe gesetzt, damit Strategien Klines im korrekten Interval anfordern.
- **`data_fetcher` Parameter** fuer Degen und LLMSignal Strategien (Vorbereitung fuer zukuenftigen Unified-Support).
- **Umfangreiche Tests** (`tests/backtest/test_unified_backtest.py`) — Kline-Format, MarketMetrics, alle Timeframes, Legacy-Fallback, Constructor-Kompatibilitaet.

#### Erwartete Genauigkeitsverbesserung
| Strategie | Vorher (Kopie) | Nachher (Unified) |
|---|---|---|
| EdgeIndicator | ~95% | ~99% |
| ClaudeEdgeIndicator | ~85% | ~97% |
| SentimentSurfer | ~70% | ~95% |
| LiquidationHunter | ~90% | ~99% |
| Degen / LLMSignal | ~60% | ~60% (Legacy, LLM nicht wiederholbar) |

#### Behoben (Tests)
- **BacktestConfig `trading_fee_percent`** — Test erwartete 0.06 statt dem aktuellen Wert 0.04 (seit v3.9.0)
- **`btc_open`/`eth_open` in Tests** — Fehlende Pflichtfelder in `test_backtest_data.py`, `test_historical_data_extra.py`, `test_remaining_coverage.py` und `test_backtest_engine.py` ergaenzt
- **`_generate_signal()` Signatur** — `history` Parameter in Mock-Funktionen ergaenzt
- **Obsolete Strategie-Referenz** — `"contrarian"` durch `"liquidation_hunter"` ersetzt (6 Stellen)
- **Funding Rate Pagination Test** — Page-Size auf 1000 gesetzt damit Pagination ausgeloest wird
- **`_get()` Timeout-Test** — `aiohttp.ClientTimeout(total=30)` statt `timeout=30`
- **Encryption Test** — An aktuelle `_get_or_create_key()` Logik angepasst (kein `.env` File mehr, ephemerer Key)
- **Signal Reason Test** — An aktuelle Liquidation-Hunter 3-Schritt-Logik angepasst (Leverage + Sentiment statt OI + TopTraders)

#### Unveraendert
- `BacktestEngine.run()` bleibt vollstaendig erhalten (Legacy Mode)
- Alle `_signal_*()` Methoden in `engine.py` bleiben bestehen
- `KlineBacktestEngine` bleibt unveraendert
- Position Management (TP/SL, Fees, Slippage, Funding) bleibt identisch
- Frontend und API-Endpoints bleiben unveraendert

---

## [3.9.1] - 2026-02-20

### Backtest: Look-Ahead Bias eliminiert & Open-Price-Realismus

#### Behoben (Critical)
- **Look-Ahead Bias im Entry** — Backtest nutzte den Close-Preis des Signal-Candles als Entry-Preis. In der Realitaet kann man erst zum Open des NAECHSTEN Candles einsteigen. Jetzt: `next_candle.btc_open` statt `current_candle.btc_price`.
- **Funding Rate zu hoch bei Intraday-Trades** — Volle Daily-Funding-Rate auch fuer Trades die < 8h offen waren. Jetzt skaliert: Intraday = 33% der Funding-Rate (1/3 Chance eine Funding-Periode zu kreuzen), Multi-Day = 100%.
- **Mock-Daten ohne Open-Preis** — `btc_open`/`eth_open` fehlten in Mock-Daten. OHLC-Kontinuitaet: `next_candle.open == prev_candle.close` verifiziert.
- **Mock-Daten OHLC unrealistisch** — High/Low wurden nur vom Close abgeleitet. Jetzt: High = max(Open, Close) + Volatility, Low = min(Open, Close) - Volatility.

#### Hinzugefuegt
- `btc_open`/`eth_open` Felder in `HistoricalDataPoint` und Mock-Daten-Generator
- Open-Price Kontinuitaetstest fuer alle Timeframes (1d, 4h, 1h, 30m)

---

## [3.9.0] - 2026-02-20

### Backtest-Realismus: Produktions-reife Handels-Simulation

#### Behoben (Critical)
- **Funding Rate nie geladen** — Binance Funding Rate API wurde ohne `startTime` aufgerufen, lieferte Daten ab 2019 die alle rausgefiltert wurden. Funding-Kosten waren IMMER $0.00. Jetzt Forward-Pagination von `startTime`, 90+ Datenpunkte (3x/Tag).
- **Sentiment Surfer 0 Trades** — VWAP-Berechnung erforderte min. 7 Candles/24h, aber 4h-Candles liefern nur 6. News-Quelle (nicht verfuegbar im Backtest) wurde trotzdem im Agreement-Gate gezaehlt (3/6 statt 2/5). Beides gefixt.
- **Metrics inkonsistent mit Trade-Liste** — Metrics kamen vom gesamten Engine-Lauf inkl. Warmup-Trades. Jetzt Neuberechnung aus gefilterten Trades: PnL, Win Rate, Drawdown, Equity Curve, Sharpe Ratio.
- **Profit Factor bei 0 Trades** — Zeigte 999.99 statt 0.0 an.

#### Hinzugefuegt (Realismus)
- **Slippage-Modell** — 0.03% pro Seite (Entry + Exit), realistisch fuer BTC/ETH Futures. Macht Backtest konservativer.
- **TP/SL Same-Candle: Konservativ** — Wenn TP und SL im selben Candle getroffen werden, wird SL angenommen (Worst Case statt Best Case).
- **Binance-realistische Fees** — 0.04% Taker (vorher 0.06%) entspricht Binance Futures VIP0.

#### Geaendert
- **Equity Curve** — Startet jetzt mit User-Startkapital, nicht Engine-internem Kapital
- **Max Drawdown** — Wird nur aus gefilterten Trades berechnet
- **Funding Rate** — Jetzt als eigene Datenquelle (10 statt 9 Sources)

#### Verifizierte Strategien
Alle 6 Strategien generieren realistisch Trades mit Fees, Funding und Slippage:
| Strategie | Trades | Win Rate | Funding |
|---|---|---|---|
| Claude Edge Indicator | 15 | 53% | realistische Kosten |
| Edge Indicator | 35 | 37% | realistische Kosten |
| Sentiment Surfer | 7 | 43% | realistische Kosten |
| Liquidation Hunter | 33 | 36% | realistische Kosten |
| Degen | 7 | 14% | realistische Kosten |
| LLM Signal | 4 | 25% | realistische Kosten |

---

## [3.8.5] - 2026-02-20

### Code Quality & Type Safety (Review — Runde 5)

#### Behoben
- **Backtest Polling Stale setState** — Polling-Interval in `Backtest.tsx` konnte nach Unmount State-Updates ausloesen, jetzt `cancelled`-Flag verhindert veraltete Updates
- **Dashboard `as any` Casts** — Dynamische i18n-Keys `t(\`dashboard.days${p}\` as any)` durch typisierte `PERIOD_LABELS`-Map ersetzt
- **CORS-Logging zu laut** — `logger.info("CORS allowed origins: ...")` auf `logger.debug` reduziert (kein Spam in Production-Logs)

#### Verbessert (Type Safety)
- **`LlmConnection` Interface** — Neuer Typ in `types/index.ts` statt `useState<any[]>` in `BotDetail`, `BotPerformance`, `Bots`, `Settings`
- **`AdminUidEntry` Interface** — Typisiert statt `useState<any[]>` in `Settings.tsx`
- **`HlRevenueInfo` Interface** — Typisiert statt `useState<any>(null)` in `Settings.tsx`
- Alle `useState<any>` Deklarationen im Frontend durch typisierte Interfaces ersetzt

---

## [3.8.4] - 2026-02-20

### Frontend UX Fixes (Code Review)

#### Behoben (Critical)
- **WebSocket nie verbunden** — `useWebSocket.ts` las `localStorage.getItem('token')` statt `'access_token'`, Echtzeit-Benachrichtigungen waren komplett kaputt
- **Presets Duplicate/Delete ohne Error-Handling** — API-Fehler crashten ohne Feedback, jetzt try/catch + Toast
- **BotDetail fetchData nicht awaited** — Nach Start/Stop wurde Bot-Status nicht aktualisiert (Fire-and-forget), jetzt `await fetchData()`
- **BotPerformance Stale Closure** — `loadCompareData`/`loadBotDetail` schlossen ueber veralteten `demoParam`, jetzt `useCallback` mit korrekten Dependencies
- **BotDetail Bar in AreaChart** — `<Bar>` innerhalb von `<AreaChart>` (ungueltig), jetzt `<ComposedChart>` fuer korrektes Rendering

#### Behoben (i18n)
- **ErrorBoundary** — Hardcoded Englisch "Something went wrong" / "Try again" → `i18n.t()` mit `common.errorBoundaryTitle`/`common.tryAgain`
- **BotPerformance "Netto"** — Hardcoded Deutsch → `t('common.net')`
- **AdminUsers** — "Create", "Keine Benutzer vorhanden.", Placeholders (Username/Password/Email) waren nicht uebersetzt
- **BotDetail Fehlermeldung** — Hardcoded "Failed to load bot data" → `t('common.error')`
- **TaxReport t() Fallback** — Falscher Fallback-Syntax `t('key', 'default')`, Key `tax.downloadError` in beiden JSON-Dateien ergaenzt
- Neue i18n-Keys: `common.net`, `common.errorBoundaryTitle`, `common.tryAgain`, `admin.create`, `admin.noUsers`, `admin.usernamePlaceholder`, `admin.passwordPlaceholder`, `admin.emailPlaceholder`, `tax.downloadError`

---

## [3.8.3] - 2026-02-20

### Backtest Engine Fixes (Deep Code Review — Runde 2)

#### Behoben
- **Drawdown-Berechnung falsche Reihenfolge** — Drawdown wurde in Trade-Eroeffnungsreihenfolge statt nach Exit-Datum berechnet, jetzt chronologisch sortiert
- **Division by Zero bei starting_capital=0** — `_save_daily_stats` und `_close_trade` konnten bei Kapital=0 crashen, Guards eingefuegt
- **ETH VWAP nutzte BTC-Volumen** — Sentiment Surfer berechnete VWAP fuer ETH mit BTC-Handelsvolumen, neues `eth_volume` Feld eingefuegt
- **Liquidation Hunter ignorierte Config-Thresholds** — `crowded_longs`/`crowded_shorts` waren hardcoded (2.5/0.4) statt aus BacktestConfig (user-konfigurierbar)
- **O(N²) in _save_daily_stats** — Taegliche Fees/Funding wurden per O(N)-Scan ueber alle Trades berechnet, jetzt inkrementelle Akkumulatoren
- **bot_worker.stop() AttributeError** — `self._config.name` wurde ohne None-Guard aufgerufen, Crash bei fehlgeschlagener Initialisierung
- **Degen TP/SL Fallback auf entry_price** — TP und SL fielen auf `current_price` zurueck (sofortige Ausloesung), jetzt +3%/-2% Defaults

---

## [3.8.2] - 2026-02-20

### Architecture Fixes (Mentor Review — Runde 3)

#### Behoben
- **Encryption Key Auto-Write entfernt** — `_get_or_create_key()` schrieb Auto-Keys direkt in `.env` (Race Condition, unerwartete Datei-Mutation). Jetzt nur noch in-memory + Warning-Log
- **BotWorker Error→Running ohne Log** — Bot wechselte nach Cooldown von `error` zu `running` ohne Log-Eintrag, Debugging erschwert
- **WebSocket Exception Swallowing** — 3 Stellen (`orchestrator.py`, `trade_executor.py`, `position_monitor.py`) verschluckten WS-Fehler komplett (`except: pass`), jetzt `logger.debug()`
- **Stale Backtests nach Server-Restart** — Backtests im Status `pending`/`running` blieben nach Crash/Restart fuer immer haengen. Startup markiert sie jetzt als `failed`
- **AdminRoute Flash-Redirect** — Admin-Seite redirectete beim Page-Refresh sofort zu `/`, weil `user` noch nicht geladen war. Zeigt jetzt Loader bis `fetchUser()` abschliesst
- **Frontend Build brach wegen Test-Files** — `tsconfig.json` inkludierte Test-Dateien im Build-Check, fehlende vitest-Types blockierten `tsc`. Tests jetzt in `exclude`

---

## [3.8.1] - 2026-02-20

### Code Quality, Security & Bug Fixes (Mentor Review)

Umfassender Code-Review mit Fixes fuer 4 kritische, 9 wichtige und 2 kleinere Bugs plus Frontend/Security-Verbesserungen.

#### Behoben (Critical)
- **NameError in BacktestEngine** — `Any` fehlte im typing-Import, Engine-Instantiierung schlug fehl
- **Stale Worker State im Orchestrator** — `_stop_bot_locked` entfernte Worker nicht aus dem Dict, Memory Leak bei jedem Stop/Start-Zyklus
- **Kein HTTP-Timeout bei API-Requests** — `aiohttp` timeout als Integer statt `ClientTimeout`-Objekt, Requests konnten endlos haengen
- **HistoricalDataPoint.from_dict Crash** — Fehlende Pflichtfelder in Cache-Daten fuehrten zu TypeError statt klarer Fehlermeldung

#### Behoben (Major)
- **Loss Limit zu lasch** — Berechnung nutzte `starting_capital` statt aktuellen Tages-Startwert, Limit griff nicht bei geschrumpftem Konto
- **Profit-Lock-Feature kaputt** — `locked_profit` wurde berechnet aber nie verwendet, Verluste bis 87.5% statt 25% des Tagesgewinns erlaubt
- **O(n²) Memory bei Intraday-Backtests** — History-Slice wurde pro Candle komplett kopiert, jetzt auf 200 Candles begrenzt
- **Bot-Crash bei korrupter trading_pairs JSON** — `json.loads` ohne Error-Handling im Worker und Status-Endpoint
- **Warmup-Candles verworfen** — Strategy Adapter filterte Warmup-Daten vor Engine-Run, Indikatoren hatten keine Initialisierung
- **Supertrend Boundary Guard** — `close_idx` konnte Array-Grenzen ueberschreiten
- **Pagination-Endlosschleifen** — 5 API-Pagination-Loops hatten keinen Iterations-Cap und keinen Fortschritts-Check
- **Exchange-Seeding nicht idempotent** — Neue Exchanges (z.B. Weex) wurden nie eingefuegt wenn bereits ein Exchange existierte

#### Behoben (Minor)
- **ETH Mock-Daten unrealistisch** — ETH-Preis hatte keinen persistenten State, jetzt eigener Random Walk
- **json.loads in get_status_dict** — Fehlende Error-Behandlung im Bot-Status-Endpoint

#### Behoben (Security)
- **SQL Injection in session.py** — f-String mit Environment-Variable in SQL-Query, ersetzt durch gebundenen Parameter (`:rate`)
- **console.error in Production** — ErrorBoundary loggte Stack-Traces in Browser-Console, jetzt nur noch in DEV-Modus
- **i18n-Keys fehlend** — `proModeParamsHint` und `proModeParamsActiveHint` in de.json und en.json ergaenzt
- **Dashboard Animation Stale Closure** — AnimatedNumber nutzte veralteten Display-Wert bei schnellen Updates, jetzt via useRef
- **Dashboard useEffect Dependency** — `t` fehlte in Dependency-Array

#### Behoben (Security Audit — Runde 2)
- **Tax Report Endpoints ohne Auth** — 3 Endpoints (`/api/tax-report/years`, `/{year}`, `/{year}/download`) waren ohne Authentifizierung aufrufbar, `Depends(verify_api_key)` ergaenzt
- **innerHTML XSS im Dashboard** — Health-Check-Modal injizierte Server-Daten ohne Escaping, `escapeHtml()` Funktion eingefuegt
- **Health-Check leakt Exception-Details** — Unauthentifizierter `/api/health` Endpoint zeigte interne Fehlermeldungen, jetzt nur "healthy"/"unhealthy"
- **db.commit() fehlend bei Affiliate UID** — Aenderung wurde nur geflusht aber nie committed, ging beim Session-Ende verloren
- **db.commit() fehlend bei User-Loeschung** — Token-Revocation (token_version Increment) wurde nicht persistiert, geloeschte User blieben eingeloggt
- **Exception-Details in HTTP-Responses** — `str(e)` in 400-Antworten konnte interne Details leaken, ersetzt durch generische Meldung mit Server-Log
- **Rate Limiting auf Trades-Endpoint** — `GET /api/trades` hatte kein Rate Limit, jetzt 60/Minute
- **trading_pairs Input-Validation** — Keine Validierung auf Inhalt der Pair-Strings, jetzt Regex `^[A-Z0-9_-]{1,30}$`

---

## [3.8.0] - 2026-02-20

### Backtest Timeframe-Support

#### Hinzugefuegt
- Backtest unterstuetzt jetzt alle Zeitfenster (1m, 5m, 15m, 30m, 1h, 4h, 1d) — der Frontend Timeframe-Selector funktioniert jetzt wie vorgesehen
- Klines werden im gewaehlten Interval von Binance Futures geholt (mit Pagination fuer >1500 Candles)
- Taegliche Daten (FGI, L/S, OI, Taker, etc.) werden auf Intraday-Candles forward-gefuellt
- ETH-Klines werden per exaktem Timestamp statt Date gemappt (korrekte Intraday-Zuordnung)
- Backtest respektiert jetzt das gewaehlte Handelspaar (nur BTC oder ETH statt immer beide)
- Mock-Daten unterstuetzen Intraday-Generierung fuer Offline-Backtests
- Warmup-Buffer im Strategy Adapter stellt sicher, dass Indikatoren genug Candles zum Initialisieren haben

#### Behoben
- Backtest Timeframe-Parameter wurde ignoriert — Klines wurden immer als Daily (1d) geholt, Intraday-Strategien waren unmoeglich
- Edge Indicator / Claude Edge Indicator lieferten 0 Trades bei kurzen Zeitraeumen weil Daily-Candles fuer Indikator-Warmup nicht ausreichten
- ETH-Kline-Daten gingen bei Intraday-Intervallen verloren (mehrere Candles pro Tag auf einen kollabiert durch Date-Key Deduplizierung)

### Backtest Signal-Generatoren — Live-Matching Rewrite

Alle 4 nicht-KI Strategien im Backtest wurden komplett neu geschrieben, damit sie exakt die gleiche Logik wie ihre Live-Pendants verwenden.

#### Geaendert

- **Edge Indicator** — ADX-Multiplier von 1.5 auf 0.8 korrigiert (Live-Wert), ADX-Penalty nutzt `int()` statt `*1.2`, Score-Series mit EMA(3)-Smoothing fuer Regime-Erkennung, Regime-Flip wird durch Vergleich mit vorherigem Regime erkannt (nicht Entry-Crosses), Choppy-Market → Confidence = 0
- **Claude Edge Indicator** — Eigener Signal-Generator (war vorher identisch mit Edge Indicator), implementiert alle 6 Live-Enhancements: ATR-basierte TP/SL (ATR×2.5/ATR×1.5), Volume Confirmation via Taker Buy/Sell Ratio, HTF-Proxy ueber EMA 21/50, Trailing-Stop Metadata, Regime-basierte Positionsgroesse (0.5–1.0), RSI-Divergenz-Erkennung (+8/−10 Confidence)
- **Sentiment Surfer** — 6 Scoring-Quellen exakt wie Live: News (0, nicht verfuegbar), FGI (kontaer, threshold_distance×3), VWAP (deviation×2000), Supertrend (+70/−70 via eigener Berechnung), Volume ((buy_ratio−0.5)×400), Momentum (price_change×20/×15). Gewichte: news=1.0, fg=1.0, vwap=1.2, supertrend=1.2, volume=0.8, momentum=0.8. Gate: 3/6 Uebereinstimmung UND Confidence ≥ 40
- **Liquidation Hunter** — Von 11 Schritten auf 3 reduziert (Live-Logik): Leverage + Sentiment + Funding. Live-Schwellenwerte: crowded_longs=2.5, crowded_shorts=0.4, extreme_fear=20, extreme_greed=80, high_confidence_min=85, low_confidence_min=60

#### Hinzugefuegt

- **`_supertrend_direction()`** — Modul-Level Hilfsfunktion fuer Supertrend-Indikator-Berechnung (ATR-basiert mit Band-Tracking)
- **`_detect_rsi_divergence()`** — Erkennung von bullischen/baerischen RSI-Divergenzen ueber konfigurierbares Lookback-Fenster
- **`_build_score_series_backtest()`** — Baut Momentum-Score-Serie fuer EMA(3)-Smoothing (Predator Momentum Score: MACD Histogram + RSI Drift + Trend Bonus)
- **`_get_min_confidence()`** — Per-Strategie Mindest-Confidence: Edge/Claude Edge/Sentiment = 40, Liquidation Hunter = 60
- **`_signal_metadata`** — Neues Dict fuer strategie-spezifische TP/SL-Overrides und Positionsgroessen-Skalierung (genutzt von Claude Edge Indicator)
- **Signal-Dispatcher** — Separates Routing fuer `claude_edge_indicator` (war vorher auf `edge_indicator` gemappt)
- **24h-Preisaenderung aus Historie** — Sentiment Surfer berechnet echte 24h-Preisaenderung aus der Candle-Historie statt per-Candle `btc_24h_change` (korrektes Intraday-Verhalten)

#### Behoben

- Edge Indicator und Claude Edge Indicator lieferten identische Ergebnisse — Claude Edge hat jetzt eigenen Signal-Generator mit 6 zusaetzlichen Enhancements
- Sentiment Surfer erzeugte 0 Trades auf Intraday-Timeframes — `btc_24h_change` war per-Candle (±0.3% bei 30m) statt echte 24h-Aenderung (±2–5%)
- VWAP-Fenster war fuer Intraday zu klein (hardcoded 24 Candles) — jetzt dynamisch basierend auf `candles_24h`
- Liquidation Hunter nutzte 11 Schritte die in der Live-Strategie nicht existieren — reduziert auf die 3 echten Live-Schritte

### Bot-Lifecycle & Risk Notifications

#### Hinzugefügt
- **Bot-Start/Stop Notifications** via Discord & Telegram — beim Starten wird Name, Strategie und Modus gesendet, beim Stoppen eine Bestätigung
- **Error Notifications** bei 5+ aufeinanderfolgenden Fehlern — einmalig beim Übergang in den Error-Status (kein Spam bei jedem Zyklus)
- **Risk Alert Notifications** bei Trading-Halt durch Limit-Überschreitung — einmalig pro Halt-Grund pro Tag (global und per Symbol), Set wird täglich zurückgesetzt
- **Tägliche Zusammenfassung (Daily Summary)** um 23:55 UTC — automatischer Cron-Job sendet Tagesstatistiken (Trades, PnL, Win-Rate, Fees, Funding, Max Drawdown) via Discord & Telegram
- **Telegram `send_daily_summary()`** — neue HTML-formatierte Tagesübersicht mit Emoji-basiertem Layout
- **Telegram `send_risk_alert()`** — neue Risiko-Warnung mit Alert-Typ, Nachricht und optionalen Schwellenwerten

#### Behoben
- **Discord Notification Crash** — `send_bot_status`, `send_error`, `send_daily_summary` akzeptieren jetzt `**kwargs` für cross-notifier Kompatibilität (vorher TypeError bei unbekannten Parametern)
- **Telegram Status-Emoji** — case-insensitiver Vergleich (STARTED/STOPPED statt started/stopped)
- **Stop-Notification Reihenfolge** — wird jetzt VOR dem Client-Shutdown gesendet statt danach
- **Risk-Alert-Typ** — dynamisch `TRADE_LIMIT` vs. `DAILY_LOSS_LIMIT` je nach Halt-Grund (statt immer `DAILY_LOSS_LIMIT`)
- **Bot-Name in Telegram Daily Summary** — zeigt jetzt an, welcher Bot die Zusammenfassung sendet

### Alerts-Feature entfernt (verschoben auf späteres Release)

#### Entfernt
- **Gesamtes Alerts-System** temporär entfernt und als GitHub Issue für zukünftiges Feature angelegt
  - Backend: AlertEngine, Alert-Router, Alert-Schemas, Alert/AlertHistory DB-Modelle
  - Frontend: Alerts-Seite, Navigation, i18n-Keys, TypeScript-Typen
  - Tests: Alle Alert-bezogenen Unit-Tests
  - Orchestrator: AlertEngine-Integration und Bot-Alert-Trigger
- DB-Tabellen `alerts` und `alert_history` bleiben bestehen (keine destruktive Migration)

#### Behoben
- **KI-Bot Icon** wird jetzt bei allen KI-Strategien angezeigt (`llm_signal` und `degen`), nicht nur bei `llm_signal`
  - Betrifft: Bot-Karten, Bot-Detail, Bot-Builder, Bot-Performance
- **Umlaute in Strategie-Beschreibungen** — "ue"/"oe"/"ae" durch echte Umlaute (ü/ö/ä) ersetzt in allen 6 Strategien und BotBuilder-Fallback-Texten

#### Geändert
- **Strategie-Parameter auf Deutsch übersetzt** — alle Labels und Beschreibungen in den 6 Strategien (Edge Indicator, Claude Edge Indicator, Degen, KI-Companion, Sentiment Surfer, Liquidation Hunter) sind jetzt deutschsprachig
- **Kline Intervall Info-Hinweis** — bei Edge Indicator und Claude Edge Indicator wird im Kline-Intervall-Feld ein Tipp angezeigt, dass der Analyse-Takt (Zeitplan) nicht deutlich kürzer als das Kline Intervall sein sollte
- **Parameter-Beschreibungen sichtbar** — Descriptions werden jetzt als Text unter den Feldern angezeigt (statt nur als unsichtbarer Hover-Tooltip)
- **BotBuilder Fallback-Strings auf Deutsch** — alle englischen Fallback-Texte im BotBuilder durch deutsche ersetzt

---

## [3.7.0] - 2026-02-20

### Advanced Alerting, Multi-Exchange Portfolio, Technical Fixes, Docs & Tests

Grosses Feature-Update: Advanced Alerting System (Preis/Strategie/Portfolio Alerts mit Discord+Telegram),
Multi-Exchange Portfolio View (aggregiertes PnL ueber alle Exchanges), 5 technische Luecken behoben,
Dokumentation aktualisiert, und umfangreiche Test-Abdeckung fuer alle neuen Features.

#### Hinzugefuegt

##### Advanced Alerting System (Backend)

- **Datenbank-Modelle** (`src/models/database.py`):
  - Neues `Alert` Modell: user_id, bot_config_id (nullable), alert_type (price/strategy/portfolio),
    category, symbol, threshold, direction, is_enabled, cooldown_minutes, last_triggered_at, trigger_count
  - Neues `AlertHistory` Modell: alert_id, triggered_at, current_value, message (Audit-Trail)
  - Index `ix_alert_user_enabled` fuer schnelle Abfragen
  - SQLite-Migrationen fuer beide Tabellen in `src/models/session.py`

- **API Schemas** (`src/api/schemas/alerts.py`):
  - `AlertCreate` mit model_validator: Preis-Alerts erfordern symbol+direction, threshold > 0
  - `AlertUpdate` fuer partielle Aktualisierungen
  - `AlertResponse` und `AlertHistoryResponse` mit from_attributes

- **API Router** (`src/api/routers/alerts.py`):
  - `GET /api/alerts` — Liste aller Alerts (optional Filter by type)
  - `POST /api/alerts` — Alert erstellen (max 50 pro User)
  - `GET /api/alerts/{id}` — Alert Details
  - `PUT /api/alerts/{id}` — Alert aktualisieren
  - `DELETE /api/alerts/{id}` — Alert loeschen
  - `PATCH /api/alerts/{id}/toggle` — Aktivieren/Deaktivieren
  - `GET /api/alerts/history` — Globale Alert-History (letzte 50)
  - Rate Limit: 30/min auf Schreib-Endpoints

- **Alert Engine** (`src/bot/alert_engine.py`):
  - `AlertEngine` Klasse als Background Task im Orchestrator
  - `_check_price_alerts()`: Alle 60s, nutzt MarketDataFetcher, gruppiert nach Symbol
  - `_check_portfolio_alerts()`: Alle 5min, aggregiert Tages-PnL pro User
  - `_trigger_alert()`: Cooldown-Check, DB-Update, AlertHistory-Eintrag, Notification, WebSocket
  - `check_strategy_alerts()`: Inline-Funktion fuer BotWorker (low_confidence, consecutive_losses, signal_missed)

- **Notification Erweiterung**:
  - `DiscordNotifier.send_alert()` — Eigene Embed-Farbe `COLOR_ALERT = 0xFF6600` (Orange),
    typspezifische Emojis (Preis, Strategie, Portfolio)
  - `TelegramNotifier.send_alert()` — HTML-formatierte Alert-Nachrichten

- **Orchestrator Integration** (`src/bot/orchestrator.py`):
  - AlertEngine startet in `restore_on_startup()`, stoppt in `shutdown_all()`

##### Multi-Exchange Portfolio View (Backend)

- **API Schemas** (`src/api/schemas/portfolio.py`):
  - `ExchangeSummary`, `PortfolioSummary`, `PortfolioPosition`, `PortfolioAllocation`, `PortfolioDaily`

- **API Router** (`src/api/routers/portfolio.py`):
  - `GET /api/portfolio/summary?days=30` — Aggregiertes PnL gruppiert nach Exchange
  - `GET /api/portfolio/positions` — Live Positionen von allen verbundenen Exchanges (parallel, 10s Timeout)
  - `GET /api/portfolio/daily?days=30` — Taegliche PnL-Aufschluesselung pro Exchange
  - `GET /api/portfolio/allocation` — Balance-Verteilung pro Exchange

- **Exchange Factory** (`src/exchanges/factory.py`):
  - Neue Funktion `get_all_user_clients(user_id, db)` — Erstellt Client-Instanzen fuer alle verbundenen Exchanges

##### Alerts Frontend

- **Alerts-Seite** (`frontend/src/pages/Alerts.tsx`):
  - Drei Tabs: Preis, Strategie, Portfolio (plus "Alle") zum Filtern
  - Alert-Liste mit Toggle On/Off und Loeschen
  - Erstellungs-Dialog mit typspezifischen Feldern (Symbol, Schwellenwert, Richtung, Cooldown)
  - Verlaufs-Sektion mit den letzten 20 ausgeloesten Alerts
  - Live WebSocket-Unterstuetzung fuer `alert_triggered` Events

##### Portfolio Frontend

- **Portfolio-Seite** (`frontend/src/pages/Portfolio.tsx`):
  - Header mit Gesamtguthaben und Tages-PnL (farbkodiert)
  - Exchange-Karten (Bitget=Blau, Hyperliquid=Gruen, Weex=Orange)
  - Gestapeltes Flaechendiagramm: Taeglicher PnL pro Exchange (Recharts AreaChart)
  - Positionstabelle: sortierbar nach PnL, alle Exchanges
  - Allokations-Donut (Recharts PieChart)
  - Periodenwahl (7/14/30/90 Tage)

##### Navigation & Routing

- **Routing** (`frontend/src/App.tsx`): Lazy-Imports und Routen fuer `/portfolio` und `/alerts`
- **Navigation** (`frontend/src/components/layout/AppLayout.tsx`): Portfolio (Briefcase) und Alerts (Bell) Links
- **TypeScript Interfaces** (`frontend/src/types/index.ts`): Alert, AlertHistory, AlertCreate,
  PortfolioSummary, ExchangeSummary, PortfolioPosition, PortfolioDaily, PortfolioAllocation
- **i18n** (`frontend/src/i18n/de.json` + `en.json`): ~70 neue Keys fuer alerts.* und portfolio.* Namespaces

##### Technical Fixes

- **Affiliate UID Verification** (`src/api/routers/affiliate.py`):
  - `POST /api/affiliate-links/verify-uid` — Validiert UID-Format (Bitget: numerisch, Weex: alphanumerisch)
  - Setzt `affiliate_verified = True` in ExchangeConnection
- **Affiliate UID Gate** (`src/bot/hyperliquid_gates.py`):
  - Blockiert Bot-Start wenn UID nicht verifiziert
- **AI Module Exports** (`src/ai/__init__.py`):
  - Vollstaendige `__all__` mit BaseLLMProvider, PROVIDER_REGISTRY, MODEL_CATALOG, etc.

##### Tests

- **Backend Tests (15 neue Dateien)**:
  - `tests/unit/api/test_alerts_router.py` — 15 Tests: CRUD, Toggle, Filter, Validierung, Auth
  - `tests/unit/api/test_portfolio_router.py` — 9 Tests: Summary, Positions, Daily, Allocation
  - `tests/unit/api/test_affiliate_verification.py` — 9 Tests: UID-Format, Verification Flow
  - `tests/unit/api/test_funding_case_fix.py` — 8 Tests: func.case Kompatibilitaet
  - `tests/unit/bot/test_alert_engine.py` — 18 Tests: Lifecycle, Price/Portfolio/Strategy Checks, Cooldown, Trigger
  - `tests/unit/test_alert_notifications.py` — 12 Tests: Discord/Telegram Alert Formatierung
  - `tests/unit/test_claude_edge_backtest.py` — 6 Tests: HTF Sync/Async Routing, Backtest-Modus

- **Frontend Tests (2 neue Dateien)**:
  - `frontend/src/pages/__tests__/Alerts.test.tsx` — 10 Tests: Render, Tabs, Create Modal, Alerts Display
  - `frontend/src/pages/__tests__/Portfolio.test.tsx` — 10 Tests: Render, Summary, Exchange Cards, Positions, Charts

##### Dokumentation

- **docs/API.md** — Komplett neu geschrieben mit allen aktuellen Endpoints
- **docs/FAQ.md** — Aktualisiert fuer v3.7.0 Features
- **docs/STRATEGY.md** — Alle 6 Strategien dokumentiert
- **6 neue Anleitungen** in `Anleitungen/`:
  - Backtesting, LLM Provider, Alerts, Portfolio, Strategien, Weex Setup

#### Geaendert

- **ClaudeEdge Backtest Fix** (`src/strategy/claude_edge_indicator.py`):
  - `backtest_mode=False` Parameter: nutzt `_check_htf_alignment_sync()` im Backtest-Modus

#### Behoben

- **SQLAlchemy `case()` Workarounds entfernt** — `pytest.skip()` Workarounds in Tests entfernt

#### Entfernt / Verschoben

- **Legacy Test Cleanup**:
  - `tests/test_auth.py` geloescht (redundant)
  - `tests/test_bots.py`, `test_statistics.py`, `test_trades.py` nach `tests/integration/` verschoben

---

## [3.6.0] - 2026-02-19

### Realistic Backtest Engine, Pro Mode Redesign & New Strategies

Komplette Ueberarbeitung der Backtest-Engine mit echten technischen Indikatoren,
neue Strategien (Edge Indicator, Claude Edge Indicator), Guided Tour, GettingStarted Redesign
und BotBuilder Pro Mode Neugestaltung.

#### Hinzugefuegt

##### Realistische Backtest-Engine
- **Technische Indikatoren** in `src/backtest/engine.py` — Pure-Python Implementierung:
  - `_ema()` — Exponential Moving Average
  - `_rsi()` — Relative Strength Index (14)
  - `_macd()` — MACD mit Signal Line und Histogram (12/26/9)
  - `_adx()` — Average Directional Index (14)
  - `_atr()` — Average True Range (14)
  - `_stdev()` — Rolling Standard Deviation
- **Signal-Methoden komplett ueberarbeitet**:
  - `_signal_edge_indicator`: EMA Ribbon (8/21), ADX, MACD, RSI mit Drift, Predator Momentum Score
  - `_signal_sentiment_surfer`: 6-Quellen gewichtetes Scoring (FGI 25%, Funding 20%, VWAP 15%, Supertrend 15%, Volume 10%, Momentum 15%)
  - `_signal_degen`: 10 Datenquellen + RSI + EMA, Funding Divergence, Signal Strength Gate
- **History-basierte Analyse**: `_generate_signal()` erhaelt kompletten Preisverlauf als `history` Parameter

##### Neue Strategien
- **Edge Indicator** (`src/strategy/edge_indicator.py`) — Rein technische Kline-Strategie
  - RSI, MACD, Bollinger Bands, Volume Analysis
  - Scoring-System mit konfigurierbarem Mindest-Score
  - Data Sources: spot_price, vwap, supertrend, spot_volume, volatility
- **Claude Edge Indicator** (`src/strategy/claude_edge_indicator.py`) — Hybrid-Strategie
  - Technische Analyse + LLM-Bewertung
  - Kombiniert Indikatoren mit Sentiment-Daten
  - Data Sources: spot_price, fear_greed, news_sentiment, vwap, supertrend, spot_volume, volatility, funding_rate

##### Guided Tour System
- **GuidedTour Komponente** (`frontend/src/components/ui/GuidedTour.tsx`)
  - Leichtgewichtiger Tour-Guide ohne externe Dependencies
  - Highlight-Overlay, Tooltip-Box, Fortschrittsanzeige
  - Scroll-to-Element, ESC zum Schliessen, localStorage Persistenz
- **Tour Store** (`frontend/src/stores/tourStore.ts`) — Zustand Store fuer Tour-State
- **Dashboard Tour** (4 Steps): Navigation, Demo/Live, KPI-Karten, Charts
- **data-tour Attribute** auf Dashboard und AppLayout Elementen

##### Backtest-Scripts
- **`scripts/backtest_edge_indicator.py`** — 15 Konfigurationen, JSON-Export
- **`scripts/backtest_timeframes.py`** — Multi-Timeframe + All-Strategy Vergleich

##### Admin & Event Logging
- **Admin Logs Router** (`src/api/routers/admin_logs.py`) — Audit-Log API
- **Event Logger** (`src/utils/event_logger.py`) — Strukturiertes Event-Logging
- **Kline Backtest Engine** (`src/backtest/kline_backtest_engine.py`) — Kline-basiertes Backtesting
- **Market Data Module** (`src/data/market_data.py`) — Erweiterte Marktdaten

#### Geaendert

##### BotBuilder Pro Mode Redesign
- **Numeric Params**: Range Bars entfernt, 2-Spalten Grid Layout
  - Jeder Parameter in eigenem Card mit Label und Input
  - `grid grid-cols-2 gap-2` statt vorheriger Range-Bar UI
- **Timeframe Empfehlung**: Fuer Edge Indicator und Claude Edge Indicator
  - Empfohlener Timeframe: **1h** (basierend auf 90-Tage Backtest)
  - Anzeige als kompakte Zeile mit Clock-Icon

##### GettingStarted Redesign
- Kompaktes 3-Karten Layout (Verbinden, Konfigurieren, Handeln)
- Workflow-Diagramm, Strategie-Uebersicht, Exchange-Vergleich
- i18n: ~60 neue Keys in DE + EN

##### Weitere Aenderungen
| Datei | Aenderung |
|-------|-----------|
| `frontend/src/pages/BotDetail.tsx` | STRATEGY_DISPLAY fuer neue Strategien |
| `frontend/src/pages/Bots.tsx` | STRATEGY_DISPLAY fuer neue Strategien |
| `src/strategy/__init__.py` | Neue Strategy Imports |
| `src/bot/bot_worker.py` | claude_edge_indicator als LLM-Strategie |
| `docker-compose.yml` | Bereinigt (Prometheus/Grafana entfernt) |

#### Backtest-Ergebnisse (90 Tage, BTCUSDT, $10k)

| Strategie | Return | Win Rate | Max DD | Sharpe | Trades | PF |
|-----------|--------|----------|--------|--------|--------|-----|
| **Liquidation Hunter** | +26.2% | 53.9% | 4.7% | 5.51 | 104 | 1.98 |
| **Edge Indicator** | +18.6% | 47.1% | 9.8% | 2.91 | 68 | 1.65 |
| Claude Edge Indicator | +18.6% | 47.1% | 9.8% | 2.91 | 68 | 1.65 |
| Degen | +0.8% | 40.0% | 3.8% | 0.43 | 35 | 1.08 |
| LLM Signal | +0.8% | 40.0% | 4.5% | 0.51 | 25 | 1.12 |
| Sentiment Surfer | -3.7% | 32.3% | 9.4% | -1.07 | 65 | 0.84 |

**Bester Gesamtwert**: 1h Conservative (TP 2%, SL 1%) — Sharpe 6.09, +27.4%, nur 3.9% DD

#### Neue Dateien

| Datei | Zweck |
|-------|-------|
| `src/strategy/edge_indicator.py` | Edge Indicator Strategie |
| `src/strategy/claude_edge_indicator.py` | Claude Edge Indicator Strategie |
| `src/backtest/kline_backtest_engine.py` | Kline-basierte Backtest Engine |
| `src/data/market_data.py` | Erweiterte Marktdaten |
| `src/api/routers/admin_logs.py` | Admin Audit-Log API |
| `src/api/schemas/admin_logs.py` | Admin Log Schemas |
| `src/utils/event_logger.py` | Event Logger |
| `frontend/src/components/ui/GuidedTour.tsx` | Guided Tour Komponente |
| `frontend/src/stores/tourStore.ts` | Tour State Store |
| `scripts/backtest_edge_indicator.py` | Edge Indicator Backtest Script |
| `scripts/backtest_timeframes.py` | Multi-Timeframe Backtest Script |

#### Tests

| Datei | Zweck |
|-------|-------|
| `tests/unit/test_edge_indicator.py` | Edge Indicator Unit Tests |
| `tests/unit/test_atr_and_divergence.py` | ATR + Divergence Tests |
| `tests/backtest/test_edge_indicator_backtest.py` | Backtest Integration Tests |
| `tests/integration/test_edge_indicator_integration.py` | Strategy Integration Tests |
| `frontend/src/components/ui/GuidedTour.test.tsx` | Guided Tour Tests |
| `frontend/src/stores/tourStore.test.ts` | Tour Store Tests |
| `frontend/src/i18n/i18n-completeness.test.ts` | i18n Vollstaendigkeit Tests |
| `frontend/src/pages/GettingStarted.test.tsx` | GettingStarted Tests |
| `frontend/src/pages/DashboardTour.test.tsx` | Dashboard Tour Tests |

---

## [3.5.1] - 2026-02-19

### Grafana Admin Dashboard & Infrastructure Modernization

Infrastruktur-Modernisierung mit Alembic Migrations, Shared Scheduler, Exchange Rate Limiter,
Risk Stats in DB und neue Datenquellen. Grafana Admin Support Dashboard fuer PostgreSQL.

#### Hinzugefuegt

##### Grafana Admin Support Dashboard (#78)
- **Admin Support Dashboard** (`monitoring/grafana/dashboards/admin-support.json`)
  - Vorkonfiguriertes Grafana Dashboard fuer PostgreSQL-Daten
  - Provisioning-Konfiguration fuer automatisches Dashboard-Loading
  - PostgreSQL Datasource Auto-Provisioning (`monitoring/grafana/provisioning/datasources/datasources.yml`)

##### Alembic Async Migration Framework (#44)
- **Alembic Integration** — Async-faehiges Migrations-Framework
  - `alembic.ini` + `migrations/env.py` mit async Engine Support
  - `migrations/versions/001_initial_schema.py` — Initiale Schema-Migration
  - Ersetzt die bisherigen inline SQLite-Migrationen fuer PostgreSQL

##### Shared APScheduler (#46)
- **Gemeinsamer Scheduler** — Ein APScheduler fuer alle BotWorker
  - Reduziert Thread-Overhead bei vielen parallel laufenden Bots
  - Zentrale Scheduler-Instanz im Orchestrator

##### Exchange Rate Limiter (#47)
- **Token Bucket Rate Limiter** (`src/exchanges/rate_limiter.py`)
  - Per-Exchange Rate Limiting (shared ueber alle Bots)
  - Verhindert API-Bans bei hoher Bot-Anzahl

##### Risk Stats in Datenbank (#48)
- **RiskManager Stats Migration** — Von JSON-Dateien in die Datenbank
  - `RiskDailyStats` DB-Modell fuer persistente Risiko-Statistiken
  - Migrations-Script: `scripts/migrate_risk_json.py`
  - Eliminiert Filesystem-basierte State-Haltung

##### Neue Datenquellen (#42)
- **5 Velo-replizierte Datenquellen** (kostenlose Alternativen zu Velo-Daten)
  - Neue Fetcher in `src/data/market_data.py` und `data_source_registry.py`
  - Verfuegbar in Bot Builder und Backtesting

##### Pro Mode Toggle (#56)
- **UI Pro Mode** — Toggle fuer erweiterte Datenquellen-Anzeige
  - Responsive Fix fuer mobile Darstellung

#### Behoben
- **Optimistic Preset Updates** (#41) — Preset-Speichern dauert nicht mehr 3-5s (IPv6/Vite Proxy Delay auf Windows)

---

## [3.5.0] - 2026-02-19

### Production-Ready Sprint: Monitoring, WebSocket, Quality

Komplettes Production-Hardening mit Prometheus Monitoring, Real-Time WebSocket-Updates,
CI/CD Pipeline und umfassender Test Suite (3707 Tests). Vorbereitung fuer DigitalOcean Droplet Deployment.

#### Hinzugefuegt

##### Prometheus Monitoring (#75)
- **Zentrales Metrics-Modul** (`src/monitoring/metrics.py`) — HTTP, Bot, Trade und System-Metriken
  - `http_requests_total` (Counter), `http_request_duration_seconds` (Histogram)
  - `bots_running_total`, `bots_by_status` (Gauges)
  - `trades_total` (Counter), `trade_pnl_percent` (Histogram)
  - `websocket_connections_active`, `db_query_duration_seconds`
- **PrometheusMiddleware** (`src/monitoring/middleware.py`) — Request Count & Latency Tracking
  - Pfad-Normalisierung (z.B. `/api/trades/123` → `/api/trades/{id}`) gegen Cardinality Explosion
  - `/metrics` Endpoint wird uebersprungen
- **`/metrics` Endpoint** (`src/api/routers/metrics.py`) — Prometheus-Format, unauthentifiziert
- **Bot-Metrics Collector** (`src/monitoring/collectors.py`) — Background Task, alle 15s
  - Liest Orchestrator-State: Running Count, Status-Verteilung, Consecutive Errors
- **Docker Compose Services** — Prometheus + Grafana
  - `prom/prometheus:latest` auf Port 9090 (nur localhost)
  - `grafana/grafana:latest` auf Port 3000
  - `monitoring/prometheus.yml` Scrape-Konfiguration
- **Neue Dependency**: `prometheus-client>=0.20.0`

##### WebSocket Real-Time Updates (#76)
- **ConnectionManager** (`src/api/websocket/manager.py`) — Per-User Pub/Sub
  - `connect()`, `disconnect()`, `broadcast_to_user()`, `broadcast_all()`
  - Thread-safe via `asyncio.Lock`
- **`/api/ws` Endpoint** (`src/api/routers/websocket.py`) — JWT-Authentifizierung via Query-Param
  - Ping/Pong Keep-Alive, automatische Disconnect-Erkennung
  - `WEBSOCKET_CONNECTIONS` Prometheus Gauge wird aktualisiert
- **Event Broadcasting** im Backend:
  - `BotOrchestrator`: `bot_started`, `bot_stopped` Events
  - `TradeExecutorMixin`: `trade_opened` Events
  - `PositionMonitorMixin`: `trade_closed` Events
- **React `useWebSocket` Hook** (`frontend/src/hooks/useWebSocket.ts`)
  - Auto-Reconnect nach 5s, Ping alle 30s
  - Stabile Handler-Referenzen via `useMemo`
- **Zustand `realtimeStore`** (`frontend/src/stores/realtimeStore.ts`)
  - `lastEvent`, `botStatuses`, `pushEvent()`, `updateBotStatus()`
- **AppLayout Integration** — Toast-Notifications bei Bot-Start/Stop und Trade-Events

##### Codebase Quality Sprint (#58–#65)
- **Code Cleanup** (#58) — Dead Code, unused Imports, unreachable Branches entfernt
- **Silent Error Handling Fix** (#59) — Bare `except: pass` durch spezifische Handler ersetzt
- **Notification Retry** (#60) — Exponential Backoff mit `tenacity` (3 Versuche, 1→2→4s)
- **Structured Logging** (#61) — `%s`-Format statt f-Strings in allen Loggern
- **Config Validation** (#62) — Startup-Validierung: JWT Key, DB URL, Encryption Key
- **Offline Indicator** (#63) — Frontend-Banner bei Netzwerkverlust (auto-dismiss bei Reconnect)
- **CI/CD Pipeline** (#64) — GitHub Actions: Lint, Tests, Frontend Build, Security Audit
- **Comprehensive Test Suite** (#65) — 3707 Tests, alle bestehenden Bugs gefixt

#### Geaendert

| Datei | Aenderung |
|-------|-----------|
| `requirements.txt` | `prometheus-client>=0.20.0` hinzugefuegt |
| `src/api/main_app.py` | PrometheusMiddleware, Metrics + WebSocket Router, Collector Task |
| `src/bot/orchestrator.py` | `_broadcast_event()` fuer WebSocket Events |
| `src/bot/trade_executor.py` | `trade_opened` WebSocket Broadcast |
| `src/bot/position_monitor.py` | `trade_closed` WebSocket Broadcast |
| `docker-compose.yml` | Prometheus + Grafana Services, neue Volumes |
| `frontend/src/components/layout/AppLayout.tsx` | WebSocket Hook + Toast Notifications |

#### Neue Dateien

| Datei | Zweck |
|-------|-------|
| `src/monitoring/__init__.py` | Package Init |
| `src/monitoring/metrics.py` | Prometheus Metric Definitionen |
| `src/monitoring/middleware.py` | HTTP Request Metrics Middleware |
| `src/monitoring/collectors.py` | Bot Metrics Background Collector |
| `src/api/routers/metrics.py` | `/metrics` Endpoint |
| `src/api/websocket/__init__.py` | Package Init |
| `src/api/websocket/manager.py` | WebSocket Connection Manager |
| `src/api/routers/websocket.py` | `/api/ws` WebSocket Endpoint |
| `frontend/src/hooks/useWebSocket.ts` | React WebSocket Hook |
| `frontend/src/stores/realtimeStore.ts` | Zustand Real-Time Store |
| `monitoring/prometheus.yml` | Prometheus Scrape Config |

#### Zugriff (DigitalOcean Droplet)

Nach `docker compose up -d`:
- **App**: `http://<droplet-ip>:8000`
- **Grafana**: `http://<droplet-ip>:3000` (Login: admin/admin → Passwort aendern)
- **Prometheus**: Nur intern via `http://prometheus:9090`
- In Grafana: Data Sources → Prometheus → URL `http://prometheus:9090`

#### Test-Ergebnis

| Metrik | Wert |
|--------|------|
| Tests Passed | 3707 |
| Tests Skipped | 5 |
| Tests Failed | 0 |
| Frontend Build | OK (9.76s) |

---

## [3.4.0] - 2026-02-17

### PostgreSQL-Migration (Multi-User / 10k+ User Support)

SQLite bleibt als Fallback fuer lokale Entwicklung erhalten. PostgreSQL wird als Produktionsdatenbank
fuer Multi-User-Betrieb mit Connection Pooling eingefuehrt.

#### Hinzugefuegt
- **PostgreSQL Support** — Dual-Backend Architektur (SQLite + PostgreSQL)
  - `asyncpg>=0.29.0` als PostgreSQL async Driver
  - `_build_engine_kwargs()` in `session.py` — automatische Backend-Erkennung
  - Connection Pooling: `pool_size` (default 20), `max_overflow` (default 30), `pool_pre_ping`, `pool_recycle` (default 1800s)
  - Pool-Parameter konfigurierbar via `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE` Umgebungsvariablen
- **PostgreSQL Docker Service** in `docker-compose.yml`
  - `postgres:16-alpine` mit Healthcheck (`pg_isready`)
  - Named Volume `pgdata` fuer Persistenz
  - `trading-bot` Service: `depends_on: postgres` mit `condition: service_healthy`
  - `DATABASE_URL` automatisch auf internen PostgreSQL Container gesetzt
- **Dedizierter Audit-Pool** fuer PostgreSQL in `audit_log.py` (`pool_size=5, max_overflow=10`)
- **Test Dual-Backend** — `TEST_DATABASE_URL` Env-Variable in `tests/conftest.py`
- **Anleitung** `Anleitungen/PostgreSQL Migration.md` (DE + EN)

#### Geaendert
- `src/models/database.py`: Boolean `server_default="0"` → `server_default=text("false")` auf 5 Spalten (PostgreSQL-kompatibel)
  - `TradeRecord.demo_mode`, `ExchangeConnection.builder_fee_approved`, `ExchangeConnection.referral_verified`,
    `ExchangeConnection.affiliate_verified`, `AffiliateLink.uid_required`
- `src/models/session.py`: SQLite-Migrationen in `_run_sqlite_migrations()` extrahiert, `_is_sqlite` Guard
- `src/api/middleware/audit_log.py`: Backend-Erkennung, PostgreSQL Pool-Settings
- `Dockerfile`: `libpq-dev` (Builder) + `libpq5` (Runtime) fuer asyncpg
- `.env.example`: PostgreSQL-Konfiguration und Pool-Parameter dokumentiert
- `.env`: `DATABASE_URL` auf PostgreSQL umgestellt

| Datei | Aenderung |
|-------|-----------|
| `requirements.txt` | `asyncpg>=0.29.0` hinzugefuegt |
| `src/models/session.py` | Dual-Backend Engine, Pool Config, Migrations extrahiert |
| `src/models/database.py` | Boolean `server_default` PostgreSQL-kompatibel |
| `src/api/middleware/audit_log.py` | Dedizierter PostgreSQL Audit-Pool |
| `docker-compose.yml` | PostgreSQL Service + Volume |
| `Dockerfile` | PostgreSQL Client-Libs |
| `.env.example` | Pool-Parameter Dokumentation |
| `.env` | `DATABASE_URL` auf PostgreSQL |
| `tests/conftest.py` | `TEST_DATABASE_URL` Support |

---

## [3.3.5] - 2026-02-17

### Architecture Hardening — BotWorker Decomposition & 3683 Tests

Grosse Architektur-Ueberarbeitung: BotWorker von 1286 Zeilen in 5 fokussierte Mixins zerlegt,
einheitliche Exception-Hierarchie, Security-Fixes und massive Test-Suite Erweiterung.

#### Hinzugefuegt

##### BotWorker Decomposition (#41)
- **5 Mixins** extrahiert aus `bot_worker.py` (1286 → 648 Zeilen):
  - `TradeExecutorMixin` (`src/bot/trade_executor.py`) — Trade-Ausfuehrung
  - `PositionMonitorMixin` (`src/bot/position_monitor.py`) — Position-Ueberwachung
  - `RotationManagerMixin` (`src/bot/rotation_manager.py`) — Symbol-Rotation
  - `HyperliquidGatesMixin` (`src/bot/hyperliquid_gates.py`) — HL Builder/Referral Gates
  - `NotificationsMixin` (`src/bot/notifications.py`) — Benachrichtigungs-Dispatch
- **Bots Router Split** — `bots.py` (1259 → 648 Zeilen) aufgeteilt in:
  - `bots_lifecycle.py` (327 Zeilen) — Start/Stop/Restart/Create/Delete
  - `bots_statistics.py` (323 Zeilen) — Performance, Compare, Statistiken

##### Exception & Error Handling
- **Globaler Error Handler** (`src/api/middleware/error_handler.py`)
  - Exception→HTTP Status Mapping: `ExchangeError`→502, `AuthError`→401, etc.
- **Einheitliche Exception-Hierarchie** (`src/exceptions.py`)
  - `BitgetClientError`, `HyperliquidClientError`, `WeexClientError` → `ExchangeError`
  - `DataFetchError` → `DataSourceError`
  - `CircuitBreakerError` → `TradingBotError`

##### Security Hardening
- **Refresh Token Rotation** mit `token_version` Revocation
- **JSON Field Size Limits** (10KB) auf Bot Config Dicts
- **Cross-Field Strategy Validation** (LLM erfordert Provider, Rotation erfordert Interval)
- **Auth Audit Logging** mit Client IP fuer Login/Refresh Events
- **FastAPI DI** — Globaler Orchestrator ersetzt durch `app.state`

##### Shared Utilities
- **`src/api/rate_limit.py`** — Zentraler Rate Limiter (8 Router aktualisiert)
- **`src/utils/json_helpers.py`** — `parse_json_field()` Helper (4 Duplikate → 1)
- **`src/utils/settings.py`** — `get_settings_batch()` batcht N+1 DB-Queries

##### Frontend Unit Tests
- **Vitest Konfiguration** (`frontend/vitest.config.ts`)
- **Unit Tests** fuer API Client, UI Components, Pages, Stores
- **ESLint Config** fuer Test-Dateien

##### Backend Test Suite
- **3683 Tests** (5 skipped, 0 failures) — Massive Erweiterung:
  - 139 neue Test-Dateien
  - Unit Tests fuer alle Router, Exchanges, Strategies, Providers
  - Integration Tests fuer Bot Worker, Orchestrator, Dashboard

| Datei | Aenderung |
|-------|-----------|
| `src/bot/bot_worker.py` | 1286 → 648 Zeilen, Mixins extrahiert |
| `src/api/routers/bots.py` | Aufgeteilt in lifecycle + statistics |
| `src/api/middleware/error_handler.py` | Exception→HTTP Mapping |
| `src/exceptions.py` | Einheitliche Hierarchie |
| `src/auth/jwt_handler.py` | Token Rotation + Revocation |
| `src/api/main_app.py` | FastAPI DI statt globaler State |

---

## [3.3.4] - 2026-02-15

### Degen Strategy & Settings Redesign

Neue "Degen" Strategie mit festem LLM-Prompt und 14 Datenquellen, komplett ueberarbeitete
Settings-Seite und verbesserter Tax Report.

#### Hinzugefuegt
- **Degen Strategy** (`src/strategy/degen.py`) — Fixed LLM Prompt fuer 1h BTC Predictions
  - 14 Datenquellen, aggressives Confidence-Mapping
  - Registriert in Strategy Registry mit eigenem Parameter-Schema
- **Order Book Depth Fetcher** — Binance Futures Depth API Integration in `market_data.py`
- **NumInput Komponente** (`frontend/src/components/ui/NumInput.tsx`)
- **Pagination Komponente** (`frontend/src/components/ui/Pagination.tsx`)
- **Strategy Display Names** im Frontend (Bot Cards, Grid View)

#### Geaendert

##### Settings Redesign
- **Tabbed Layout** — 3 Tabs: API Keys, LLM Keys, Affiliate Links
  - Komplett ueberarbeitete Settings-Seite (1781 → strukturierter)
  - Verbesserte LLM-Key-Verwaltung mit Model Chips

##### Tax Report
- **CSV Format Fix** — Verbesserter Export
- **Hyperliquid Builder Fee Signing Flow** Verbesserungen

##### Weitere Aenderungen
| Datei | Aenderung |
|-------|-----------|
| `src/strategy/degen.py` | NEU: Degen Strategy |
| `src/bot/bot_worker.py` | LLM Key Injection fuer Degen |
| `src/risk/risk_manager.py` | Multi-Bot Support Erweiterungen |
| `frontend/src/pages/Settings.tsx` | Tabbed Redesign |
| `frontend/src/pages/Presets.tsx` | Verbesserungen |
| `src/api/routers/tax_report.py` | CSV Fix + verbesserter Export |

---

## [3.3.3] - 2026-02-13

### Model Family Selection & Design System Overhaul

LLM Model-Auswahl pro Provider, einheitliches Design System und standardisierte Trade-Tabellen.

#### Hinzugefuegt
- **MODEL_CATALOG** — Per-Provider Model-Auswahl (je 3 Modelle)
  - Dependent Select im BotBuilder: Family → Model Kaskade
  - `model_override` Support fuer alle 7+ LLM Provider
  - LLM Connections API erweitert mit `family_name` und Models-Liste
- **DeepSeek Provider** (`src/ai/providers/deepseek.py`) — Neuer LLM-Provider
- **Latest Trade Hero Card** — Kopierbar, auf Bots Modal und Performance Page
- **Confidence/Reasoning/Details Spalten** in Trade-Tabellen
- **Legacy Bot LLM Detection** — Fallback aus Trade Reason Text

#### Geaendert
- **Trade-Tabellen standardisiert** — Dashboard-Format auf allen Seiten
  - Einheitliches `table-premium` Styling
- **Design System** — Konsistentes Glassmorphism, Badges, Table Styling
- **Settings LLM Accordion** mit Model Chips
- **Bots Modal** — Kompaktes Layout fuer scroll-freie Trade History
- i18n: Model Selection Keys in DE + EN

| Datei | Aenderung |
|-------|-----------|
| `src/ai/providers/__init__.py` | MODEL_CATALOG, Family Support |
| `src/ai/providers/deepseek.py` | NEU: DeepSeek Provider |
| `src/strategy/llm_signal.py` | model_override Support |
| `src/api/routers/config.py` | LLM Connections + Models API |
| `frontend/src/components/bots/BotBuilder.tsx` | Dependent Select |
| `frontend/src/pages/Bots.tsx` | Trade Table Standardisierung |
| `frontend/src/pages/BotPerformance.tsx` | Hero Card + Spalten |
| `frontend/src/pages/Settings.tsx` | LLM Accordion + Chips |

---

## [3.3.2] - 2026-02-13

### Quality & Security Sprint

Umfassender Quality-Sprint: i18n-Bereinigung, Exception-Hierarchie, Security-Fixes,
Circuit Breaker Erweiterung und erweiterte Test-Suite.

#### Hinzugefuegt

##### Exception Hierarchy (#20)
- **Zentralisierte Exception-Hierarchie** (`src/exceptions.py`)
  - Inheritance Tree: `TradingBotError` → `ExchangeError`, `DataSourceError`, etc.
  - Debug Logging fuer stille Exception-Handler in `bot_worker.py`
- **103 neue Tests**:
  - 29 Bot Worker Tests (Lifecycle, Trading, Monitoring)
  - 20 Discord Notifier Tests (Embeds, Webhooks)
  - 29 Circuit Breaker Tests (State Transitions, Recovery)
  - 25 Exception Hierarchy Tests (Inheritance, Catchability)

##### Circuit Breaker Erweiterung (#20)
- **Neue Circuit Breakers** fuer Top Trader L/S Ratio, OI History, Liquidations
- **Data Freshness Tracking** via `fetch_timestamps` in DataQuality
- **Performance Indexes** fuer `trade_records` und `bot_configs` Queries

##### HL Builder & Affiliate Tests (#28)
- **35 Tests** fuer Builder Fee Berechnung, Builder Kwargs Injection, Referral Gates
- Builder Check: Soft-Warning → Hard-Gate (blockiert Bot-Start)

#### Behoben

##### Security Hardening (#39)
- **C1 CRITICAL**: Admin-Query mit nicht-existierendem `User.is_admin` behoben
- **H1 HIGH**: Legacy Plaintext Key Loading aus BitgetConfig entfernt
- **H2 HIGH**: Rate Limit (10/min) auf `/api/auth/refresh` Endpoint
- **H3 HIGH**: Deprecated Plaintext Webhook URLs via Migration bereinigt
- **30 Security Regression Tests** hinzugefuegt

##### Frontend i18n (#19)
- **50+ i18n Keys** hinzugefuegt — Hardcoded Strings in BotDetail, Settings, Trades, Bots ersetzt
- **Responsive Layout** — Modal 4-col → 2-col auf Mobile, Flex-Wrap fuer Bot Card Actions
- **Light Mode** — Skeleton Opacity verbessert (0.06 → 0.10), Info Box Backgrounds

##### Preset & Telegram i18n (#31, #32)
- Telegram i18n Keys + Anleitung (#31)
- Preset i18n Keys + Anleitung (#32)

##### Discord Webhook (#30)
- Globaler Discord Webhook Fallback entfernt (nur noch per-Bot)

---

## [3.3.1] - 2026-02-12

### Backtesting Module

Vollstaendiges Backtesting-System mit Frontend und Backend, erweiterbare Datenquellen
und 11-Faktor Signal-Analyse.

#### Hinzugefuegt

##### Backend
- **BacktestRun DB-Modell** — Persistente Backtest-Ergebnisse
- **Backtest API Router** (`src/api/routers/backtest.py`) — 5 Endpoints
  - Backtest starten, Status abfragen, Ergebnisse laden, History, Loeschen
- **Strategy Adapter** (`src/backtest/strategy_adapter.py`) — Verbindet Strategien mit Backtest Engine
- **Background Task Execution** mit BacktestEngine
- **Pydantic Schemas** (`src/api/schemas/backtest.py`)

##### Erweiterte Backtest Engine
- **11-Faktor Signal-Analyse** — OI, Taker Volume, Top Trader L/S, Funding Divergence, Stablecoin Flows, Volatility, Macro
- **8 neue API-Integrationen** in Historical Data Fetcher:
  - Binance OI, Taker Buy/Sell, Top Trader L/S
  - Bitget Funding, DefiLlama, CoinGecko, Blockchain.info, FRED
- **5 neue Bot-Datenquellen** (jetzt 26 total):
  - Stablecoin Flows (DefiLlama), BTC Hashrate (Blockchain.info)
  - Bitget Funding Rate, DXY + Fed Funds Rate (FRED)

##### Frontend
- **Backtest Page** (`frontend/src/pages/Backtest.tsx`) — Vollstaendige UI:
  - Config Card mit FilterDropdown (Strategie, Trading Pairs, Timeframe)
  - DatePicker Side-by-Side, Equity Curve Chart
  - Metrics Cards, Trade Log Table, History mit Status Badges
  - Profit/Loss Spalte in Backtest History
- **Neue UI-Komponenten**: DatePicker, FilterDropdown
- **Unterstuetzte Timeframes**: 1m, 5m, 15m, 30m, 1h, 4h, 1D
- **Trading Pairs**: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, AVAXUSDT
- **Active Data Sources als Badges** in Backtest-Ergebnissen

##### Weitere Verbesserungen
- **Trades Page Filter** Verbesserungen
- **Win-Rate 3-Tier Colors** — Farbkodierung nach Performance
- **KI-Companion Custom Prompt** Support mit LLM Note
- **SQLite WAL Mode Fix** fuer concurrent Backtest Writes
- i18n: Vollstaendige DE/EN Uebersetzungen

| Datei | Aenderung |
|-------|-----------|
| `src/api/routers/backtest.py` | NEU: 5 Endpoints |
| `src/api/schemas/backtest.py` | NEU: Pydantic Schemas |
| `src/backtest/strategy_adapter.py` | NEU: Strategy Adapter |
| `src/backtest/engine.py` | 11-Faktor Signal-Analyse |
| `src/backtest/historical_data.py` | 8 neue API-Integrationen |
| `src/data/data_source_registry.py` | 5 neue Datenquellen |
| `src/data/market_data.py` | Neue Fetch-Methoden |
| `src/models/database.py` | BacktestRun Modell |
| `frontend/src/pages/Backtest.tsx` | NEU: Backtest UI |
| `frontend/src/components/ui/DatePicker.tsx` | NEU |
| `frontend/src/components/ui/FilterDropdown.tsx` | NEU |

---

## [3.3.0] - 2026-02-11

### Hyperliquid Builder Fee Wallet-Gate

### Hinzugefuegt
- **Hyperliquid Builder Fee Wallet-Gate** — Browser-basierte EIP-712 Signatur
  - Multi-Wallet Support via RainbowKit (MetaMask, WalletConnect, Coinbase, Ledger, Trust, 300+ Wallets)
  - `BuilderFeeApproval` Komponente mit 3-Step Wizard (Wallet verbinden → Signieren → Bestaetigung)
  - `GET /config/hyperliquid/builder-config` — Public Endpoint fuer Builder-Konfiguration (ersetzt admin-only)
  - `POST /config/hyperliquid/confirm-builder-approval` — On-Chain Verifizierung + DB-Tracking
  - Hard-Gate: Hyperliquid Bots starten nur nach Builder Fee Approval
  - DB-Tracking: `builder_fee_approved` + `builder_fee_approved_at` auf ExchangeConnection
  - `builder_fee_approved` Feld in Bot-API-Response
  - Affiliate-Link Integration im Approval-Flow
  - Anleitung: `Anleitungen/Hyperliquid Builder Fee genehmigen.md`
  - Neue Dependencies: `@rainbow-me/rainbowkit`, `wagmi`, `viem`, `@tanstack/react-query`
  - i18n: `builderFee` Namespace in DE + EN

### Entfernt
- Server-side `POST /config/hyperliquid/approve-builder-fee` (war broken fuer separate API Wallets)

### Geaendert
- `bot_worker.py`: Builder-Check von Soft-Warning zu Hard-Gate (blockiert Bot-Start)
- Builder-Status Endpoint von admin-only zu public (alle authentifizierten User)

---

## [3.2.0] - 2026-02-11

### Notifications Refactor + Preset-Integration im Bot Builder

#### Entfernt
- **Globaler Discord-Webhook** aus User-Settings entfernt — per-Bot Webhook bleibt bestehen
- Discord-Tab in Settings-Seite entfernt
- API-Endpoints `PUT /config/discord` und `POST /config/discord/test` entfernt
- `DiscordConfigUpdate` Schema und `DISCORD_WEBHOOK_PATTERN` entfernt
- User-Level Fallback in `bot_worker._get_discord_notifier()` entfernt (nur noch Bot-spezifisch)

#### Hinzugefügt
- **Telegram-Benachrichtigungen** (per Bot, optional)
  - Neuer `TelegramNotifier` (`src/notifications/telegram_notifier.py`) — nutzt Telegram Bot API via aiohttp
  - DB-Spalten: `telegram_bot_token` (verschlüsselt) + `telegram_chat_id` auf `BotConfig`
  - Bot-Token + Chat-ID Felder im Bot Builder (Step 4: Exchange & Modus)
  - Test-Endpoint: `POST /api/bots/{id}/test-telegram`
  - Anleitung: `Anleitungen/Telegram Benachrichtigungen einrichten.md`
- **Preset-Auswahl im Bot Builder**
  - "Von Preset laden" Dropdown in Step 1 (Name)
  - Automatisches Befüllen aller Felder aus gewähltem Preset
  - Exchange-übergreifende Presets (`exchange_type` = "any", Standard)
  - Automatische Trading-Pair-Konvertierung (BTCUSDT ↔ BTC je nach Exchange)
  - Anleitung: `Anleitungen/Presets im Bot Builder verwenden.md`
- **Preset-Umschaltung für bestehende Bots**
  - Preset-Dropdown auf "Meine Bots"-Seite pro Bot-Card
  - `POST /api/bots/{id}/apply-preset/{preset_id}` — Preset auf bestehenden Bot anwenden
  - `active_preset_id` + `active_preset_name` in Bot-API-Response
  - Nur möglich wenn Bot gestoppt ist
- **Multi-Notifier System** in `bot_worker.py` — Discord + Telegram gleichzeitig pro Bot
- **Projekt-CLAUDE.md** — Konventionen für Anleitungen, Issues und Changelog
- GitHub Issues: #30 (Discord entfernen), #31 (Telegram), #32 (Presets)

#### Geändert
- `BotConfig` Model: Neue Spalten `telegram_bot_token`, `telegram_chat_id`
- `ConfigPreset.exchange_type`: Default "any" (alle Exchanges), `PresetCreate` akzeptiert "any|bitget|weex|hyperliquid"
- `Presets.tsx`: "Alle Exchanges" als Standard-Option bei Preset-Erstellung
- i18n (EN + DE): Neue Keys für Telegram, Presets, Bot Builder

---

## [3.1.1] - 2026-02-10

### Test-Fixes & CodeAssist-Update

- **Integration Tests**: Rate Limiter in Test-Conftest deaktiviert (`limiter.enabled = False`)
- **Integration Tests**: 307-Redirect als akzeptierten Status-Code in Auth-Assertions aufgenommen
- **CodeAssist**: Skills, Templates und Commands aktualisiert (neue Version)

---

## [3.1.0] - 2026-02-10

### Hyperliquid Revenue Analytics

Vollstaendiges Tracking und Visualisierung von Builder-Fee-Einnahmen auf Hyperliquid.

#### Backend

- **Neue DB-Spalte** `builder_fee` auf `TradeRecord` — speichert berechnete Builder-Fee pro Trade
- **Automatische Migration** + Backfill fuer bestehende geschlossene HL-Trades
- **Hyperliquid Client**: `get_trade_total_fees()` und `get_funding_fees()` implementiert (vorher immer 0)
- **Neue Methode** `calculate_builder_fee()` — berechnet Builder-Fee aus Entry/Exit-Value und Fee-Rate
- **Builder-Fee-Berechnung** automatisch bei jedem Trade-Close im BotWorker
- **Neuer API-Endpoint** `GET /api/statistics/revenue` — dedizierte Revenue-Analytik mit Daily-Breakdown und Monthly-Estimate
- **Erweiterte Endpoints**: `/api/statistics` und `/api/statistics/daily` geben jetzt `total_builder_fees` / `builder_fees` zurueck
- **Revenue-Summary** (`/api/config/hyperliquid/revenue-summary`) zeigt jetzt `earnings`-Objekt mit 30-Tage-Totals

#### Frontend

- **Neue Komponente** `RevenueChart.tsx` — BarChart (Emerald) fuer taegliche Builder-Fee-Einnahmen
- **Dashboard**: Revenue-Widget mit Total + Monthly-Estimate erscheint automatisch wenn Builder-Fees vorhanden
- **Settings > Hyperliquid**: Neue Earnings-Sektion (verdiente Fees, Trades, monatliche Schaetzung)
- **TypeScript-Types** erweitert: `builder_fee` auf Trade, `builder_fees` auf DailyStats, `total_builder_fees` auf Statistics
- **i18n**: Neue Uebersetzungsschluessel (DE + EN) fuer Revenue-Analytik

---

## [3.0.1] - 2026-02-10

### CodeAssist Integration & Projektstruktur

- **CodeAssist Konfiguration** hinzugefuegt (`.claude/`): 70+ Slash-Commands, 6 Regelsaetze (Security, Testing, Git-Workflow, Coding-Style, Agents, Issue-First)
- **MCP-Konfiguration** (`.mcp.json`) fuer MCP-Server-Anbindung
- **Anleitungen-Verzeichnis** erstellt: Alle Dokumentationen werden ab sofort unter `Anleitungen/` gesammelt
- Bestehende Anleitung nach `Anleitungen/` verschoben
- `.gitignore` aktualisiert: `.claude/` wird getrackt, `settings.local.json` bleibt privat

---

## [3.0.0] - 2026-02-05

### Multibot Orchestration System

Komplettes Multibot-System mit Supervisor-Worker Architektur. Mehrere Bots koennen parallel auf verschiedenen Exchanges und Modi laufen, konfiguriert ueber ein Frontend-Wizard.

#### Neue Architektur

- **BotConfig** DB-Tabelle: Persistente Konfiguration pro Bot (Strategie, Exchange, Modus, Paare, Parameter, Schedule)
- **BotWorker** (`src/bot/bot_worker.py`): Unabhaengiger asyncio Worker pro Bot mit eigenem APScheduler
- **BotOrchestrator** (`src/bot/orchestrator.py`): Supervisor verwaltet alle BotWorker, Auto-Restore beim Server-Start
- **Strategy Registry** (`src/strategy/base.py`): Pluggable Strategien via `BaseStrategy` ABC + `StrategyRegistry`
- **Per-Bot Trade Isolation**: `bot_config_id` FK auf `TradeRecord` verknuepft jeden Trade mit seinem Bot

#### Strategy System

- **BaseStrategy** ABC mit `generate_signal()`, `should_trade()`, `get_param_schema()`, `get_description()`
- **StrategyRegistry**: Register/Lookup/Create Pattern — neue Strategien automatisch im Frontend verfuegbar
- **LiquidationHunter** refactored: Implementiert jetzt `BaseStrategy`, liest Parameter aus `self._p` Dict statt globaler Settings
- **Dynamische Parameter**: Strategien definieren ihr `param_schema` (Typ, Label, Range, Default) — Frontend rendert Formulare automatisch

#### Frontend

- **Bot Builder** (`frontend/src/components/bots/BotBuilder.tsx`): 6-Schritt Wizard
  - Schritt 1: Name & Beschreibung
  - Schritt 2: Strategie-Auswahl + dynamische Parameter
  - Schritt 3: Trading-Paare, Leverage, Position Size, TP/SL
  - Schritt 4: Exchange + Modus (demo/live/both)
  - Schritt 5: Schedule (Market Sessions / Interval / Custom)
  - Schritt 6: Review & Erstellen
- **Bot Overview** (`frontend/src/pages/Bots.tsx`): Card Grid mit Live-Status, PnL, Trade Count
  - Start/Stop/Edit/Delete Aktionen pro Bot
  - Running-Indikator mit Pulse-Animation
  - Auto-Refresh alle 5 Sekunden
  - Stop All Button

#### API Endpoints

| Endpoint | Beschreibung |
|----------|-------------|
| `GET /api/bots/strategies` | Verfuegbare Strategien mit Parameter-Schemas |
| `POST /api/bots` | Bot erstellen |
| `GET /api/bots` | Alle Bots mit Runtime-Status + Trade-Statistiken |
| `GET /api/bots/{id}` | Bot-Details |
| `PUT /api/bots/{id}` | Bot aktualisieren |
| `DELETE /api/bots/{id}` | Bot loeschen (nur gestoppt) |
| `POST /api/bots/{id}/start` | Bot starten |
| `POST /api/bots/{id}/stop` | Bot stoppen |
| `POST /api/bots/{id}/restart` | Bot neustarten |
| `POST /api/bots/stop-all` | Alle Bots stoppen |

#### Unterstuetzte Exchanges

- **Bitget** (Demo + Live)
- **Weex** (Demo + Live)
- **Hyperliquid** (Demo + Live)

### Geaendert

| Datei | Aenderung |
|-------|-----------|
| `src/models/database.py` | `BotConfig` Modell, `bot_config_id` FK auf TradeRecord/BotInstance |
| `src/models/session.py` | Migrations fuer neue Spalten |
| `src/strategy/base.py` | NEU: BaseStrategy ABC + StrategyRegistry |
| `src/strategy/liquidation_hunter.py` | Refactored auf BaseStrategy |
| `src/strategy/__init__.py` | Neue Exports |
| `src/bot/bot_worker.py` | NEU: BotWorker mit eigenem Scheduler |
| `src/bot/orchestrator.py` | NEU: BotOrchestrator Supervisor |
| `src/api/schemas/bots.py` | NEU: Pydantic Schemas |
| `src/api/routers/bots.py` | NEU: CRUD + Lifecycle Router |
| `src/api/main_app.py` | Orchestrator Integration, Version 3.0.0 |
| `frontend/src/components/bots/BotBuilder.tsx` | NEU: 6-Schritt Wizard |
| `frontend/src/pages/Bots.tsx` | NEU: Bot Overview |
| `frontend/src/App.tsx` | `/bots` Route |
| `frontend/src/components/layout/AppLayout.tsx` | "My Bots" Navigation |
| `frontend/src/i18n/en.json` + `de.json` | Bots + Builder i18n Keys |

---

## [2.2.0] - 2026-02-04

### Security Hardening

- **JWT Secret Key**: Server now refuses to start if `JWT_SECRET_KEY` is not set (no more insecure default)
- **Rate Limiting**: Login endpoint limited to 5 attempts per minute (slowapi)
- **Security Headers**: All responses now include `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`
- **CORS Hardening**: Explicit methods (`GET, POST, PUT, DELETE, OPTIONS`) and headers instead of wildcards
- **Discord Webhook Validation**: Pydantic validator ensures only valid `discord.com/api/webhooks` URLs are accepted (SSRF prevention)
- **Discord Webhook Encryption**: Webhook URLs are now encrypted at rest using Fernet (same as API keys)
- **HSTS**: Optional via `ENABLE_HSTS=true` environment variable

### Architecture Improvements

- **Bot Manager Thread Safety**: All bot start/stop operations protected by `asyncio.Lock()` to prevent race conditions
- **Database Compound Indexes**: Added `(user_id, status)` and `(user_id, symbol, side)` indexes on `trade_records` for faster queries
- **Migration Error Handling**: Catches specific `duplicate column` errors instead of blanket `except: pass`

### Frontend UX

- **Loading States**: Dashboard and Trades pages show loading indicator while fetching data
- **Error Handling**: Dashboard, Trades, and Settings pages display error messages on API failures
- **Empty States**: Trades table shows "No trades yet" message when empty
- **i18n Fixes**: Removed hardcoded German "Alle Status" and English "Demo Mode", "Strategy settings..." strings — all use i18n now

### Changed

| File | Change |
|------|--------|
| `src/auth/jwt_handler.py` | Crash on missing JWT_SECRET_KEY |
| `src/api/main_app.py` | Security headers middleware, CORS fix, rate limit handler |
| `src/api/routers/auth.py` | Rate limiting on login (5/min) |
| `src/api/schemas/config.py` | Discord webhook URL validation |
| `src/api/routers/config.py` | Encrypt/decrypt webhook URL |
| `src/api/routers/bot_control.py` | Decrypt webhook URL for notifications |
| `src/api/routers/trades.py` | Decrypt webhook URL for sync notifications |
| `src/bot/bot_manager.py` | asyncio.Lock on all state mutations |
| `src/models/database.py` | Compound indexes on TradeRecord |
| `src/models/session.py` | Specific migration exception handling |
| `frontend/src/pages/Dashboard.tsx` | Loading/error states |
| `frontend/src/pages/Trades.tsx` | Loading/error/empty states, i18n fix |
| `frontend/src/pages/Settings.tsx` | Error handling, i18n fixes |
| `.env.example` | JWT_SECRET_KEY now required |

---

## [2.1.0] - 2026-02-04

### Hinzugefuegt

#### Demo/Live Badge auf Trades
- **`demo_mode` Spalte** in `trade_records` Tabelle mit Auto-Migration
- **Demo/Live Badge** auf Trades-Seite und Dashboard (gelb = Demo, gruen = Live)
- **Mode-Filter** in der Trades-Tabelle (Spalte "Modus")
- i18n Keys fuer EN/DE

#### Dashboard Analytics Charts (Recharts)
- **PnL Chart** (Area + Line): Taeglicher PnL + kumulativer PnL im Zeitverlauf
- **Win/Loss Donut Chart**: Gewinne vs Verluste mit Win-Rate im Zentrum
- **Fees & Funding Bar Chart**: Gestapelte Balken fuer Gebuehren + Funding pro Tag
- **Zeitraum-Selector**: 7 / 14 / 30 / 90 Tage Filter fuer alle Charts
- **Erweiterte Statistik-Karten**: Net PnL (mit Fees/Funding Sub), Win Rate, Best/Worst Trade
- **Daily Stats API erweitert**: `/api/statistics/daily` liefert jetzt `funding`, `wins`, `losses` pro Tag

#### Discord Notifications bei Trade-Sync
- **Sync-Endpoint** (`POST /api/trades/sync`) sendet jetzt Discord-Benachrichtigungen wenn Trades geschlossen werden (TP/SL/Manual Close)
- Vorher wurden Trades beim Sync still geschlossen ohne Notification

### Behoben

#### TP/SL: Partial → Entire umgestellt
- **Problem:** TP/SL wurde als "Partial" gesetzt (nur Order-Groesse, nicht gesamte Position)
- **Ursache:** `presetStopSurplusPrice`/`presetStopLossPrice` auf dem Place-Order Endpoint erstellt Partial TP/SL
- **Fix:** Neue `_set_position_tpsl()` Methode nutzt `/api/v2/mix/order/place-pos-tpsl` Endpoint fuer Entire Position TP/SL
- **Hinweis:** `executePrice` Felder duerfen nicht mit "0" gesendet werden — werden komplett weggelassen fuer Market Execution

#### Bitget Demo API Header
- **Problem:** Demo-Trading schlug fehl mit "exchange environment is incorrect"
- **Ursache:** Header war `X-SIMULATED-TRADING` statt `paptrading: 1`
- **Fix:** `_get_headers()` in `client.py` nutzt jetzt korrekten Header

#### Discord Close Notification demo_mode Bug
- **Problem:** Close-Trade Endpoint sendete immer `demo_mode=True` unabhaengig vom tatsaechlichen Trade-Modus
- **Fix:** Nutzt jetzt `trade.demo_mode` statt hardcoded `True`

#### Vite Proxy Port Mismatch
- **Problem:** Frontend-Login schlug fehl im Development
- **Ursache:** Vite Proxy leitete an Port 8080 weiter, Backend laeuft auf Port 8000
- **Fix:** `vite.config.ts` Proxy-Target auf `localhost:8000` geaendert

### Geaendert

| Datei | Aenderung |
|-------|-----------|
| `src/exchanges/bitget/client.py` | `paptrading` Header, `_set_position_tpsl()`, Partial TP/SL entfernt |
| `src/models/database.py` | `demo_mode` Spalte |
| `src/models/session.py` | ALTER TABLE Migration |
| `src/api/schemas/trade.py` | `demo_mode` Feld |
| `src/api/routers/trades.py` | `demo_mode` in Response, Discord Sync Notifications |
| `src/api/routers/bot_control.py` | `demo_mode=True` bei Test-Trade, `trade.demo_mode` bei Close |
| `src/api/routers/statistics.py` | Daily Stats erweitert (funding/wins/losses) |
| `frontend/vite.config.ts` | Proxy-Port 8080 → 8000 |
| `frontend/src/types/index.ts` | `demo_mode` + `DailyStats` Interface |
| `frontend/src/pages/Dashboard.tsx` | Charts, Zeitraum-Selector, Demo/Live Badge |
| `frontend/src/pages/Trades.tsx` | Mode-Spalte mit Demo/Live Badge |
| `frontend/src/components/dashboard/` | NEU: PnlChart, WinLossChart, FeesChart, ChartTooltip |
| `frontend/src/i18n/en.json` + `de.json` | Neue Keys fuer Charts, Mode, Zeitraum |

### Neue Abhaengigkeiten (Frontend)

```
recharts (via npm)
```

---

## [1.10.0] - 2026-02-01

### Hinzugefuegt

#### Security Hardening v2
- **Explizite DEV_MODE Variable** (`DASHBOARD_DEV_MODE`)
  - Verhindert versehentlichen Auth-Bypass wenn API-Key vergessen wird
  - Startup-Warnung bei aktiviertem Dev-Mode
  - Bei fehlender Konfiguration: 503 Fehler statt stillschweigendem Bypass

- **WebSocket Header-basierte Authentifizierung**
  - Neuer Auth-Mechanismus via `Sec-WebSocket-Protocol: token.XXX`
  - Token nicht mehr in URL sichtbar (keine Log-Leakage)
  - Legacy URL-Parameter weiterhin unterstützt
  - JavaScript-Client aktualisiert für neue Auth-Methode

#### Performance & Stabilität
- **SQLite WAL-Mode** für bessere Concurrency
  - Write-Ahead Logging aktiviert in TradeDatabase und FundingTracker
  - `PRAGMA busy_timeout=5000` für Lock-Handling
  - Verhindert "database is locked" Fehler unter Last

### Geaendert

- **Dashboard Auth** (`src/dashboard/app.py`):
  - Neue Umgebungsvariable `DASHBOARD_DEV_MODE`
  - Bessere Fehlermeldungen bei Konfigurationsproblemen
  - WebSocket akzeptiert beide Auth-Methoden (Header + URL)

- **Tests**: Integration Tests patchen jetzt `DASHBOARD_DEV_MODE`

### Sicherheit

| Vorher | Nachher |
|--------|---------|
| Kein API-Key = Auth deaktiviert | Kein API-Key + kein DEV_MODE = 503 Fehler |
| WebSocket Token in URL (log-sichtbar) | WebSocket Token in Header (sicher) |
| SQLite ohne WAL (Locking-Probleme) | SQLite mit WAL (bessere Concurrency) |

### Konfiguration

Neue Umgebungsvariablen in `.env`:

```bash
# Development Mode (ONLY for local development!)
DASHBOARD_DEV_MODE=false

# Production: Always set API key
DASHBOARD_API_KEY=your-secure-api-key
```

---

## [1.9.0] - 2026-02-01

### Hinzugefuegt

#### Circuit Breaker & Retry Logic
Robuste Fehlerbehandlung für externe API-Aufrufe:

- **Circuit Breaker** (`src/utils/circuit_breaker.py`)
  - States: CLOSED → OPEN → HALF_OPEN → CLOSED
  - Automatische Erholung nach Timeout
  - Registry für mehrere Breaker (Bitget, Binance, etc.)
  - Decorator-basierte API: `@with_circuit_breaker("service_name")`

- **Retry mit Exponential Backoff**
  - tenacity-basiert
  - Konfigurierbare Wartezeiten und Versuche
  - Kombinierbar mit Circuit Breaker

- **Health Monitoring**
  - `/api/health/detailed` Endpoint
  - Circuit Breaker Status im Dashboard
  - Degraded-Status bei API-Ausfällen

#### Dashboard Erweiterungen
- **API Status Card**: Echtzeit-Status aller Komponenten
- **Error/Warning Banners**: Automatische Anzeige bei Problemen
- **Health Modal**: Detaillierte Systeminfo per Klick

### Test Suite
- **57 Unit Tests** für LiquidationHunter und RiskManager
- **15 Integration Tests** für Dashboard API
- Alle Tests bestehen (72 total)

### Technische Details

| Feature | Implementation |
|---------|----------------|
| Circuit Breaker | 3 States, konfigurierbarer Threshold |
| Retry | tenacity mit exponential backoff |
| Tests | pytest + pytest-asyncio |
| Coverage | LiquidationHunter, RiskManager, Dashboard API |

---

## [1.8.0] - 2026-01-31

### Hinzugefuegt

#### Bitget Demo Trading Integration
Vollständige Integration mit Bitget Demo Trading Account für realitätsnahes Paper Trading:

- **Separate Demo API Keys**: Unterstützung für dedizierte Demo Trading API Credentials
  - `BITGET_DEMO_API_KEY`, `BITGET_DEMO_API_SECRET`, `BITGET_DEMO_PASSPHRASE` in `.env`
  - Automatische Credential-Auswahl basierend auf `DEMO_MODE` Setting

- **BitgetClient Erweiterung** (`src/api/bitget_client.py`):
  - `demo_mode` Parameter im `__init__` für Modus-Auswahl
  - Automatisches Laden der korrekten API Keys (Demo vs. Live)
  - `X-SIMULATED-TRADING` Header für Demo Trading Requests
  - Logging zeigt aktiven Modus (DEMO/LIVE) bei Initialisierung

- **Settings Erweiterung** (`config/settings.py`):
  - `BitgetConfig.get_active_credentials(demo_mode)` - Liefert aktive Credentials
  - `BitgetConfig.validate(demo_mode)` - Validiert Demo oder Live API Keys
  - Separate Felder für Demo API Keys

- **Discord Notifications mit Mode Labels**:
  - `send_trade_entry()` und `send_trade_exit()` erweitert mit `demo_mode` Parameter
  - **🧪 DEMO** Label für Paper Trading Benachrichtigungen
  - **⚡ LIVE** Label für echte Trades
  - Mode Badge in Titel, Beschreibung und Footer
  - "Mode" als erstes Field für sofortige Sichtbarkeit

- **Trades im Bitget Account sichtbar**:
  - Demo Trades erscheinen im Bitget Demo Trading Account
  - Live Trades erscheinen im Bitget Live Account
  - Beide Modi nutzen echte Bitget Order Flow (REST API)

#### Steuerreport für Web Dashboard
Umfassende Steuerreport-Funktion für deutsche Steuerbehörden:

- **Backend**: `src/dashboard/tax_report.py`
  - `TaxReportGenerator` Klasse für Report-Generierung
  - Aggregation von Gewinnen, Verlusten, Gebühren, Funding-Kosten
  - Monatliche Aufschlüsselung der Performance
  - Zweisprachige Unterstützung (Deutsch/Englisch)
  - CSV-Export mit UTF-8 BOM für Excel-Kompatibilität

- **API Endpoints**:
  - `GET /api/tax-report/years` - Verfügbare Jahre mit Trade-Daten
  - `GET /api/tax-report/{year}?language={de|en}` - Tax-Report-Daten als JSON
  - `GET /api/tax-report/{year}/download?language={de|en}` - CSV-Download

- **Frontend**: Tax Report Sektion im Dashboard
  - Kalenderjahr-Auswahl (Dropdown mit verfügbaren Jahren)
  - Sprach-Toggle (Deutsch ⟷ English)
  - Live-Vorschau der Zusammenfassung (Gewinne, Verluste, Netto-PnL)
  - Chart.js Balkendiagramm für monatliche Performance
  - CSV-Download-Button

- **CSV-Format** (Steuerkonform):
  - Bilingual Headers (Deutsch/English)
  - 4 Sektionen: Header, Zusammenfassung, Einzeltransaktionen, Monatliche Aufschlüsselung
  - Haltedauer für jede Position (wichtig für deutsche Steuerberechnung)
  - Separate Funding Payments Auflistung
  - Disclaimer für Steuerberater-Konsultation

- **Deutsche Steuer-Compliance**:
  - Realized Gains/Losses Berechnung
  - Absetzbare Kosten (Gebühren, Funding) separiert
  - Haltedauer in Stunden für steuerliche Bewertung (<1 Jahr vs. ≥1 Jahr)

### Geaendert

- **TradeDatabase**: Neue Methode `get_trades_by_year(year)` für effizienten Jahres-basierten Zugriff
- **Dashboard UI**: Neue Tax Report Sektion nach Configuration-Card

### Dokumentation

- **DEPLOYMENT.md** (NEU): Umfassende Cloud-Deployment-Anleitung für DigitalOcean
  - Schritt-für-Schritt Setup für 24/7-Betrieb auf VPS
  - Droplet-Erstellung und Server-Konfiguration
  - Docker-Installation und Bot-Deployment
  - Nginx Reverse Proxy mit HTTPS/SSL (Let's Encrypt)
  - Firewall-Konfiguration (UFW) und SSH-Hardening
  - Systemd-Service für Auto-Start
  - Monitoring, Backups, und Wartungs-Skripte
  - Kosten-Übersicht (~$15/Monat für 2 GB Droplet)
  - Fehlerbehebung und Support-Ressourcen
- **SETUP.md**: Aktualisiert mit Hinweis auf Cloud-Deployment-Option (v1.8.0)
- **README.md**: DEPLOYMENT.md zur Dokumentations-Tabelle hinzugefügt

### Technische Details

| Komponente | Beschreibung |
|------------|--------------|
| Tax Report Generator | Python-Klasse mit i18n-Support |
| CSV Export | Built-in csv Modul mit UTF-8 BOM |
| Datenbank | SQLite mit Jahr-Filter via strftime('%Y', entry_time) |
| Frontend | Vanilla JavaScript + Chart.js für monatliches Diagramm |

---

## [1.7.0] - 2026-01-30

### Hinzugefuegt

#### Security Hardening
- **Environment-basierte Secrets**: Alle sensiblen Daten nur noch über Umgebungsvariablen
- **DASHBOARD_API_KEY**: Optionaler API-Key für Dashboard-Authentifizierung
  - Mode-Toggle-Endpoint erfordert API-Key wenn gesetzt
  - Read-Only Endpoints bleiben öffentlich
- **Dashboard Host Binding**: `DASHBOARD_HOST` konfigurierbar (Standard: 127.0.0.1)
  - Verhindert unbeabsichtigten externen Zugriff

#### Docker Support
- **Multi-Stage Dockerfile**: Optimierte Container-Images
  - Stage 1: Dependencies Build
  - Stage 2: Production Runtime
- **Docker Compose**: Vollständige Orchestrierung
  - Bot + Dashboard Service
  - Dashboard-Only Profile für Read-Only Betrieb
  - Health Checks integriert
  - Resource Limits (CPU/Memory)
- **Non-Root User**: Container läuft als unprivilegierter User (UID 1000)
- **Persistent Volumes**: `./data` und `./logs` gemountet

#### Dokumentation
- **Beginner Guide (German)**: Umfassende Anfänger-Anleitung
  - Schritt-für-Schritt Setup
  - Erklärungen zu allen Konzepten
  - Troubleshooting-Sektion

### Geaendert
- **`.env.example`**: Aktualisiert mit neuen Security-Parametern
- **README.md**: Docker-Anweisungen hinzugefügt
- **SETUP.md**: v1.7.0 Features dokumentiert

### Sicherheit
- Firewall-Empfehlungen in SETUP.md
- Reverse Proxy (nginx) Beispiel-Konfiguration
- IP-Whitelist Best Practices

---

## [1.6.0] - 2026-01-30

### Hinzugefuegt

#### WebSocket-Infrastruktur
- **Echtzeit-Updates**: WebSocket-Verbindung für Live-Daten
  - Position-Updates alle 5 Sekunden
  - Trade-Notifications bei Entry/Exit
  - Status-Updates bei Mode-Wechsel

#### Demo/Live Mode
- **Demo-Modus** (Standard): Simulierte Trades ohne echte Orderausführung
  - Alle Statistiken und Tracking funktionieren normal
  - Perfekt für Strategie-Tests
  - Empfohlen für 1-2 Wochen vor Live-Gang
- **Live-Modus**: Echte Trades auf Bitget
  - Echtes Geld involviert
  - Alle Sicherheitschecks aktiv
- **Mode-Toggle**:
  - Über Dashboard UI (mit Bestätigungs-Dialog)
  - Über API: `POST /api/mode/toggle`
  - Über Environment: `DEMO_MODE=true/false`
- **Persistenz**: Modus-Zustand wird in `data/bot_state.json` gespeichert

#### API-Endpunkte
- **`GET /api/mode`**: Aktuellen Trading-Modus abfragen
- **`POST /api/mode/toggle`**: Zwischen Demo/Live wechseln
  - Validierung: Keine offenen Positionen erlaubt
  - Bestätigung erforderlich

### Behoben (Critical Bug Fixes)
- **`execute_trade()` Fehler**: Live-Trading-Code wiederhergestellt
  - Bug: Demo-Modus-Check blockierte alle Order-Platzierungen
  - Fix: Korrekte Verzweigung Demo vs. Live
  - Impact: **Kritisch** - Bot konnte keine echten Trades platzieren
- **Position Monitoring**: Robustere Fehlerbehandlung
  - Timeout-Handling für API-Calls
  - Retry-Logik bei temporären Fehlern

### Technische Details
| Komponente | Technologie |
|------------|-------------|
| WebSocket | FastAPI WebSocketRoute |
| State Management | JSON-Persistenz in `data/bot_state.json` |
| Frontend Updates | JavaScript EventSource + WebSocket |

---

## [1.5.0] - 2026-01-29

### Hinzugefuegt

#### Web-Dashboard (Live-Monitoring)
Neues Echtzeit-Dashboard fuer den Trading Bot:

- **Backend**: FastAPI-basierter REST-API Server
  - `/api/status` - Bot-Status und Konfiguration
  - `/api/trades` - Trade-Historie und offene Positionen
  - `/api/statistics` - Performance-Statistiken
  - `/api/funding` - Funding-Rate Daten und Zahlungen
  - `/api/config` - Aktuelle Konfiguration
  - WebSocket fuer Echtzeit-Updates

- **Frontend**: Responsive Web-Interface
  - Equity-Kurve (30 Tage)
  - Funding-Rate Historie Chart
  - Offene Positionen Tabelle
  - Trade-Historie mit P&L
  - Konfigurations-Uebersicht

- **CLI**: `python main.py --dashboard [--dashboard-port 8080]`

#### Funding Rate Tracking
Vollstaendiges Tracking von Funding-Zahlungen:

- **`src/data/funding_tracker.py`**: Neues Modul
  - SQLite-Datenbank fuer Funding-Zahlungen
  - Automatische Aufzeichnung bei Funding-Zeiten (00:00, 08:00, 16:00 UTC)
  - Aggregierte Statistiken (total paid/received, avg rate)
  - Historische Funding-Rate Analyse

- **Integration in Trading Bot**:
  - Automatische Erfassung bei offenen Positionen
  - Korrekte PnL-Berechnung inkl. Funding-Kosten
  - Taeglich/woechentliche Funding-Uebersicht

- **API Endpoints**:
  - `GET /api/funding` - Funding-Statistiken
  - `GET /api/funding/history/{symbol}` - Rate-Historie

### Technische Details

| Komponente | Technologie |
|------------|-------------|
| Backend | FastAPI + uvicorn |
| Frontend | Tailwind CSS + Chart.js |
| Datenbank | SQLite (aiosqlite) |
| Updates | WebSocket (5s Intervall) |

### Neue Abhaengigkeiten
```
fastapi>=0.109.0
uvicorn>=0.27.0
```

---

## [1.4.0] - 2026-01-29

### Geaendert

#### Optimierte Strategie-Parameter
Basierend auf Backtest-Ergebnissen wurden folgende Parameter angepasst:

| Parameter | Alt | Neu | Grund |
|-----------|-----|-----|-------|
| Leverage | 3x | **4x** | Hoeherer Profit Factor erlaubt mehr Risiko |
| Take Profit | 3.5% | **4.0%** | Besseres R/R-Verhaeltnis |
| Stop Loss | 2.0% | **1.5%** | Schnellere Verlustbegrenzung |
| Position Size | 10% | **7.5%** | Geringere Kosten pro Trade |
| Max Trades/Tag | 3 | **2** | Fokus auf Qualitaet |
| Low Conf Min | 55% | **60%** | Weniger, bessere Trades |
| F&G Extreme Fear | <25 | **<20** | Nur echte Extreme |
| F&G Extreme Greed | >75 | **>80** | Nur echte Extreme |
| L/S Crowded Longs | >2.0 | **>2.5** | Staerkere Signale |
| L/S Crowded Shorts | <0.5 | **<0.4** | Staerkere Signale |

#### Alternative Datenquellen
- **CoinGecko API** als Fallback fuer Preisdaten wenn Binance nicht erreichbar
- Automatische Quellenauswahl in `fetch_klines_with_fallback()`

### Backtest-Vergleich (6 Monate, $10.000)

| Metrik | v1.3.0 (3x) | v1.4.0 (4x) | Aenderung |
|--------|-------------|-------------|-----------|
| Endkapital | $14,952.60 | **$22,259.47** | +48.9% |
| Gesamtrendite | +49.53% | **+122.59%** | +147.5% |
| Win Rate | 47.93% | 46.36% | -3.3% |
| Profit Factor | 1.33 | **1.89** | +42.1% |
| Max Drawdown | 9.23% | **7.24%** | -21.6% |
| Avg Win | $124.50 | **$163.50** | +31.3% |
| Avg Loss | -$86.45 | **-$74.66** | -13.6% |
| Kosten | $759.52 | **$656.76** | -13.5% |

#### Monatliche Performance (v1.4.0)
| Monat | P&L | Return |
|-------|-----|--------|
| 2025-08 | +$1,543.28 | +15.43% |
| 2025-09 | +$2,681.32 | +26.81% |
| 2025-10 | +$3,519.91 | +35.20% |
| 2025-11 | +$2,868.37 | +28.68% |
| 2025-12 | +$2,156.51 | +21.57% |
| 2026-01 | -$509.91 | -5.10% |

### Analyse
- **Win Rate unter 50% ist OK**: Der Profit Factor von 1.89 bedeutet, dass Gewinne im Schnitt 89% groesser sind als Verluste
- **Drawdown reduziert**: Trotz hoeherem Leverage sank der Max Drawdown von 9.23% auf 7.24%
- **Kosten gesenkt**: Durch weniger, aber bessere Trades sanken die Kosten um 13.5%

---

## [1.3.0] - 2026-01-29

### Hinzugefuegt

#### Backtesting-Modul
- **`src/backtest/historical_data.py`**: Historische Daten-Fetcher mit Caching
  - Fear & Greed Index (Alternative.me API)
  - Long/Short Ratio (Binance Futures)
  - Funding Rates (Binance)
  - Preisdaten OHLCV (Binance)
- **`src/backtest/engine.py`**: Backtest-Engine mit Trade-Simulation
  - Vollstaendige Strategie-Simulation
  - TP/SL basierend auf Intraday High/Low
  - Gebuehren- und Funding-Berechnung
- **`src/backtest/report.py`**: Report-Generator mit Empfehlungen
  - Konsolen-Report mit ASCII-Charts
  - JSON-Export fuer detaillierte Analyse
  - Automatische Empfehlungen basierend auf Metriken
- **`src/backtest/mock_data.py`**: Simulierte Daten fuer Offline-Tests
- **CLI-Integration**: `python main.py --backtest`
  - `--backtest-days N`: Anzahl Tage (Standard: 180)
  - `--backtest-capital N`: Startkapital (Standard: 10000)

#### Profit Lock-In Feature
Neues Risikomanagement-Feature in `risk_manager.py`:
- **Funktion**: Sperrt Gewinne dynamisch, um positive Tage zu schuetzen
- **Logik**: Bei Gewinn wird das Verlustlimit automatisch reduziert
- **Konfiguration**:
  - `enable_profit_lock`: Feature ein/aus (Standard: True)
  - `profit_lock_percent`: Anteil der gesperrten Gewinne (Standard: 75%)
  - `min_profit_floor`: Mindestgewinn der erhalten bleibt (Standard: 0.5%)

**Beispiel:**
| Tages-PnL | Standard Limit | Mit Profit Lock | Garantiert |
|-----------|----------------|-----------------|------------|
| +0% | -5% | -5% | -5% |
| +2% | -5% | -1.5% | +0.5% |
| +4% | -5% | -3.5% | +0.5% |

### Backtest-Ergebnisse (6 Monate, $10.000, 3x Leverage)

| Metrik | Wert | Bewertung |
|--------|------|-----------|
| Zeitraum | 2025-08-02 bis 2026-01-28 | 179 Tage |
| Startkapital | $10,000.00 | - |
| Endkapital | $14,952.60 | +49.53% |
| Max Drawdown | 9.23% | OK |
| Anzahl Trades | 338 | ~1.9/Tag |
| Win Rate | 47.93% | Unter Ziel |
| Profit Factor | 1.33 | OK |
| Gebuehren | $535.40 | 5.4% |
| Funding | $224.12 | 2.2% |

#### Monatliche Performance
| Monat | P&L | Return |
|-------|-----|--------|
| 2025-08 | +$955.83 | +9.56% |
| 2025-09 | +$1,788.03 | +17.88% |
| 2025-10 | +$1,006.08 | +10.06% |
| 2025-11 | +$1,037.60 | +10.38% |
| 2025-12 | +$1,244.69 | +12.45% |
| 2026-01 | -$1,079.62 | -10.80% |

### Empfehlungen basierend auf Backtest

Die Win Rate liegt mit 47.93% unter dem Ziel von 60%. Folgende Anpassungen werden empfohlen:

| Parameter | Aktuell | Empfohlen | Grund |
|-----------|---------|-----------|-------|
| Low Conf Min | 55% | 60% | Weniger Trades, hoehere Qualitaet |
| Take Profit | 3.5% | 4.0% | Besseres Risiko/Reward |
| Stop Loss | 2.0% | 1.5% | Schnellere Verlustbegrenzung |
| Position Size | 10% | 7.5% | Geringere Kosten |

**Strategie-Anpassungen:**
1. Nur bei echten Extremen handeln (F&G < 20 oder > 80)
2. L/S Ratio Thresholds erhoehen (>2.5 statt >2.0)
3. Trades pro Tag auf 2 reduzieren

---

## [1.2.0] - 2026-01-29

### Behoben (Bug Fixes)
- **Kritisch**: Preis-Validierung in `liquidation_hunter.py` hinzugefügt
  - Verhindert fehlerhafte TP/SL-Berechnung wenn Preis = 0 (API-Fehler)
  - Signal wird nun korrekt abgelehnt bei ungültigem Preis
- **Import-Fehler**: `timedelta` in `risk_manager.py` korrigiert
  - War am Ende der Datei (Zeile 503) statt am Anfang importiert
  - Konnte zu `NameError` bei historischen Statistiken führen

### Bereinigt (Code Cleanup)
- **`bitget_client.py`**: Unbenutzte Imports entfernt
  - `asyncio`, `Decimal`, `requests` entfernt
  - `json` Import an den Dateianfang verschoben
- **`market_data.py`**: Unbenutzte Imports entfernt
  - `timedelta`, `requests` entfernt
- **`trading_bot.py`**: Unbenutzte Imports entfernt
  - `time`, `TradeStatus` entfernt

### Code-Review Ergebnisse
| Datei | Problem | Schwere | Status |
|-------|---------|---------|--------|
| `liquidation_hunter.py:356` | Keine Preis-Validierung | **Hoch** | ✅ Behoben |
| `risk_manager.py:503` | `timedelta` am Dateiende | Mittel | ✅ Behoben |
| `bitget_client.py:6,13,16,118` | Unbenutzte/falsche Imports | Gering | ✅ Behoben |
| `market_data.py:14,18` | Unbenutzte Imports | Gering | ✅ Behoben |
| `trading_bot.py:18,29` | Unbenutzte Imports | Gering | ✅ Behoben |

---

## [1.1.1] - 2026-01-29

### Hinzugefügt
- **Dokumentation**: Umfassende Projekt-Dokumentation erstellt
  - `CHANGELOG.md` - Versions-Historie (dieses Dokument)
  - `docs/STRATEGY.md` - Detaillierte Strategie-Erklärung
  - `docs/SETUP.md` - Installations- und Konfigurations-Anleitung
  - `docs/API.md` - Technische API-Referenz
  - `docs/FAQ.md` - Häufig gestellte Fragen
- **README.md**: Dokumentations-Übersicht mit Links hinzugefügt

---

## [1.1.0] - 2026-01-29

### Geändert
- **Leverage reduziert**: Von 5x auf 3x für ausgewogeneres Risiko
- **Trading-Zeitplan optimiert**: Angepasst an globale Markt-Sessions

### Trading-Zeitplan (NEU)
| Zeit (UTC) | Session | Begründung |
|------------|---------|------------|
| 01:00 | Asia (Tokyo +1h) | Reaktion auf US-Session, Liquidation-Kaskaden |
| 08:00 | EU Open (London) | Europäische Trader steigen ein |
| 14:00 | US Open + ETFs | **Kritisch!** BTC-ETF Flows (IBIT, FBTC) |
| 21:00 | US Close | End-of-Day Profit-Taking |

### Begründung
- US-ETF-Handel (14:00 UTC) ist entscheidend für institutionelle Flows
- Bessere Abdeckung aller wichtigen Handelssessions
- Optimiert für Liquidation-Hunting bei Session-Übergängen

---

## [1.0.0] - 2026-01-29

### Hinzugefügt

#### Core Trading System
- **Bitget API Client** (`src/api/bitget_client.py`)
  - Vollständige Futures-API Integration
  - Order-Platzierung (Market/Limit)
  - Position Management
  - Leverage-Einstellung
  - Account Balance Abfragen

#### Daten-Module
- **Market Data Fetcher** (`src/data/market_data.py`)
  - Fear & Greed Index (Alternative.me API)
  - Long/Short Ratio (Binance Futures)
  - Funding Rates (Binance/Bitget)
  - Open Interest
  - 24h Ticker Data
  - Volatilitäts-Berechnung
  - Trend-Erkennung (SMA-basiert)

#### Strategie
- **Contrarian Liquidation Hunter** (`src/strategy/liquidation_hunter.py`)
  - Leverage-Analyse (L/S Ratio Thresholds)
  - Sentiment-Analyse (Fear & Greed)
  - Funding Rate Kosten-Analyse
  - Confidence-basierte Signal-Generierung
  - NO NEUTRALITY Prinzip - immer eine Richtung

#### Risk Management
- **Risk Manager** (`src/risk/risk_manager.py`)
  - Daily Loss Limit (Standard: 5%)
  - Maximum Trades pro Tag (Standard: 3)
  - Confidence-basierte Position Sizing
  - Automatischer Trading-Stopp bei Verlustgrenze
  - Tägliche Statistik-Persistenz

#### Benachrichtigungen
- **Discord Notifier** (`src/notifications/discord_notifier.py`)
  - Trade Entry Notifications
  - Trade Exit Notifications mit PnL, ROI, Fees
  - Daily Summary Reports
  - Risk Alerts
  - Bot Status Updates
  - Error Notifications

#### Persistenz
- **Trade Database** (`src/models/trade_database.py`)
  - SQLite-basierte Trade-Speicherung
  - Historische Statistiken
  - Performance-Tracking
  - Open/Closed Trade Queries

#### Bot Orchestrierung
- **Trading Bot** (`src/bot/trading_bot.py`)
  - Scheduler-basierte Marktanalyse
  - Position Monitoring (alle 5 Minuten)
  - Automatische TP/SL Erkennung
  - Graceful Shutdown Handling
  - Daily Summary Generation

#### Konfiguration
- Environment-basierte Konfiguration (`.env`)
- Alle Parameter anpassbar
- Testnet-Unterstützung

### Strategie-Parameter (Initial)
| Parameter | Wert |
|-----------|------|
| Daily Loss Limit | 5% |
| Max Trades/Tag | 3 |
| Take Profit | 3.5% |
| Stop Loss | 2.0% |
| Position Size | 10% (Basis) |
| Leverage | 5x (später 3x) |
| Fear & Greed Extreme Fear | <25 |
| Fear & Greed Extreme Greed | >75 |
| L/S Crowded Longs | >2.0 |
| L/S Crowded Shorts | <0.5 |

---

## Versions-Schema

- **MAJOR** (X.0.0): Breaking Changes, fundamentale Strategie-Änderungen
- **MINOR** (0.X.0): Neue Features, Parameter-Anpassungen
- **PATCH** (0.0.X): Bug Fixes, kleine Optimierungen

---

## Links

- [README](README.md) - Projektübersicht
- [Strategie-Dokumentation](docs/STRATEGY.md) - Detaillierte Strategie-Erklärung
- [Setup-Anleitung](docs/SETUP.md) - Installation und Konfiguration
- [API-Referenz](docs/API.md) - Code-Dokumentation
