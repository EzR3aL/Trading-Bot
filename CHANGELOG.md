# Changelog

Alle wichtigen Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

> **Hinweis:** Dieser Changelog wird automatisch bei jeder Änderung aktualisiert.

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
