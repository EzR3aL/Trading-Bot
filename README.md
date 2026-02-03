# Bitget Trading Bot

**Contrarian Liquidation Hunter Strategy** | v2.0.0

An automated cryptocurrency trading bot with a React Web UI, multi-user support, multi-exchange architecture (Bitget, Weex, Hyperliquid), configurable presets, and comprehensive Discord notifications.

---

## What's New in v2.0.0

- **React Web UI** with dark theme (shadcn/ui + Tailwind CSS)
- **Multi-User Support** (1-5 users) with JWT authentication
- **Multi-Exchange Architecture** (Bitget, Weex, Hyperliquid) via adapter pattern
- **Config Presets** -- save, switch, and duplicate trading configurations
- **Per-User Bot Control** -- start/stop/mode per user via Web UI
- **API Key Encryption** (Fernet) -- keys stored encrypted in database
- **Tax Report with CSV Export** -- yearly/monthly breakdown
- **Built-in Getting Started Guide** -- interactive tutorial in the Web UI
- **Sidebar with Icons** -- lucide-react icons for all menu items
- **Discord Notifications** -- trade open/close with strategy reasoning
- **146 Tests** (93 unit + 53 integration) with 80%+ coverage target
- **Multi-Stage Docker Build** -- frontend + backend in one image

---

## Quick Start

### Option 1: Local Development

```bash
# Clone and setup
git clone https://github.com/EzR3aL/Bitget-Trading-Bot.git
cd Bitget-Trading-Bot

# Backend
python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # Linux/Mac
pip install -r requirements.txt

# Frontend
cd frontend && npm install && npm run build && cd ..

# Configure
cp .env.example .env
# Edit .env with your credentials

# Create admin user
python main.py --create-admin --username admin --password yourpassword

# Start Web UI
python main.py --dashboard
# Open http://localhost:8080
```

### Option 2: Docker

```bash
git clone https://github.com/EzR3aL/Bitget-Trading-Bot.git
cd Bitget-Trading-Bot
cp .env.example .env
# Edit .env

docker-compose up -d
# Open http://localhost:8080
```

---

## Web UI Overview

| Page | Description |
|------|-------------|
| **Dashboard** | Account balance, PnL, win rate, open positions, recent trades |
| **Trades** | Full trade history with filters (status, symbol, exchange), pagination |
| **Presets** | Create/edit/duplicate/activate trading configuration presets |
| **Settings** | Tabs: Trading, Strategy, API Keys, Discord, Profile |
| **Bot Control** | Start/Stop bot, Demo/Live toggle, exchange + preset selection |
| **Tax Report** | Yearly summary, monthly breakdown, CSV download |
| **Guide** | Step-by-step tutorial for new users |
| **Admin** | User management (admin only) |

The UI supports **German and English** (toggle in sidebar).

---

## Strategy Overview

The bot acts as a "Contrarian Liquidation Hunter" by analyzing:

1. **Leverage Analysis** (Long/Short Ratio)
   - Ratio > 2.0: Crowded longs detected -> SHORT signal
   - Ratio < 0.5: Crowded shorts detected -> LONG signal

2. **Cost Analysis** (Funding Rate)
   - Rate > 0.05%: Expensive to hold longs -> Strengthens SHORT (+20 confidence)
   - Rate < -0.02%: Expensive to hold shorts -> Strengthens LONG (+20 confidence)

3. **Sentiment Analysis** (Fear & Greed Index)
   - Index > 75: Extreme Greed -> SHORT bias
   - Index < 25: Extreme Fear -> LONG bias

### Decision Matrix

| Leverage Signal | Sentiment Signal | Result |
|----------------|------------------|--------|
| Crowded Longs | Extreme Greed | HIGH confidence SHORT (85-95%) |
| Crowded Shorts | Extreme Fear | HIGH confidence LONG (85-95%) |
| Mixed signals | Any | Follow 24h trend with LOW confidence (55-65%) |

---

## Architecture

```
Bitget-Trading-Bot/
├── main.py                          # Entry point (--dashboard, --create-admin)
├── requirements.txt                 # Python dependencies
├── Dockerfile                       # Multi-stage build (Node + Python)
├── docker-compose.yml               # Production compose
├── config/
│   └── settings.py                  # Legacy config (fallback)
├── frontend/                        # React + Vite + shadcn/ui
│   ├── src/
│   │   ├── api/                     # API client with JWT interceptor
│   │   ├── stores/                  # Zustand state management
│   │   ├── pages/                   # Dashboard, Trades, Settings, ...
│   │   ├── components/              # Layout, forms, shared components
│   │   └── i18n/                    # de.json, en.json translations
│   └── package.json
├── src/
│   ├── api/
│   │   ├── main_app.py              # FastAPI app, lifespan, static files
│   │   ├── routers/                 # auth, trades, config, presets, bot, ...
│   │   └── schemas/                 # Pydantic validation models
│   ├── auth/
│   │   ├── jwt_handler.py           # JWT access + refresh tokens
│   │   ├── password.py              # bcrypt hashing
│   │   └── dependencies.py          # get_current_user, get_current_admin
│   ├── exchanges/
│   │   ├── base.py                  # ABC: ExchangeClient, ExchangeWebSocket
│   │   ├── factory.py               # create_exchange_client()
│   │   ├── types.py                 # Balance, Order, Position, Ticker
│   │   ├── symbol_map.py            # Cross-exchange symbol normalization
│   │   ├── bitget/                  # Bitget adapter (REST + WS)
│   │   ├── weex/                    # Weex adapter
│   │   └── hyperliquid/             # Hyperliquid adapter
│   ├── bot/
│   │   ├── trading_bot.py           # Main bot orchestrator
│   │   └── bot_manager.py           # Per-user bot instances
│   ├── models/
│   │   ├── database.py              # SQLAlchemy ORM models
│   │   └── session.py               # Async engine + session factory
│   ├── strategy/
│   │   └── liquidation_hunter.py    # Contrarian strategy
│   ├── risk/
│   │   └── risk_manager.py          # Position sizing, daily limits
│   ├── notifications/
│   │   └── discord_notifier.py      # Discord webhook embeds
│   └── utils/
│       ├── encryption.py            # Fernet API key encryption
│       ├── logger.py                # Structured logging
│       └── circuit_breaker.py       # Circuit breaker + retry
├── tests/
│   ├── unit/                        # 93 unit tests
│   │   ├── auth/                    # JWT, password hashing
│   │   ├── exchanges/               # Symbol map, factory
│   │   ├── models/                  # Encryption
│   │   └── bot/                     # BotManager
│   ├── integration/                 # 53 integration tests
│   │   ├── test_auth_flow.py        # Login, token refresh
│   │   ├── test_config_api.py       # Settings CRUD
│   │   ├── test_preset_api.py       # Preset CRUD
│   │   └── test_user_isolation.py   # Multi-tenant isolation
│   └── e2e/                         # Playwright E2E tests
├── scripts/
│   └── migrate_legacy_data.py       # Migration from v1.x
└── data/                            # SQLite databases (gitignored)
```

---

## Multi-Exchange Support

| Feature | Bitget | Weex | Hyperliquid |
|---------|--------|------|-------------|
| Auth | HMAC-SHA256 + Passphrase | HMAC-SHA256 | Wallet Signature |
| Demo Mode | X-SIMULATED-TRADING header | Testnet URL | Testnet URL |
| Symbol Format | BTCUSDT | BTC/USDT:USDT | BTC |
| API Style | REST v2 | REST | JSON-RPC |

All exchanges implement the same `ExchangeClient` ABC, making them interchangeable.

---

## Config Presets

Presets let you save and switch between different trading configurations:

```
+--------------------------------------------------+
| My Presets                           [+ New]     |
+--------------------------------------------------+
| [*] Conservative BTC         Bitget    ACTIVE    |
|     3x Leverage | 5% Position | 2% SL            |
|     [Edit] [Duplicate]                            |
+--------------------------------------------------+
| [ ] Aggressive ETH           Bitget              |
|     10x Leverage | 15% Position | 1% SL           |
|     [Activate] [Edit] [Duplicate] [X]             |
+--------------------------------------------------+
```

Each preset stores: exchange, leverage, position size, TP/SL, strategy thresholds, and trading pairs.

---

## API Endpoints

### Authentication

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/login` | POST | Login (returns JWT) |
| `/api/auth/refresh` | POST | Refresh access token |
| `/api/auth/me` | GET | Current user profile |

### Trading

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/trades` | GET | Trade history (filters: status, symbol, exchange) |
| `/api/trades/{id}` | GET | Single trade details |
| `/api/statistics` | GET | Trading statistics (N days) |
| `/api/statistics/daily` | GET | Daily PnL breakdown |
| `/api/funding` | GET | Funding payment history |
| `/api/funding/summary` | GET | Funding summary |

### Configuration

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/config` | GET | Current user config |
| `/api/config/trading` | PUT | Update trading parameters |
| `/api/config/strategy` | PUT | Update strategy thresholds |
| `/api/config/api-keys` | PUT | Update exchange API keys |
| `/api/config/api-keys/test` | POST | Test exchange connection |
| `/api/config/discord` | PUT | Update Discord webhook |
| `/api/config/discord/test` | POST | Send test notification |

### Presets

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/presets` | GET | List all presets |
| `/api/presets` | POST | Create preset |
| `/api/presets/{id}` | GET | Get preset |
| `/api/presets/{id}` | PUT | Update preset |
| `/api/presets/{id}` | DELETE | Delete preset |
| `/api/presets/{id}/activate` | POST | Activate preset |
| `/api/presets/{id}/duplicate` | POST | Duplicate preset |

### Bot Control

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/bot/status` | GET | Bot status |
| `/api/bot/start` | POST | Start bot (exchange + preset + mode) |
| `/api/bot/stop` | POST | Stop bot |
| `/api/bot/mode` | POST | Switch demo/live |
| `/api/bot/test-trade` | POST | Open a demo test trade |
| `/api/bot/close-trade/{id}` | POST | Close a trade manually |

### Admin

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/users` | GET | List users (admin) |
| `/api/users` | POST | Create user (admin) |
| `/api/users/{id}` | PUT | Update user (admin) |
| `/api/users/{id}` | DELETE | Delete user (admin) |

### Other

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/status` | GET | Bot status + balance |
| `/api/exchanges` | GET | Supported exchanges |
| `/api/tax-report` | GET | Tax report (JSON) |
| `/api/tax-report/csv` | GET | Tax report (CSV download) |

---

## Discord Notifications

The bot sends formatted Discord embeds for:

### Trade Entry
- Mode (Demo/Live), Symbol, Direction
- Entry price, size, leverage, value
- Take profit and stop loss levels
- Confidence score and **strategy reasoning**

### Trade Exit
- Entry/exit prices, price change
- Gross PnL, ROI%, fees, funding
- Net PnL, exit reason (TP/SL/Manual)
- Duration and **original strategy decision**

### Other
- Daily summary (trades, win rate, PnL, drawdown)
- Risk alerts (loss limit, max trades)
- Bot status (started, stopped, errors)

---

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Unit tests only
python -m pytest tests/unit -v

# Integration tests only
python -m pytest tests/integration -v

# With coverage
python -m pytest tests/ --cov=src --cov-report=html

# Exchange-specific tests
python -m pytest tests/ -m exchange -v
```

Current: **146 tests** (93 unit + 53 integration), all passing.

---

## Configuration

### Environment Variables (.env)

```env
# Database
DATABASE_URL=sqlite+aiosqlite:///data/bot.db

# JWT Authentication
JWT_SECRET_KEY=your-secret-key-here

# API Key Encryption
ENCRYPTION_KEY=your-fernet-key-here

# Bitget API
BITGET_API_KEY=your_api_key
BITGET_API_SECRET=your_api_secret
BITGET_PASSPHRASE=your_passphrase

# Discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Trading Mode
DEMO_MODE=true

# Trading Parameters
MAX_TRADES_PER_DAY=3
DAILY_LOSS_LIMIT_PERCENT=5.0
POSITION_SIZE_PERCENT=10.0
LEVERAGE=3
TAKE_PROFIT_PERCENT=3.5
STOP_LOSS_PERCENT=2.0

# Strategy Thresholds
FEAR_GREED_EXTREME_FEAR=25
FEAR_GREED_EXTREME_GREED=75
LONG_SHORT_CROWDED_LONGS=2.0
LONG_SHORT_CROWDED_SHORTS=0.5
```

---

## Security

- **JWT Authentication** with access (30 min) + refresh (7 day) tokens
- **API Key Encryption** using Fernet (symmetric, AES-128-CBC)
- **bcrypt Password Hashing** via passlib
- **User Isolation** -- each user sees only their own data
- **CORS Protection** and rate limiting
- **No API keys in responses** -- only masked values shown

### Best Practices

- Use API keys with **trading-only permissions** (no withdrawals)
- Start with **Demo Mode** before going live
- Set **realistic stop-loss** values
- **Rotate** API keys periodically
- Use **IP whitelisting** on your exchange

---

## Migration from v1.x

```bash
# Run the migration script
python scripts/migrate_legacy_data.py

# This will:
# 1. Read existing data/trades.db
# 2. Read existing data/funding_tracker.db
# 3. Create admin user from .env credentials
# 4. Import trades + funding with user_id = admin
# 5. Create default preset from .env config
```

---

## Version History

| Version | Features |
|---------|----------|
| **v2.0.0** | React Web UI, multi-user, multi-exchange, presets, JWT auth, encrypted keys, 146 tests |
| v1.10.0 | Security hardening, performance improvements |
| v1.9.0 | Circuit breaker, retry logic, health monitoring |
| v1.8.0 | Tax reports, demo trading, bilingual UI |
| v1.7.0 | Security hardening, Docker support |
| v1.6.0 | WebSocket infrastructure, Demo/Live mode |
| v1.5.0 | Web Dashboard, funding tracking |

See [CHANGELOG.md](CHANGELOG.md) for full details.

---

## Troubleshooting

### API Keys not working
Ensure your exchange API keys have **futures trading** permission enabled. Test via Settings > API Keys > "Test Connection".

### Discord notifications not sending
Check that the webhook URL is valid under Settings > Discord > "Send Test Message".

### Frontend not loading
Rebuild the frontend: `cd frontend && npm run build`. The built files must be in `static/frontend/`.

### Database errors
Ensure the `data/` directory exists: `mkdir -p data`.

---

## Disclaimer

**This bot is for educational purposes only.** Trading cryptocurrency carries significant risk. Past performance does not guarantee future results. Only trade with funds you can afford to lose.

The authors are not responsible for any financial losses incurred through the use of this software.

---

## License

MIT License - See LICENSE file for details.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.
