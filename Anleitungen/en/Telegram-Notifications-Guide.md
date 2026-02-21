# Guide: Setting Up Telegram Notifications

A step-by-step guide to activate Telegram notifications for your trading bot.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Creating a Telegram Bot](#2-creating-a-telegram-bot)
3. [Finding Your Chat ID](#3-finding-your-chat-id)
4. [Configuring in the Bot Builder](#4-configuring-in-the-bot-builder)
5. [Sending a Test Message](#5-sending-a-test-message)
6. [Understanding Notifications](#6-understanding-notifications)
7. [Common Issues & Solutions](#7-common-issues--solutions)

---

## 1. Overview

Each trading bot can receive its own Telegram notifications. You will receive messages for:

- **Trade Entry** -- When a new position is opened
- **Trade Exit** -- When a position is closed (with PnL)
- **Bot Status** -- Start, stop, errors
- **Error Messages** -- When something goes wrong

### Why Telegram?

| Benefit | Description |
|---------|-------------|
| **Instant** | Push notifications on your phone |
| **Free** | No fees |
| **Per Bot** | Each bot has its own channel |
| **Combinable** | Works alongside Discord |

---

## 2. Creating a Telegram Bot

### Step 2.1: Open BotFather

1. Open Telegram on your phone or desktop
2. Search for **@BotFather** (the official Telegram bot creator)
3. Start a chat with BotFather

### Step 2.2: Create a New Bot

1. Send the message: `/newbot`
2. BotFather asks: **"Alright, a new bot. How are we going to call it?"**
3. Give your bot a name, e.g.: `My Trading Bot`
4. BotFather asks: **"Good. Now let's choose a username..."**
5. Enter a unique username, e.g.: `my_trading_alert_bot`
   - Must end with `_bot`
   - Must not already be taken

### Step 2.3: Copy the Token

After creation, you will receive a message with your **Bot Token**:

```
Done! Congratulations on your new bot.
...
Use this token to access the HTTP API:
7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Copy this token!** You will need it in the Bot Builder.

> **Security Notice:** NEVER share this token with anyone! Whoever has the token can send messages through your bot.

---

## 3. Finding Your Chat ID

The Chat ID tells the bot where to send messages.

### Option A: Personal Messages (Recommended)

1. Open Telegram and search for the bot you just created
2. Click on **"Start"** or send `/start`
3. Now open the following URL in your browser:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
   Replace `<YOUR_TOKEN>` with your bot token.

4. You will see a response like:
   ```json
   {
     "result": [{
       "message": {
         "chat": {
           "id": 123456789,
           "type": "private"
         }
       }
     }]
   }
   ```

5. The number at `"id"` is your **Chat ID** (e.g., `123456789`)

### Option B: Group Chat

If you want to receive notifications in a group:

1. Create a Telegram group
2. Add your bot as a member
3. Send a message in the group
4. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
5. The group Chat ID starts with `-` (e.g., `-1001234567890`)

---

## 4. Configuring in the Bot Builder

### Step 4.1: Create or Edit a Bot

1. Go to **My Bots**
2. Click on **"New Bot"** or edit an existing bot

### Step 4.2: Exchange Step (Step 4 in the Builder)

In the **"Exchange"** step of the Bot Builder, you will find the Telegram fields:

| Field | Value | Example |
|-------|-------|---------|
| **Telegram Bot Token** | The token from Step 2.3 | `7123456789:AAHxxx...` |
| **Telegram Chat ID** | The ID from Step 3 | `123456789` |

### Step 4.3: Enter and Save

1. Enter the **Bot Token**
2. Enter the **Chat ID**
3. Continue with the next steps or save the bot

> **Note:** Telegram fields are optional. If you leave them empty, no Telegram messages will be sent. You can add them at any time later.

---

## 5. Sending a Test Message

After creating the bot, you can test the Telegram connection:

1. Go to the **Bot Detail Page** (click on the bot name)
2. Under the configuration, you will see **"Telegram configured"**
3. Click on **"Test Telegram"**
4. You should receive a test message in your Telegram chat

If no message arrives:
- Check if you started the bot in Telegram (`/start`)
- Check the token and Chat ID for typos
- Make sure the bot token is valid

---

## 6. Understanding Notifications

### Trade Entry

```
TRADE OPENED

Bot: Alpha Bot
Symbol: BTCUSDT
Direction: LONG
Entry Price: $95,000.00
Size: 0.015
Leverage: 3x
Take Profit: $98,325.00
Stop Loss: $93,100.00
Confidence: 85%
Mode: DEMO
```

### Trade Exit

```
TRADE CLOSED - PROFIT

Bot: Alpha Bot
Symbol: BTCUSDT
Direction: LONG
Entry: $95,000.00
Exit: $97,500.00
PnL: +$106.87 (+2.63%)
Fees: $2.85
Duration: 4h 23m
Mode: DEMO
```

### Bot Status

```
BOT STATUS: STARTED

Bot: Alpha Bot
Exchange: bitget
Mode: DEMO
```

### Error

```
BOT ERROR

Bot: Alpha Bot
Error: Connection timeout
Details: Exchange API not responding
```

---

## 7. Common Issues & Solutions

### Issue: No messages are arriving

| Check | Solution |
|-------|----------|
| Bot started in Telegram? | Open the bot and send `/start` |
| Token correct? | Compare with the BotFather message |
| Chat ID correct? | Re-check via `/getUpdates` |
| Bot running? | Bot must be started for messages |

### Issue: "Unauthorized" error

**Cause:** Bot token is invalid or expired.

**Solution:**
1. Go to @BotFather
2. Send `/mybots`
3. Select your bot
4. Click on "API Token" > "Revoke current token"
5. Copy the new token
6. Update the token in the Bot Builder

### Issue: "Chat not found" error

**Cause:** Chat ID is wrong or bot was not started.

**Solution:**
1. Open the bot in Telegram
2. Send `/start`
3. Retrieve the Chat ID again via `/getUpdates`

### Issue: Messages arriving twice

**Cause:** Both Discord and Telegram are configured.

**Solution:** This is normal! Both channels work independently. If you only want one channel, leave the fields of the other empty.

---

## Summary: Quick Setup

1. Open **@BotFather** in Telegram
2. Send `/newbot` and create a bot
3. **Copy the token**
4. **Start** the bot in Telegram (`/start`)
5. **Find the Chat ID** via `/getUpdates`
6. Enter the **Token + Chat ID** in the **Bot Builder**
7. **Send a test message** from the bot detail page

---

*Done! Your bot now sends notifications directly to your phone.*
