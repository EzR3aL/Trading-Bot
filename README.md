# Bitget Trading Bot

**Contrarian Liquidation Hunter Strategy**

An automated cryptocurrency trading bot for Bitget Futures that implements a sophisticated contrarian strategy, betting against the crowd when leverage and sentiment reach extreme levels.

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

## Features

- **Automated Trading**: Executes up to 2-3 trades per day on BTC and ETH
- **Risk Management**: Daily loss limits, position sizing based on confidence
- **Discord Notifications**: Real-time trade alerts with full details
- **Persistent Tracking**: SQLite database for trade history and statistics
- **Multi-Source Data**: Combines Binance, Alternative.me, and Bitget data

## Documentation

| Document | Description |
|----------|-------------|
| [CHANGELOG.md](CHANGELOG.md) | Version history and all changes |
| [docs/STRATEGY.md](docs/STRATEGY.md) | Detailed strategy explanation |
| [docs/SETUP.md](docs/SETUP.md) | Installation and configuration guide |
| [docs/API.md](docs/API.md) | Technical API reference |
| [docs/FAQ.md](docs/FAQ.md) | Frequently asked questions |

## Project Structure

```
Bitget-Trading-Bot/
├── main.py                     # Main entry point
├── requirements.txt            # Python dependencies
├── .env.example               # Environment variables template
├── config/
│   ├── __init__.py
│   └── settings.py            # Configuration management
├── src/
│   ├── api/
│   │   └── bitget_client.py   # Bitget API wrapper
│   ├── data/
│   │   └── market_data.py     # Market data fetchers
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

## Installation

### Prerequisites

- Python 3.10 or higher
- Bitget account with API access
- Discord server with webhook

### Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/Bitget-Trading-Bot.git
   cd Bitget-Trading-Bot
   ```

2. **Create virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # or
   venv\Scripts\activate     # Windows
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

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

## Usage

### Run the Bot
```bash
python main.py
```

### Test Mode (Analysis Only)
```bash
python main.py --test
```

### Check Status
```bash
python main.py --status
```

### Debug Mode
```bash
python main.py --log-level DEBUG
```

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

## Risk Management

### Daily Loss Limit
Default: **5%** of starting balance. When reached, trading halts for the day.

**Recommendation:** For conservative trading, set to 3-5%. For aggressive trading, 7-10%.

### Position Sizing
Base position: **10%** of available balance, scaled by confidence:
- 90%+ confidence: 1.5x (15% of balance)
- 80%+ confidence: 1.25x (12.5% of balance)
- 70%+ confidence: 1.0x (10% of balance)
- 60%+ confidence: 0.75x (7.5% of balance)
- <60% confidence: 0.5x (5% of balance)

### Maximum Trades
Default: **3 trades per day** to avoid overtrading.

## Trading Schedule

The bot analyzes markets at optimal times aligned with major market sessions:

| Time (UTC) | Session | Reason |
|------------|---------|--------|
| **01:00** | Asia (Tokyo +1h) | Reaction to US session, liquidation cascades |
| **08:00** | EU Open (London) | European traders enter, potential reversals |
| **14:00** | US Open + ETFs | **Critical!** BTC ETF flows (IBIT, FBTC, etc.) |
| **21:00** | US Close | End-of-day profit-taking, position adjustments |

Position monitoring runs every 5 minutes.

Daily summary sent at 23:55 UTC.

## Performance Goals

- **Success Rate Target:** 60%+ win rate
- **Risk/Reward:** 3.5% TP / 2% SL = 1.75:1 ratio
- **Maximum Drawdown:** 5% daily limit

## API Data Sources

| Data | Source | Update Frequency |
|------|--------|-----------------|
| Fear & Greed Index | Alternative.me | Daily |
| Long/Short Ratio | Binance Futures | Hourly |
| Funding Rate | Binance/Bitget | 8-hour intervals |
| Price Data | Binance Futures | Real-time |
| Open Interest | Binance Futures | Real-time |

## Safety Features

1. **Testnet Support:** Enable `BITGET_TESTNET=true` for paper trading
2. **Rate Limiting:** Respects API rate limits
3. **Error Handling:** Graceful handling of API errors
4. **Shutdown Handling:** Clean shutdown on SIGINT/SIGTERM
5. **Position Monitoring:** Automatic detection of closed positions

## Troubleshooting

### "Bitget API credentials not configured"
Ensure your `.env` file has valid API credentials.

### "Discord webhook error"
Check that your webhook URL is valid and the Discord channel exists.

### "Trading not allowed: Daily loss limit reached"
Wait until the next day or adjust `DAILY_LOSS_LIMIT_PERCENT`.

### "No remaining trades for today"
Maximum trades reached. Wait until tomorrow or adjust `MAX_TRADES_PER_DAY`.

## Disclaimer

**This bot is for educational purposes only.** Trading cryptocurrency carries significant risk. Past performance does not guarantee future results. Only trade with funds you can afford to lose.

The authors are not responsible for any financial losses incurred through the use of this software.

## License

MIT License - See LICENSE file for details.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## Support

For issues and questions, please open a GitHub issue.
