# Portfolio View

Guide for the multi-exchange portfolio overview.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Portfolio Summary](#2-portfolio-summary)
3. [Live Positions](#3-live-positions)
4. [Daily PnL Charts](#4-daily-pnl-charts)
5. [Allocation View](#5-allocation-view)
6. [Filters and Settings](#6-filters-and-settings)

---

## 1. Overview

The Portfolio View provides a **cross-exchange overview** of all your trading activities. Instead of checking each exchange separately, you see everything on one page.

### Prerequisites

- At least one exchange connected (Settings -> API Keys)
- At least one completed trade (for statistics)

### Features

| Feature | Description |
|---------|-------------|
| **Portfolio Summary** | Aggregated PnL per exchange |
| **Live Positions** | Real-time positions from all exchanges |
| **Daily PnL Charts** | Stacked bar chart per exchange |
| **Allocation View** | Capital distribution across exchanges |

---

## 2. Portfolio Summary

### What does the Summary show?

The Portfolio Summary aggregates all completed trades and shows:

| Metric | Description |
|--------|-------------|
| **Total PnL** | Total profit/loss across all exchanges |
| **Total Trades** | Total number of trades |
| **Win Rate** | Winning trades / total trades in % |
| **Total Fees** | Total trading fees |
| **Total Funding** | Total funding payments |

### Exchange Cards

For each connected exchange, you see a separate card with:

- **Exchange name** and logo
- **PnL** for the selected time period
- **Trade count** (total and won)
- **Win Rate** for the exchange
- **Fees** and **Funding** totals

### Example

```
Total Portfolio:  +$2,340.50  |  210 Trades  |  58.1% Win Rate

Bitget:           +$1,580.30  |  140 Trades  |  60.0% Win Rate
Hyperliquid:      +$760.20    |  70 Trades   |  54.3% Win Rate
```

---

## 3. Live Positions

### What does the Position Table show?

All currently open positions from **all connected exchanges** in a single table:

| Column | Description |
|--------|-------------|
| **Exchange** | Which exchange the position is on |
| **Symbol** | Trading pair (e.g., BTCUSDT) |
| **Direction** | LONG or SHORT |
| **Size** | Position size |
| **Entry Price** | Entry price |
| **Current Price** | Current market price |
| **Unrealized PnL** | Unrealized profit/loss |
| **Leverage** | Leverage used |
| **Margin** | Margin deposited |

### Real-Time Updates

Positions are fetched fresh from the exchanges on each page load. Each exchange has a timeout of 10 seconds -- if one exchange does not respond, the others are still displayed.

---

## 4. Daily PnL Charts

### Stacked Bar Chart

The chart shows the **daily PnL per exchange** as stacked bars:

- **Positive days**: Bars upward
- **Negative days**: Bars downward
- **Colors**: Each exchange has its own color

### Selecting a Time Period

You can filter by time period:
- 7 days
- 14 days
- 30 days (default)
- 90 days
- 365 days

### What can you learn from this?

- **Which exchange performs best?** -> Largest positive bars
- **Are there loss streaks?** -> Multiple red days in a row
- **Diversification** -> Are the exchanges correlated or independent?

---

## 5. Allocation View

### Capital Distribution

The Allocation View shows how your capital is distributed across the various exchanges:

- **PnL share** per exchange
- **Trade share** per exchange
- **Percentage share** of the total portfolio

### When is the Allocation important?

- **Too much on one exchange?** -> Risk from exchange outages
- **Uneven performance?** -> Consider switching strategy or exchange
- **Check diversification** -> Ideal: Capital distributed across multiple exchanges

---

## 6. Filters and Settings

### Demo/Live Filter

You can filter between different modes:

| Filter | Shows |
|--------|-------|
| **All** | All trades (Demo + Live) |
| **Live** | Only real trades |
| **Demo** | Only simulated trades |

### Time Period

Select the time period for statistics:
- Default: 30 days
- Minimum: 1 day
- Maximum: 365 days
