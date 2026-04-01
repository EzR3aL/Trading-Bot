# Trading Bot

## Tech Stack
- **Backend**: FastAPI 0.109 + SQLAlchemy 2.0 (async) + APScheduler
- **Frontend**: React 18 + TypeScript + Vite + Tailwind + Zustand
- **DB**: PostgreSQL 16 (Docker) + Alembic (5 Migrationen, auto-run beim Start)
- **Tests**: pytest (Backend, asyncio_mode=auto) + Vitest (Frontend)
- **Deployment**: Docker Compose auf VPS (46.101.130.50)

## Strategien (`src/strategy/`)
| Strategie | Signalquelle |
|-----------|-------------|
| Edge Indicator | EMA + MACD + ADX + ATR (Risikoprofile: standard/1h, conservative/4h) |
| Liquidation Hunter | Liquidations-Kaskaden |

## Exchanges (`src/exchanges/`)
Bitget, Weex, Hyperliquid (DEX), Bitunix, BingX — alle via `ExchangeClient` Interface

## Bot-Architektur (`src/bot/`)
- `bot_worker.py`: Hauptloop — Schedule -> `strategy.generate_signal()` -> Risk Check -> Trade
- `orchestrator.py`: Multi-Bot Lifecycle Manager
- Mixins: TradeExecutor, PositionMonitor, RotationManager, Notifications
- Locks: Per-Symbol Lock + Per-User Trade Lock (verhindert Race Conditions)

## API-Endpunkte (Wichtigste)
| Pfad | Zweck |
|------|-------|
| `POST /api/auth/login` | Login (5/min Rate Limit) |
| `GET/POST /api/bots` | Bot-Liste / Bot erstellen |
| `POST /api/bots/{id}/start\|stop` | Bot Lifecycle |
| `GET /api/trades` | Trade-Liste (Filter: status, symbol, bot, dates) |
| `GET /api/statistics` | PnL-Zusammenfassung |
| `GET /api/health` | Health Check |

## Datenbank (15 Tabellen)
Wichtigste: `bot_configs`, `trade_records`, `exchange_connections`, `users`

## Deployment
- Ablauf: commit -> push -> ssh pull -> docker build --no-cache -> up -d -> verify
- Bei Frontend-Aenderungen IMMER `--no-cache` verwenden
- SSH Host: `trading-bot`, Pfad: `/root/Trading-Bot`
- Container: `bitget-trading-bot`, DB: `tradingbot-postgres`

## Projektkonventionen

### Changelog (PFLICHT)
- **CHANGELOG.md MUSS bei JEDEM Commit und Push aktualisiert werden**
- Format: Keep a Changelog + Semantic Versioning
- Neue Eintraege immer oben (neueste Version zuerst)

### Issues
- Jedes Feature/Bugfix als GitHub Issue BEVOR Code geschrieben wird
- Branch-Name mit Issue-Nummer: `feature/123-beschreibung`
- Commits referenzieren Issue: `feat: add telegram (#123)`

### Anleitungen
- Benutzeranleitungen in `Anleitungen/` (Deutsch, Einsteiger-freundlich)

## Version
Check: `cat .claude/VERSION`
