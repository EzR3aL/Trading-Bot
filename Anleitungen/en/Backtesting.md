# Backtesting Guide

How to create and run backtests and interpret the results.

---

## Table of Contents

1. [What is Backtesting?](#1-what-is-backtesting)
2. [Creating a Backtest](#2-creating-a-backtest)
3. [Interpreting Results](#3-interpreting-results)
4. [Comparing Strategies](#4-comparing-strategies)
5. [Tips for Meaningful Backtests](#5-tips-for-meaningful-backtests)

---

## 1. What is Backtesting?

Backtesting simulates a trading strategy with **historical market data**. You can test how a strategy would have performed in the past before risking real money.

### Available Since

Version **3.3.1** (February 2026). Fully integrated in the frontend.

### Supported Strategies

All 6 strategies can be tested:
- LiquidationHunter
- LLM Signal
- Sentiment Surfer
- Degen
- Edge Indicator
- Claude Edge Indicator

---

## 2. Creating a Backtest

### Step 1: Open the Backtest Page

Navigate to the **"Backtest"** page in the left sidebar of the dashboard.

### Step 2: Choose Configuration

| Setting | Description | Recommendation |
|---------|-------------|----------------|
| **Strategy** | Which trading strategy to test | Edge Indicator for beginners |
| **Trading Pair** | BTCUSDT, ETHUSDT, SOLUSDT, etc. | BTCUSDT |
| **Timeframe** | Candle interval: 1m, 5m, 15m, 30m, 1h, 4h, 1D | **1h** (best accuracy/speed ratio) |
| **Start Date** | Beginning of the test period | 90 days back |
| **End Date** | End of the test period | Today |
| **Initial Capital** | Simulated starting capital in USD | $10,000 |
| **Leverage** | Leverage multiplier | 3x |
| **Take Profit** | Profit target in % | 3.5% |
| **Stop Loss** | Loss limit in % | 2.0% |

### Step 3: Start the Backtest

Click on **"Start Backtest"**. The backtest runs in the background -- you can leave the page and return later.

### Step 4: View Results

After completion, the page shows:
- **Equity Curve** (capital progression)
- **Metrics Cards** (Return, Win Rate, Drawdown, etc.)
- **Trade Log** (all simulated trades)

---

## 3. Interpreting Results

### Key Metrics

| Metric | Meaning | Good Value |
|--------|---------|------------|
| **Total Return** | Overall return in % | > 10% (90 days) |
| **Win Rate** | Percentage of winning trades | > 45% |
| **Max Drawdown** | Maximum capital decline | < 10% |
| **Sharpe Ratio** | Return relative to risk | > 2.0 |
| **Profit Factor** | Ratio of wins to losses | > 1.5 |
| **Total Trades** | Number of executed trades | Depends on timeframe |

### Reading the Equity Curve

The equity curve shows the **capital progression** over the test period:

- **Steadily rising**: Good sign -- strategy is consistently profitable
- **Sharp swings**: High volatility -- check risk parameters
- **Long plateaus**: Few trades or sideways market
- **Steep drop**: Drawdown phase -- check if temporary or systemic

### Understanding the Trade Log

Each trade in the log shows:

| Column | Description |
|--------|-------------|
| Date | Entry timestamp |
| Symbol | Trading pair |
| Direction | LONG or SHORT |
| Entry Price | Entry price |
| Exit Price | Exit price |
| PnL | Profit/loss in USD |
| PnL % | Profit/loss in percent |
| Duration | Holding time |

### Warning Signs

- **Win Rate < 35%**: Strategy generates too many losing trades
- **Max Drawdown > 15%**: Too much risk, reduce position size
- **Profit Factor < 1.0**: Strategy is net unprofitable
- **Sharpe Ratio < 0**: Return is negative or too volatile
- **Few Trades (< 20)**: Not statistically significant

---

## 4. Comparing Strategies

### Comparison Approach

Run multiple backtests with **identical parameters** and compare:

1. **Same time period** for all strategies
2. **Same trading pair** (e.g., BTCUSDT)
3. **Same timeframe** (e.g., 1h)
4. **Same capital and leverage**

### Comparison Checklist

| Criterion | Weight | Why |
|-----------|--------|-----|
| Sharpe Ratio | High | Best measure for risk-adjusted return |
| Max Drawdown | High | Protects against excessive losses |
| Profit Factor | Medium | Shows whether wins exceed losses |
| Total Return | Medium | Absolute performance |
| Win Rate | Low | Not meaningful alone (consider R/R) |

### Example Comparison

```
Strategy A: Return +26%, Win Rate 54%, Drawdown 4.7%, Sharpe 5.51
Strategy B: Return +18%, Win Rate 47%, Drawdown 9.8%, Sharpe 2.91

-> Strategy A is better: Higher return with lower risk
```

---

## 5. Tips for Meaningful Backtests

### Do's

- **Test at least 90 days** -- Shorter periods are statistically unreliable
- **Use 1h timeframe** -- Best balance of accuracy and signal quality
- **Test different market phases** -- Bull, bear, and sideways
- **Compare with buy-and-hold** -- Does the strategy outperform simple holding?
- **Check the max drawdown** -- Could you emotionally handle this loss?

### Don'ts

- **Don't over-optimize** -- Perfect backtest parameters often don't work live
- **Don't focus only on win rate** -- A bot with 40% win rate can be profitable (if R/R is good)
- **Don't use very short periods** -- 7 days tell you nothing
- **Don't expect backtest = live** -- Slippage, fees, and timing differ in live trading

### Next Steps After Backtesting

1. **Found the best backtest?** -> Run in demo mode for 1-2 weeks
2. **Demo performance good?** -> Go live with small capital
3. **Live performance matches?** -> Gradually increase position size
