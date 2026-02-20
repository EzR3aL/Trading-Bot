# Backtesting-Anleitung

Wie du Backtests erstellst, ausfuehrst und die Ergebnisse interpretierst.

---

## Inhaltsverzeichnis

1. [Was ist Backtesting?](#1-was-ist-backtesting)
2. [Einen Backtest erstellen](#2-einen-backtest-erstellen)
3. [Ergebnisse interpretieren](#3-ergebnisse-interpretieren)
4. [Strategien vergleichen](#4-strategien-vergleichen)
5. [Tipps fuer aussagekraeftige Backtests](#5-tipps-fuer-aussagekraeftige-backtests)

---

## 1. Was ist Backtesting?

Backtesting simuliert eine Trading-Strategie mit **historischen Marktdaten**. Du kannst testen, wie eine Strategie in der Vergangenheit abgeschnitten haette, bevor du echtes Geld riskierst.

### Verfuegbar seit

Version **3.3.1** (Februar 2026). Vollstaendig im Frontend integriert.

### Unterstuetzte Strategien

Alle 6 Strategien koennen getestet werden:
- LiquidationHunter
- LLM Signal
- Sentiment Surfer
- Degen
- Edge Indicator
- Claude Edge Indicator

---

## 2. Einen Backtest erstellen

### Schritt 1: Backtest-Seite oeffnen

Navigiere im Dashboard zur Seite **"Backtest"** in der linken Navigation.

### Schritt 2: Konfiguration waehlen

| Einstellung | Beschreibung | Empfehlung |
|-------------|-------------|------------|
| **Strategie** | Welche Trading-Strategie getestet werden soll | Edge Indicator fuer Anfaenger |
| **Trading Pair** | BTCUSDT, ETHUSDT, SOLUSDT, etc. | BTCUSDT |
| **Timeframe** | Kerzen-Intervall: 1m, 5m, 15m, 30m, 1h, 4h, 1D | **1h** (bestes Verhaeltnis Genauigkeit/Geschwindigkeit) |
| **Startdatum** | Beginn des Testzeitraums | 90 Tage zurueck |
| **Enddatum** | Ende des Testzeitraums | Heute |
| **Startkapital** | Simuliertes Anfangskapital in USD | $10,000 |
| **Leverage** | Hebelwirkung | 3x |
| **Take Profit** | Gewinnmitnahme in % | 3.5% |
| **Stop Loss** | Verlustbegrenzung in % | 2.0% |

### Schritt 3: Backtest starten

Klicke auf **"Backtest starten"**. Der Backtest laeuft im Hintergrund -- du kannst die Seite verlassen und spaeter zurueckkommen.

### Schritt 4: Ergebnisse ansehen

Nach Abschluss zeigt die Seite:
- **Equity Curve** (Kapitalverlauf)
- **Metriken-Karten** (Return, Win Rate, Drawdown, etc.)
- **Trade Log** (alle simulierten Trades)

---

## 3. Ergebnisse interpretieren

### Wichtige Metriken

| Metrik | Bedeutung | Guter Wert |
|--------|-----------|------------|
| **Total Return** | Gesamtrendite in % | > 10% (90 Tage) |
| **Win Rate** | Anteil gewonnener Trades | > 45% |
| **Max Drawdown** | Maximaler Kapitalrueckgang | < 10% |
| **Sharpe Ratio** | Rendite im Verhaeltnis zum Risiko | > 2.0 |
| **Profit Factor** | Verhaeltnis Gewinne zu Verlusten | > 1.5 |
| **Total Trades** | Anzahl ausgefuehrter Trades | Abhaengig von Timeframe |

### Equity Curve lesen

Die Equity Curve zeigt den **Kapitalverlauf** ueber den Testzeitraum:

- **Stetig steigend**: Gutes Zeichen -- Strategie ist konsistent profitabel
- **Starke Ausschlaege**: Hohe Volatilitaet -- Risiko pruefen
- **Lange Plateaus**: Wenige Trades oder Seitwaetrtsmarkt
- **Steiler Abfall**: Drawdown-Phase -- pruefen ob temporaer oder systemisch

### Trade Log verstehen

Jeder Trade im Log zeigt:

| Spalte | Beschreibung |
|--------|-------------|
| Datum | Entry-Zeitpunkt |
| Symbol | Trading Pair |
| Richtung | LONG oder SHORT |
| Entry Price | Einstiegspreis |
| Exit Price | Ausstiegspreis |
| PnL | Gewinn/Verlust in USD |
| PnL % | Gewinn/Verlust in Prozent |
| Dauer | Haltezeit |

### Warnzeichen

- **Win Rate < 35%**: Strategie generiert zu viele Verlusttrades
- **Max Drawdown > 15%**: Zu hohes Risiko, Position Size reduzieren
- **Profit Factor < 1.0**: Strategie ist netto verlustbringend
- **Sharpe Ratio < 0**: Rendite ist negativ oder zu volatil
- **Wenige Trades (< 20)**: Statistisch nicht aussagekraeftig

---

## 4. Strategien vergleichen

### Vergleichsansatz

Fuehre mehrere Backtests mit **identischen Parametern** durch und vergleiche:

1. **Gleicher Zeitraum** fuer alle Strategien
2. **Gleiches Trading Pair** (z.B. BTCUSDT)
3. **Gleicher Timeframe** (z.B. 1h)
4. **Gleiches Kapital und Leverage**

### Vergleichs-Checkliste

| Kriterium | Gewichtung | Warum |
|-----------|------------|-------|
| Sharpe Ratio | Hoch | Bestes Mass fuer risikoadjustierte Rendite |
| Max Drawdown | Hoch | Schuetzt vor zu grossen Verlusten |
| Profit Factor | Mittel | Zeigt ob Gewinne Verluste uebersteigen |
| Total Return | Mittel | Absolute Performance |
| Win Rate | Niedrig | Allein nicht aussagekraeftig (R/R beachten) |

### Beispiel-Vergleich

```
Strategie A: Return +26%, Win Rate 54%, Drawdown 4.7%, Sharpe 5.51
Strategie B: Return +18%, Win Rate 47%, Drawdown 9.8%, Sharpe 2.91

-> Strategie A ist besser: Hoehere Rendite bei geringerem Risiko
```

---

## 5. Tipps fuer aussagekraeftige Backtests

### Do's

- **Teste mindestens 90 Tage** -- Kuerzere Zeitraeume sind statistisch unzuverlaessig
- **Verwende 1h Timeframe** -- Bestes Verhaeltnis aus Genauigkeit und Signal-Qualitaet
- **Teste verschiedene Marktphasen** -- Bull, Bear und Seitwaetrts
- **Vergleiche mit Buy-and-Hold** -- Uebertrifft die Strategie einfaches Halten?
- **Pruefe den Max Drawdown** -- Koenntest du diesen Verlust emotional verkraften?

### Don'ts

- **Nicht ueberoptimieren** -- Perfekte Backtest-Parameter funktionieren oft nicht live
- **Nicht nur Win Rate beachten** -- Ein Bot mit 40% Win Rate kann profitabel sein (wenn R/R stimmt)
- **Nicht zu kurze Zeitraeume** -- 7 Tage sagen nichts aus
- **Nicht Backtest = Live erwarten** -- Slippage, Fees und Timing sind live anders

### Naechste Schritte nach dem Backtest

1. **Bester Backtest gefunden?** -> Im Demo-Modus 1-2 Wochen live testen
2. **Demo-Performance gut?** -> Mit kleinem Kapital live gehen
3. **Live-Performance stimmt?** -> Schrittweise Position Size erhoehen

---

---

# Backtesting Guide (English)

How to create and run backtests and interpret the results.

---

## Table of Contents

1. [What is Backtesting?](#what-is-backtesting)
2. [Creating a Backtest](#creating-a-backtest)
3. [Interpreting Results](#interpreting-results)
4. [Comparing Strategies](#comparing-strategies)
5. [Tips for Meaningful Backtests](#tips-for-meaningful-backtests)

---

## What is Backtesting?

Backtesting simulates a trading strategy with **historical market data**. You can test how a strategy would have performed in the past before risking real money.

Available since version **3.3.1** (February 2026). Fully integrated in the frontend.

All 6 strategies can be tested: LiquidationHunter, LLM Signal, Sentiment Surfer, Degen, Edge Indicator, Claude Edge Indicator.

---

## Creating a Backtest

### Step 1: Open Backtest Page

Navigate to the **"Backtest"** page in the left sidebar.

### Step 2: Choose Configuration

| Setting | Description | Recommendation |
|---------|-------------|----------------|
| **Strategy** | Which trading strategy to test | Edge Indicator for beginners |
| **Trading Pair** | BTCUSDT, ETHUSDT, SOLUSDT, etc. | BTCUSDT |
| **Timeframe** | Candle interval: 1m, 5m, 15m, 30m, 1h, 4h, 1D | **1h** (best accuracy/speed ratio) |
| **Start Date** | Beginning of test period | 90 days back |
| **End Date** | End of test period | Today |
| **Initial Capital** | Simulated starting capital in USD | $10,000 |
| **Leverage** | Leverage multiplier | 3x |
| **Take Profit** | Profit target in % | 3.5% |
| **Stop Loss** | Loss limit in % | 2.0% |

### Step 3: Start Backtest

Click **"Start Backtest"**. The backtest runs in the background -- you can leave the page and return later.

### Step 4: View Results

After completion, the page shows:
- **Equity Curve** (capital progression)
- **Metrics Cards** (Return, Win Rate, Drawdown, etc.)
- **Trade Log** (all simulated trades)

---

## Interpreting Results

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

- **Steadily rising**: Good sign -- strategy is consistently profitable
- **Sharp swings**: High volatility -- check risk parameters
- **Long plateaus**: Few trades or sideways market
- **Steep drop**: Drawdown phase -- check if temporary or systemic

### Warning Signs

- **Win Rate < 35%**: Strategy generates too many losing trades
- **Max Drawdown > 15%**: Too much risk, reduce position size
- **Profit Factor < 1.0**: Strategy is net unprofitable
- **Sharpe Ratio < 0**: Return is negative or too volatile
- **Few Trades (< 20)**: Not statistically significant

---

## Comparing Strategies

Run multiple backtests with **identical parameters** and compare:

1. Same time period for all strategies
2. Same trading pair (e.g., BTCUSDT)
3. Same timeframe (e.g., 1h)
4. Same capital and leverage

### Comparison Priority

| Criterion | Weight | Why |
|-----------|--------|-----|
| Sharpe Ratio | High | Best measure for risk-adjusted return |
| Max Drawdown | High | Protects against excessive losses |
| Profit Factor | Medium | Shows if wins exceed losses |
| Total Return | Medium | Absolute performance |
| Win Rate | Low | Not meaningful alone (consider R/R) |

---

## Tips for Meaningful Backtests

### Do's

- **Test at least 90 days** -- shorter periods are statistically unreliable
- **Use 1h timeframe** -- best balance of accuracy and signal quality
- **Test different market phases** -- bull, bear, and sideways
- **Compare with buy-and-hold** -- does the strategy outperform simple holding?
- **Check max drawdown** -- could you emotionally handle this loss?

### Don'ts

- **Don't over-optimize** -- perfect backtest parameters often don't work live
- **Don't focus only on win rate** -- a 40% win rate bot can be profitable (if R/R is good)
- **Don't use short periods** -- 7 days tell you nothing
- **Don't expect backtest = live** -- slippage, fees, and timing differ in live trading

### Next Steps After Backtesting

1. **Found the best backtest?** -> Run in demo mode for 1-2 weeks
2. **Demo performance good?** -> Go live with small capital
3. **Live performance matches?** -> Gradually increase position size
