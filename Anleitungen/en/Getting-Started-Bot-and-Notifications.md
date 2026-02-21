# Getting Started with Trading Department & Notifications

A simple step-by-step guide for beginners.

---

## Table of Contents

1. [What does this bot do?](#1-what-does-this-bot-do)
2. [Prerequisites](#2-prerequisites)
3. [Bitget Account & API Setup](#3-bitget-account--api-setup)
4. [Discord Notifications Setup](#4-discord-notifications-setup)
5. [Download & Install the Bot](#5-download--install-the-bot)
6. [Configuration (.env File)](#6-configuration-env-file)
7. [Starting the Bot](#7-starting-the-bot)
8. [The Web Dashboard](#8-the-web-dashboard)
9. [Understanding Notifications](#9-understanding-notifications)
10. [Demo Mode vs. Live Mode](#10-demo-mode-vs-live-mode)
11. [Common Issues & Solutions](#11-common-issues--solutions)
12. [Security Tips](#12-security-tips)

---

## 1. What does this bot do?

Trading Department is an automated trading assistant for cryptocurrencies. It:

- **Analyzes the market** automatically (Bitcoin, Ethereum)
- **Detects trading signals** based on market data
- **Executes trades** on your Bitget account (if you choose to)
- **Notifies you** via Discord about all activities

### Who is this bot for?

- You want to trade automatically without constantly watching the market
- You have basic knowledge of cryptocurrencies
- You understand that trading involves risks

### Important Notice

> **Trading involves significant risks!** Only invest money you can afford to lose. Test the bot in demo mode first before using real money.

---

## 2. Prerequisites

Before you start, make sure you have the following:

### What you need:

| What | Why | Difficulty |
|------|-----|------------|
| Computer with internet | Bot runs locally | - |
| Bitget account | This is where trades are executed | Easy |
| Discord account | For notifications | Easy |
| Python 3.10+ | Bot software | Medium |

### Installing Python (if not already installed)

**Windows:**
1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Click on "Download Python 3.11"
3. Start the installation
4. **IMPORTANT:** Check the box "Add Python to PATH"
5. Click "Install Now"

**Mac:**
```bash
# Enter in Terminal:
brew install python
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
```

### Verify Python Installation

Open a terminal (Windows: "cmd" or "PowerShell") and type:

```bash
python --version
```

You should see something like `Python 3.11.x`.

---

## 3. Bitget Account & API Setup

### Step 3.1: Create a Bitget Account

1. Go to [www.bitget.com](https://www.bitget.com)
2. Click on "Sign Up"
3. Enter your email address
4. Create a secure password
5. Verify your email address
6. **Important:** Enable Two-Factor Authentication (2FA)

### Step 3.2: Activate Futures Trading

1. Log in to Bitget
2. Go to "Futures" -> "USDT-M Futures"
3. Accept the terms and conditions for futures trading
4. Transfer some USDT to your futures account

### Step 3.3: Create an API Key

The API key allows the bot to trade on your account.

1. Click on your profile (top right)
2. Go to **"API Management"**
3. Click on **"Create API"**

### Step 3.4: Set API Permissions

**VERY IMPORTANT -- Set the permissions exactly as follows:**

| Permission | Status | Why |
|------------|--------|-----|
| Read | Enable | Bot needs to read account data |
| Trade | Enable | Bot needs to execute trades |
| **Withdraw** | **NEVER enable!** | Protection against theft |

### Step 3.5: Set Up IP Whitelist (Recommended)

For additional security:

1. Find your IP address: Go to [whatismyip.com](https://www.whatismyip.com/)
2. Enter this IP in Bitget under "IP Whitelist"
3. Only from this IP can the bot trade

### Step 3.6: Save Your API Credentials

After creation, you will receive three important pieces of data:

```
API Key:        bg_xxxxxxxxxxxxxxxx
API Secret:     xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Passphrase:     your_chosen_password
```

**Keep these credentials safe!** You will need them later for configuration.

> **Security Notice:** NEVER share these credentials with anyone! Whoever has them can trade on your account.

---

## 4. Discord Notifications Setup

Discord is a chat application through which the bot sends you messages.

### Step 4.1: Create a Discord Account (if not already done)

1. Go to [discord.com](https://discord.com)
2. Click on "Register"
3. Create your account

### Step 4.2: Create or Select a Server

You need a Discord server where you have admin rights:

**Create a new server:**
1. Open Discord
2. Click the **"+"** symbol on the left
3. Select "Create My Own"
4. Give the server a name (e.g., "My Trading Bot")
5. Click "Create"

### Step 4.3: Create a Channel for Bot Messages

1. Right-click on your server (left side)
2. Select "Create Channel"
3. Name it e.g., `#trading-alerts`
4. Click "Create"

### Step 4.4: Create a Webhook

A webhook is like a "phone number" for the channel:

1. Right-click on the `#trading-alerts` channel
2. Select **"Edit Channel"**
3. Click on **"Integrations"** on the left
4. Click on **"Webhooks"**
5. Click on **"New Webhook"**
6. Give the webhook a name (e.g., "Trading Bot")
7. Click on **"Copy Webhook URL"**

The URL looks like this:
```
https://discord.com/api/webhooks/1234567890/abcdefghijklmnop...
```

**Save this URL!** You will need it for configuration.

---

## 5. Download & Install the Bot

### Step 5.1: Download Bot Files

**Option A: With Git (recommended)**

Open a terminal and type:

```bash
git clone https://github.com/yourusername/Bitget-Trading-Bot.git
cd Bitget-Trading-Bot
```

**Option B: Download as ZIP**

1. Go to the bot's GitHub page
2. Click the green "Code" button
3. Select "Download ZIP"
4. Extract the ZIP file to a folder of your choice

### Step 5.2: Open Terminal in the Bot Folder

Navigate to the bot folder:

```bash
cd /path/to/Bitget-Trading-Bot
```

### Step 5.3: Create a Python Environment

A "virtual environment" keeps the bot software separate from other programs:

```bash
# Create the environment
python -m venv venv

# Activate the environment (Windows)
venv\Scripts\activate

# Activate the environment (Mac/Linux)
source venv/bin/activate
```

After activation, you will see `(venv)` at the beginning of the line.

### Step 5.4: Install Required Packages

```bash
pip install -r requirements.txt
```

Wait until all packages are installed. This may take a few minutes.

---

## 6. Configuration (.env File)

The `.env` file contains all important settings for the bot.

### Step 6.1: Copy the Example File

```bash
# Windows
copy .env.example .env

# Mac/Linux
cp .env.example .env
```

### Step 6.2: Edit the .env File

Open the `.env` file with a text editor (Notepad, VS Code, etc.) and fill in the values:

```env
# ============ BITGET API CREDENTIALS ============
# Your API credentials from Step 3.6
BITGET_API_KEY=bg_xxxxxxxxxxxxxxxx
BITGET_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
BITGET_PASSPHRASE=your_password_here
BITGET_TESTNET=false

# ============ DISCORD CONFIGURATION ============
# Your webhook URL from Step 4.4
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# ============ TRADING CONFIGURATION ============
# Maximum trades per day (recommended: 3)
MAX_TRADES_PER_DAY=3

# Daily loss limit in percent (recommended: 5)
DAILY_LOSS_LIMIT_PERCENT=5.0

# Position size in percent of account balance (recommended: 10)
POSITION_SIZE_PERCENT=10.0

# Leverage (recommended: 3, maximum 5)
LEVERAGE=3

# Take profit in percent (recommended: 3.5)
TAKE_PROFIT_PERCENT=3.5

# Stop loss in percent (recommended: 2.0)
STOP_LOSS_PERCENT=2.0

# ============ ASSETS TO TRADE ============
# Which cryptocurrencies should be traded
TRADING_PAIRS=BTCUSDT,ETHUSDT

# ============ TRADING MODE ============
# Demo mode: true = no real trades, false = real trades
DEMO_MODE=true
```

### What do the settings mean?

| Setting | Meaning | Recommendation |
|---------|---------|----------------|
| `MAX_TRADES_PER_DAY` | Maximum number of trades per day | 3 |
| `DAILY_LOSS_LIMIT_PERCENT` | Bot stops when loss reaches this value | 5% |
| `POSITION_SIZE_PERCENT` | How much of the account is used per trade | 10% |
| `LEVERAGE` | Leverage (multiplies both profit AND loss!) | 3x |
| `TAKE_PROFIT_PERCENT` | Take profit at this percentage | 3.5% |
| `STOP_LOSS_PERCENT` | Automatic sell at this loss | 2% |
| `DEMO_MODE` | `true` = simulation, `false` = real trading | true (to start!) |

### Step 6.3: Verify Configuration

```bash
python main.py --status
```

This shows you whether all settings are correct.

---

## 7. Starting the Bot

### Demo Mode (Recommended to Start!)

In demo mode, no real trades are executed. Perfect for testing!

```bash
python main.py
```

You should see:
```
============================================================
BITGET TRADING BOT - STARTING
============================================================
Mode: DEMO (No real trades)
Trading Pairs: BTCUSDT, ETHUSDT
...
Bot is running. Press Ctrl+C to stop.
```

### With Dashboard (Web Interface)

```bash
python main.py --dashboard
```

Then open your browser and go to: http://localhost:8080

### Run Bot in Background (Linux/Mac)

```bash
nohup python main.py > /dev/null 2>&1 &
```

### Stopping the Bot

Press `Ctrl + C` in the terminal.

---

## 8. The Web Dashboard

The dashboard shows you all important information at a glance.

### Starting the Dashboard

```bash
python main.py --dashboard
```

### Opening the Dashboard

Go to: **http://localhost:8080**

### What you see in the dashboard:

| Section | What it shows |
|---------|---------------|
| **Equity Curve** | Development of your account balance over 30 days |
| **Open Positions** | Currently open trades |
| **Trade History** | Past trades with profit/loss |
| **Funding Rates** | Market funding rates |
| **Configuration** | Current settings |
| **Mode Toggle** | Switch between Demo/Live |

### Securing the Dashboard (for advanced users)

If you want to make the dashboard accessible from outside:

1. Generate a secure key:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. Add it to `.env`:
   ```env
   DASHBOARD_API_KEY=your_generated_key
   ```

---

## 9. Understanding Notifications

The bot sends various messages to Discord:

### Trade Entry (New Position Opened)

```
NEW LONG POSITION OPENED

Asset: BTCUSDT
Direction: LONG
Leverage: 3x
Entry Price: $95,000.00
Position Size: 0.015 BTC
Position Value: $1,425.00

Take Profit: $98,325.00 (+3.5%)
Stop Loss: $93,100.00 (-2.0%)

Strategy: Crowded Shorts detected
Confidence: 85%
```

**What does this mean?**
- The bot bought Bitcoin (LONG = betting on rising prices)
- Leverage 3x = profits and losses are tripled
- Take Profit = at this price, the position is automatically sold (profit)
- Stop Loss = at this price, the position is automatically sold (limiting loss)

### Trade Exit (Position Closed)

```
POSITION CLOSED - PROFIT

Asset: BTCUSDT
Direction: LONG
Duration: 4h 23m

Entry: $95,000.00
Exit: $97,500.00

Gross PnL: +$106.87 (+2.63%)
Fees: -$2.85
Funding: +$1.20
Net PnL: +$105.22
```

**What does this mean?**
- The trade was closed with a profit
- Gross PnL = profit before fees
- Fees = trading fees
- Funding = funding rate (can be positive or negative)
- Net PnL = actual profit after all deductions

### Daily Summary

```
DAILY SUMMARY

Date: 2025-01-30
Total Trades: 2
Wins: 1 | Losses: 1
Win Rate: 50%

Total PnL: +$52.30
Max Drawdown: -$48.50
```

### Warnings

```
DAILY LOSS LIMIT REACHED

Current Loss: -5.2%
Limit: -5.0%

Trading halted for today.
```

---

## 10. Demo Mode vs. Live Mode

### Demo Mode (Safe for Testing)

- **No real trades** are executed
- All calculations and notifications work normally
- Perfect for observing the strategy
- **Recommended for at least 1-2 weeks** before going live

**Activate:**
```env
DEMO_MODE=true
```

### Live Mode (Real Trading)

- **Real trades** are executed on Bitget
- **Real money** is involved
- Only use if you understand the strategy

**Activate:**
```env
DEMO_MODE=false
```

### Switching Modes

**Option 1: In the Dashboard**
1. Open http://localhost:8080
2. Click on the Mode button (DEMO/LIVE)
3. Confirm the warning

**Option 2: In the .env File**
1. Open `.env`
2. Change `DEMO_MODE=true` to `DEMO_MODE=false`
3. Restart the bot

### Recommended Approach

1. **Weeks 1-2:** Keep demo mode active
2. **Observe:** Check trades and performance in the dashboard
3. **Understand:** Why were specific trades made?
4. **Decide:** Are you satisfied with the performance?
5. **Go live:** Only if you understand what the bot is doing

---

## 11. Common Issues & Solutions

### Issue: "Bitget API credentials not configured"

**Cause:** API credentials are missing or incorrect.

**Solution:**
1. Check if the `.env` file exists
2. Check if all three values are correct:
   - `BITGET_API_KEY`
   - `BITGET_API_SECRET`
   - `BITGET_PASSPHRASE`
3. No spaces or quotes around the values!

### Issue: "Discord webhook error: 401"

**Cause:** Webhook URL is invalid.

**Solution:**
1. Create a new webhook in Discord (Step 4.4)
2. Copy the new URL
3. Replace the old URL in `.env`

### Issue: "ModuleNotFoundError: No module named 'xyz'"

**Cause:** Python packages are missing.

**Solution:**
```bash
pip install -r requirements.txt
```

### Issue: Bot won't start

**Troubleshooting steps:**

1. **Check Python version:**
   ```bash
   python --version
   ```
   Must be 3.10 or higher!

2. **Virtual environment activated?**
   You should see `(venv)` at the beginning of the line.

3. **Check logs:**
   ```bash
   cat logs/trading_bot.log
   ```

### Issue: No trades are being executed

**Possible causes:**

| Cause | Check | Solution |
|-------|-------|----------|
| Daily limit reached | Dashboard -> Daily Stats | Wait until tomorrow |
| No strong signals | This is normal | Bot is waiting for a good opportunity |
| Open position | Dashboard -> Positions | Bot is waiting for position to close |
| Demo mode active | Check `.env` | `DEMO_MODE=true` is intentional! |

### Issue: Dashboard not accessible

1. Is the bot running with `--dashboard`?
   ```bash
   python main.py --dashboard
   ```

2. Correct port?
   Default: http://localhost:8080

3. Firewall blocking?
   Allow port 8080 in your firewall

---

## 12. Security Tips

### API Key Security

| Rule | Why |
|------|-----|
| **NEVER** enable Withdraw permission | Protection against theft |
| Use IP whitelist | Only your computer can trade |
| NEVER share API credentials | Whoever has them can trade your money |
| NEVER upload the `.env` file | Contains sensitive data |

### Trading Security

| Rule | Why |
|------|-----|
| Use demo mode first | Understand the bot before risking money |
| Start with small positions | `POSITION_SIZE_PERCENT=5` to start |
| Use low leverage | `LEVERAGE=3` or less |
| Only use money you can afford to lose | Trading is risky! |

### Regular Checks

- [ ] Check account balance on Bitget
- [ ] Review bot logs for errors
- [ ] Check the dashboard regularly
- [ ] Read Discord notifications

---

## Summary: Quick Start

1. **Create a Bitget account** and generate an API key
2. **Create a Discord webhook**
3. **Download the bot** and install it
4. **Configure the .env file** with your credentials
5. **Start the bot** with `python main.py --dashboard`
6. **Open the dashboard** at http://localhost:8080
7. **Observe in demo mode for 1-2 weeks**
8. **Activate live mode** when you are ready

---

## Help & Support

If you encounter problems:

1. **Check logs:** `cat logs/trading_bot.log`
2. **Review this guide** again
3. **Open a GitHub issue** for technical problems

---

*Good luck with Trading Department!*
