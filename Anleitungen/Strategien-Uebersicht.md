# Strategien-Uebersicht

Alle 6 Trading-Strategien erklaert: Funktionsweise, Risikoprofil, Parameter-Empfehlungen und wann welche Strategie sinnvoll ist.

---

## Inhaltsverzeichnis

1. [Strategie-Vergleich](#1-strategie-vergleich)
2. [LiquidationHunter](#2-liquidationhunter)
3. [LLM Signal](#3-llm-signal)
4. [Sentiment Surfer](#4-sentiment-surfer)
5. [Degen](#5-degen)
6. [Edge Indicator](#6-edge-indicator)
7. [Contrarian Pulse](#7-contrarian-pulse)
8. [Welche Strategie passt zu mir?](#8-welche-strategie-passt-zu-mir)

---

## 1. Strategie-Vergleich

### Uebersichts-Tabelle

| Strategie | Typ | Datenquellen | API-Kosten | Risiko | Empfohlen fuer |
|-----------|-----|-------------|------------|--------|----------------|
| LiquidationHunter | Contrarian | L/S, F&G, Funding | Keine | Mittel | Erfahrene Trader |
| LLM Signal | KI | Konfigurierbar | LLM-API | Variabel | KI-Enthusiasten |
| Sentiment Surfer | Hybrid | 6 Quellen | Keine | Mittel | Balanced Trading |
| Degen | KI-Arena | 19 feste Quellen | LLM-API | Hoch | Experimentell |
| Edge Indicator | Technisch | Nur Klines | Keine | Niedrig-Mittel | Anfaenger/Technisch |
| Contrarian Pulse | Algo | F&G, EMA, RSI, Derivate | Keine | Mittel | Contrarian-Scalper |

### Backtest-Ergebnisse (90 Tage, BTCUSDT, $10k, 1h)

| Strategie | Return | Win Rate | Max DD | Sharpe | PF | Trades |
|-----------|--------|----------|--------|--------|-----|--------|
| **LiquidationHunter** | +26.2% | 53.9% | 4.7% | 5.51 | 1.98 | 104 |
| **Edge Indicator** | +18.6% | 47.1% | 9.8% | 2.91 | 1.65 | 68 |
| Degen | +0.8% | 40.0% | 3.8% | 0.43 | 1.08 | 35 |
| LLM Signal | +0.8% | 40.0% | 4.5% | 0.51 | 1.12 | 25 |
| Sentiment Surfer | -3.7% | 32.3% | 9.4% | -1.07 | 0.84 | 65 |

### Risikoprofil-Matrix

| Risiko | Strategie | Begruendung |
|--------|-----------|-------------|
| **Niedrig** | Edge Indicator | Nur Kline-Daten, klare Regeln, ADX-Filter |
| **Mittel** | LiquidationHunter | Contrarian mit klaren Signalen |
| **Mittel** | Sentiment Surfer | Multi-Faktor, ausgewogen |
| **Mittel-Hoch** | LLM Signal | Abhaengig von LLM-Qualitaet |
| **Hoch** | Degen | Aggressiv, 19 Quellen, fester Prompt |

---

## 2. LiquidationHunter

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

## 3. LLM Signal

### Was macht sie?

Sendet aktuelle Marktdaten an ein **externes KI-Modell** (GPT-4, Claude, Llama, etc.), das dann entscheidet: LONG oder SHORT. Jeder Zyklus ist stateless -- der LLM hat kein Gedaechtnis ueber vorherige Trades.

### Fuer wen?

- KI-Enthusiasten, die Prompt Engineering moegen
- Trader, die verschiedene LLM-Provider testen wollen
- Wer eigene Analyse-Prompts schreiben moechte

### Besonderheiten

- **7+ LLM-Provider** unterstuetzt (OpenAI, Anthropic, Gemini, Groq, Mistral, xAI, Perplexity, DeepSeek)
- **Custom Prompts** moeglich (max. 4000 Zeichen)
- **Model Selection** pro Bot (z.B. GPT-4o vs. GPT-4o-mini)
- **Konfigurierbare Datenquellen** (waehle welche Daten der LLM erhaelt)

### Parameter-Empfehlungen

| Parameter | Konservativ | Standard | Aggressiv |
|-----------|------------|----------|-----------|
| Provider | OpenAI | Groq | Beliebig |
| Temperatur | 0.2 | 0.4 | 0.6 |
| Timeframe | 4h | 1h | 30m |
| Take Profit | 3.0% | 2.5% | 2.0% |
| Stop Loss | 1.5% | 1.5% | 1.0% |

### Kosten

LLM-API-Kosten pro Analysezyklus (geschaetzt):

| Provider | Pro Aufruf | Pro Tag (1h TF, 24 Calls) |
|----------|-----------|---------------------------|
| GPT-4o | ~$0.03 | ~$0.72 |
| GPT-4o-mini | ~$0.005 | ~$0.12 |
| Groq (Llama 70B) | ~$0.003 | ~$0.07 |
| DeepSeek | ~$0.002 | ~$0.05 |

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

## 5. Degen

### Was macht sie?

Eine **vorkonfigurierte KI-Arena-Strategie** mit festem Prompt. Sammelt **19 Datenquellen** und schickt alles an einen LLM. Der User konfiguriert nur Provider, Modell und Temperatur -- der Rest ist fix. Optimiert fuer aggressive 1h BTC-Predictions.

### Fuer wen?

- Experimentierfreudige Trader
- Wer die volle Bandbreite an Marktdaten nutzen moechte
- Hoeheres Risiko akzeptabel

### Besonderheiten

- **19 feste Datenquellen** (CoinGecko, Binance, Coinbase, Bybit, Deribit)
- **Fester System-Prompt** (nicht aenderbar)
- **NEUTRAL ist verboten** -- der LLM muss sich entscheiden
- Daten umfassen: Options-Daten, Volatilitaets-Index, Coinbase Premium, und mehr

### Parameter-Empfehlungen

| Parameter | Empfehlung |
|-----------|------------|
| Provider | Groq oder OpenAI |
| Temperatur | 0.3 - 0.5 |
| Timeframe | 1h (fest empfohlen) |
| Take Profit | 2.0 - 3.0% |
| Stop Loss | 1.0 - 1.5% |
| Leverage | 3x |

---

## 6. Edge Indicator (v2 — optimierte Exits)

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

## 7. Contrarian Pulse

### Was macht sie?

Eine **rein algorithmische Contrarian-Strategie** fuer BTC, die den Fear & Greed Index als Haupt-Signalgeber nutzt. Bei extremer Angst (<30) wird Long gegangen, bei extremer Gier (>70) Short. Das Signal wird durch mehrere Bestaetiger validiert.

### Fuer wen?

- Trader, die Contrarian-Scalping bevorzugen
- Wer keine KI/LLM-Kosten moechte
- Mittleres Risikoprofil mit klaren Regeln

### Datenquellen & Bestaetiger

| # | Quelle | Logik |
|---|--------|-------|
| 1 | Fear & Greed Index | Primaer-Signal: <30 = Long, >70 = Short |
| 2 | EMA 50/200 | Trend-Bestaetigung |
| 3 | RSI (14) | Ueberkauft/Ueberverkauft |
| 4 | CVD (Cumulative Volume Delta) | Kauf-/Verkaufsdruck |
| 5 | Long/Short Ratio | Positionierung der Masse |
| 6 | Volume | Volumen-Bestaetigung |
| 7 | Open Interest | Markt-Engagement |
| 8 | Funding Rate | Contrarian-Signal |

### Besonderheiten

- **Kein LLM erforderlich** — rein algorithmisch
- **HOLD bei neutralem F&G** (30-70) — handelt nur bei Extremen
- **Backtest-verifiziert** mit echten Marktdaten
- Alle Derivate-Daten von Binance Futures

### Parameter-Empfehlungen

| Parameter | Konservativ | Standard | Aggressiv |
|-----------|------------|----------|-----------|
| Leverage | 2x | 3x | 4x |
| Take Profit | 3.0% | 2.5% | 2.0% |
| Stop Loss | 1.5% | 1.5% | 1.0% |
| Position Size | 5% | 10% | 15% |
| Timeframe | 1h | 1h | 30m |

---

## 8. Welche Strategie passt zu mir?

### Entscheidungsbaum

```
Bist du Anfaenger?
  Ja -> Edge Indicator (klare Regeln, keine API-Kosten)

Willst du KI/LLM nutzen?
  Ja -> Eigene Prompts schreiben?
         Ja -> LLM Signal (Custom Prompt)
         Nein -> Degen (fester Prompt, 19 Datenquellen)

Bevorzugst du Contrarian-Trading?
  Ja -> Regelbasiert?
         Ja -> Contrarian Pulse (F&G + Bestaetiger, kein LLM)
         Nein -> LiquidationHunter (L/S Ratio, Funding)

Willst du einen ausgewogenen Multi-Faktor-Ansatz?
  Ja -> Sentiment Surfer (6 Quellen, gewichtet)
```

### Empfehlungen nach Erfahrungslevel

| Level | Primaere Strategie | Alternative |
|-------|-------------------|-------------|
| Anfaenger | Edge Indicator | LiquidationHunter |
| Fortgeschritten | Sentiment Surfer | LiquidationHunter |
| Experte | LLM Signal (Custom Prompt) | Degen |

### Empfehlungen nach Risikotoleranz

| Risiko | Strategie | Position Size | Leverage |
|--------|-----------|--------------|----------|
| Niedrig | Edge Indicator | 5% | 2x |
| Mittel | LiquidationHunter | 10% | 3x |
| Hoch | Degen | 15% | 4x |

### Kombinationsstrategien

Du kannst **mehrere Bots parallel** laufen lassen:

| Kombination | Vorteil |
|-------------|---------|
| Edge Indicator + LiquidationHunter | Technisch + Contrarian diversifiziert |
| Edge Indicator + LLM Signal | Technisch + KI-Analyse |
| Edge Indicator (BTC) + Edge Indicator (ETH) | Gleiche Strategie, verschiedene Assets |

---

---

# Strategy Overview (English)

All 6 trading strategies explained: how they work, risk profiles, parameter recommendations, and when to use each.

---

## Strategy Comparison

| Strategy | Type | Data Sources | API Costs | Risk | Best For |
|----------|------|-------------|-----------|------|----------|
| LiquidationHunter | Contrarian | L/S, F&G, Funding | None | Medium | Experienced traders |
| LLM Signal | AI | Configurable | LLM API | Variable | AI enthusiasts |
| Sentiment Surfer | Hybrid | 6 sources | None | Medium | Balanced trading |
| Degen | AI Arena | 19 fixed sources | LLM API | High | Experimental |
| Edge Indicator | Technical | Kline only | None | Low-Medium | Beginners / Technical |
| Contrarian Pulse | Algo | F&G, EMA, RSI, Derivatives | None | Medium | Contrarian scalpers |

---

## Quick Strategy Guide

### LiquidationHunter
Contrarian strategy that bets against crowded positions. Uses L/S Ratio, Fear & Greed, and Funding Rate. Best when markets are at extremes.

### LLM Signal
Sends market data to an external LLM (GPT-4, Claude, Llama, etc.) for analysis. Customizable prompts and data sources. 7+ providers supported.

### Sentiment Surfer
Combines 6 weighted data sources (News, Fear & Greed, VWAP, Supertrend, Volume, Momentum). Requires minimum agreement of 3/6 sources.

### Degen
Pre-configured AI arena with fixed prompt and 19 data sources. Aggressive 1h BTC predictions. User only configures LLM provider, model, and temperature.

### Edge Indicator (v2 — Optimized Exits)
Pure technical strategy using only Binance kline data. Three layers: EMA Ribbon (8/21), ADX filter, Predator Momentum Score. No external API dependencies. v2 exit tuning lets profitable trades run longer (+200% avg return on 1h).

### Contrarian Pulse
Algorithmic contrarian Fear & Greed scalping strategy for BTC. Goes Long on extreme fear (<30), Short on extreme greed (>70). Confirmed by 50/200 EMA trend, RSI, and derivatives signals (CVD, Long/Short Ratio, Volume, OI, Funding Rate). No LLM required. HOLDs when F&G is neutral (30-70).

---

## Which Strategy Is Right For You?

| Experience | Primary | Alternative |
|-----------|---------|-------------|
| Beginner | Edge Indicator | LiquidationHunter |
| Intermediate | Sentiment Surfer | LiquidationHunter |
| Expert | LLM Signal (Custom) | Degen |

| Risk Tolerance | Strategy | Position Size | Leverage |
|---------------|----------|--------------|----------|
| Low | Edge Indicator | 5% | 2x |
| Medium | LiquidationHunter | 10% | 3x |
| High | Degen | 15% | 4x |
