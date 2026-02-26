# Strategie-Dokumentation

Der Trading Bot bietet 5 Strategien mit unterschiedlichen Ansaetzen, Risikoprofilen und Datenquellen.

---

## Strategie-Uebersicht

| # | Strategie | Typ | Datenquellen | Risiko | Empfohlen fuer |
|---|-----------|-----|-------------|--------|----------------|
| 1 | LiquidationHunter | Contrarian | L/S Ratio, Fear&Greed, Funding | Mittel | Erfahrene Trader |
| 2 | LLM Signal | KI-gesteuert | Konfigurierbar (7+ Quellen) | Variabel | KI-Enthusiasten |
| 3 | Sentiment Surfer | Hybrid | 6 gewichtete Quellen | Mittel | Balanced Trading |
| 4 | Degen | KI-Arena | 19 feste Quellen | Hoch | Experimentell |
| 5 | Edge Indicator | Technisch | Nur Kline-Daten (OHLCV) | Niedrig-Mittel | Technische Trader |

### Backtest-Ergebnisse (90 Tage, BTCUSDT, $10k)

| Strategie | Return | Win Rate | Max DD | Sharpe | Trades | PF |
|-----------|--------|----------|--------|--------|--------|-----|
| **LiquidationHunter** | +26.2% | 53.9% | 4.7% | 5.51 | 104 | 1.98 |
| **Edge Indicator** | +18.6% | 47.1% | 9.8% | 2.91 | 68 | 1.65 |
| Degen | +0.8% | 40.0% | 3.8% | 0.43 | 35 | 1.08 |
| LLM Signal | +0.8% | 40.0% | 4.5% | 0.51 | 25 | 1.12 |
| Sentiment Surfer | -3.7% | 32.3% | 9.4% | -1.07 | 65 | 0.84 |

---

## 1. LiquidationHunter

`src/strategy/liquidation_hunter.py`

### Ueberblick

Die aelteste Strategie des Bots. Agiert als **Contrarian** -- sie wettet gegen die Masse, wenn Leverage und Sentiment extreme Werte erreichen. Wenn zu viele Trader auf einer Seite sind, wird eine Liquidations-Kaskade wahrscheinlich. Der Bot positioniert sich auf der Gegenseite.

### Kernlogik

#### Schritt 1: Leverage-Analyse (Long/Short Ratio)

```
Ratio > 2.5  ->  Zu viele Longs  ->  SHORT Signal
Ratio < 0.4  ->  Zu viele Shorts ->  LONG Signal
Ratio 0.4-2.5 -> Neutral         ->  Kein Signal
```

#### Schritt 2: Sentiment-Analyse (Fear & Greed Index)

```
Index > 80  ->  Extreme Greed  ->  SHORT Bias
Index < 20  ->  Extreme Fear   ->  LONG Bias
Index 20-80 ->  Neutral        ->  Kein Bias
```

#### Schritt 3: Funding Rate Kosten-Analyse

```
Rate > 0.05%   ->  Teuer fuer Longs   ->  SHORT Confidence +20
Rate < -0.02%  ->  Teuer fuer Shorts  ->  LONG Confidence +20
```

### Entscheidungsmatrix

| Leverage Signal | Sentiment Signal | Ergebnis |
|-----------------|------------------|----------|
| Crowded Longs | Extreme Greed | **HIGH Confidence SHORT (85-95%)** |
| Crowded Shorts | Extreme Fear | **HIGH Confidence LONG (85-95%)** |
| Crowded Longs | Neutral/Fear | Medium Confidence SHORT (70-80%) |
| Crowded Shorts | Neutral/Greed | Medium Confidence LONG (70-80%) |
| Neutral | Extreme Greed | Low Confidence SHORT (60-70%) |
| Neutral | Extreme Fear | Low Confidence LONG (60-70%) |
| Neutral | Neutral | **Follow 24h Trend (55-65%)** |

### NO NEUTRALITY Prinzip

Der Bot **muss** immer eine Richtung waehlen. Wenn alle Signale neutral sind:
1. Analysiere den 24h-Preistrend
2. Folge dem Trend mit niedriger Confidence (55-65%)
3. Verwende kleinere Position Size

### Datenquellen

| Metrik | Quelle |
|--------|--------|
| Fear & Greed | Alternative.me |
| L/S Ratio | Binance Futures |
| Funding Rate | Binance Futures |
| Ticker | Binance Futures |
| Open Interest | Binance Futures |

### Empfohlene Parameter

| Parameter | Empfehlung |
|-----------|------------|
| Timeframe | 4h oder Market Sessions |
| Take Profit | 3.5 - 4.0% |
| Stop Loss | 1.5 - 2.0% |
| Leverage | 3x |
| Trading Pairs | BTCUSDT, ETHUSDT |

---

## 2. LLM Signal

`src/strategy/llm_signal.py`

### Ueberblick

Delegiert die Signal-Generierung an einen externen **LLM-Provider** (OpenAI, Anthropic, Gemini, Groq, Mistral, xAI, Perplexity, DeepSeek). Jeder Analysezyklus ist **stateless** -- der LLM erhaelt aktuelle Marktdaten und einen Prompt und muss eine Richtung (LONG/SHORT) mit Confidence waehlen.

### Funktionsweise

```
1. Marktdaten abrufen (konfigurierbare Datenquellen)
2. Daten + User-Prompt formatieren
3. An LLM-Provider senden
4. Antwort parsen: DIRECTION, CONFIDENCE, REASONING
5. TradeSignal zurueckgeben
```

### Konfigurierbare Datenquellen

| Quelle | Beschreibung |
|--------|-------------|
| spot_price | Aktueller BTC/ETH Preis |
| fear_greed | Fear & Greed Index |
| long_short_ratio | Binance L/S Ratio |
| funding_rate | Funding Rate |
| news_sentiment | GDELT News Sentiment |
| vwap | Volume Weighted Average Price |
| supertrend | ATR-basierter Trend-Indikator |
| spot_volume | Spot-Handelsvolumen |
| volatility | Realisierte Volatilitaet |

### Unterstuetzte LLM-Provider

| Provider | Beliebte Modelle |
|----------|-----------------|
| OpenAI | GPT-4o, GPT-4o-mini |
| Anthropic | Claude 3.5 Sonnet, Claude 3 Haiku |
| Gemini | Gemini 1.5 Pro, Gemini 1.5 Flash |
| Groq | Llama 3.1 70B, Mixtral 8x7B |
| Mistral | Mistral Large, Mistral Small |
| xAI | Grok-2 |
| Perplexity | Sonar Large, Sonar Small |
| DeepSeek | DeepSeek Chat, DeepSeek Coder |

### Custom Prompt

Du kannst einen eigenen System-Prompt schreiben (max. 4000 Zeichen) oder den Standard-Prompt verwenden. Der Standard-Prompt analysiert:
- Fear & Greed (contrarian)
- Long/Short Ratio (crowded positions)
- Funding Rate (cost pressure)
- VWAP (fair value)
- Supertrend (trend direction)
- Volume (buy/sell ratio)

### Empfohlene Parameter

| Parameter | Empfehlung |
|-----------|------------|
| LLM Provider | Groq (schnell + guenstig) oder OpenAI (genau) |
| Timeframe | 1h |
| Take Profit | 2.0 - 3.5% |
| Stop Loss | 1.0 - 2.0% |
| Leverage | 3x |

---

## 3. Sentiment Surfer

`src/strategy/sentiment_surfer.py`

### Ueberblick

Eine **ausgewogene Hybrid-Strategie**, die 6 Datenquellen kombiniert. Jede Quelle erzeugt einen Score von -100 (extrem bearish) bis +100 (extrem bullish). Die Scores werden gewichtet aggregiert, um eine finale Richtung und Confidence zu bestimmen.

### 6 Scoring-Quellen

| # | Quelle | Gewicht | Logik |
|---|--------|---------|-------|
| 1 | News Sentiment (GDELT) | 1.0 | Positiver Medien-Ton = bullish |
| 2 | Fear & Greed Index | 1.0 | Contrarian: Angst = bullish, Gier = bearish |
| 3 | VWAP/OIWAP | 1.2 | Preis ueber Fair Value = bullish Momentum |
| 4 | Supertrend | 1.2 | ATR-basierter Trend: gruen = bullish |
| 5 | Spot Volume | 0.8 | Taker Buy Dominanz = Akkumulation |
| 6 | Price Momentum | 0.8 | 24h Preisaenderung (Richtung + Staerke) |

### Entscheidungslogik

- **Gewichteter Durchschnitt** aller Scores bestimmt Richtung und Confidence
- **Minimum Source Agreement**: Mindestens 3 von 6 Quellen muessen in dieselbe Richtung zeigen
- **Balanced Approach**: Keine einzelne Quelle dominiert

### Empfohlene Parameter

| Parameter | Empfehlung |
|-----------|------------|
| Timeframe | 1h - 4h |
| Take Profit | 3.5% |
| Stop Loss | 1.5% |
| Min Agreement | 3 |
| Min Confidence | 40 |

---

## 4. Degen

`src/strategy/degen.py`

### Ueberblick

Inspiriert von myquant.gg's Degen Bot. Eine **vorkonfigurierte KI-Arena-Strategie** mit festem System-Prompt, optimiert fuer aggressive 1h BTC-Direktional-Calls. Der User konfiguriert nur den LLM-Provider, das Modell und die Temperatur -- der Rest ist fix.

### 19 feste Datenquellen

| # | Quelle | API |
|---|--------|-----|
| 1 | Bitcoin Price | CoinGecko / Binance |
| 2 | Futures Volume | Binance 24h Ticker |
| 3 | Futures Premium / Funding Rate | Binance premiumIndex |
| 4 | Tape / Trade Flow | Binance Klines (Taker) |
| 5 | Spot Volume Analysis | Binance Klines |
| 6 | Order Book Depth | Binance Depth |
| 7 | Perp/Spot Volume Ratio | Berechnet |
| 8 | Market Cap & Float | CoinGecko |
| 9 | VWAP / OIWAP | Berechnet |
| 10 | Realized Volatility | Berechnet |
| 11 | Total Return with Funding | Berechnet |
| 12 | Supertrend Indicator | Berechnet |
| 13 | Binance Long/Short Ratio | Binance Futures |
| 14 | Liquidation Risk Score | Binance forceOrders + Funding |
| 15 | Cumulative Volume Delta | Binance Klines |
| 16 | Coinbase Premium Index | Coinbase vs Binance Spread |
| 17 | Bybit Futures OI + Funding | Bybit V5 API |
| 18 | Deribit Options: IV, Skew, Put/Call | Deribit API |
| 19 | Deribit DVOL (Crypto VIX) | Deribit API |

### Fester System-Prompt

Der Prompt zwingt den LLM zu:
1. **Immer LONG oder SHORT** waehlen (kein NEUTRAL erlaubt)
2. Confidence Score (0-100) angeben
3. Preis-Vorhersage fuer 1 Stunde
4. Kurze Begruendung (max. 3 Saetze)

### Empfohlene Parameter

| Parameter | Empfehlung |
|-----------|------------|
| LLM Provider | Groq oder OpenAI |
| Timeframe | 1h (fest) |
| Take Profit | 2.0 - 3.0% |
| Stop Loss | 1.0 - 1.5% |
| Leverage | 3x |
| Temperatur | 0.3 - 0.7 |

---

## 5. Edge Indicator

`src/strategy/edge_indicator.py`

### Ueberblick

Eine **rein technische Strategie** basierend auf dem TradingView "Trading Edge" Indikator. Verwendet ausschliesslich Binance Kline-Daten (OHLCV) -- keine externen APIs, hohe Zuverlaessigkeit. Kombiniert drei Analyse-Schichten:

### 3 Analyse-Schichten

#### Schicht 1: EMA Ribbon (8/21) -- Trend Direction

```
Preis > EMA 8 > EMA 21  ->  Bull Trend (LONG)
Preis < EMA 8 < EMA 21  ->  Bear Trend (SHORT)
Preis zwischen EMAs      ->  Neutral (KEIN Trade)
```

#### Schicht 2: ADX / Chop Filter -- Market Quality

```
ADX > 18  ->  Trending Market  ->  Trade erlaubt
ADX < 18  ->  Choppy Market   ->  KEIN Trade
```

Der ADX filtert Seitwaetrtsmaerkte heraus, in denen technische Signale unzuverlaessig sind.

#### Schicht 3: Predator Momentum Score -- Timing & Confirmation

Kombiniert mehrere Momentum-Indikatoren zu einem Score von -1 bis +1:

| Komponente | Methode |
|-----------|---------|
| MACD Histogram (12/26/9) | Normalisiert via tanh |
| RSI Drift (RSI 14, EMA 5) | Erste Ableitung, normalisiert |
| EMA Ribbon Alignment | Trend-Bonus (+/-0.6) |

**Regime-Erkennung:**
- Score > 0.20: Bull Regime
- Score < -0.20: Bear Regime
- Dazwischen: Neutral

### Entscheidung

- **LONG**: Bull Trend + ADX trending + Bull Momentum
- **SHORT**: Bear Trend + ADX trending + Bear Momentum
- **KEIN TRADE**: Neutral Trend ODER Choppy Market

### Empfohlene Parameter

| Parameter | Empfehlung |
|-----------|------------|
| Timeframe | **1h** (basierend auf 90-Tage Backtest) |
| EMA Fast | 8 |
| EMA Slow | 21 |
| ADX Threshold | 18 |
| Take Profit | 2.0 - 3.5% |
| Stop Loss | 1.0 - 2.0% |
| Leverage | 3x |

---

## Confidence-System

Alle Strategien verwenden ein einheitliches Confidence-System:

### Position Sizing nach Confidence

| Confidence | Multiplier | Effektive Position |
|------------|------------|-------------------|
| 90%+ | 1.5x | 15% des Balances |
| 80-89% | 1.25x | 12.5% des Balances |
| 70-79% | 1.0x | 10% des Balances |
| 60-69% | 0.75x | 7.5% des Balances |
| 55-59% | 0.5x | 5% des Balances |
| <55% | - | Kein Trade |

### Risk/Reward Verhaeltnis

**Standard-Konfiguration:**
- Take Profit: 3.5%
- Stop Loss: 2.0%
- Risk/Reward Ratio: 1.75:1

**Break-Even Win Rate:**
```
Break-Even = 1 / (1 + R/R) = 1 / (1 + 1.75) = 36.4%
```

---

## Strategie-Vergleich: Wann welche verwenden?

| Situation | Empfohlene Strategie |
|-----------|---------------------|
| Anfaenger, sichere Wahl | Edge Indicator |
| Maximale Zuverlaessigkeit, keine externen APIs | Edge Indicator |
| Erfahrener Trader, Contrarian-Ansatz | LiquidationHunter |
| Eigene KI-Analyse, Custom Prompts | LLM Signal |
| Ausgewogener Multi-Faktor Ansatz | Sentiment Surfer |
| Experimentell, aggressive Predictions | Degen |
| Nur Kline-Daten, keine API-Abhaengigkeiten | Edge Indicator |

---

## Trading-Zeitplan

### Optimierte Sessions

| Zeit (UTC) | Session | Strategie-Relevanz |
|------------|---------|-------------------|
| **01:00** | Asia | Liquidations nach US-Close |
| **08:00** | EU Open | Frisches Kapital, moegliche Reversals |
| **14:00** | US Open | ETF-Flows, hoechste Volatilitaet |
| **21:00** | US Close | Profit-Taking, Position-Adjustments |

### Warum diese Zeiten?

1. **Session-Uebergaenge** haben die hoechste Liquidations-Wahrscheinlichkeit
2. **ETF-Handel** (14:00 UTC) bringt institutionelle Flows
3. **4 Analyse-Fenster** ermoeglichen bis zu 3 Trades pro Tag

---

## Limitationen

1. **Nicht fuer Seitwaetrtsmaerkte optimiert** -- Strategien brauchen Volatilitaet
2. **Abhaengig von externen APIs** -- Alternative.me, Binance koennen ausfallen (Circuit Breaker vorhanden)
3. **Keine Fundamentalanalyse** -- Ignoriert News, Halving-Events, etc. (ausser Sentiment Surfer / Degen)
4. **Historische Korrelationen** -- Vergangene Muster garantieren keine Zukunft
5. **LLM-Strategien** -- Abhaengig von Provider-Verfuegbarkeit und API-Kosten
