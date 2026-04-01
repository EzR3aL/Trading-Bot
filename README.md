# Trading Department

A production-grade automated cryptocurrency trading platform with multi-exchange support, pluggable strategy engine, and a real-time React dashboard. Built for serious traders who need reliable execution, strict risk controls, and full operational visibility.

---

## Features

**Multi-Exchange Execution**
- Bitget, Weex, Hyperliquid, Bitunix, and BingX via a unified adapter pattern
- Cross-exchange symbol normalization
- Exchange-specific auth (HMAC-SHA256, wallet signatures)
- Demo and Live mode isolation per exchange

**Strategy Engine**
- Two trading strategies with a common `BaseStrategy` interface
- Strategy registry for runtime selection per bot instance

**Real-Time Dashboard**
- React + TypeScript frontend with Vite, Tailwind CSS, and shadcn/ui
- WebSocket-driven live updates (positions, PnL, bot status)
- Multi-language UI (German / English)
- Dark theme, responsive layout

**Risk Management**
- Daily loss limits (percentage-based)
- Configurable position sizing and leverage caps
- Maximum trades per day enforcement
- Circuit breaker and retry logic for exchange API failures

**Account Security**
- JWT authentication with access and refresh token rotation
- API key encryption at rest (Fernet / AES-128-CBC)
- bcrypt password hashing
- Account lockout after failed login attempts
- Rate limiting on all auth endpoints
- Security headers (CSP, HSTS, X-Frame-Options)

**Operational Tooling**
- Prometheus metrics export with Grafana dashboards
- Discord, Telegram, and WhatsApp trade notifications
- Health check endpoint with Docker healthcheck integration
- Structured logging with configurable levels
- Tax report generation with CSV export

---

## Architecture

```
Frontend (React/TS)  --->  FastAPI Backend  --->  Exchange Adapters
     |                          |                       |
  WebSocket            SQLAlchemy ORM             Bitget / Weex / Hyperliquid / Bitunix / BingX
  Zustand              Pydantic Schemas
  React Router         APScheduler
  Recharts             Prometheus Client
  RainbowKit           Alembic Migrations
```

### Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui, Zustand, Recharts |
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2 (async), Pydantic v2 |
| Database | SQLite (development), PostgreSQL (production) |
| Auth | JWT (PyJWT), bcrypt, Fernet encryption |
| Scheduling | APScheduler (async) |
| Monitoring | Prometheus, Grafana |
| Notifications | Discord webhooks, Telegram Bot API, WhatsApp (Business Cloud API) |
| Infrastructure | Docker, Docker Compose, multi-stage builds |

### Project Structure

```
trading-department/
├── main.py                      # Entry point (--dashboard, --create-admin)
├── frontend/                    # React + Vite + shadcn/ui
│   ├── src/
│   │   ├── api/                 # Axios client with JWT interceptor
│   │   ├── stores/              # Zustand state management
│   │   ├── pages/               # Dashboard, Trades, Settings, Admin, ...
│   │   ├── components/          # Shared UI components
│   │   └── i18n/                # de.json, en.json
│   └── package.json
├── src/
│   ├── api/                     # FastAPI app, routers, schemas
│   ├── auth/                    # JWT, password hashing, dependencies
│   ├── exchanges/               # Bitget, Weex, Hyperliquid, Bitunix, BingX adapters
│   ├── bot/                     # Orchestrator, BotWorker, BotManager
│   ├── strategy/                # Pluggable strategy engine
│   ├── risk/                    # Position sizing, daily loss limits
│   ├── notifications/           # Discord, Telegram, WhatsApp
│   ├── models/                  # SQLAlchemy ORM, async sessions
│   └── utils/                   # Encryption, logging, circuit breaker
├── tests/
│   ├── unit/                    # Unit tests
│   ├── integration/             # API integration tests
│   └── e2e/                     # Playwright E2E tests
├── monitoring/                  # Prometheus + Grafana config
├── Dockerfile                   # Multi-stage build (Node + Python)
├── docker-compose.yml           # App + Prometheus + Grafana
└── requirements.txt
```

---

## Quick Start

### Prerequisites

- Python 3.11 or higher
- Node.js 18 or higher
- Git

### Local Development

```bash
# Clone the repository
git clone https://github.com/EzR3aL/Bitget-Trading-Bot.git
cd Bitget-Trading-Bot

# Create and activate virtual environment
python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # Linux / macOS

# Install Python dependencies
pip install -r requirements.txt

# Build the frontend
cd frontend && npm install && npm run build && cd ..

# Configure environment
cp .env.example .env
# Edit .env -- at minimum set JWT_SECRET_KEY

# Create the admin account
python main.py --create-admin --username admin --password <your-password>

# Start the application
python main.py --dashboard
# Open http://localhost:8000
```

### Docker

```bash
git clone https://github.com/EzR3aL/Bitget-Trading-Bot.git
cd Bitget-Trading-Bot
cp .env.example .env
# Edit .env with your configuration

docker compose up --build -d
# Application:  http://localhost:8000
# Prometheus:   http://localhost:9090
# Grafana:      http://localhost:3000
```

---

## Configuration

All configuration is managed through environment variables in `.env`. Key variables:

### Required

| Variable | Description |
|----------|-------------|
| `JWT_SECRET_KEY` | Secret for signing JWT tokens. Generate with `python -c "import secrets; print(secrets.token_urlsafe(64))"` |

### Database

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Database connection string | `sqlite+aiosqlite:///data/bot.db` |
| `DB_POOL_SIZE` | PostgreSQL connection pool size | `20` |
| `DB_MAX_OVERFLOW` | Extra connections beyond pool | `30` |

### Security

| Variable | Description |
|----------|-------------|
| `ENCRYPTION_KEY` | Fernet key for API credential encryption. Auto-generated if unset |

### Hyperliquid Revenue

| Variable | Description |
|----------|-------------|
| `HL_BUILDER_ADDRESS` | Wallet address receiving builder fees |
| `HL_BUILDER_FEE` | Fee in tenths of basis points (1-100) |
| `HL_REFERRAL_CODE` | Referral code for affiliate revenue |

### Logging

| Variable | Description | Default |
|----------|-------------|---------|
| `LOG_LEVEL` | Logging verbosity | `INFO` |

All trading parameters (leverage, position size, TP/SL, strategy thresholds) are configured per-user through the dashboard Settings page or via config presets.

---

## Trading Strategies

The strategy engine uses a plugin architecture. All strategies implement `BaseStrategy` and register with `StrategyRegistry` for runtime selection.

| Strategy | Type | Description |
|----------|------|-------------|
| **Edge Indicator** | Technical | EMA ribbon + ADX chop filter + MACD/RSI momentum score. Pure price action from Binance klines |
| **Liquidation Hunter** | Contrarian | Bets against crowded positions using long/short ratio, funding rate, and Fear & Greed Index |

Each strategy can be assigned per bot instance, and users can run multiple bots with different strategies simultaneously (up to 10 per user).

---

## API Documentation

Interactive API documentation is available at:

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

### Key Endpoint Groups

| Group | Base Path | Description |
|-------|-----------|-------------|
| Auth | `/api/auth/` | Login, token refresh, profile |
| Bot Control | `/api/bots/` | Start, stop, status, mode switching |
| Trades | `/api/trades/` | Trade history with filtering and pagination |
| Statistics | `/api/statistics/` | PnL, win rate, daily breakdown |
| Config | `/api/config/` | Trading parameters, strategy, API keys, notifications |
| Portfolio | `/api/portfolio/` | Account balance and positions |
| Tax Report | `/api/tax-report/` | Yearly/monthly reports, CSV export |
| Admin | `/api/users/` | User management (admin only) |
| Metrics | `/api/metrics/` | Prometheus metrics endpoint |
| Health | `/api/health` | Liveness and readiness check |

---

## Security

### Authentication and Authorization

- JWT access tokens (short-lived) with refresh token rotation
- bcrypt password hashing with configurable rounds
- Account lockout after repeated failed login attempts
- Role-based access control (admin / user)
- Per-user data isolation enforced at the query level

### Credential Protection

- Exchange API keys encrypted at rest using Fernet (AES-128-CBC)
- API keys never returned in API responses (masked display only)
- JWT secret validated at startup; server refuses to start without it

### Transport and Headers

- CORS middleware with configurable origins
- Rate limiting via SlowAPI on sensitive endpoints
- Security headers: CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy
- HSTS enabled in production environments

### Best Practices

- Use exchange API keys with **trading-only permissions** (no withdrawal access)
- Enable **IP whitelisting** on your exchange accounts
- Start with **Demo Mode** to validate configuration before going live
- Rotate API keys periodically
- Run behind a reverse proxy (nginx/Caddy) with TLS in production

---

## Monitoring

### Prometheus Metrics

The application exports metrics at `/api/metrics` in Prometheus format. The Docker Compose stack includes pre-configured Prometheus and Grafana services.

| Service | URL | Purpose |
|---------|-----|---------|
| Application | `http://localhost:8000` | Trading bot and dashboard |
| Prometheus | `http://localhost:9090` | Metrics collection and querying |
| Grafana | `http://localhost:3000` | Dashboards and alerting |

### Health Endpoint

```
GET /api/health
```

Returns service status with database connectivity check. Used by Docker healthcheck for automatic container restart on failure.

### Notifications

| Channel | Events |
|---------|--------|
| Discord | Trade entry/exit with strategy reasoning, daily summaries, risk alerts, bot status changes |
| Telegram | Trade notifications, error alerts |
| WhatsApp | Trade notifications via WhatsApp Business Cloud API |

---

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Unit tests only
python -m pytest tests/unit -v

# Integration tests only
python -m pytest tests/integration -v

# With coverage report
python -m pytest tests/ --cov=src --cov-report=html
```

---

## Multi-Exchange Support

| Feature | Bitget | Weex | Hyperliquid | Bitunix | BingX |
|---------|--------|------|-------------|---------|-------|
| Authentication | HMAC-SHA256 + Passphrase | HMAC-SHA256 | EIP-712 Wallet Signature | HMAC-SHA256 + Passphrase | HMAC-SHA256 |
| Demo Mode | X-SIMULATED-TRADING header | Testnet URL | Testnet URL | Testnet URL | VST Mode |
| Symbol Format | `BTCUSDT` | `BTC/USDT:USDT` | `BTC` | `BTCUSDT` | `BTC-USDT` |
| API Style | REST v2 | REST | JSON-RPC | REST | REST |

All exchanges implement the `ExchangeClient` abstract base class, making them interchangeable at runtime.

---

## Disclaimer

This software is provided for educational and informational purposes only. Cryptocurrency trading carries significant financial risk. Past performance does not guarantee future results. Only trade with capital you can afford to lose. The authors assume no liability for financial losses incurred through the use of this software.

---

## License

Proprietary. All rights reserved.
