# Strategien-Uebersicht

Die 2 verfuegbaren Trading-Strategien erklaert: Funktionsweise, Risikoprofil, Parameter-Empfehlungen und wann welche Strategie sinnvoll ist.

---

## Inhaltsverzeichnis

1. [Strategie-Vergleich](#1-strategie-vergleich)
2. [Edge Indicator](#2-edge-indicator)
3. [LiquidationHunter](#3-liquidationhunter)
4. [Welche Strategie passt zu mir?](#4-welche-strategie-passt-zu-mir)
---

## 1. Strategie-Vergleich

### Uebersichts-Tabelle

| Strategie | Typ | Datenquellen | API-Kosten | Risiko | Empfohlen fuer |
|-----------|-----|-------------|------------|--------|----------------|
| Edge Indicator | Technisch | Nur Klines | Keine | Niedrig-Mittel | Anfaenger/Technisch |
| LiquidationHunter | Contrarian | L/S, F&G, Funding | Keine | Mittel | Erfahrene Trader |

### Backtest-Ergebnisse (90 Tage, BTCUSDT, $10k, 1h)

| Strategie | Return | Win Rate | Max DD | Sharpe | PF | Trades |
|-----------|--------|----------|--------|--------|-----|--------|
| **LiquidationHunter** | +26.2% | 53.9% | 4.7% | 5.51 | 1.98 | 104 |
| **Edge Indicator** | +18.6% | 47.1% | 9.8% | 2.91 | 1.65 | 68 |

### Risikoprofil-Matrix

| Risiko | Strategie | Begruendung |
|--------|-----------|-------------|
| **Niedrig** | Edge Indicator | Nur Kline-Daten, klare Regeln, ADX-Filter |
| **Mittel** | LiquidationHunter | Contrarian mit klaren Signalen |

---

## 2. Edge Indicator (v2 — optimierte Exits)

### Was macht sie?

Eine **rein technische Strategie**, die ausschliesslich Kline-Daten (OHLCV) von Binance verwendet. Keine externen APIs, maximale Zuverlaessigkeit. Basiert auf dem TradingView "Trading Edge" Indikator.

> **v2 (v3.32.0):** Exit-Schwellen optimiert — Trades werden laenger gehalten, profitable Positionen laufen weiter. A/B-Test zeigt +200% Return-Steigerung auf 1h (10 Coins, 90d).

### Fuer wen?

- Anfaenger (klare, verstaendliche Regeln)
- Trader, die keine API-Abhaengigkeiten wollen
- Wer eine bewaehrte technische Analyse bevorzugt

### 3 Schichten

1. **EMA Ribbon (8/21)** -- Trend-Richtung
2. **ADX Filter (14)** -- Choppy Market erkennen und vermeiden
3. **Predator Momentum Score** -- MACD + RSI + Trend-Bonus

### Entscheidungsregeln

```
LONG:  Bull Trend + ADX > 18 + Bull Momentum
SHORT: Bear Trend + ADX > 18 + Bear Momentum
KEIN TRADE: Neutral ODER choppy Market
```

### Parameter-Empfehlungen

| Parameter | Konservativ | Standard |
|-----------|------------|----------|
| EMA Fast | 8 | 8 |
| EMA Slow | 21 | 21 |
| ADX Threshold | 22 | 18 |
| Momentum Threshold | 0.40 | **0.35** |
| Trailing Trail ATR | 3.0 | **2.5** |
| Trailing Breakeven ATR | 2.0 | **1.5** |
| Momentum Smooth | 7 | **5** |
| Timeframe | 4h | **1h** |
| Take Profit | 3.0% | 2.5% |
| Stop Loss | 1.5% | 1.5% |

> **Hinweis:** Das Aggressiv-Profil (15m) wurde in v4.6.2 entfernt. Simulationen zeigten eine Winrate von nur 27% und -7.27% PnL. Es stehen nur noch Standard (1h) und Konservativ (4h) zur Verfuegung.

---

## 3. LiquidationHunter

### Was macht sie?

Wettet **gegen die Masse**. Wenn zu viele Trader Long sind (L/S Ratio > 2.5), geht der Bot Short -- und umgekehrt. Nutzt den Fear & Greed Index als zusaetzlichen Contrarian-Indikator.

### Fuer wen?

- Erfahrene Trader, die Contrarian-Ansaetze verstehen
- Trader, die Extremsituationen im Markt nutzen wollen
- Wer keine externen API-Kosten moechte

### Datenquellen

- Long/Short Ratio (Binance Futures)
- Fear & Greed Index (Alternative.me)
- Funding Rate (Binance)
- Open Interest (Binance)
- 24h Ticker (Binance)

### Parameter-Empfehlungen

| Parameter | Konservativ | Standard | Aggressiv |
|-----------|------------|----------|-----------|
| Leverage | 2x | 3x | 4x |
| Take Profit | 4.0% | 3.5% | 3.0% |
| Stop Loss | 1.5% | 2.0% | 2.5% |
| Position Size | 5% | 10% | 15% |
| Max Trades/Tag | 2 | 3 | 4 |

---

## 4. Welche Strategie passt zu mir?

### Entscheidungsbaum

```
Bist du Anfaenger?
  Ja -> Edge Indicator (klare Regeln, keine API-Kosten)

Bevorzugst du Contrarian-Trading?
  Ja -> LiquidationHunter (L/S Ratio, Funding)

Unsicher?
  -> Edge Indicator als Einstieg, spaeter LiquidationHunter dazu
```

### Empfehlungen nach Erfahrungslevel

| Level | Primaere Strategie | Alternative |
|-------|-------------------|-------------|
| Anfaenger | Edge Indicator | -- |
| Fortgeschritten | Edge Indicator | LiquidationHunter |
| Experte | LiquidationHunter | Edge Indicator |

### Empfehlungen nach Risikotoleranz

| Risiko | Strategie | Position Size | Leverage |
|--------|-----------|--------------|----------|
| Niedrig | Edge Indicator | 5% | 2x |
| Mittel | LiquidationHunter | 10% | 3x |

### Kombinationsstrategien

Du kannst **mehrere Bots parallel** laufen lassen:

| Kombination | Vorteil |
|-------------|---------|
| Edge Indicator + LiquidationHunter | Technisch + Contrarian diversifiziert |
| Edge Indicator (BTC) + Edge Indicator (ETH) | Gleiche Strategie, verschiedene Assets |
| LiquidationHunter (BTC) + Edge Indicator (ETH) | Unterschiedliche Strategien pro Asset |

---

---

# Strategy Overview (English)

The 2 available trading strategies explained: how they work, risk profiles, parameter recommendations, and when to use each.

---

## Strategy Comparison

| Strategy | Type | Data Sources | API Costs | Risk | Best For |
|----------|------|-------------|-----------|------|----------|
| Edge Indicator | Technical | Kline only | None | Low-Medium | Beginners / Technical |
| LiquidationHunter | Contrarian | L/S, F&G, Funding | None | Medium | Experienced traders |

### Backtest Results (90 days, BTCUSDT, $10k, 1h)

| Strategy | Return | Win Rate | Max DD | Sharpe | PF | Trades |
|----------|--------|----------|--------|--------|-----|--------|
| **LiquidationHunter** | +26.2% | 53.9% | 4.7% | 5.51 | 1.98 | 104 |
| **Edge Indicator** | +18.6% | 47.1% | 9.8% | 2.91 | 1.65 | 68 |

---

## Quick Strategy Guide

### Edge Indicator (v2 — Optimized Exits)
Pure technical strategy using only Binance kline data. Three layers: EMA Ribbon (8/21), ADX filter, Predator Momentum Score. No external API dependencies. v2 exit tuning lets profitable trades run longer (+200% avg return on 1h). Available risk profiles: Standard (1h) and Conservative (4h).

> **Note:** The Aggressive profile (15m) was removed in v4.6.2 due to poor simulation results (27% winrate, -7.27% PnL).

### LiquidationHunter
Contrarian strategy that bets against crowded positions. Uses L/S Ratio, Fear & Greed, and Funding Rate. Best when markets are at extremes.

---

## Which Strategy Is Right For You?

| Experience | Primary | Alternative |
|-----------|---------|-------------|
| Beginner | Edge Indicator | -- |
| Intermediate | Edge Indicator | LiquidationHunter |
| Expert | LiquidationHunter | Edge Indicator |

| Risk Tolerance | Strategy | Position Size | Leverage |
|---------------|----------|--------------|----------|
| Low | Edge Indicator | 5% | 2x |
| Medium | LiquidationHunter | 10% | 3x |

### Combination Strategies

You can run **multiple bots in parallel**:

| Combination | Advantage |
|-------------|-----------|
| Edge Indicator + LiquidationHunter | Technical + Contrarian diversification |
| Edge Indicator (BTC) + Edge Indicator (ETH) | Same strategy, different assets |
| LiquidationHunter (BTC) + Edge Indicator (ETH) | Different strategies per asset |

