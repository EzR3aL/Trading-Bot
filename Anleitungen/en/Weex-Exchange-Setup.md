# Weex Exchange Setup

Guide for setting up the Weex exchange in Trading Department.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Creating a Weex Account](#2-creating-a-weex-account)
3. [Creating an API Key](#3-creating-an-api-key)
4. [Configuring in the Bot](#4-configuring-in-the-bot)
5. [Demo vs. Live Mode](#5-demo-vs-live-mode)
6. [Troubleshooting](#6-troubleshooting)

---

## 1. Overview

**Weex** is a crypto futures exchange supported in Trading Department as an alternative to Bitget and Hyperliquid.

### Weex Comparison

| Feature | Weex | Bitget | Hyperliquid |
|---------|------|--------|-------------|
| Auth Type | API Key | API Key | Wallet |
| Passphrase | Yes | Yes | No |
| Demo Mode | Yes | Yes | Yes |
| Futures Trading | Yes (USDT-M) | Yes (USDT-M) | Yes (Perp) |

---

## 2. Creating a Weex Account

### Step 1: Registration

1. Go to [www.weex.com](https://www.weex.com)
2. Click on **"Sign Up"**
3. Enter your email address
4. Create a secure password
5. Verify your email address

### Step 2: Verification (KYC)

1. Log in to Weex
2. Navigate to **Profile** -> **Verification**
3. Upload an ID document
4. Wait for approval (usually within 24 hours)

### Step 3: Activate Futures Trading

1. Navigate to **Futures** -> **USDT-M Futures**
2. Accept the terms and conditions
3. Transfer USDT to your futures account

---

## 3. Creating an API Key

### Step 1: Open API Management

1. Click on your profile icon (top right)
2. Go to **"API Management"**
3. Click on **"Create API"**

### Step 2: Set Permissions

**IMPORTANT -- Set the permissions exactly as follows:**

| Permission | Status | Why |
|------------|--------|-----|
| Read | Enable | Bot needs to read account data |
| Trade | Enable | Bot needs to execute trades |
| **Withdraw** | **NEVER enable!** | Protection against theft |

### Step 3: Set a Passphrase

Choose a **secure passphrase**. This is required in addition to the API key and secret.

### Step 4: IP Whitelist (recommended)

For maximum security:
1. Find your IP address: [whatismyip.com](https://www.whatismyip.com/)
2. Enter the IP at Weex under **"IP Whitelist"**

### Step 5: Save Credentials Securely

After creation, you will receive three important pieces of data:

```
API Key:      wx_xxxxxxxxxxxxxxxx
API Secret:   xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Passphrase:   your_chosen_password
```

**Keep these credentials safe!** The API Secret is only shown once.

---

## 4. Configuring in the Bot

### Step 1: Open Settings

In the dashboard, navigate to **Settings** (gear icon).

### Step 2: Select the "API Keys" Tab

Click on the **"API Keys"** tab.

### Step 3: Add Weex

1. Select **"Weex"** as the exchange
2. Enter:
   - **API Key**: Your Weex API key
   - **API Secret**: Your Weex API secret
   - **Passphrase**: Your chosen passphrase
3. Click on **"Save"**

The API credentials are stored **encrypted** in the database.

### Step 4: Test the Connection

Click on **"Test Connection"**. You should see a success message.

### Step 5: Create a Bot

In the **Bot Builder**:
1. Select **"Weex"** as the exchange
2. Select the mode: **Demo** or **Live**
3. Configure the remaining settings (strategy, pairs, etc.)
4. Create and start the bot

---

## 5. Demo vs. Live Mode

### Demo Mode

- **No real trades** -- everything is simulated
- Uses the **demo trading API** from Weex
- Perfect for testing a new strategy
- **Recommended for at least 1-2 weeks** before live trading

### Live Mode

- **Real trades** on Weex
- **Real money** is involved
- All safety mechanisms active (TP/SL, daily loss limit)

### Selecting Mode in the Bot Builder

When creating a bot (Step 4):
- **Demo**: Select `demo` as the mode
- **Live**: Select `live` as the mode
- **Both**: Bot runs in both modes in parallel

### Switching from Demo to Live

1. Stop the bot
2. Edit the bot (pencil icon)
3. Change the mode from `demo` to `live`
4. Save and restart

---

## 6. Troubleshooting

### Issue: "API credentials invalid"

| Cause | Solution |
|-------|----------|
| Incorrect credentials | Check API key, secret, and passphrase |
| Spaces | Remove spaces at the beginning/end |
| Key expired | Create a new API key on Weex |
| IP not whitelisted | Add your current IP to the whitelist |

### Issue: "Insufficient balance"

| Cause | Solution |
|-------|----------|
| No USDT in futures account | Transfer USDT from spot to futures |
| Position size too large | Reduce `position_size_percent` |
| Wrong account | Check if USDT is in the USDT-M futures account |

### Issue: "Order rejected"

| Cause | Solution |
|-------|----------|
| Symbol not supported | Check if the trading pair is available on Weex |
| Order too small | Observe minimum order size |
| Leverage not set | Bot sets leverage automatically |

### Issue: "Connection timeout"

| Cause | Solution |
|-------|----------|
| Weex API unreachable | Wait and try again |
| Network issue | Check your internet connection |
| Rate limit | Bot has a built-in rate limiter |

### Issue: Demo mode not working

1. Check if the API keys are authorized for demo trading
2. Some Weex regions have restricted demo access
3. Try the Bitget demo mode as an alternative

### Checking Logs

```bash
# View latest log entries
tail -f logs/trading_bot.log

# Search for Weex-specific errors
grep -i "weex" logs/trading_bot.log
```
