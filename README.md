# Bitget Trading Bot

**Contrarian Liquidation Hunter Strategy** | v1.8.0

An automated cryptocurrency trading bot for Bitget Futures that implements a sophisticated contrarian strategy, betting against the crowd when leverage and sentiment reach extreme levels.

---

## Neu hier? Einsteiger-Anleitung

Wenn du neu bist und eine einfache Schritt-für-Schritt Anleitung suchst:

**[Anleitung für den Bot & Notification](Anleitung%20für%20den%20Bot%20%26%20Notification.md)** - Komplette Anleitung für Einsteiger (Deutsch)

Diese Anleitung erklärt:
- Bitget Account & API einrichten
- Discord Benachrichtigungen aktivieren
- Bot installieren und starten
- Alle Einstellungen verstehen

---

## Quick Start

```bash
# Clone and setup
git clone https://github.com/yourusername/Bitget-Trading-Bot.git
cd Bitget-Trading-Bot
pip install -r requirements.txt
cp .env.example .env

# Configure your credentials in .env, then:

# Run in Demo Mode (safe testing, no real trades)
python main.py

# Start Web Dashboard
python main.py --dashboard
# Open http://localhost:8080
```

**Or with Docker:**
```bash
docker-compose up -d
```

---

## Strategy Overview

The bot acts as an "Institutional Market Maker" by analyzing:

1. **Leverage Analysis** (Long/Short Ratio)
   - Ratio > 2.0: Crowded longs detected → SHORT signal
   - Ratio < 0.5: Crowded shorts detected → LONG signal

2. **Cost Analysis** (Funding Rate)
   - Rate > 0.05%: Expensive to hold longs → Strengthens SHORT (+20 confidence)
   - Rate < -0.02%: Expensive to hold shorts → Strengthens LONG (+20 confidence)

3. **Sentiment Analysis** (Fear & Greed Index)
   - Index > 75: Extreme Greed → SHORT bias
   - Index < 25: Extreme Fear → LONG bias

### Decision Matrix

| Leverage Signal | Sentiment Signal | Result |
|----------------|------------------|--------|
| Crowded Longs | Extreme Greed | HIGH confidence SHORT (85-95%) |
| Crowded Shorts | Extreme Fear | HIGH confidence LONG (85-95%) |
| Mixed signals | Any | Follow 24h trend with LOW confidence (55-65%) |

**Key Principle:** NO NEUTRALITY - The bot always picks a side. When leverage is extreme, it ignores news and trends to bet on the reversal.

---

## Features

### Core Trading
- **Automated Trading**: Executes up to 2-3 trades per day on BTC and ETH
- **Risk Management**: Daily loss limits, position sizing based on confidence
- **Persistent Tracking**: SQLite database for trade history and statistics

### Web Dashboard (v1.5.0+)
- **Real-time Monitoring**: Live equity curve, open positions, trade history
- **Funding Rate Tracking**: 30-day funding history with daily breakdown
- **Configuration View**: Current settings and daily statistics
- **Demo/Live Toggle**: Switch trading modes directly from the UI

### Demo/Live Mode (v1.6.0+)
- **Demo Mode** (Default): Simulates trades without placing real orders
- **Live Mode**: Executes real trades on Bitget
- Test your strategy for days/weeks before going live

### WebSocket Infrastructure (v1.6.0+)
- **Binance WebSocket**: Real-time market data (mark prices, funding rates)
- **Bitget WebSocket**: Execution prices and position updates

### Security Features (v1.7.0+)
- **API Key Authentication**: Protect dashboard with `X-API-Key` header
- **CORS Protection**: Restricted to localhost origins
- **Rate Limiting**: 5 requests/minute on mode toggle
- **Secure Defaults**: Dashboard binds to 127.0.0.1 only

### Tax Reporting (v1.8.0+)
- **Steuerreport für deutsche Behörden**: Comprehensive tax reports for German tax compliance
- **CSV Export**: Download complete trade history with realized gains/losses, fees, funding costs
- **Bilingual Support**: Toggle between German and English (Deutsch ⟷ English)
- **Calendar Year Reports**: Select any year with trade data for tax filing
- **Monthly Breakdown**: Performance aggregated by month with visual chart
- **Tax-Compliant Format**: Includes holding duration (critical for German tax: <1yr vs ≥1yr)
- **Deductible Costs**: Trading fees and funding payments separated for tax deductions
- **Live Preview**: View summary (gains, losses, net PnL) before downloading

### Notifications
- **Discord Integration**: Real-time trade alerts with full details
- Entry/exit notifications with PnL breakdown
- Daily summaries and risk alerts

---

## Documentation

| Document | Description |
|----------|-------------|
| [CHANGELOG.md](CHANGELOG.md) | Version history and all changes |
| [docs/STRATEGY.md](docs/STRATEGY.md) | Detailed strategy explanation |
| [docs/SETUP.md](docs/SETUP.md) | Local installation and configuration guide |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | **Cloud deployment guide (DigitalOcean, 24/7)** |
| [docs/API.md](docs/API.md) | Technical API reference |
| [docs/FAQ.md](docs/FAQ.md) | Frequently asked questions |

---

## Project Structure

```
Bitget-Trading-Bot/
├── main.py                     # Main entry point
├── requirements.txt            # Python dependencies
├── .env.example               # Environment variables template
├── Dockerfile                 # Production Docker image
├── docker-compose.yml         # Docker Compose configuration
├── config/
│   └── settings.py            # Configuration management
├── src/
│   ├── api/
│   │   └── bitget_client.py   # Bitget API wrapper
│   ├── websocket/             # WebSocket clients (v1.6.0+)
│   │   ├── binance_ws.py      # Binance market data
│   │   └── bitget_ws.py       # Bitget execution data
│   ├── dashboard/             # Web Dashboard (v1.5.0+)
│   │   └── app.py             # FastAPI application
│   ├── data/
│   │   ├── market_data.py     # Market data fetchers
│   │   └── funding_tracker.py # Funding rate tracking
│   ├── strategy/
│   │   └── liquidation_hunter.py  # Main trading strategy
│   ├── risk/
│   │   └── risk_manager.py    # Risk management
│   ├── notifications/
│   │   └── discord_notifier.py # Discord integration
│   ├── models/
│   │   └── trade_database.py  # Trade persistence
│   ├── bot/
│   │   └── trading_bot.py     # Main bot orchestrator
│   └── utils/
│       └── logger.py          # Logging utilities
├── data/                       # Database and risk data
└── logs/                       # Log files
```

---

## Installation

### Option 1: Python (Recommended for Development)

**Prerequisites:**
- Python 3.10 or higher
- Bitget account with API access
- Discord server with webhook

```bash
# Clone the repository
git clone https://github.com/yourusername/Bitget-Trading-Bot.git
cd Bitget-Trading-Bot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials
```

### Option 2: Docker (Recommended for Production)

```bash
# Clone the repository
git clone https://github.com/yourusername/Bitget-Trading-Bot.git
cd Bitget-Trading-Bot

# Configure environment
cp .env.example .env
# Edit .env with your credentials

# Build and run
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

---

## Configuration

Edit the `.env` file with your credentials:

### Bitget API (Required)
```env
BITGET_API_KEY=your_api_key
BITGET_API_SECRET=your_api_secret
BITGET_PASSPHRASE=your_passphrase
BITGET_TESTNET=false
```

### Discord (Required for notifications)
```env
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

### Trading Mode (v1.6.0+)
```env
# Demo mode for testing (true = no real trades)
DEMO_MODE=true
```

### Dashboard Security (v1.7.0+)
```env
# API key for dashboard authentication (leave empty for development)
# Generate: python -c "import secrets; print(secrets.token_urlsafe(32))"
DASHBOARD_API_KEY=

# Host binding (127.0.0.1 = localhost only, 0.0.0.0 = all interfaces)
# WARNING: Only use 0.0.0.0 if you have set DASHBOARD_API_KEY!
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8080
```

### Trading Parameters
```env
MAX_TRADES_PER_DAY=3           # Maximum trades per day
DAILY_LOSS_LIMIT_PERCENT=5.0   # Stop trading if daily loss exceeds this
POSITION_SIZE_PERCENT=10.0     # Base position size as % of balance
LEVERAGE=3                      # Leverage for futures trades (3x recommended)
TAKE_PROFIT_PERCENT=3.5        # Take profit target
STOP_LOSS_PERCENT=2.0          # Stop loss level
```

### Strategy Thresholds
```env
FEAR_GREED_EXTREME_FEAR=25     # Fear & Greed threshold for LONG
FEAR_GREED_EXTREME_GREED=75    # Fear & Greed threshold for SHORT
LONG_SHORT_CROWDED_LONGS=2.0   # L/S ratio threshold for SHORT
LONG_SHORT_CROWDED_SHORTS=0.5  # L/S ratio threshold for LONG
```

---

## Usage

### Run the Bot

```bash
# Demo Mode (default, no real trades)
python main.py

# Test Mode (single analysis, no trading)
python main.py --test

# Check Status
python main.py --status

# Run Backtest
python main.py --backtest --backtest-days 180

# Debug Mode
python main.py --log-level DEBUG
```

### Web Dashboard

```bash
# Start dashboard at http://localhost:8080
python main.py --dashboard

# Custom port
python main.py --dashboard --dashboard-port 3000
```

**Dashboard Features:**
- Real-time equity curve (30 days)
- Open positions with TP/SL levels
- Recent trades history
- Funding rate tracking
- Demo/Live mode toggle
- Configuration view

### Demo/Live Mode

The bot defaults to **Demo Mode** for safety. In demo mode:
- Trades are simulated (no real orders placed)
- All statistics and tracking work normally
- Perfect for testing strategy changes

**Switch to Live Mode:**

1. **Via Dashboard**: Click the mode toggle button (requires confirmation)

2. **Via API**:
   ```bash
   # Without API key (development)
   curl -X POST http://localhost:8080/api/mode/toggle

   # With API key (production)
   curl -X POST -H "X-API-Key: your_key" http://localhost:8080/api/mode/toggle
   ```

3. **Via Environment**:
   ```env
   DEMO_MODE=false
   ```

---

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/health` | GET | No | Health check for monitoring |
| `/api/status` | GET | No | Bot status and daily stats |
| `/api/mode` | GET | No | Current trading mode |
| `/api/mode/toggle` | POST | Yes* | Toggle demo/live mode |
| `/api/trades` | GET | No | Trade history |
| `/api/funding` | GET | No | Funding rate history |
| `/api/performance/daily` | GET | No | Daily performance stats |

*Auth required only if `DASHBOARD_API_KEY` is set

### Example API Usage

```bash
# Get bot status
curl http://localhost:8080/api/status

# Get current mode
curl http://localhost:8080/api/mode

# Toggle mode (with auth)
curl -X POST -H "X-API-Key: your_key" http://localhost:8080/api/mode/toggle

# Get recent trades
curl http://localhost:8080/api/trades?limit=20

# Get funding history
curl http://localhost:8080/api/funding?days=30

# Health check
curl http://localhost:8080/api/health
```

---

## Discord Notifications

The bot sends detailed notifications for:

### Trade Entry
- Asset, direction, leverage
- Entry price, size, value
- Take profit and stop loss levels
- Strategy confidence and reasoning

### Trade Exit
- Entry/exit prices
- Gross PnL and ROI%
- Fees and funding costs
- Net PnL
- Trade duration

### Daily Summary
- Total trades, wins/losses
- Win rate
- Total PnL breakdown
- Maximum drawdown

### Risk Alerts
- Daily loss limit reached
- Maximum trades reached
- Errors and warnings

---

## Risk Management

### Daily Loss Limit
Default: **5%** of starting balance. When reached, trading halts for the day.

### Position Sizing
Base position: **10%** of available balance, scaled by confidence:
- 90%+ confidence: 1.5x (15% of balance)
- 80%+ confidence: 1.25x (12.5% of balance)
- 70%+ confidence: 1.0x (10% of balance)
- 60%+ confidence: 0.75x (7.5% of balance)
- <60% confidence: 0.5x (5% of balance)

### Maximum Trades
Default: **3 trades per day** to avoid overtrading.

---

## Security Best Practices

### Production Deployment

1. **Set API Key**:
   ```bash
   # Generate secure key
   python -c "import secrets; print(secrets.token_urlsafe(32))"

   # Add to .env
   DASHBOARD_API_KEY=your_generated_key
   ```

2. **Use Docker** with resource limits (included in docker-compose.yml)

3. **Bind to localhost** unless you need external access:
   ```env
   DASHBOARD_HOST=127.0.0.1
   ```

4. **If external access needed**, set API key AND use reverse proxy (nginx) with HTTPS

### API Key Security

- Never commit `.env` to version control
- Rotate keys periodically
- Use IP whitelisting on Bitget API
- Disable withdraw permissions on Bitget API

---

## Troubleshooting

### "Bitget API credentials not configured"
Ensure your `.env` file has valid API credentials.

### "Discord webhook error"
Check that your webhook URL is valid and the Discord channel exists.

### "Trading not allowed: Daily loss limit reached"
Wait until the next day or adjust `DAILY_LOSS_LIMIT_PERCENT`.

### "No remaining trades for today"
Maximum trades reached. Wait until tomorrow or adjust `MAX_TRADES_PER_DAY`.

### Dashboard not accessible
- Check if running: `python main.py --dashboard`
- Verify port: default is 8080
- Check firewall settings

### Mode toggle returns 401
Set `X-API-Key` header if `DASHBOARD_API_KEY` is configured.

---

## Version History

| Version | Features |
|---------|----------|
| v1.7.0 | Security hardening, Docker support, health checks |
| v1.6.0 | WebSocket infrastructure, Demo/Live mode |
| v1.5.0 | Web Dashboard, Funding rate tracking |
| v1.4.0 | Backtesting module, profit lock-in |
| v1.0.0 | Initial release |

See [CHANGELOG.md](CHANGELOG.md) for full details.

---

## Disclaimer

**This bot is for educational purposes only.** Trading cryptocurrency carries significant risk. Past performance does not guarantee future results. Only trade with funds you can afford to lose.

The authors are not responsible for any financial losses incurred through the use of this software.

---

## License

MIT License - See LICENSE file for details.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## Support

For issues and questions, please open a GitHub issue.
