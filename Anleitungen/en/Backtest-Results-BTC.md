# Backtest Results BTC (BTCUSDT)

**Date:** February 21, 2026
**Asset:** BTCUSDT (Binance Futures)
**Initial Capital:** $10,000 per backtest

> **Disclaimer:** These results are based solely on historical backtest data and do not constitute investment advice. Past performance does not guarantee future profits. Cryptocurrency trading involves significant risks, including total loss of invested capital. Only trade with capital you can afford to lose.

---

## Overview: 6 Strategies x 7 Timeframes = 42 Backtests

### Edge Indicator

EMA Ribbon + ADX Filter + Predator Momentum. Purely technical strategy without AI.

| Timeframe | Period | Return % | Win Rate | Max DD % | Sharpe | Profit Factor | Trades | End Capital |
|-----------|--------|----------|----------|----------|--------|---------------|--------|-------------|
| 1m | 7 days | -2.09 | 48.7% | 2.51 | 0.11 | 0.80 | 191 | $9,791.45 |
| 5m | 30 days | -1.91 | 42.9% | 7.44 | 0.10 | 0.94 | 196 | $9,808.65 |
| 15m | 90 days | -0.70 | 41.3% | 5.39 | 0.32 | 0.98 | 225 | $9,929.57 |
| 30m | 180 days | +0.05 | 40.7% | 8.16 | 0.41 | 1.00 | 258 | $10,005.09 |
| **1h** | **365 days** | **+17.87** | **41.4%** | **10.97** | **1.84** | **1.16** | **374** | **$11,786.80** |
| **4h** | **365 days** | **+11.73** | **38.1%** | **7.65** | **1.46** | **1.18** | **218** | **$11,172.96** |
| 1d | 365 days | +3.18 | 37.0% | 3.72 | 0.73 | 1.13 | 81 | $10,318.24 |

**Recommendation:** 1h or 4h. Best risk-adjusted return of all strategies (Sharpe 1.84 on 1h). Recommended for beginners.

---

### Liquidation Hunter

Contrarian strategy trading against crowded positions (liquidation heatmap).

| Timeframe | Period | Return % | Win Rate | Max DD % | Sharpe | Profit Factor | Trades | End Capital |
|-----------|--------|----------|----------|----------|--------|---------------|--------|-------------|
| 1m | 7 days | -1.55 | 14.3% | 1.98 | -12.57 | 0.24 | 7 | $9,845.07 |
| 5m | 30 days | -1.32 | 25.6% | 3.41 | -1.93 | 0.92 | 39 | $9,868.48 |
| **15m** | **90 days** | **+2.04** | **30.9%** | **4.14** | **1.07** | **1.14** | **81** | **$10,203.55** |
| 30m | 180 days | -1.79 | 28.6% | 8.08 | -0.54 | 0.99 | 140 | $9,820.81 |
| 1h | 365 days | -11.22 | 26.7% | 15.04 | -1.68 | 0.88 | 281 | $8,878.21 |
| 4h | 365 days | -11.19 | 27.5% | 15.37 | -1.85 | 0.87 | 269 | $8,881.23 |
| 1d | 365 days | -9.88 | 29.1% | 14.73 | -2.15 | 0.82 | 179 | $9,012.26 |

**Recommendation:** 15m (only profitable timeframe). Generally weak performance -- only for experienced traders with their own analysis.

---

### Sentiment Surfer

Combines market sentiment (Fear & Greed, social media) with technical indicators.

| Timeframe | Period | Return % | Win Rate | Max DD % | Sharpe | Profit Factor | Trades | End Capital |
|-----------|--------|----------|----------|----------|--------|---------------|--------|-------------|
| 1m | 7 days | 0.00 | 0.0% | 0.00 | N/A | 0.00 | 0 | $10,000.00 |
| 5m | 30 days | +0.78 | 66.7% | 0.24 | 44.06 | 4.39 | 3 | $10,078.07 |
| 15m | 90 days | -1.17 | 26.1% | 2.15 | -3.53 | 0.74 | 23 | $9,882.70 |
| 30m | 180 days | -1.48 | 28.2% | 2.20 | -3.09 | 0.82 | 39 | $9,851.53 |
| 1h | 365 days | -3.50 | 28.3% | 5.81 | -2.60 | 0.81 | 92 | $9,650.28 |
| 4h | 365 days | -3.30 | 29.1% | 5.09 | -2.83 | 0.80 | 79 | $9,669.65 |
| 1d | 365 days | -1.67 | 31.2% | 2.76 | -2.86 | 0.76 | 32 | $9,833.17 |

**Recommendation:** No clearly profitable timeframe. The strategy generates few signals and was not profitable in the backtest period. Only use in combination with your own market assessment.

---

### Degen (AI Arena)

AI arena with 14 data sources and fixed prompt. Highest profit potential but also highest risk.

| Timeframe | Period | Return % | Win Rate | Max DD % | Sharpe | Profit Factor | Trades | End Capital |
|-----------|--------|----------|----------|----------|--------|---------------|--------|-------------|
| 1m | 7 days | +1.38 | 50.0% | 0.03 | N/A | 62.73 | 2 | $10,138.26 |
| 5m | 30 days | -22.28 | 16.7% | 23.27 | -15.85 | 0.24 | 24 | $7,771.63 |
| 15m | 90 days | -17.19 | 27.9% | 19.62 | -6.10 | 0.58 | 43 | $8,280.65 |
| 30m | 180 days | -9.99 | 36.7% | 21.07 | -2.02 | 0.82 | 60 | $9,000.98 |
| 1h | 365 days | +7.21 | 40.3% | 21.79 | 0.58 | 1.07 | 124 | $10,721.19 |
| **4h** | **365 days** | **+18.83** | **42.0%** | **20.57** | **1.43** | **1.17** | **119** | **$11,883.49** |
| 1d | 365 days | -15.76 | 34.3% | 24.50 | -1.61 | 0.85 | 102 | $8,423.51 |

**Recommendation:** 4h. Highest return of all strategies (+18.83%), but also high drawdowns (20-24% across all timeframes). Only suitable for risk-tolerant traders.

---

### LLM Signal

AI analyzes market data and gives LONG/SHORT recommendations based on LLM analysis.

| Timeframe | Period | Return % | Win Rate | Max DD % | Sharpe | Profit Factor | Trades | End Capital |
|-----------|--------|----------|----------|----------|--------|---------------|--------|-------------|
| 1m | 7 days | -0.32 | 25.0% | 1.00 | -2.93 | 0.71 | 4 | $9,968.45 |
| 5m | 30 days | -4.86 | 15.0% | 5.35 | -13.73 | 0.30 | 20 | $9,513.62 |
| 15m | 90 days | -4.82 | 23.5% | 6.45 | -6.52 | 0.55 | 34 | $9,518.46 |
| 30m | 180 days | -5.91 | 26.8% | 6.96 | -4.63 | 0.65 | 56 | $9,408.66 |
| 1h | 365 days | -8.94 | 26.3% | 9.45 | -4.10 | 0.67 | 95 | $9,106.06 |
| 4h | 365 days | -4.57 | 30.9% | 8.06 | -1.82 | 0.84 | 97 | $9,543.04 |
| 1d | 365 days | -6.51 | 28.8% | 7.76 | -2.98 | 0.74 | 80 | $9,348.88 |

**Recommendation:** No profitable timeframe in the backtest period. The strategy loses on all timeframes. Only use for testing purposes or in combination with other strategies.

---

## Top-5 Ranking (by Sharpe Ratio)

| Rank | Strategy | Timeframe | Return % | Sharpe | Max DD % | Trades |
|------|----------|-----------|----------|--------|----------|--------|
| 1 | Edge Indicator | 1h | +17.87 | 1.84 | 10.97 | 374 |
| 2 | Edge Indicator | 4h | +11.73 | 1.46 | 7.65 | 218 |
| 3 | Degen (AI Arena) | 4h | +18.83 | 1.43 | 20.57 | 119 |
| 4 | Liquidation Hunter | 15m | +2.04 | 1.07 | 4.14 | 81 |

## Recommendations for Beginners

1. **Edge Indicator on 1h** -- Best overall package: high return, good Sharpe, moderate drawdowns
2. **Edge Indicator on 4h** -- Fewer trades, more stable, good Sharpe

## Recommendations for Experienced Traders

1. **Degen on 4h** -- Highest return (+18.83%), but expect ~20% drawdowns
2. **Edge Indicator on 1h** -- Reliable and profitable

---

## Methodology

- **Data Source:** Binance Futures (historical kline data)
- **Periods:** 7 days (1m) to 365 days (1h, 4h, 1d)
- **Initial Capital:** $10,000 per backtest
- **Fees:** Standard taker/maker fees included
- **Slippage:** Not simulated
- **Backtest Date:** February 21, 2026

> **Note:** Backtests simulate ideal execution conditions. In practice, slippage, liquidity and market conditions can affect results. This data serves as orientation and does not replace your own analysis.
