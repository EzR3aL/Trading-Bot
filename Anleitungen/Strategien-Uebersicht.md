# Strategien-Uebersicht

Die 3 verfuegbaren Trading-Strategien erklaert: Funktionsweise, Risikoprofil, Parameter-Empfehlungen und wann welche Strategie sinnvoll ist.

---

## Inhaltsverzeichnis

1. [Strategie-Vergleich](#1-strategie-vergleich)
2. [Edge Indicator](#2-edge-indicator)
3. [LiquidationHunter](#3-liquidationhunter)
4. [Sentiment Surfer](#4-sentiment-surfer)
5. [Welche Strategie passt zu mir?](#5-welche-strategie-passt-zu-mir)
6. [Weitere Strategien (derzeit nicht verfuegbar)](#6-weitere-strategien-derzeit-nicht-verfuegbar)

---

## 1. Strategie-Vergleich

### Uebersichts-Tabelle

| Strategie | Typ | Datenquellen | API-Kosten | Risiko | Empfohlen fuer |
|-----------|-----|-------------|------------|--------|----------------|
| Edge Indicator | Technisch | Nur Klines | Keine | Niedrig-Mittel | Anfaenger/Technisch |
| LiquidationHunter | Contrarian | L/S, F&G, Funding | Keine | Mittel | Erfahrene Trader |
| Sentiment Surfer | Hybrid | 6 Quellen | Keine | Mittel | Balanced Trading |

### Backtest-Ergebnisse (90 Tage, BTCUSDT, $10k, 1h)

| Strategie | Return | Win Rate | Max DD | Sharpe | PF | Trades |
|-----------|--------|----------|--------|--------|-----|--------|
| **LiquidationHunter** | +26.2% | 53.9% | 4.7% | 5.51 | 1.98 | 104 |
| **Edge Indicator** | +18.6% | 47.1% | 9.8% | 2.91 | 1.65 | 68 |
| Sentiment Surfer | -3.7% | 32.3% | 9.4% | -1.07 | 0.84 | 65 |

### Risikoprofil-Matrix

| Risiko | Strategie | Begruendung |
|--------|-----------|-------------|
| **Niedrig** | Edge Indicator | Nur Kline-Daten, klare Regeln, ADX-Filter |
| **Mittel** | LiquidationHunter | Contrarian mit klaren Signalen |
| **Mittel** | Sentiment Surfer | Multi-Faktor, ausgewogen |

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

| Parameter | Konservativ | Standard | Aggressiv |
|-----------|------------|----------|-----------|
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

## 4. Sentiment Surfer

### Was macht sie?

Kombiniert **6 verschiedene Datenquellen** mit konfigurierbaren Gewichtungen. Jede Quelle erzeugt einen Score von -100 bis +100. Der gewichtete Durchschnitt ergibt die finale Entscheidung.

### Fuer wen?

- Trader, die einen ausgewogenen Multi-Faktor-Ansatz bevorzugen
- Wer nicht nur auf einen Indikator vertrauen moechte
- Mittleres Risiko-Profil

### 6 Scoring-Quellen

| # | Quelle | Gewicht | Logik |
|---|--------|---------|-------|
| 1 | News Sentiment | 1.0x | Positive Medien = bullish |
| 2 | Fear & Greed | 1.0x | Contrarian: Angst = bullish |
| 3 | VWAP/OIWAP | 1.2x | Preis ueber Fair Value = bullish |
| 4 | Supertrend | 1.2x | ATR-Trend: gruen = bullish |
| 5 | Spot Volume | 0.8x | Buy-Dominanz = bullish |
| 6 | Price Momentum | 0.8x | 24h Richtung |

### Parameter-Empfehlungen

| Parameter | Konservativ | Standard | Aggressiv |
|-----------|------------|----------|-----------|
| Min Agreement | 4 | 3 | 2 |
| Min Confidence | 50 | 40 | 30 |
| Take Profit | 3.5% | 3.5% | 3.0% |
| Stop Loss | 1.5% | 1.5% | 2.0% |

---

## 5. Welche Strategie passt zu mir?

### Entscheidungsbaum

```
Bist du Anfaenger?
  Ja -> Edge Indicator (klare Regeln, keine API-Kosten)

Bevorzugst du Contrarian-Trading?
  Ja -> LiquidationHunter (L/S Ratio, Funding)

Willst du einen ausgewogenen Multi-Faktor-Ansatz?
  Ja -> Sentiment Surfer (6 Quellen, gewichtet)
```

### Empfehlungen nach Erfahrungslevel

| Level | Primaere Strategie | Alternative |
|-------|-------------------|-------------|
| Anfaenger | Edge Indicator | LiquidationHunter |
| Fortgeschritten | Sentiment Surfer | LiquidationHunter |
| Experte | LiquidationHunter | Sentiment Surfer |

### Empfehlungen nach Risikotoleranz

| Risiko | Strategie | Position Size | Leverage |
|--------|-----------|--------------|----------|
| Niedrig | Edge Indicator | 5% | 2x |
| Mittel | LiquidationHunter | 10% | 3x |
| Mittel | Sentiment Surfer | 10% | 3x |

### Kombinationsstrategien

Du kannst **mehrere Bots parallel** laufen lassen:

| Kombination | Vorteil |
|-------------|---------|
| Edge Indicator + LiquidationHunter | Technisch + Contrarian diversifiziert |
| Edge Indicator + Sentiment Surfer | Technisch + Multi-Faktor diversifiziert |
| Edge Indicator (BTC) + Edge Indicator (ETH) | Gleiche Strategie, verschiedene Assets |

---

## 6. Weitere Strategien (derzeit nicht verfuegbar)

Die folgenden 3 Strategien existieren im System, sind aber derzeit fuer normale Nutzer nicht sichtbar:

| Strategie | Grund fuer Ausblendung |
|-----------|----------------------|
| **Contrarian Pulse** | ~70% Ueberschneidung mit LiquidationHunter. Die beiden Strategien nutzen sehr aehnliche Datenquellen und Contrarian-Logik, weshalb Contrarian Pulse zugunsten von LiquidationHunter versteckt wurde. |
| **LLM Signal** | Erfordert externe LLM-API-Keys (OpenAI, Anthropic, Groq, etc.). Derzeit nur fuer Admin-Nutzer verfuegbar. |
| **Degen** | Erfordert externe LLM-API-Keys. Aggressiver, vorkonfigurierter KI-Prompt mit 19 Datenquellen. Derzeit nur fuer Admin-Nutzer verfuegbar. |

Falls ein Admin dir Zugang zu LLM Signal oder Degen freischaltet, findest du die LLM-Provider-Konfiguration in der Anleitung [LLM-Provider-Konfiguration](LLM-Provider-Konfiguration.md).

---

---

# Strategy Overview (English)

The 3 available trading strategies explained: how they work, risk profiles, parameter recommendations, and when to use each.

---

## Strategy Comparison

| Strategy | Type | Data Sources | API Costs | Risk | Best For |
|----------|------|-------------|-----------|------|----------|
| Edge Indicator | Technical | Kline only | None | Low-Medium | Beginners / Technical |
| LiquidationHunter | Contrarian | L/S, F&G, Funding | None | Medium | Experienced traders |
| Sentiment Surfer | Hybrid | 6 sources | None | Medium | Balanced trading |

---

## Quick Strategy Guide

### Edge Indicator (v2 — Optimized Exits)
Pure technical strategy using only Binance kline data. Three layers: EMA Ribbon (8/21), ADX filter, Predator Momentum Score. No external API dependencies. v2 exit tuning lets profitable trades run longer (+200% avg return on 1h).

### LiquidationHunter
Contrarian strategy that bets against crowded positions. Uses L/S Ratio, Fear & Greed, and Funding Rate. Best when markets are at extremes.

### Sentiment Surfer
Combines 6 weighted data sources (News, Fear & Greed, VWAP, Supertrend, Volume, Momentum). Requires minimum agreement of 3/6 sources.

---

## Which Strategy Is Right For You?

| Experience | Primary | Alternative |
|-----------|---------|-------------|
| Beginner | Edge Indicator | LiquidationHunter |
| Intermediate | Sentiment Surfer | LiquidationHunter |
| Expert | LiquidationHunter | Sentiment Surfer |

| Risk Tolerance | Strategy | Position Size | Leverage |
|---------------|----------|--------------|----------|
| Low | Edge Indicator | 5% | 2x |
| Medium | LiquidationHunter | 10% | 3x |
| Medium | Sentiment Surfer | 10% | 3x |

---

## Additional Strategies (Currently Unavailable)

The following 3 strategies exist in the system but are currently hidden from regular users:

| Strategy | Reason |
|----------|--------|
| **Contrarian Pulse** | ~70% overlap with LiquidationHunter. Both use similar data sources and contrarian logic, so Contrarian Pulse was hidden in favor of LiquidationHunter. |
| **LLM Signal** | Requires external LLM API keys (OpenAI, Anthropic, Groq, etc.). Currently only available to admin users. |
| **Degen** | Requires external LLM API keys. Aggressive, pre-configured AI prompt with 19 data sources. Currently only available to admin users. |

If an admin grants you access to LLM Signal or Degen, see the [LLM Provider Configuration](en/Trading-Strategies-Overview.md) guide for setup instructions.
