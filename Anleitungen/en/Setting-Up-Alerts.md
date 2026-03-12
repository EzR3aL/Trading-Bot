# Setting Up Alerts

Guide for setting up and managing price, strategy, and portfolio alerts with Discord, Telegram, and WhatsApp notifications.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Price Alerts](#2-price-alerts)
3. [Strategy Alerts](#3-strategy-alerts)
4. [Portfolio Alerts](#4-portfolio-alerts)
5. [Cooldown Configuration](#5-cooldown-configuration)
6. [Discord Notifications](#6-discord-notifications)
7. [Telegram Notifications](#7-telegram-notifications)
8. [WhatsApp Notifications](#8-whatsapp-notifications)
9. [Managing Alerts](#9-managing-alerts)

---

## 1. Overview

The alert system notifies you about important events in your trading. You can create up to **50 alerts** per user.

### Three Alert Types

| Type | Description | Example |
|------|-------------|---------|
| **Price** | Price above/below a threshold | "BTC above $100,000" |
| **Strategy** | Missed signal, low confidence, loss streaks | "3 consecutive losses" |
| **Portfolio** | Daily loss, drawdown, profit target | "Daily loss > 5%" |

### Notification Channels

- **Discord** (webhook per bot)
- **Telegram** (bot token + chat ID per bot)
- **WhatsApp** (WhatsApp Business Cloud API per bot)

---

## 2. Price Alerts

Price alerts notify you when an asset reaches a specific price.

### Creating an Alert

1. Navigate to **Alerts** in the dashboard
2. Click on **"New Alert"**
3. Select the type **"Price"**
4. Configure:

| Field | Description | Example |
|-------|-------------|---------|
| **Symbol** | Trading pair | BTCUSDT |
| **Direction** | `above` or `below` | above |
| **Threshold** | Price in USD | 100000 |
| **Cooldown** | Minutes until the next notification | 60 |

### Example: BTC above $100,000

```
Type:       Price
Symbol:     BTCUSDT
Direction:  above
Threshold:  100000
Cooldown:   60 minutes
```

### Example: ETH below $3,000

```
Type:       Price
Symbol:     ETHUSDT
Direction:  below
Threshold:  3000
Cooldown:   30 minutes
```

---

## 3. Strategy Alerts

Strategy alerts notify you about important events in your trading strategies.

### Available Categories

| Category | Description | When useful |
|----------|-------------|-------------|
| **signal_missed** | Signal was generated but not executed | Check if the bot is running |
| **low_confidence** | Confidence below a threshold | Market conditions are changing |
| **consecutive_losses** | Consecutive losing trades | Review the strategy |

### Example: 3 Consecutive Losses

```
Type:       Strategy
Category:   consecutive_losses
Threshold:  3
Cooldown:   240 minutes (4 hours)
Bot:        (optional) Specific bot
```

### Example: Confidence below 40%

```
Type:       Strategy
Category:   low_confidence
Threshold:  40
Cooldown:   60 minutes
```

---

## 4. Portfolio Alerts

Portfolio alerts monitor your overall trading portfolio.

### Available Categories

| Category | Description | Threshold |
|----------|-------------|-----------|
| **daily_loss** | Daily loss exceeds limit | Loss in % (e.g., 5) |
| **drawdown** | Maximum decline from peak | Drawdown in % (e.g., 10) |
| **profit_target** | Profit target reached | Profit in % (e.g., 20) |

### Example: Daily Loss > 5%

```
Type:       Portfolio
Category:   daily_loss
Threshold:  5
Cooldown:   1440 minutes (24 hours)
```

### Example: Profit Target 20% Reached

```
Type:       Portfolio
Category:   profit_target
Threshold:  20
Cooldown:   1440 minutes (24 hours)
```

### Example: Drawdown > 10%

```
Type:       Portfolio
Category:   drawdown
Threshold:  10
Cooldown:   480 minutes (8 hours)
```

---

## 5. Cooldown Configuration

The **cooldown** prevents you from being flooded with notifications.

### How does the cooldown work?

After an alert is triggered, it is **muted** for the specified duration. Only after that time can it trigger again.

### Recommended Cooldown Values

| Alert Type | Recommended Cooldown | Reason |
|------------|----------------------|--------|
| Price Alert (volatile assets) | 60 minutes | Avoids spam during rapid fluctuations |
| Price Alert (target price) | 1440 minutes (24h) | One notification per day |
| Strategy Alerts | 240 minutes (4h) | Enough time for analysis |
| Daily Loss | 1440 minutes (24h) | Once per day is sufficient |
| Drawdown | 480 minutes (8h) | Regular updates |
| Profit Target | 1440 minutes (24h) | One-time success notification |

### Limits

- Minimum: **1 minute**
- Maximum: **1440 minutes** (24 hours)

---

## 6. Discord Notifications

Alerts are sent via the **bot-specific Discord webhook**.

### Prerequisites

- Discord server with admin rights
- Webhook created for the channel

### Setting Up a Webhook

1. Right-click on the desired Discord channel
2. **Edit Channel** -> **Integrations** -> **Webhooks**
3. Create a **New Webhook**
4. **Copy the Webhook URL**
5. Enter it in the **Bot Builder** (Step 4)

### Notification Format

Discord alerts contain:
- **Alert type** and category
- **Current value** (e.g., current price)
- **Threshold** that was triggered
- **Timestamp**

---

## 7. Telegram Notifications

Alerts can also be sent via Telegram.

### Prerequisites

- Telegram account
- Your own Telegram bot (created via @BotFather)

### Creating a Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Follow the instructions (choose a name and username)
4. You will receive a **Bot Token** (e.g., `123456:ABC-DEF1234...`)
5. Send a message to the new bot
6. Find your **Chat ID**:
   - Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   - The `chat.id` is your Chat ID

### Configuring in the Bot

In the **Bot Builder** (Step 4: Exchange & Mode):
1. Enter the **Bot Token**
2. Enter the **Chat ID**
3. Click on **"Send Test"** to verify the connection

For a detailed guide, see: [Setting-Up-Telegram-Notifications.md](Setting-Up-Telegram-Notifications.md)

---

## 8. WhatsApp Notifications

Alerts can also be sent via WhatsApp using the **WhatsApp Business Cloud API** from Meta.

### Prerequisites

- Meta Business Account
- WhatsApp Business API access (via Meta for Developers)
- Phone Number ID, Access Token, and recipient number

### Setting Up WhatsApp Business API

1. Go to [developers.facebook.com](https://developers.facebook.com/)
2. Create an app with the **WhatsApp** product
3. Navigate to **WhatsApp** -> **API Setup**
4. Note your:
   - **Phone Number ID**: Your WhatsApp Business number ID
   - **Access Token**: Your permanent API token
   - **Recipient Number**: The number to receive messages (with country code, e.g., `4917612345678`)

### Configuring in the Bot

In the **Bot Builder** (Step 4: Exchange & Mode):
1. Enter the **Phone Number ID**
2. Enter the **Access Token**
3. Enter the **Recipient Number**
4. Click on **"Send Test"** to verify the connection

### Notification Format

WhatsApp alerts contain the same information as Discord/Telegram:
- **Alert type** and category
- **Current value** (e.g., current price)
- **Threshold** that was triggered
- **Timestamp**

---

## 9. Managing Alerts

### Alert List

Under **Alerts** in the dashboard, you can see all your alerts with:
- Status (active / paused)
- Type and category
- Threshold
- Number of triggers
- Last trigger time

### Enabling/Disabling Alerts

Click the **toggle button** next to an alert to enable or disable it without deleting it.

### Editing an Alert

Click on an alert to change its settings:
- Adjust the threshold
- Change the cooldown
- Change the direction (for Price Alerts)

### Deleting an Alert

Click on the **delete icon** and confirm.

### Alert History

Under **Alerts** -> **History**, you can see a chronological log of all triggered alerts with:
- Timestamp
- Current value at the time of triggering
- Message text
