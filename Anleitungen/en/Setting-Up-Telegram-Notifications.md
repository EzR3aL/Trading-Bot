# Setting Up Telegram Notifications

A step-by-step guide for setting up Telegram notifications for your trading bot.

---

## Table of Contents

1. [What are Telegram Notifications?](#1-what-are-telegram-notifications)
2. [Creating a Telegram Bot via @BotFather](#2-creating-a-telegram-bot-via-botfather)
3. [Finding Your Chat ID](#3-finding-your-chat-id)
4. [Entering Token & Chat ID in the Bot Builder](#4-entering-token--chat-id-in-the-bot-builder)
5. [Sending a Test Message](#5-sending-a-test-message)
6. [Common Issues & Solutions](#6-common-issues--solutions)

---

## 1. What are Telegram Notifications?

Your trading bot can notify you via Telegram about important events:

- **Trade opened** -- Symbol, direction, entry price, leverage
- **Trade closed** -- Profit/loss, duration
- **Bot status** -- Started, stopped
- **Errors** -- When something goes wrong

### Advantages over Discord

| | Telegram | Discord |
|--|----------|---------|
| Mobile push notifications | Instant | Sometimes delayed |
| Setup | Easy | Easy |
| Privacy | Private chat | Server required |
| Speed | Very fast | Fast |

> **Note:** You can use Telegram and Discord simultaneously! Both channels work independently of each other per bot.

---

## 2. Creating a Telegram Bot via @BotFather

The @BotFather is the official Telegram bot for creating new bots. Here is how to proceed:

### Step 1: Open BotFather

1. Open Telegram on your phone or desktop
2. Search for **@BotFather** in the search bar
3. Click on the verified bot (blue checkmark)
4. Click on **"Start"**

### Step 2: Create a New Bot

1. Send the message: `/newbot`
2. BotFather asks for a **name** for your bot
   - Example: `My Trading Bot`
3. BotFather asks for a **username** (must end with `bot`)
   - Example: `my_trading_alerts_bot`

### Step 3: Copy the Token

After creation, you will receive a message like:

```
Done! Congratulations on your new bot.
...
Use this token to access the HTTP API:
6123456789:ABCdefGhIjKlMnOpQrStUvWxYz123456789
```

> **IMPORTANT:** Copy this token and keep it safe! Never share it with anyone -- whoever has the token can send messages through your bot.

---

## 3. Finding Your Chat ID

The Chat ID tells the bot where to send messages.

### Option A: Personal Chat (recommended)

1. Open a chat with your newly created bot
2. Send it any message (e.g., "Hello")
3. Open this URL in your browser (replace `YOUR_TOKEN`):
   ```
   https://api.telegram.org/botYOUR_TOKEN/getUpdates
   ```
4. In the response, you will find your Chat ID:
   ```json
   "chat": {
     "id": 123456789,
     ...
   }
   ```
5. The number at `"id"` is your **Chat ID**

### Option B: Via @userinfobot

1. Search for **@userinfobot** in Telegram
2. Click on **"Start"**
3. The bot responds with your User ID -- this is also your Chat ID

### Option C: Group Chat

If you want to send notifications to a group:

1. Create a Telegram group
2. Add your bot as a member
3. Send a message in the group
4. Open `https://api.telegram.org/botYOUR_TOKEN/getUpdates`
5. The group Chat ID starts with `-` (e.g., `-1001234567890`)

---

## 4. Entering Token & Chat ID in the Bot Builder

1. Open the web dashboard at `http://localhost:5173`
2. Go to **Bots** -> **Create New Bot** (or edit an existing bot)
3. Navigate to **Step 4: Exchange & Mode**
4. Scroll to the **Notifications** section
5. Enter:
   - **Telegram Bot Token**: The token from @BotFather
   - **Telegram Chat ID**: Your Chat ID from Step 3
6. Continue with bot creation or save the changes

> **Tip:** You can use different Telegram channels for different bots!

---

## 5. Sending a Test Message

After saving, you can test whether everything works:

1. Go to the **Bot Detail Page** of the corresponding bot
2. Click on **"Test Telegram"**
3. You should receive a test message in your Telegram chat:

```
Telegram Notification Test

Your Telegram notifications are configured correctly!
2026-02-11 15:30 UTC
```

If the message arrives, everything is set up correctly!

---

## 6. Common Issues & Solutions

### "Failed to send Telegram message"

| Cause | Solution |
|-------|----------|
| Token is wrong | Check the token at @BotFather with `/mybots` |
| Chat ID is wrong | Repeat Step 3 to determine the Chat ID |
| Bot not started | Open a chat with your bot and send `/start` |
| Bot not in group | Add the bot as a member to the group |

### "Unauthorized" Error

- The token is invalid or has been revoked
- Create a new token at @BotFather: `/mybots` -> Select bot -> **API Token** -> **Revoke**

### No Notifications During Live Operation

- Make sure the bot is **started** (green status)
- Check that both token and Chat ID are entered
- Test with the "Test Telegram" button

### Messages Arriving with Delay

- Telegram normally delivers messages in under 1 second
- Check your internet connection
- For group chats: Make sure the bot has admin rights

---

> **Security Notice:** Your Telegram Bot Token is stored encrypted in the database. Nevertheless: Never share your token with third parties and use the bot exclusively for trading notifications.
