# Guide: Presets and Bot Builder

A step-by-step guide for creating and using configuration presets in the Bot Builder.

---

## Table of Contents

1. [What are Presets?](#1-what-are-presets)
2. [Creating a Preset](#2-creating-a-preset)
3. [Using a Preset in the Bot Builder](#3-using-a-preset-in-the-bot-builder)
4. [Switching Presets](#4-switching-presets)
5. [Managing Presets](#5-managing-presets)
6. [Exchange Compatibility](#6-exchange-compatibility)
7. [Example Presets](#7-example-presets)
8. [Tips & Best Practices](#8-tips--best-practices)

---

## 1. What are Presets?

Presets are **saved configurations** for your trading bots. Instead of manually entering all parameters each time you create a new bot, you can load a preset and the values are automatically applied.

### Benefits

| Benefit | Description |
|---------|-------------|
| **Time savings** | Load parameters with one click |
| **Consistency** | Same settings for multiple bots |
| **Experimentation** | Save and compare different configurations |
| **Exchange-agnostic** | One preset works on all 5 exchanges (Bitget, Weex, Hyperliquid, Bitunix, BingX) |

### What is saved in a Preset?

- Leverage
- Position size (%)
- Take Profit (%)
- Stop Loss (%)
- Max trades per day
- Daily loss limit
- Trading pairs (e.g., BTCUSDT, ETHUSDT)
- Strategy parameters (e.g., Fear & Greed thresholds)

---

## 2. Creating a Preset

### Step 2.1: Open the Presets Page

1. Click on **"Presets"** in the navigation
2. You will see the list of all saved presets

### Step 2.2: Create a New Preset

1. Click on **"New Preset"** (top right)
2. Fill out the form:

| Field | Description | Example |
|-------|-------------|---------|
| **Name** | Unique name for the preset | "Conservative BTC" |
| **Description** | Brief description | "Low-risk BTC strategy" |
| **Leverage** | Leverage (1-20x) | 3 |
| **Position %** | Percentage of account balance per trade | 5.0 |
| **TP %** | Take Profit in percent | 3.5 |
| **SL %** | Stop Loss in percent | 1.5 |

3. Click on **"Save"**

### Step 2.3: Activate a Preset (optional)

- An active preset is marked as the default for new bots
- Click on **"Activate"** for the desired preset
- The active preset is displayed with an **"ACTIVE"** badge

---

## 3. Using a Preset in the Bot Builder

### Step 3.1: Create a New Bot

1. Go to **"My Bots"**
2. Click on **"New Bot"**

### Step 3.2: Load a Preset

In the first step of the Bot Builder ("Name"), below the Name/Description fields, you will find the option **"Load from Preset"**:

1. Click on the dropdown menu
2. Select a preset from the list
3. The trading parameters are automatically applied:
   - Leverage
   - Position size
   - Take Profit / Stop Loss
   - Trading pairs
   - Strategy parameters

4. You will see the confirmation: **"Preset loaded -- adjust settings as needed"**

### Step 3.3: Adjust Values

After loading, you can still individually modify all values. The preset serves as a starting point -- you are not bound to the values.

### Step 3.4: Complete the Bot

Go through the remaining steps of the Bot Builder:
1. **Strategy** -- Select or confirm the strategy
2. **Trading** -- Review/modify the loaded parameters
3. **Exchange** -- Select the exchange and mode
4. **Schedule** -- Configure the trading rhythm
5. **Overview** -- Review everything and create the bot

---

## 4. Switching Presets

You can also change the preset of an existing bot after creation:

1. Go to **"My Bots"**
2. Find the bot whose preset you want to change
3. **Important:** The bot must be stopped!
4. Click on **"Switch Preset"**
5. Select the new preset
6. The configuration will be updated

> **Note:** When switching presets, the trading parameters are overwritten. Exchange and schedule remain unchanged.

---

## 5. Managing Presets

### Editing a Preset

1. Go to **Presets**
2. Click on **"Edit"** for the desired preset
3. Modify the values
4. Click on **"Save"**

> **Note:** Existing bots using this preset are NOT automatically updated. You need to reload the preset for each bot.

### Duplicating a Preset

- Click on **"Duplicate"** to create a copy
- Useful for testing variations of a configuration

### Deleting a Preset

- Click on **"Delete"** and confirm
- Existing bots are not affected by this

---

## 6. Exchange Compatibility

Presets are **exchange-agnostic** -- they work on all supported exchanges:

| Exchange | Pair Format | Automatic Conversion |
|----------|-------------|----------------------|
| **Bitget** | BTCUSDT | Preset: BTCUSDT -> Bot: BTCUSDT |
| **Weex** | BTCUSDT | Preset: BTCUSDT -> Bot: BTCUSDT |
| **Hyperliquid** | BTC | Preset: BTCUSDT -> Bot: BTC (automatic) |
| **Bitunix** | BTCUSDT | Preset: BTCUSDT -> Bot: BTCUSDT |
| **BingX** | BTC-USDT | Preset: BTCUSDT -> Bot: BTC-USDT (automatic) |

### How does the conversion work?

When you load a preset with the pair `BTCUSDT` on Hyperliquid, it is automatically converted to `BTC`. For BingX, it is converted to `BTC-USDT`. Conversely, for Bitget/Weex/Bitunix, the `USDT` suffix is appended if it is missing.

---

## 7. Example Presets

### Conservative (Beginner)

| Parameter | Value |
|-----------|-------|
| Leverage | 2x |
| Position | 5% |
| Take Profit | 3% |
| Stop Loss | 1.5% |
| Max Trades/Day | 2 |
| Loss Limit | 3% |

### Moderate (Intermediate)

| Parameter | Value |
|-----------|-------|
| Leverage | 4x |
| Position | 7.5% |
| Take Profit | 4% |
| Stop Loss | 2% |
| Max Trades/Day | 3 |
| Loss Limit | 5% |

### Aggressive (Experienced)

| Parameter | Value |
|-----------|-------|
| Leverage | 8x |
| Position | 10% |
| Take Profit | 5% |
| Stop Loss | 2.5% |
| Max Trades/Day | 5 |
| Loss Limit | 8% |

> **Warning:** Aggressive settings significantly increase risk. Only use if you understand the risks!

---

## 8. Tips & Best Practices

### Naming Convention

Use descriptive names for your presets:

```
Conservative BTC          <- clear what it does
Aggressive Multi-Asset    <- risk profile + scope
Rotation 4h ETH           <- strategy + time interval
```

### Preset Strategy

1. **Start conservative** -- Low leverage, small positions
2. **Test in demo mode** -- Simulate every new preset first
3. **Compare presets** -- Create multiple bots with different presets
4. **Document** -- Use the description field for notes

### Common Mistakes to Avoid

| Mistake | Solution |
|---------|----------|
| Leverage too high | Maximum 4x for beginners |
| Positions too large | Maximum 10% per trade |
| No stop loss | ALWAYS set a stop loss |
| Preset never tested | Always test in demo mode first |

---

*Good luck configuring your trading bots!*
