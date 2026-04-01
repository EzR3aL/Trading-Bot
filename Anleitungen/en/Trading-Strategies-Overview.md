# Trading Strategies Overview

The 2 available trading strategies explained: how they work, risk profiles, parameter recommendations, and when to use each.

---

## Table of Contents

1. [Strategy Comparison](#1-strategy-comparison)
2. [Edge Indicator](#2-edge-indicator)
3. [LiquidationHunter](#3-liquidationhunter)
4. [Which Strategy is Right for You?](#4-which-strategy-is-right-for-you)

---

## 1. Strategy Comparison

### Overview Table

| Strategy | Type | Data Sources | API Costs | Risk | Recommended For |
|----------|------|-------------|-----------|------|-----------------|
| Edge Indicator | Technical | Kline only | None | Low-Medium | Beginners / Technical |
| LiquidationHunter | Contrarian | L/S, F&G, Funding | None | Medium | Experienced traders |

### Backtest Results (90 Days, BTCUSDT, $10k, 1h)

| Strategy | Return | Win Rate | Max DD | Sharpe | PF | Trades |
|----------|--------|----------|--------|--------|-----|--------|
| **LiquidationHunter** | +26.2% | 53.9% | 4.7% | 5.51 | 1.98 | 104 |
| **Edge Indicator** | +18.6% | 47.1% | 9.8% | 2.91 | 1.65 | 68 |

### Risk Profile Matrix

| Risk | Strategy | Reason |
|------|----------|--------|
| **Low** | Edge Indicator | Kline data only, clear rules, ADX filter |
| **Medium** | LiquidationHunter | Contrarian with clear signals |

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

## 4. Which Strategy is Right for You?

### Decision Tree

```
Are you a beginner?
  Yes -> Edge Indicator (clear rules, no API costs)

Do you prefer contrarian trading?
  Yes -> LiquidationHunter (L/S Ratio, Funding)

Unsure?
  -> Edge Indicator to start, add LiquidationHunter later
```

### Recommendations by Experience Level

| Level | Primary Strategy | Alternative |
|-------|-----------------|-------------|
| Beginner | Edge Indicator | -- |
| Intermediate | Edge Indicator | LiquidationHunter |
| Expert | LiquidationHunter | Edge Indicator |

### Recommendations by Risk Tolerance

| Risk | Strategy | Position Size | Leverage |
|------|----------|--------------|----------|
| Low | Edge Indicator | 5% | 2x |
| Medium | LiquidationHunter | 10% | 3x |

### Combination Strategies

You can run **multiple bots in parallel**:

| Combination | Benefit |
|-------------|---------|
| Edge Indicator + LiquidationHunter | Technical + contrarian diversification |
| Edge Indicator (BTC) + Edge Indicator (ETH) | Same strategy, different assets |
| LiquidationHunter (BTC) + Edge Indicator (ETH) | Different strategies per asset |

