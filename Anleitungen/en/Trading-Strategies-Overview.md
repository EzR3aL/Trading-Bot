# Trading Strategies Overview

The 3 available trading strategies explained: how they work, risk profiles, parameter recommendations, and when to use each.

---

## Table of Contents

1. [Strategy Comparison](#1-strategy-comparison)
2. [Edge Indicator](#2-edge-indicator)
3. [LiquidationHunter](#3-liquidationhunter)
4. [Sentiment Surfer](#4-sentiment-surfer)
5. [Which Strategy is Right for You?](#5-which-strategy-is-right-for-you)
6. [Additional Strategies (Currently Unavailable)](#6-additional-strategies-currently-unavailable)

---

## 1. Strategy Comparison

### Overview Table

| Strategy | Type | Data Sources | API Costs | Risk | Recommended For |
|----------|------|-------------|-----------|------|-----------------|
| Edge Indicator | Technical | Kline only | None | Low-Medium | Beginners / Technical |
| LiquidationHunter | Contrarian | L/S, F&G, Funding | None | Medium | Experienced traders |
| Sentiment Surfer | Hybrid | 6 sources | None | Medium | Balanced trading |

### Backtest Results (90 Days, BTCUSDT, $10k, 1h)

| Strategy | Return | Win Rate | Max DD | Sharpe | PF | Trades |
|----------|--------|----------|--------|--------|-----|--------|
| **LiquidationHunter** | +26.2% | 53.9% | 4.7% | 5.51 | 1.98 | 104 |
| **Edge Indicator** | +18.6% | 47.1% | 9.8% | 2.91 | 1.65 | 68 |
| Sentiment Surfer | -3.7% | 32.3% | 9.4% | -1.07 | 0.84 | 65 |

### Risk Profile Matrix

| Risk | Strategy | Reason |
|------|----------|--------|
| **Low** | Edge Indicator | Kline data only, clear rules, ADX filter |
| **Medium** | LiquidationHunter | Contrarian with clear signals |
| **Medium** | Sentiment Surfer | Multi-factor, balanced |

---

## 2. Edge Indicator (v2 — Optimized Exits)

### What does it do?

A **purely technical strategy** that exclusively uses kline data (OHLCV) from Binance. No external APIs, maximum reliability. Based on the TradingView "Trading Edge" indicator.

> **v2 (v3.32.0):** Exit thresholds optimized — trades are held longer, profitable positions run further. A/B test shows +200% return increase on 1h (10 coins, 90d).

### Who is it for?

- Beginners (clear, understandable rules)
- Traders who want no API dependencies
- Those who prefer proven technical analysis

### 3 Layers

1. **EMA Ribbon (8/21)** -- Trend direction
2. **ADX Filter (14)** -- Detect and avoid choppy markets
3. **Predator Momentum Score** -- MACD + RSI + Trend bonus

### Decision Rules

```
LONG:     Bull Trend + ADX > 18 + Bull Momentum
SHORT:    Bear Trend + ADX > 18 + Bear Momentum
NO TRADE: Neutral OR choppy market
```

### Parameter Recommendations

| Parameter | Conservative | Standard | Aggressive |
|-----------|-------------|----------|------------|
| EMA Fast | 8 | 8 | 5 |
| EMA Slow | 21 | 21 | 13 |
| ADX Threshold | 22 | 18 | 15 |
| Momentum Threshold | 0.40 | **0.35** | 0.25 |
| Trailing Trail ATR | 3.0 | **2.5** | 2.0 |
| Trailing Breakeven ATR | 2.0 | **1.5** | 1.0 |
| Momentum Smooth | 7 | **5** | 3 |
| Timeframe | 4h | **1h** | 15m |
| Take Profit | 3.0% | 2.5% | 2.0% |
| Stop Loss | 1.5% | 1.5% | 1.0% |

---

## 3. LiquidationHunter

### What does it do?

Bets **against the crowd**. When too many traders are long (L/S Ratio > 2.5), the bot goes short -- and vice versa. Uses the Fear & Greed Index as an additional contrarian indicator.

### Who is it for?

- Experienced traders who understand contrarian approaches
- Traders who want to exploit extreme market situations
- Those who want no external API costs

### Data Sources

- Long/Short Ratio (Binance Futures)
- Fear & Greed Index (Alternative.me)
- Funding Rate (Binance)
- Open Interest (Binance)
- 24h Ticker (Binance)

### Parameter Recommendations

| Parameter | Conservative | Standard | Aggressive |
|-----------|-------------|----------|------------|
| Leverage | 2x | 3x | 4x |
| Take Profit | 4.0% | 3.5% | 3.0% |
| Stop Loss | 1.5% | 2.0% | 2.5% |
| Position Size | 5% | 10% | 15% |
| Max Trades/Day | 2 | 3 | 4 |

---

## 4. Sentiment Surfer

### What does it do?

Combines **6 different data sources** with configurable weightings. Each source produces a score from -100 to +100. The weighted average determines the final decision.

### Who is it for?

- Traders who prefer a balanced multi-factor approach
- Those who don't want to rely on a single indicator
- Medium risk profile

### 6 Scoring Sources

| # | Source | Weight | Logic |
|---|--------|--------|-------|
| 1 | News Sentiment | 1.0x | Positive media = bullish |
| 2 | Fear & Greed | 1.0x | Contrarian: fear = bullish |
| 3 | VWAP/OIWAP | 1.2x | Price above fair value = bullish |
| 4 | Supertrend | 1.2x | ATR trend: green = bullish |
| 5 | Spot Volume | 0.8x | Buy dominance = bullish |
| 6 | Price Momentum | 0.8x | 24h direction |

### Parameter Recommendations

| Parameter | Conservative | Standard | Aggressive |
|-----------|-------------|----------|------------|
| Min Agreement | 4 | 3 | 2 |
| Min Confidence | 50 | 40 | 30 |
| Take Profit | 3.5% | 3.5% | 3.0% |
| Stop Loss | 1.5% | 1.5% | 2.0% |

---

## 5. Which Strategy is Right for You?

### Decision Tree

```
Are you a beginner?
  Yes -> Edge Indicator (clear rules, no API costs)

Do you prefer contrarian trading?
  Yes -> LiquidationHunter (L/S Ratio, Funding)

Do you want a balanced multi-factor approach?
  Yes -> Sentiment Surfer (6 sources, weighted)
```

### Recommendations by Experience Level

| Level | Primary Strategy | Alternative |
|-------|-----------------|-------------|
| Beginner | Edge Indicator | LiquidationHunter |
| Intermediate | Sentiment Surfer | LiquidationHunter |
| Expert | LiquidationHunter | Sentiment Surfer |

### Recommendations by Risk Tolerance

| Risk | Strategy | Position Size | Leverage |
|------|----------|--------------|----------|
| Low | Edge Indicator | 5% | 2x |
| Medium | LiquidationHunter | 10% | 3x |
| Medium | Sentiment Surfer | 10% | 3x |

### Combination Strategies

You can run **multiple bots in parallel**:

| Combination | Benefit |
|-------------|---------|
| Edge Indicator + LiquidationHunter | Technical + contrarian diversification |
| Edge Indicator + Sentiment Surfer | Technical + multi-factor diversification |
| Edge Indicator (BTC) + Edge Indicator (ETH) | Same strategy, different assets |

---

## 6. Additional Strategies (Currently Unavailable)

The following 3 strategies exist in the system but are currently hidden from regular users:

| Strategy | Reason |
|----------|--------|
| **Contrarian Pulse** | ~70% overlap with LiquidationHunter. Both use similar data sources and contrarian logic, so Contrarian Pulse was hidden in favor of LiquidationHunter. |
| **LLM Signal** | Requires external LLM API keys (OpenAI, Anthropic, Groq, etc.). Currently only available to admin users. |
| **Degen** | Requires external LLM API keys. Aggressive, pre-configured AI prompt with 19 data sources. Currently only available to admin users. |

If an admin grants you access to LLM Signal or Degen, see the [LLM Provider Configuration](../LLM-Provider-Konfiguration.md) guide for setup instructions.
