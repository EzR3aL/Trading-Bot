# Strategie-Dokumentation

Der Trading Bot bietet 2 Strategien mit unterschiedlichen Ansaetzen, Risikoprofilen und Datenquellen.

---

## Strategie-Uebersicht

| # | Strategie | Typ | Datenquellen | Risiko | Empfohlen fuer |
|---|-----------|-----|-------------|--------|----------------|
| 1 | Edge Indicator | Technisch | Nur Kline-Daten (OHLCV) | Niedrig-Mittel | Technische Trader |
| 2 | LiquidationHunter | Contrarian | L/S Ratio, Fear&Greed, Funding | Mittel | Erfahrene Trader |

### Backtest-Ergebnisse (90 Tage, BTCUSDT, $10k)

| Strategie | Return | Win Rate | Max DD | Sharpe | Trades | PF |
|-----------|--------|----------|--------|--------|--------|-----|
| **LiquidationHunter** | +26.2% | 53.9% | 4.7% | 5.51 | 104 | 1.98 |
| **Edge Indicator** | +18.6% | 47.1% | 9.8% | 2.91 | 68 | 1.65 |

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

## 2. Edge Indicator

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
3. **Keine Fundamentalanalyse** -- Ignoriert News, Halving-Events, etc.
4. **Historische Korrelationen** -- Vergangene Muster garantieren keine Zukunft
