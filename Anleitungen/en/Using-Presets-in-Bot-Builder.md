# Using Presets in the Bot Builder

A guide for creating and using presets when setting up a new bot.

---

## Table of Contents

1. [What are Presets?](#1-what-are-presets)
2. [Creating a Preset](#2-creating-a-preset)
3. [Loading a Preset When Creating a Bot](#3-loading-a-preset-when-creating-a-bot)
4. [Adjusting Settings After Loading](#4-adjusting-settings-after-loading)
5. [Cross-Exchange Presets](#5-cross-exchange-presets)

---

## 1. What are Presets?

Presets are **saved configuration templates** for your bots. Instead of manually entering all settings for each new bot, you can load a preset and have the values automatically applied.

### What is saved in a Preset?

| Setting | Example |
|---------|---------|
| Leverage | 10x |
| Position Size | 100 USDT |
| Take Profit | 2% |
| Stop Loss | 1% |
| Maximum Trades | 5 |
| Daily Loss Limit | 50 USDT |
| Trading Pairs | BTC, ETH, SOL |
| Strategy Settings | Timeframe, indicators |

### Benefits

- **Time savings** -- Configure once, reuse as many times as you want
- **Consistency** -- Same settings for multiple bots
- **Cross-exchange** -- One preset for both Bitget AND Hyperliquid
- **Flexible** -- Always adjustable after loading

---

## 2. Creating a Preset

### Step 1: Open the Presets Page

1. Open the web dashboard
2. Click on **Presets** in the side menu
3. Click on **"Create New Preset"**

### Step 2: Configure the Preset

1. **Name** -- Give your preset a descriptive name
   - Example: `Conservative BTC/ETH`, `Aggressive Altcoins`, `Scalping 5min`

2. **Exchange** -- Select an exchange or **"All Exchanges"**
   - "All Exchanges" makes the preset usable for all 5 exchanges (Bitget, Weex, Hyperliquid, Bitunix, BingX)
   - Trading pairs are automatically converted (see Section 5)

3. **Trading Settings** -- Set the default values:
   - Leverage, position size, TP/SL, etc.

4. **Trading Pairs** -- Select the pairs you want to trade

5. **Strategy** -- Configure the strategy parameters

### Step 3: Save

Click on **"Save"**. The preset now appears in your list and can be loaded when creating a bot.

---

## 3. Loading a Preset When Creating a Bot

### How to Load a Preset

1. Go to **Bots** -> **Create New Bot**
2. In **Step 1 (Name)**, you will see the dropdown **"Load from Preset"**
3. Select a preset from the list
4. The fields are automatically populated:
   - Leverage, position size, TP/SL
   - Maximum trades, loss limit
   - Trading pairs
   - Strategy settings
5. A confirmation message appears: *"Preset loaded -- adjust settings as needed"*

### No Preset Available?

If you have not created any presets yet, a link will be displayed:
**"Create a preset first"** -> Redirects you to the presets page.

---

## 4. Adjusting Settings After Loading

Loading a preset only fills in the fields -- you can **change everything** afterward:

- **Bot Name** -- Not taken from the preset (always enter manually)
- **Exchange** -- Selected separately
- **Individual Values** -- Leverage, TP/SL, etc. can be adjusted after loading
- **Add/Remove Pairs** -- The loaded pairs are just a suggestion

### Example Workflow

1. Load preset "Conservative BTC/ETH"
2. Enter bot name: `BTC Conservative Bitget`
3. Select exchange: Bitget
4. Reduce leverage from 5x to 3x (for even more conservative trading)
5. Create the bot

---

## 5. Cross-Exchange Presets

### What does "cross-exchange" mean?

A preset with exchange type **"All Exchanges"** can be used for all 5 supported exchanges (Bitget, Weex, Hyperliquid, Bitunix, BingX). The trading pairs are automatically adjusted:

### Automatic Pair Conversion

| Preset Pair | Bitget | Hyperliquid |
|-------------|--------|-------------|
| BTC | BTCUSDT | BTC |
| ETH | ETHUSDT | ETH |
| SOL | SOLUSDT | SOL |

- **Bitget** uses the format `SYMBOLUSDT` (e.g., `BTCUSDT`)
- **Hyperliquid** uses the base symbol (e.g., `BTC`)
- The conversion happens **automatically** when loading the preset

### Recommendation

If you run bots on different exchanges, create your presets with **"All Exchanges"**. This way you can use the same strategy on both platforms without having to manually adjust the pairs.

---

> **Tip:** Create different presets for different market conditions -- e.g., a conservative preset for sideways markets and an aggressive one for trending markets. This allows you to quickly switch between strategies.
