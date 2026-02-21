# Trading Strategies Overview

All 6 trading strategies explained: how they work, risk profiles, parameter recommendations, and when to use each.

---

## Table of Contents

1. [Strategy Comparison](#1-strategy-comparison)
2. [LiquidationHunter](#2-liquidationhunter)
3. [LLM Signal](#3-llm-signal)
4. [Sentiment Surfer](#4-sentiment-surfer)
5. [Degen](#5-degen)
6. [Edge Indicator](#6-edge-indicator)
7. [Claude Edge Indicator](#7-claude-edge-indicator)
8. [Which Strategy is Right for You?](#8-which-strategy-is-right-for-you)

---

## 1. Strategy Comparison

### Overview Table

| Strategy | Type | Data Sources | API Costs | Risk | Recommended For |
|----------|------|-------------|-----------|------|-----------------|
| LiquidationHunter | Contrarian | L/S, F&G, Funding | None | Medium | Experienced traders |
| LLM Signal | AI | Configurable | LLM API | Variable | AI enthusiasts |
| Sentiment Surfer | Hybrid | 6 sources | None | Medium | Balanced trading |
| Degen | AI Arena | 19 fixed sources | LLM API | High | Experimental |
| Edge Indicator | Technical | Kline only | None | Low-Medium | Beginners / Technical |
| Claude Edge Indicator | Technical+ | Kline+Volume+MTF | None | Low-Medium | Advanced |

### Backtest Results (90 Days, BTCUSDT, $10k, 1h)

| Strategy | Return | Win Rate | Max DD | Sharpe | PF | Trades |
|----------|--------|----------|--------|--------|-----|--------|
| **LiquidationHunter** | +26.2% | 53.9% | 4.7% | 5.51 | 1.98 | 104 |
| **Edge Indicator** | +18.6% | 47.1% | 9.8% | 2.91 | 1.65 | 68 |
| Claude Edge Indicator | +18.6% | 47.1% | 9.8% | 2.91 | 1.65 | 68 |
| Degen | +0.8% | 40.0% | 3.8% | 0.43 | 1.08 | 35 |
| LLM Signal | +0.8% | 40.0% | 4.5% | 0.51 | 1.12 | 25 |
| Sentiment Surfer | -3.7% | 32.3% | 9.4% | -1.07 | 0.84 | 65 |

### Risk Profile Matrix

| Risk | Strategy | Reason |
|------|----------|--------|
| **Low** | Edge Indicator | Kline data only, clear rules, ADX filter |
| **Low-Medium** | Claude Edge Indicator | Edge + dynamic risk management |
| **Medium** | LiquidationHunter | Contrarian with clear signals |
| **Medium** | Sentiment Surfer | Multi-factor, balanced |
| **Medium-High** | LLM Signal | Depends on LLM quality |
| **High** | Degen | Aggressive, 19 sources, fixed prompt |

---

## 2. LiquidationHunter

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

## 3. LLM Signal

### What does it do?

Sends current market data to an **external AI model** (GPT-4, Claude, Llama, etc.), which then decides: LONG or SHORT. Each cycle is stateless -- the LLM has no memory of previous trades.

### Who is it for?

- AI enthusiasts who enjoy prompt engineering
- Traders who want to test different LLM providers
- Those who want to write custom analysis prompts

### Special Features

- **7+ LLM providers** supported (OpenAI, Anthropic, Gemini, Groq, Mistral, xAI, Perplexity, DeepSeek)
- **Custom prompts** possible (max 4000 characters)
- **Model selection** per bot (e.g., GPT-4o vs. GPT-4o-mini)
- **Configurable data sources** (choose which data the LLM receives)

### Parameter Recommendations

| Parameter | Conservative | Standard | Aggressive |
|-----------|-------------|----------|------------|
| Provider | OpenAI | Groq | Any |
| Temperature | 0.2 | 0.4 | 0.6 |
| Timeframe | 4h | 1h | 30m |
| Take Profit | 3.0% | 2.5% | 2.0% |
| Stop Loss | 1.5% | 1.5% | 1.0% |

### Costs

Estimated LLM API costs per analysis cycle:

| Provider | Per Call | Per Day (1h TF, 24 Calls) |
|----------|---------|---------------------------|
| GPT-4o | ~$0.03 | ~$0.72 |
| GPT-4o-mini | ~$0.005 | ~$0.12 |
| Groq (Llama 70B) | ~$0.003 | ~$0.07 |
| DeepSeek | ~$0.002 | ~$0.05 |

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

## 5. Degen

### What does it do?

A **pre-configured AI arena strategy** with a fixed prompt. Collects **19 data sources** and sends everything to an LLM. The user only configures the provider, model, and temperature -- everything else is fixed. Optimized for aggressive 1h BTC predictions.

### Who is it for?

- Experimentally-minded traders
- Those who want to leverage the full range of market data
- Higher risk acceptable

### Special Features

- **19 fixed data sources** (CoinGecko, Binance, Coinbase, Bybit, Deribit)
- **Fixed system prompt** (not modifiable)
- **NEUTRAL is forbidden** -- the LLM must make a decision
- Data includes: options data, volatility index, Coinbase premium, and more

### Parameter Recommendations

| Parameter | Recommendation |
|-----------|----------------|
| Provider | Groq or OpenAI |
| Temperature | 0.3 - 0.5 |
| Timeframe | 1h (firmly recommended) |
| Take Profit | 2.0 - 3.0% |
| Stop Loss | 1.0 - 1.5% |
| Leverage | 3x |

---

## 6. Edge Indicator

### What does it do?

A **purely technical strategy** that exclusively uses kline data (OHLCV) from Binance. No external APIs, maximum reliability. Based on the TradingView "Trading Edge" indicator.

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
| Timeframe | 4h | **1h** | 15m |
| Take Profit | 3.0% | 2.5% | 2.0% |
| Stop Loss | 1.5% | 1.5% | 1.0% |

---

## 7. Claude Edge Indicator

### What does it do?

The **enhanced version of the Edge Indicator** with 6 improvements for smarter risk management:

| Enhancement | Benefit |
|-------------|---------|
| ATR-based TP/SL | Adapts to volatility |
| Volume Confirmation | Confirms signals through volume |
| Multi-Timeframe (4h) | Higher TF as confirmation |
| Trailing Stop | Let profits run |
| Regime-based Sizing | Larger position on stronger signals |
| RSI Divergence | Early reversal detection |

### Who is it for?

- Advanced technical traders
- Those who prefer dynamic risk management
- Traders who like multi-timeframe analysis

### Parameter Recommendations

| Parameter | Conservative | Standard | Aggressive |
|-----------|-------------|----------|------------|
| ATR TP Multiplier | 3.0 | 2.5 | 2.0 |
| ATR SL Multiplier | 2.0 | 1.5 | 1.0 |
| Volume Weight | 0.2 | 0.3 | 0.4 |
| HTF Interval | 4h | 4h | 1h |
| Timeframe | 4h | **1h** | 15m |

---

## 8. Which Strategy is Right for You?

### Decision Tree

```
Are you a beginner?
  Yes -> Edge Indicator (clear rules, no API costs)

Do you want to use AI/LLM?
  Yes -> Want to write custom prompts?
         Yes -> LLM Signal (Custom Prompt)
         No  -> Degen (fixed prompt, 19 data sources)

Do you prefer contrarian trading?
  Yes -> LiquidationHunter (bet against the crowd)

Do you want a balanced multi-factor approach?
  Yes -> Sentiment Surfer (6 sources, weighted)

Do you want advanced risk management?
  Yes -> Claude Edge Indicator (ATR, Volume, Multi-TF)
```

### Recommendations by Experience Level

| Level | Primary Strategy | Alternative |
|-------|-----------------|-------------|
| Beginner | Edge Indicator | LiquidationHunter |
| Intermediate | Claude Edge Indicator | Sentiment Surfer |
| Expert | LLM Signal (Custom Prompt) | Degen |

### Recommendations by Risk Tolerance

| Risk | Strategy | Position Size | Leverage |
|------|----------|--------------|----------|
| Low | Edge Indicator | 5% | 2x |
| Medium | LiquidationHunter | 10% | 3x |
| High | Degen | 15% | 4x |

### Combination Strategies

You can run **multiple bots in parallel**:

| Combination | Benefit |
|-------------|---------|
| Edge Indicator + LiquidationHunter | Technical + contrarian diversification |
| Claude Edge Indicator + LLM Signal | Technical + AI analysis |
| Edge Indicator (BTC) + Edge Indicator (ETH) | Same strategy, different assets |
