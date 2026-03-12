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
7. [Contrarian Pulse](#7-contrarian-pulse)
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
| Contrarian Pulse | Algo | F&G, EMA, RSI, Derivatives | None | Medium | Contrarian scalpers |

### Backtest Results (90 Days, BTCUSDT, $10k, 1h)

| Strategy | Return | Win Rate | Max DD | Sharpe | PF | Trades |
|----------|--------|----------|--------|--------|-----|--------|
| **LiquidationHunter** | +26.2% | 53.9% | 4.7% | 5.51 | 1.98 | 104 |
| **Edge Indicator** | +18.6% | 47.1% | 9.8% | 2.91 | 1.65 | 68 |
| Degen | +0.8% | 40.0% | 3.8% | 0.43 | 1.08 | 35 |
| LLM Signal | +0.8% | 40.0% | 4.5% | 0.51 | 1.12 | 25 |
| Sentiment Surfer | -3.7% | 32.3% | 9.4% | -1.07 | 0.84 | 65 |

### Risk Profile Matrix

| Risk | Strategy | Reason |
|------|----------|--------|
| **Low** | Edge Indicator | Kline data only, clear rules, ADX filter |
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

Sends current market data to an **external AI model** (GPT-4.1, Claude, Llama 4, etc.), which then decides: LONG or SHORT. Each cycle is stateless -- the LLM has no memory of previous trades.

### Who is it for?

- AI enthusiasts who enjoy prompt engineering
- Traders who want to test different LLM providers
- Those who want to write custom analysis prompts

### Special Features

- **9 LLM providers** supported (OpenAI, Anthropic, Gemini Flash, Gemini Pro, Groq, Mistral, xAI, Perplexity, DeepSeek)
- **Custom prompts** possible (max 4000 characters)
- **Model selection** per bot (e.g., GPT-4.1 vs. GPT-4.1 Mini)
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
| GPT-4.1 | ~$0.03 | ~$0.72 |
| GPT-4.1 Mini | ~$0.005 | ~$0.12 |
| Groq (Llama 4 Maverick) | ~$0.003 | ~$0.07 |
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

## 6. Edge Indicator (v2 — Optimized Exits)

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

## 7. Contrarian Pulse

### What does it do?

A **purely algorithmic contrarian strategy** for BTC that uses the Fear & Greed Index as its primary signal. Goes Long on extreme fear (<35), Short on extreme greed (>65). The signal is validated by multiple confirmations.

### Who is it for?

- Traders who prefer contrarian scalping
- Those who want no AI/LLM costs
- Medium risk profile with clear rules

### Data Sources & Confirmations

| # | Source | Logic |
|---|--------|-------|
| 1 | Fear & Greed Index | Primary signal: <35 = Long, >65 = Short |
| 2 | EMA 50/200 | Trend confirmation |
| 3 | RSI (14) | Overbought/oversold |
| 4 | CVD (Cumulative Volume Delta) | Buy/sell pressure |
| 5 | Long/Short Ratio | Crowd positioning |
| 6 | Volume | Volume confirmation |
| 7 | Open Interest | Market engagement |
| 8 | Funding Rate | Contrarian signal |

### Special Features

- **No LLM required** — purely algorithmic
- **HOLD when F&G is neutral** (35-65) — only trades at extremes
- **Backtest-verified** with real market data
- All derivatives data from Binance Futures

### Parameter Recommendations

| Parameter | Conservative | Standard | Aggressive |
|-----------|-------------|----------|------------|
| Leverage | 2x | 3x | 4x |
| Take Profit | 3.0% | 2.5% | 2.0% |
| Stop Loss | 1.5% | 1.5% | 1.0% |
| Position Size | 5% | 10% | 15% |
| Timeframe | 1h | 1h | 30m |

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
  Yes -> Rule-based?
         Yes -> Contrarian Pulse (F&G + confirmations, no LLM)
         No  -> LiquidationHunter (L/S Ratio, Funding)

Do you want a balanced multi-factor approach?
  Yes -> Sentiment Surfer (6 sources, weighted)
```

### Recommendations by Experience Level

| Level | Primary Strategy | Alternative |
|-------|-----------------|-------------|
| Beginner | Edge Indicator | Sentiment Surfer |
| Intermediate | Sentiment Surfer | LiquidationHunter |
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
| Edge Indicator + LLM Signal | Technical + AI analysis |
| Edge Indicator (BTC) + Edge Indicator (ETH) | Same strategy, different assets |
