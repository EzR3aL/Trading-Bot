# Changelog

Alle wichtigen Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

> **Hinweis:** Dieser Changelog wird automatisch bei jeder Änderung aktualisiert.

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
