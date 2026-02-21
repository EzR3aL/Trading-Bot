# Backtest-Ergebnisse BTC (BTCUSDT)

**Datum:** 21. Februar 2026
**Asset:** BTCUSDT (Binance Futures)
**Startkapital:** $10.000 pro Backtest

> **Haftungsausschluss:** Diese Ergebnisse basieren ausschliesslich auf historischen Backtest-Daten und stellen keine Anlageberatung dar. Vergangene Performance garantiert keine zukuenftigen Gewinne. Der Handel mit Kryptowaehrungen birgt erhebliche Risiken, einschliesslich des Totalverlusts des eingesetzten Kapitals. Handeln Sie nur mit Kapital, dessen Verlust Sie sich leisten koennen.

---

## Uebersicht: 6 Strategien x 7 Timeframes = 42 Backtests

### Edge Indicator

EMA Ribbon + ADX-Filter + Predator Momentum. Rein technische Strategie ohne KI.

| Timeframe | Zeitraum | Return % | Win Rate | Max DD % | Sharpe | Profit Factor | Trades | Endkapital |
|-----------|----------|----------|----------|----------|--------|---------------|--------|------------|
| 1m | 7 Tage | -2.09 | 48.7% | 2.51 | 0.11 | 0.80 | 191 | $9,791.45 |
| 5m | 30 Tage | -1.91 | 42.9% | 7.44 | 0.10 | 0.94 | 196 | $9,808.65 |
| 15m | 90 Tage | -0.70 | 41.3% | 5.39 | 0.32 | 0.98 | 225 | $9,929.57 |
| 30m | 180 Tage | +0.05 | 40.7% | 8.16 | 0.41 | 1.00 | 258 | $10,005.09 |
| **1h** | **365 Tage** | **+17.87** | **41.4%** | **10.97** | **1.84** | **1.16** | **374** | **$11,786.80** |
| **4h** | **365 Tage** | **+11.73** | **38.1%** | **7.65** | **1.46** | **1.18** | **218** | **$11,172.96** |
| 1d | 365 Tage | +3.18 | 37.0% | 3.72 | 0.73 | 1.13 | 81 | $10,318.24 |

**Empfehlung:** 1h oder 4h. Beste risikobereinigte Rendite aller Strategien (Sharpe 1.84 auf 1h). Empfohlen fuer Einsteiger.

---

### Claude Edge Indicator

Erweiterte Version des Edge Indicator mit ATR-basiertem TP/SL, Volumenfilter, Multi-Timeframe-Analyse und Trailing Stop.

| Timeframe | Zeitraum | Return % | Win Rate | Max DD % | Sharpe | Profit Factor | Trades | Endkapital |
|-----------|----------|----------|----------|----------|--------|---------------|--------|------------|
| 1m | 7 Tage | -4.08 | 39.3% | 4.35 | -1.05 | 0.64 | 191 | $9,591.57 |
| 5m | 30 Tage | -3.34 | 42.8% | 8.60 | -0.18 | 0.89 | 180 | $9,665.94 |
| 15m | 90 Tage | -0.33 | 45.7% | 8.24 | 0.31 | 0.99 | 186 | $9,966.72 |
| 30m | 180 Tage | +4.16 | 45.5% | 11.98 | 0.74 | 1.07 | 211 | $10,416.39 |
| **1h** | **365 Tage** | **+14.20** | **44.4%** | **7.11** | **1.40** | **1.15** | **268** | **$11,420.32** |
| 4h | 365 Tage | +1.41 | 39.3% | 11.08 | 0.35 | 1.02 | 145 | $10,140.74 |
| 1d | 365 Tage | +2.52 | 40.0% | 5.98 | 0.49 | 1.09 | 70 | $10,252.29 |

**Empfehlung:** 1h. Beste Win Rate (44.4%) und niedrigster Max Drawdown unter den profitablen Strategien (7.11%). Solide Wahl fuer risikobewusste Trader.

---

### Liquidation Hunter

Contrarian-Strategie, die gegen ueberfuellte Positionen handelt (Liquidation Heatmap).

| Timeframe | Zeitraum | Return % | Win Rate | Max DD % | Sharpe | Profit Factor | Trades | Endkapital |
|-----------|----------|----------|----------|----------|--------|---------------|--------|------------|
| 1m | 7 Tage | -1.55 | 14.3% | 1.98 | -12.57 | 0.24 | 7 | $9,845.07 |
| 5m | 30 Tage | -1.32 | 25.6% | 3.41 | -1.93 | 0.92 | 39 | $9,868.48 |
| **15m** | **90 Tage** | **+2.04** | **30.9%** | **4.14** | **1.07** | **1.14** | **81** | **$10,203.55** |
| 30m | 180 Tage | -1.79 | 28.6% | 8.08 | -0.54 | 0.99 | 140 | $9,820.81 |
| 1h | 365 Tage | -11.22 | 26.7% | 15.04 | -1.68 | 0.88 | 281 | $8,878.21 |
| 4h | 365 Tage | -11.19 | 27.5% | 15.37 | -1.85 | 0.87 | 269 | $8,881.23 |
| 1d | 365 Tage | -9.88 | 29.1% | 14.73 | -2.15 | 0.82 | 179 | $9,012.26 |

**Empfehlung:** 15m (einziger profitabler Timeframe). Generell schwache Performance -- nur fuer erfahrene Trader mit eigener Analyse.

---

### Sentiment Surfer

Kombiniert Marktstimmung (Fear & Greed, Social Media) mit technischen Indikatoren.

| Timeframe | Zeitraum | Return % | Win Rate | Max DD % | Sharpe | Profit Factor | Trades | Endkapital |
|-----------|----------|----------|----------|----------|--------|---------------|--------|------------|
| 1m | 7 Tage | 0.00 | 0.0% | 0.00 | N/A | 0.00 | 0 | $10,000.00 |
| 5m | 30 Tage | +0.78 | 66.7% | 0.24 | 44.06 | 4.39 | 3 | $10,078.07 |
| 15m | 90 Tage | -1.17 | 26.1% | 2.15 | -3.53 | 0.74 | 23 | $9,882.70 |
| 30m | 180 Tage | -1.48 | 28.2% | 2.20 | -3.09 | 0.82 | 39 | $9,851.53 |
| 1h | 365 Tage | -3.50 | 28.3% | 5.81 | -2.60 | 0.81 | 92 | $9,650.28 |
| 4h | 365 Tage | -3.30 | 29.1% | 5.09 | -2.83 | 0.80 | 79 | $9,669.65 |
| 1d | 365 Tage | -1.67 | 31.2% | 2.76 | -2.86 | 0.76 | 32 | $9,833.17 |

**Empfehlung:** Kein klarer profitabler Timeframe. Die Strategie generiert wenige Signale und war im Backtest-Zeitraum nicht profitabel. Nur in Kombination mit eigener Markteinschaetzung verwenden.

---

### Degen (KI-Arena)

KI-Arena mit 14 Datenquellen und festem Prompt. Hoechstes Gewinnpotenzial aber auch hoechstes Risiko.

| Timeframe | Zeitraum | Return % | Win Rate | Max DD % | Sharpe | Profit Factor | Trades | Endkapital |
|-----------|----------|----------|----------|----------|--------|---------------|--------|------------|
| 1m | 7 Tage | +1.38 | 50.0% | 0.03 | N/A | 62.73 | 2 | $10,138.26 |
| 5m | 30 Tage | -22.28 | 16.7% | 23.27 | -15.85 | 0.24 | 24 | $7,771.63 |
| 15m | 90 Tage | -17.19 | 27.9% | 19.62 | -6.10 | 0.58 | 43 | $8,280.65 |
| 30m | 180 Tage | -9.99 | 36.7% | 21.07 | -2.02 | 0.82 | 60 | $9,000.98 |
| 1h | 365 Tage | +7.21 | 40.3% | 21.79 | 0.58 | 1.07 | 124 | $10,721.19 |
| **4h** | **365 Tage** | **+18.83** | **42.0%** | **20.57** | **1.43** | **1.17** | **119** | **$11,883.49** |
| 1d | 365 Tage | -15.76 | 34.3% | 24.50 | -1.61 | 0.85 | 102 | $8,423.51 |

**Empfehlung:** 4h. Hoechste Rendite aller Strategien (+18.83%), aber auch hohe Drawdowns (20-24% auf allen Timeframes). Nur fuer risikobereite Trader geeignet.

---

### LLM Signal

KI analysiert Marktdaten und gibt LONG/SHORT-Empfehlungen basierend auf LLM-Analyse.

| Timeframe | Zeitraum | Return % | Win Rate | Max DD % | Sharpe | Profit Factor | Trades | Endkapital |
|-----------|----------|----------|----------|----------|--------|---------------|--------|------------|
| 1m | 7 Tage | -0.32 | 25.0% | 1.00 | -2.93 | 0.71 | 4 | $9,968.45 |
| 5m | 30 Tage | -4.86 | 15.0% | 5.35 | -13.73 | 0.30 | 20 | $9,513.62 |
| 15m | 90 Tage | -4.82 | 23.5% | 6.45 | -6.52 | 0.55 | 34 | $9,518.46 |
| 30m | 180 Tage | -5.91 | 26.8% | 6.96 | -4.63 | 0.65 | 56 | $9,408.66 |
| 1h | 365 Tage | -8.94 | 26.3% | 9.45 | -4.10 | 0.67 | 95 | $9,106.06 |
| 4h | 365 Tage | -4.57 | 30.9% | 8.06 | -1.82 | 0.84 | 97 | $9,543.04 |
| 1d | 365 Tage | -6.51 | 28.8% | 7.76 | -2.98 | 0.74 | 80 | $9,348.88 |

**Empfehlung:** Kein profitabler Timeframe im Backtest-Zeitraum. Die Strategie verliert auf allen Timeframes. Nur zu Testzwecken oder in Kombination mit anderen Strategien verwenden.

---

## Top-5 Ranking (nach Sharpe Ratio)

| Rang | Strategie | Timeframe | Return % | Sharpe | Max DD % | Trades |
|------|-----------|-----------|----------|--------|----------|--------|
| 1 | Edge Indicator | 1h | +17.87 | 1.84 | 10.97 | 374 |
| 2 | Edge Indicator | 4h | +11.73 | 1.46 | 7.65 | 218 |
| 3 | Degen (KI-Arena) | 4h | +18.83 | 1.43 | 20.57 | 119 |
| 4 | Claude Edge Indicator | 1h | +14.20 | 1.40 | 7.11 | 268 |
| 5 | Liquidation Hunter | 15m | +2.04 | 1.07 | 4.14 | 81 |

## Empfehlungen fuer Einsteiger

1. **Edge Indicator auf 1h** -- Bestes Gesamtpaket: hohe Rendite, guter Sharpe, moderate Drawdowns
2. **Claude Edge Indicator auf 1h** -- Niedrigster Drawdown (7.11%), solide Rendite, beste Win Rate
3. **Edge Indicator auf 4h** -- Weniger Trades, stabiler, guter Sharpe

## Empfehlungen fuer erfahrene Trader

1. **Degen auf 4h** -- Hoechste Rendite (+18.83%), aber Drawdowns um 20% einplanen
2. **Edge Indicator auf 1h** -- Zuverlaessig und profitabel
3. **Claude Edge Indicator auf 30m** -- Kuerzerer Timeframe mit positivem Return (+4.16%)

---

## Methodik

- **Datenquelle:** Binance Futures (historische Kline-Daten)
- **Zeitraeume:** 7 Tage (1m) bis 365 Tage (1h, 4h, 1d)
- **Startkapital:** $10.000 pro Backtest
- **Gebuehren:** Standardmaessige Taker/Maker-Fees eingerechnet
- **Slippage:** Nicht simuliert
- **Backtest-Datum:** 21. Februar 2026

> **Hinweis:** Backtests bilden ideale Ausfuehrungsbedingungen ab. In der Praxis koennen Slippage, Liquiditaet und Marktbedingungen die Ergebnisse beeinflussen. Diese Daten dienen der Orientierung und ersetzen keine eigene Analyse.
