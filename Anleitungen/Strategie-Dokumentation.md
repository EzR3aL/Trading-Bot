# Trading-Strategien — Vollstaendige Dokumentation

Dieses Dokument erklaert fuer jede Strategie im Detail, **wie der Bot tatsaechlich tradet** — die zugrundeliegende Logik, die Datenquellen, die Entscheidungsregeln und die Konfidenz-Berechnung. Benutzer-Einstellungen wie Stop Loss, Take Profit, Leverage usw. werden hier nicht behandelt, da diese unabhaengig von der Strategie konfiguriert werden.

---

## Inhaltsverzeichnis

**I. Edge Indicator**
1. [Ueberblick](#i1-ueberblick)
2. [Die drei Analyse-Schichten](#i2-die-drei-analyse-schichten)
3. [Schicht 1: EMA Ribbon (8/21)](#i3-schicht-1-ema-ribbon-821)
4. [Schicht 2: ADX Chop-Filter](#i4-schicht-2-adx-chop-filter)
5. [Schicht 3: Predator Momentum Score](#i5-schicht-3-predator-momentum-score)
6. [Signal-Entscheidung](#i6-signal-entscheidung)
7. [Konfidenz-Berechnung](#i7-konfidenz-berechnung)
8. [Trade-Gate](#i8-trade-gate)
9. [Beispiel-Szenarien](#i9-beispiel-szenarien)

**II. Claude Edge Indicator**
1. [Ueberblick](#ii1-ueberblick)
2. [ATR-basierte TP/SL](#ii2-atr-basierte-tpsl)
3. [Volumen-Bestaetigung](#ii3-volumen-bestaetigung)
4. [Multi-Timeframe Abgleich](#ii4-multi-timeframe-abgleich)
5. [Trailing Stop](#ii5-trailing-stop)
6. [Regime-basierte Positionsgroesse](#ii6-regime-basierte-positionsgroesse)
7. [RSI Divergenz-Erkennung](#ii7-rsi-divergenz-erkennung)
8. [Erweiterte Konfidenz-Berechnung](#ii8-erweiterte-konfidenz-berechnung)
9. [Vergleich mit Edge Indicator](#ii9-vergleich-mit-edge-indicator)

**III. Liquidation Hunter**
1. [Ueberblick](#iii1-ueberblick)
2. [Analyse 1: Leverage (Long/Short Ratio)](#iii2-analyse-1-leverage-longshort-ratio)
3. [Analyse 2: Sentiment (Fear & Greed Index)](#iii3-analyse-2-sentiment-fear--greed-index)
4. [Analyse 3: Funding Rate](#iii4-analyse-3-funding-rate)
5. [Signal-Kombination](#iii5-signal-kombination)
6. [Konfidenz-Berechnung](#iii6-konfidenz-berechnung)
7. [Trade-Gate](#iii7-trade-gate)
8. [Beispiel-Szenarien](#iii8-beispiel-szenarien)

**IV. Sentiment Surfer**
1. [Ueberblick](#iv1-ueberblick)
2. [Die 6 Scoring-Quellen](#iv2-die-6-scoring-quellen)
3. [Quelle 1: News Sentiment (GDELT)](#iv3-quelle-1-news-sentiment-gdelt)
4. [Quelle 2: Fear & Greed Index](#iv4-quelle-2-fear--greed-index)
5. [Quelle 3: VWAP/OIWAP](#iv5-quelle-3-vwapoiwap)
6. [Quelle 4: Supertrend](#iv6-quelle-4-supertrend)
7. [Quelle 5: Spot Volume](#iv7-quelle-5-spot-volume)
8. [Quelle 6: Price Momentum](#iv8-quelle-6-price-momentum)
9. [Gewichtete Aggregation](#iv9-gewichtete-aggregation)
10. [Agreement-Check](#iv10-agreement-check)
11. [Beispiel-Szenarien](#iv11-beispiel-szenarien)

**V. Degen**
1. [Ueberblick](#v1-ueberblick)
2. [Die 19 Datenquellen](#v2-die-19-datenquellen)
3. [Der System-Prompt](#v3-der-system-prompt)
4. [Datenaufbereitung fuer den LLM](#v4-datenaufbereitung-fuer-den-llm)
5. [Trade-Gate](#v5-trade-gate)
6. [Vergleich mit LLM Signal](#v6-vergleich-mit-llm-signal)

**VI. Parameter-Referenz**

---

---

# I. Edge Indicator

## I.1 Ueberblick

Rein technische Strategie basierend auf dem TradingView "Trading Edge" Indikator. Verwendet ausschliesslich Kline-Daten (OHLCV) von Binance — keine externen APIs, keine KI.

**Datenquelle:** Binance Klines (200 Kerzen, Standard 1h)

| Staerken | Schwaechen |
|----------|-----------|
| Keine externen API-Abhaengigkeiten | Rein rueckwaertsblickend |
| Klare, nachvollziehbare Regeln | Kann in schnellen Trends zu spaet einsteigen |
| Chop-Filter verhindert Fehlsignale | Funktioniert am besten in trendenden Maerkten |
| Regime-Erkennung fuer fruehe Trendwechsel | Keine Sentiment- oder Fundamentaldaten |

---

## I.2 Die drei Analyse-Schichten

```
Kline-Daten (200 Kerzen, 1h)
         │
         ├──► Schicht 1: EMA Ribbon ──► Trend-Richtung (Bull / Bear / Neutral)
         │
         ├──► Schicht 2: ADX Filter ──► Markt-Qualitaet (Trending / Choppy)
         │
         └──► Schicht 3: Predator Momentum ──► Timing & Staerke (Score -1 bis +1)
                                                │
                                                └──► Regime (Bull / Neutral / Bear)
                                                     │
                                                     └──► Regime Flip Detection
```

---

## I.3 Schicht 1: EMA Ribbon (8/21)

Zwei Exponential Moving Averages bilden ein "Ribbon" (Band). Die Position des Preises relativ zum Band bestimmt die Trend-Richtung.

```
EMA 8  = Exponentieller Durchschnitt der letzten 8 Schlusskurse
EMA 21 = Exponentieller Durchschnitt der letzten 21 Schlusskurse

Oberkante = max(EMA 8, EMA 21)
Unterkante = min(EMA 8, EMA 21)
```

| Bedingung | Ergebnis | Bedeutung |
|-----------|----------|-----------|
| Preis > Oberkante | **Bull Trend** | Aufwaertstrend |
| Preis < Unterkante | **Bear Trend** | Abwaertstrend |
| Unterkante ≤ Preis ≤ Oberkante | **Neutral** | Kein klarer Trend |

Zusaetzlich wird erkannt, ob der Preis **gerade erst** das Ribbon durchbrochen hat (Bull/Bear Enter), was die Relevanz erhoeht.

---

## I.4 Schicht 2: ADX Chop-Filter

Der **Average Directional Index (ADX)** misst die Staerke eines Trends (nicht die Richtung).

| Wert | Bedeutung |
|------|-----------|
| ADX | Trend-Staerke (0-100) |
| +DI | Staerke der Aufwaertsbewegung |
| -DI | Staerke der Abwaertsbewegung |

**Filter-Logik:**

```
ADX ≥ 18  →  Markt trendet  →  Trading erlaubt
ADX < 18  →  Markt ist "choppy"  →  KEIN Trade
```

In Seitwaertsmaerkten erzeugen EMA-Strategien viele Fehlsignale — der ADX-Filter verhindert das.

---

## I.5 Schicht 3: Predator Momentum Score

Ein zusammengesetzter Score aus drei Komponenten:

### MACD Histogram (normalisiert)

```
MACD = EMA(12) - EMA(26)
Signal = EMA(9) von MACD
Histogram = MACD - Signal

macd_norm = tanh(Histogram / StdDev(Histogram, 100))
→ Ergebnis: [-1, +1]
```

### RSI Drift (Aenderungsrate)

```
RSI = Standard-RSI (14 Perioden)
RSI geglaettet = EMA(5) des RSI
RSI Drift = RSI_geglaettet[jetzt] - RSI_geglaettet[vorher]

rsi_norm = tanh(RSI_Drift / 2.0)
→ Ergebnis: [-1, +1]
```

Misst nicht den RSI-Wert selbst, sondern seine **Veraenderungsgeschwindigkeit**.

### Trend Bonus

```
EMA 8 > EMA 21  →  +0.6
EMA 8 < EMA 21  →  -0.6
```

### Zusammenfuehrung

```
raw_score = macd_norm + rsi_norm + trend_bonus
score = clamp(raw_score, -1.0, +1.0)
smoothed_score = EMA(3) ueber die letzten Scores
```

### Regime-Erkennung

| Smoothed Score | Regime |
|----------------|--------|
| > +0.20 | **Bull** |
| < -0.20 | **Bear** |
| -0.20 bis +0.20 | **Neutral** |

**Regime Flip**: Wechsel von einem Regime zum anderen (z.B. Neutral → Bull). Wird erkannt und erhoeht die Konfidenz um 10 Punkte.

---

## I.6 Signal-Entscheidung

### Primaere Regeln

```
LONG:   Bull Trend + ADX ≥ 18 + Momentum Regime ≥ 0
SHORT:  Bear Trend + ADX ≥ 18 + Momentum Regime ≤ 0
```

### Sekundaere Regeln (EMA neutral)

```
LONG:   ADX ≥ 18 + Momentum Regime = Bull + KEIN Bear Trend
SHORT:  ADX ≥ 18 + Momentum Regime = Bear + KEIN Bull Trend
```

### Fallback (ADX choppy)

```
Folge Momentum-Regime oder EMA-Ausrichtung
```

**Der Bot erzeugt IMMER ein Signal.** Ob es ausgefuehrt wird, entscheidet das Trade-Gate.

---

## I.7 Konfidenz-Berechnung

Startet bei **50** und wird angepasst:

| Faktor | Punkte | Bedingung |
|--------|--------|-----------|
| ADX Staerke Bonus | +0 bis +25 | 0.8 pro Punkt ueber 18 |
| ADX Chop Malus | -0 bis -20 | 1 pro Punkt unter 18 |
| Starkes Momentum | +20 | \|score\| > 0.5 |
| Mittleres Momentum | +12 | \|score\| > 0.3 |
| Schwaches Momentum | +5 | \|score\| > 0.15 |
| Volle Uebereinstimmung | +10 | EMA + ADX + Momentum aligned |
| Regime Flip | +10 | Frischer Wechsel |

**Range**: 0 bis 95

---

## I.8 Trade-Gate

```
1. Entry-Preis > 0
2. ADX-Filter: Markt darf nicht choppy sein
3. Konfidenz ≥ 40%
```

---

## I.9 Beispiel-Szenarien

### Starker Aufwaertstrend

```
EMA: Bull ✓ | ADX: 32 ✓ | Momentum: +0.72 (Bull) ✓ | Regime Flip ✓

Konfidenz: 50 + 11 + 20 + 10 + 10 = 95% → LONG
```

### Seitwaertsmarkt

```
EMA: Neutral | ADX: 12 ✗

Konfidenz: 50 - 6 = 44% → ADX-Filter blockiert → KEIN Trade
```

### Schwacher Baeren-Trend

```
EMA: Bear ✓ | ADX: 19 ✓ | Momentum: -0.18 (Neutral)

Konfidenz: 50 + 1 + 5 = 56% → SHORT (aber moderate Konfidenz)
```

---

---

# II. Claude Edge Indicator

## II.1 Ueberblick

Erweiterte Version des Edge Indicators mit **6 Verbesserungen** fuer intelligenteres Risk Management. Trotz des Namens verwendet diese Strategie **keine KI** — die Verbesserungen wurden aus einer Backtest-Analyse identifiziert.

**Basis:** Identische 3 Schichten wie Edge Indicator (EMA Ribbon, ADX, Predator Momentum)

**Datenquellen:** Binance Klines 1h + 4h (fuer Multi-Timeframe)

| # | Verbesserung | Effekt |
|---|-------------|--------|
| 1 | ATR-basierte TP/SL | Dynamische Ziele statt fester Prozente |
| 2 | Volumen-Bestaetigung | Kauf-/Verkaufsvolumen bestaetigt Signal |
| 3 | Multi-Timeframe (4h) | Hoeherer Zeitrahmen als Filter |
| 4 | Trailing Stop | Gewinne laufen lassen |
| 5 | Regime-basierte Groesse | Staerkere Signale → groessere Position |
| 6 | RSI Divergenz | Fruehe Reversal-Erkennung |

---

## II.2 ATR-basierte TP/SL

Feste %-Ziele ignorieren die Markt-Volatilitaet. **ATR** (Average True Range) misst die durchschnittliche Schwankungsbreite:

```
ATR = Durchschnitt der True Ranges der letzten 14 Kerzen

Take Profit = Einstieg ± (ATR × 2.5)
Stop Loss   = Einstieg ∓ (ATR × 1.5)
```

**Beispiel:**

```
BTC: $65,000 | ATR: $450

LONG: TP = $66,125 (+1.73%) | SL = $64,325 (-1.04%)

Bei hoher Volatilitaet (ATR = $900):
LONG: TP = $67,250 (+3.46%) | SL = $63,650 (-2.08%)
```

---

## II.3 Volumen-Bestaetigung

Aus den Klines wird das Kauf/Verkauf-Verhaeltnis berechnet:

```
Buy Ratio = Taker-Buy-Volume / Gesamtvolumen
```

| Buy Ratio | Score | Interpretation |
|-----------|-------|----------------|
| ≥ 0.58 | +1.0 | Starker Kaufdruck |
| 0.50 - 0.58 | 0 bis +1.0 | Leichter Kaufdruck |
| 0.42 - 0.50 | -1.0 bis 0 | Leichter Verkaufsdruck |
| ≤ 0.42 | -1.0 | Starker Verkaufsdruck |

**Konfidenz-Einfluss:**
- Volumen bestaetigt Richtung: **+1 bis +8 Punkte**
- Volumen widerspricht: **-3 Punkte**

---

## II.4 Multi-Timeframe Abgleich

Die Strategie holt zusaetzlich 100 Kerzen vom 4h-Chart und prueft das EMA Ribbon (8/21):

```
4h: Preis > Oberkante → HTF bullish
4h: Preis < Unterkante → HTF bearish
```

| 1h Signal | 4h Trend | Effekt |
|-----------|----------|--------|
| LONG | HTF bullish | +5 |
| SHORT | HTF bearish | +5 |
| LONG | HTF bearish | -3 |
| SHORT | HTF bullish | -3 |

---

## II.5 Trailing Stop

Statt eines festen SL folgt der Stop dem Preis:

```
1. Trade eroeffnet mit SL (ATR × 1.5)
2. Preis erreicht +ATR×1.0 im Gewinn → SL auf Einstieg (Breakeven)
3. Preis steigt weiter → SL folgt mit ATR×1.5 Abstand
4. SL bewegt sich nur in Gewinnrichtung, nie zurueck
```

**Beispiel (LONG):**

```
Einstieg: $65,000 | ATR: $450

Initial SL: $64,325
Breakeven ab: $65,450 → SL auf $65,000
Preis bei $67,000 → SL bei $66,325
Preis faellt → geschlossen bei $66,325 (Gewinn: +$1,325)
```

---

## II.6 Regime-basierte Positionsgroesse

```
Konfidenz 40%  → 0.50x (halbe Position)
Konfidenz 67%  → 0.75x
Konfidenz 95%  → 1.00x (volle Position)

Formel: scale = 0.5 + ((confidence - 40) / 55) × 0.5
```

---

## II.7 RSI Divergenz-Erkennung

Erkennt Divergenzen ueber die letzten 20 Kerzen:

| Typ | Preis | RSI | Bedeutung |
|-----|-------|-----|-----------|
| **Bullische Divergenz** | Tiefere Tiefs | Hoehere Tiefs | Abwaertstrend verliert Kraft |
| **Baerische Divergenz** | Hoehere Hochs | Tiefere Hochs | Aufwaertstrend verliert Kraft |

| Situation | Konfidenz |
|-----------|-----------|
| Divergenz bestaetigt Regime | **+8** |
| Divergenz warnt gegen Regime | **-10** |

---

## II.8 Erweiterte Konfidenz-Berechnung

Alle Edge-Indicator-Faktoren plus:

| Neuer Faktor | Punkte |
|-------------|--------|
| Volumen bestaetigt | +1 bis +8 |
| Volumen widerspricht | -3 |
| HTF bestaetigt | +5 |
| HTF widerspricht | -3 |
| RSI Divergenz bestaetigt | +8 |
| RSI Divergenz warnt | -10 |

---

## II.9 Vergleich mit Edge Indicator

| Aspekt | Edge Indicator | Claude Edge |
|--------|---------------|-------------|
| Richtungslogik | EMA + ADX + Momentum | Identisch |
| TP/SL | Feste % | ATR-basiert (dynamisch) |
| Volumen | Nicht beruecksichtigt | Buy/Sell Ratio |
| Multi-Timeframe | Nein | 4h EMA Ribbon |
| Trailing Stop | Nein | ATR-basiert mit Breakeven |
| Positionsgroesse | Fest | Konfidenz-skaliert (0.5x-1.0x) |
| RSI Divergenz | Nein | ±8/10 Punkte |
| API-Aufrufe | 1 | 2 |

---

---

# III. Liquidation Hunter

## III.1 Ueberblick

Contrarian-Strategie, die **gegen die Masse wettet**. Wenn zu viele Trader in eine Richtung positioniert sind, nimmt der Bot die Gegenposition ein — in der Erwartung, dass ueberfuellte Positionen liquidiert werden und den Preis in die andere Richtung treiben.

**Datenquellen:** Binance Futures (L/S Ratio, Funding Rate), Fear & Greed Index, 24h Ticker

| Staerken | Schwaechen |
|----------|-----------|
| Keine API-Kosten | Braucht extreme Marktbedingungen |
| Profitiert von Liquidations-Kaskaden | Bei neutralem Markt schwache Signale |
| Contrarian-Logik historisch profitabel | Kann gegen starke Trends verlieren |
| Klare Entscheidungsregeln | Abhaengig von Binance Futures-Daten |

---

## III.2 Analyse 1: Leverage (Long/Short Ratio)

### Was ist die Long/Short Ratio?

Die Binance Long/Short Account Ratio zeigt, wie viele Trader Long vs. Short positioniert sind.

```
L/S Ratio = Anzahl Long-Accounts / Anzahl Short-Accounts
```

### Interpretation (Contrarian!)

| L/S Ratio | Signal | Logik |
|-----------|--------|-------|
| > 2.5 | **SHORT** | Zu viele Longs → Liquidation der Longs erwartet |
| < 0.4 | **LONG** | Zu viele Shorts → Short Squeeze erwartet |
| 0.4 - 2.5 | Neutral | Keine extreme Positionierung |

### Konfidenz-Boost

```
Boost = min((Abstand zur Schwelle) × 2, 30)

Beispiel: L/S Ratio = 3.5
  Excess = 3.5 - 2.5 = 1.0
  Boost = min(1.0 × 2, 30) = 2 → +2% Konfidenz

Beispiel: L/S Ratio = 5.0
  Excess = 5.0 - 2.5 = 2.5
  Boost = min(2.5 × 2, 30) = 5 → +5% Konfidenz
```

---

## III.3 Analyse 2: Sentiment (Fear & Greed Index)

### Was ist der Fear & Greed Index?

Eine Skala von 0 (extreme Angst) bis 100 (extreme Gier), basierend auf Volatilitaet, Volumen, Social Media, Umfragen und Bitcoin-Dominanz.

### Interpretation (Contrarian!)

| FGI | Signal | Logik |
|-----|--------|-------|
| > 80 | **SHORT** | Extreme Gier → Markt ueberbewertet, Korrektur erwartet |
| < 20 | **LONG** | Extreme Angst → Panik-Verkaeufe, Erholung erwartet |
| 20 - 80 | Neutral | Kein Extrem |

### Spezialfall: Kapitulation (FGI < 10)

Wird als **besonders starkes LONG-Signal** gewertet ("Capitulation phase, bounce expected").

### Konfidenz-Boost

```
Boost = min(Abstand zur Schwelle, 20)

Beispiel: FGI = 5
  Excess = 20 - 5 = 15
  Boost = min(15, 20) = 15 → +15% Konfidenz fuer LONG

Beispiel: FGI = 90
  Excess = 90 - 80 = 10
  Boost = min(10, 20) = 10 → +10% Konfidenz fuer SHORT
```

---

## III.4 Analyse 3: Funding Rate

### Was ist die Funding Rate?

Periodische Zahlungen zwischen Long- und Short-Tradern auf Futures-Maerkten. Positive Rate = Longs zahlen Shorts, negative Rate = Shorts zahlen Longs.

### Interpretation

| Funding Rate | Effekt | Logik |
|-------------|--------|-------|
| > 0.05% | Verstaerkt SHORT | Teuer fuer Longs → Druck auf Long-Positionen |
| < -0.02% | Verstaerkt LONG | Teuer fuer Shorts → Druck auf Short-Positionen |
| -0.02% bis 0.05% | Neutral | Keine extreme Finanzierungsbelastung |

### Konfidenz-Boost

Bis zu **+20 Punkte** wenn die Funding Rate das Signal bestaetigt.

---

## III.5 Signal-Kombination

Die drei Analysen werden zu einem finalen Signal kombiniert:

### Entscheidungsmatrix

```
┌──────────────────┬──────────────────┬────────────────────────────┐
│ Leverage Signal   │ Sentiment Signal │ Entscheidung               │
├──────────────────┼──────────────────┼────────────────────────────┤
│ Crowded Longs    │ Extreme Gier     │ SHORT (85-95% Konfidenz)   │
│ Crowded Shorts   │ Extreme Angst    │ LONG  (85-95% Konfidenz)   │
│ Crowded Longs    │ Neutral/Angst    │ SHORT (70% Konfidenz)      │
│ Crowded Shorts   │ Neutral/Gier     │ LONG  (70% Konfidenz)      │
│ Neutral          │ Extreme Gier     │ SHORT (60-75% Konfidenz)   │
│ Neutral          │ Extreme Angst    │ LONG  (60-75% Konfidenz)   │
│ Neutral          │ Neutral          │ Folge 24h Trend (60%)      │
└──────────────────┴──────────────────┴────────────────────────────┘
```

### Logik im Detail

1. **Beide Signale stimmen ueberein** (z.B. Crowded Longs + Extreme Gier):
   - Hoechste Konfidenz (85-95%)
   - Beide Boosts addiert

2. **Nur Leverage extrem**:
   - Folge dem Leverage-Signal
   - Konfidenz gedeckelt auf 70%

3. **Nur Sentiment extrem**:
   - Folge dem Sentiment-Signal
   - Konfidenz niedriger (60-75%)

4. **Kein Signal extrem**:
   - Fallback: Folge dem 24h-Preistrend
   - Preis steigt → LONG, Preis faellt → SHORT
   - Basis-Konfidenz: 60%

### Funding Rate als Verstaerker

Die Funding Rate aendert nie die Richtung — sie verstaerkt oder schwaeht nur das bestehende Signal um bis zu ±20 Punkte.

### Konfidenz-Bereich

Am Ende wird die Konfidenz auf **60% bis 95%** begrenzt.

---

## III.6 Konfidenz-Berechnung

```
Basis:                        50
+ Leverage Boost:             0 bis +30
+ Sentiment Boost:            0 bis +20
+ Funding Rate Boost:         0 bis +20
+ Alignment Bonus:            +35 (wenn beide Analysen uebereinstimmen)
- Mixed Signal Penalty:       -15 (wenn Signale widersprechen)

Clamp: [60, 95]
```

---

## III.7 Trade-Gate

```
1. Konfidenz ≥ 60%
2. Entry-Preis > 0
3. TP muss auf der richtigen Seite des Einstiegs liegen
4. SL muss auf der richtigen Seite des Einstiegs liegen
```

**Wichtig:** Diese Strategie hat eine hoehere Mindestkonfidenz (60%) als Edge Indicator (40%), weil schwache Contrarian-Signale besonders riskant sind.

---

## III.8 Beispiel-Szenarien

### Ideales Contrarian-Setup

```
L/S Ratio: 3.8 (stark Long-lastig) → SHORT ✓
FGI: 88 (extreme Gier) → SHORT ✓
Funding Rate: 0.08% (teuer fuer Longs) → Boost SHORT ✓

→ Signal: SHORT
→ Konfidenz: 50 + 2(Leverage) + 8(Sentiment) + 20(Funding) + 35(Alignment) = 95%
```

### Nur Leverage extrem

```
L/S Ratio: 0.3 (stark Short-lastig) → LONG ✓
FGI: 55 (neutral) → kein Signal
Funding Rate: neutral

→ Signal: LONG (Leverage dominant)
→ Konfidenz: ~70% (kein Sentiment-Support)
```

### Neutraler Markt

```
L/S Ratio: 1.5 (ausgeglichen) → kein Signal
FGI: 50 (neutral) → kein Signal
BTC 24h: +1.2% → LONG (Fallback)

→ Signal: LONG (Trend-Fallback)
→ Konfidenz: 60% (Minimum)
```

### Kapitulation

```
L/S Ratio: 1.8 (leicht Long) → kein extremes Signal
FGI: 5 (extreme Angst, Kapitulation!) → starkes LONG
Funding Rate: -0.03% (Shorts zahlen) → Boost LONG

→ Signal: LONG
→ Konfidenz: 50 + 15(Sentiment) + 20(Funding) = 85%
```

---

---

# IV. Sentiment Surfer

## IV.1 Ueberblick

Ausgewogene Multi-Quellen-Strategie, die **6 verschiedene Datenquellen** kombiniert. Jede Quelle erzeugt einen Score von -100 (maximal baerisch) bis +100 (maximal bullisch). Der gewichtete Durchschnitt ergibt die finale Entscheidung.

**Besonderheit:** Es muessen mindestens 3 von 6 Quellen in die gleiche Richtung zeigen (Agreement-Check).

| Staerken | Schwaechen |
|----------|-----------|
| Multi-Faktor — nicht von einer Quelle abhaengig | Mehr API-Aufrufe = langsamer |
| Graceful Degradation bei Ausfaellen | GDELT (News) kann unzuverlaessig sein |
| Gewichtete Aggregation | Moderates Signal bei gemischten Maerkten |
| Agreement-Gate reduziert Fehlsignale | Kann starke Trends verpassen |

---

## IV.2 Die 6 Scoring-Quellen

| # | Quelle | Gewicht | Typ |
|---|--------|---------|-----|
| 1 | News Sentiment (GDELT) | 1.0x | Extern |
| 2 | Fear & Greed Index | 1.0x | Extern |
| 3 | VWAP/OIWAP | 1.2x | Berechnet |
| 4 | Supertrend | 1.2x | Berechnet |
| 5 | Spot Volume | 0.8x | Berechnet |
| 6 | Price Momentum | 0.8x | Berechnet |

VWAP und Supertrend haben **hoehere Gewichtung** (1.2x) weil sie als zuverlaessiger gelten. Volumen und Momentum haben **niedrigere Gewichtung** (0.8x) weil sie rauschiger sind.

---

## IV.3 Quelle 1: News Sentiment (GDELT)

### Datenquelle

GDELT (Global Database of Events, Language, and Tone) liefert Nachrichtenartikel der letzten 24 Stunden mit einem Tone-Score.

### Scoring

```
Tone > +1.0  → Score = Tone × 10 (bullisch)
Tone < -1.0  → Score = Tone × 10 (baerisch)
|Tone| ≤ 1.0 → Score = 0 (neutral)
```

### Graceful Degradation

Wenn GDELT keine Artikel liefert (Timeout, API-Ausfall), wird die News-Quelle komplett aus der Berechnung und dem Agreement-Check entfernt. Die verbleibenden 5 Quellen entscheiden allein.

---

## IV.4 Quelle 2: Fear & Greed Index

### Interpretation (Contrarian — wie Liquidation Hunter)

```
FGI < 25  →  Score = +100 (extreme Angst → bullisch)
FGI > 75  →  Score = -100 (extreme Gier → baerisch)
FGI 25-75 →  Score = 0 (neutral)
```

**Lineare Skalierung:**
- FGI 25 → 0 Punkte
- FGI 0 → +100 Punkte
- FGI 75 → 0 Punkte
- FGI 100 → -100 Punkte

---

## IV.5 Quelle 3: VWAP/OIWAP

### Was ist VWAP?

Volume Weighted Average Price — der durchschnittliche Preis gewichtet nach Handelsvolumen. Gilt als "fairer Preis" eines Assets.

### Was ist OIWAP?

Open Interest Weighted Average Price — wie VWAP, aber gewichtet nach Open Interest (offenen Futures-Positionen).

### Scoring

```
Abweichung = (Preis - VWAP) / VWAP × 100

Score = Abweichung × 2000 (begrenzt auf [-100, +100])

Wenn OIWAP verfuegbar:
  Blend = 60% VWAP-Score + 40% OIWAP-Score
```

| Situation | Score | Bedeutung |
|-----------|-------|-----------|
| Preis 2% ueber VWAP | +100 | Stark ueberbewertet → trotzdem bullisch (Trend) |
| Preis 0.5% ueber VWAP | +40 | Leicht ueber Fair Value |
| Preis = VWAP | 0 | Am fairen Preis |
| Preis 1% unter VWAP | -80 | Unter Fair Value → baerisch |

---

## IV.6 Quelle 4: Supertrend

### Was ist der Supertrend?

Ein ATR-basierter Trendfolge-Indikator. Er zeichnet eine Linie ober- oder unterhalb des Preises:

```
ATR Periode: 10 | Multiplikator: 3.0

Gruen (Aufwaertstrend): Preis ueber dem Supertrend-Level
Rot (Abwaertstrend): Preis unter dem Supertrend-Level
```

### Scoring

| Richtung | Score |
|----------|-------|
| Gruen (Uptrend) | **+70** |
| Rot (Downtrend) | **-70** |
| Neutral | 0 |

---

## IV.7 Quelle 5: Spot Volume

### Berechnung

```
Buy Ratio = Taker-Buy-Volume / Gesamtvolumen (ueber 24h)
```

### Scoring

```
Score = (Buy_Ratio - 0.5) × 400

Buy Ratio 0.55 → Score = +20 (Akkumulation)
Buy Ratio 0.45 → Score = -20 (Distribution)
Buy Ratio 0.60 → Score = +40 (starke Akkumulation)
```

| Buy Ratio | Score | Interpretation |
|-----------|-------|----------------|
| > 0.55 | Positiv | Kaufdruck dominiert |
| 0.45 - 0.55 | ~0 | Ausgeglichen |
| < 0.45 | Negativ | Verkaufsdruck dominiert |

---

## IV.8 Quelle 6: Price Momentum

### Berechnung

Basierend auf der 24h-Preisaenderung:

```
Grosse Bewegung (|change| > 2%):
  Score = change × 20

Moderate Bewegung (0.5% - 2%):
  Score = change × 15

Rauschen (|change| < 0.5%):
  Score = 0
```

### Beispiele

| 24h Change | Score | Interpretation |
|-----------|-------|----------------|
| +3.5% | +70 | Starker bullischer Momentum |
| +1.2% | +18 | Moderater bullischer Momentum |
| +0.3% | 0 | Rauschen, ignoriert |
| -2.8% | -56 | Starker baerischer Momentum |

---

## IV.9 Gewichtete Aggregation

Alle 6 Scores werden gewichtet zusammengefasst:

```
weighted_score = Σ(Score_i × Gewicht_i) / Σ(Gewicht_i)
```

### Beispiel

```
News:      +25  × 1.0 =  25.0
FGI:      +100  × 1.0 = 100.0
VWAP:      +40  × 1.2 =  48.0
Supertrend: +70  × 1.2 =  84.0
Volume:    +20  × 0.8 =  16.0
Momentum:  +18  × 0.8 =  14.4

Summe Gewichte: 1.0 + 1.0 + 1.2 + 1.2 + 0.8 + 0.8 = 6.0
weighted_score = 287.4 / 6.0 = 47.9

→ Richtung: LONG (positiver Score)
→ Konfidenz: 48% (= |weighted_score|, max 95)
```

---

## IV.10 Agreement-Check

Neben der Konfidenz gibt es eine **Mindestzustimmung**: Mindestens 3 von 6 Quellen muessen mit der finalen Richtung uebereinstimmen.

```
LONG-Signal:
  News > 0?       Ja → zaehlt
  FGI > 0?        Ja → zaehlt
  VWAP > 0?       Ja → zaehlt
  Supertrend > 0?  Ja → zaehlt
  Volume > 0?      Nein → zaehlt nicht
  Momentum > 0?    Ja → zaehlt

Agreement: 5/6 → ≥ 3 ✓ → Trade erlaubt
```

**Wenn News nicht verfuegbar ist:**

```
Agreement wird aus 5 statt 6 Quellen berechnet.
Min Agreement bleibt bei 3 (von 5).
```

### Trade-Gate

```
1. Agreement ≥ 3
2. Konfidenz ≥ 40%
3. Entry-Preis > 0
```

---

## IV.11 Beispiel-Szenarien

### Bullishes Alignment (5/6 Quellen)

```
News:       +25 (positive Medien)
FGI:       +100 (extreme Angst, contrarian bullisch)
VWAP:       +80 (Preis ueber VWAP)
Supertrend: +70 (gruener Uptrend)
Volume:     +32 (58% Buy Ratio)
Momentum:   +18 (1.2% 24h Anstieg)

Weighted Score: +54.7 → LONG
Agreement: 6/6 ✓
Konfidenz: 55%
```

### Gemischte Signale (3/6 Quellen)

```
News:       -12 (leicht negativ)
FGI:          0 (neutral)
VWAP:        +4 (knapp ueber VWAP)
Supertrend: -70 (roter Downtrend)
Volume:      -8 (leichter Verkaufsdruck)
Momentum:     0 (seitwaerts)

Weighted Score: -15.3 → SHORT
Agreement: 2/6 ✗ → KEIN Trade (unter Minimum von 3)
```

### Starker Abwaertstrend

```
News:       -40 (negative Medien)
FGI:          0 (neutral, nicht extrem)
VWAP:      -100 (weit unter VWAP)
Supertrend: -70 (roter Downtrend)
Volume:     -32 (Verkaufsdruck)
Momentum:   -56 (starker 24h Rueckgang)

Weighted Score: -52.8 → SHORT
Agreement: 5/6 ✓
Konfidenz: 53%
```

---

---

# V. Degen

## V.1 Ueberblick

Eine **vorkonfigurierte KI-Arena-Strategie** mit festem System-Prompt und 19 festen Datenquellen. Im Gegensatz zur LLM Signal Strategie (wo der User Prompt und Datenquellen waehlt) ist beim Degen alles vordefiniert — der User konfiguriert nur **LLM-Provider, Modell und Temperatur**.

**Kernidee:** Alle verfuegbaren Marktdaten werden als strukturiertes JSON an einen LLM geschickt, der dann LONG oder SHORT entscheiden muss.

| Staerken | Schwaechen |
|----------|-----------|
| 19 Datenquellen = breite Marktabdeckung | LLM-API-Kosten pro Aufruf |
| Keine Prompt-Kenntnisse noetig | Abhaengig von LLM-Qualitaet |
| NEUTRAL verboten = immer eine Entscheidung | Fester Prompt nicht anpassbar |
| Multi-Exchange-Daten (Binance, Bybit, Deribit) | Nicht reproduzierbar (LLM-Zufall) |

---

## V.2 Die 19 Datenquellen

Alle Daten werden **gleichzeitig** (parallel) geholt:

### Preis & Sentiment

| # | Quelle | API | Inhalt |
|---|--------|-----|--------|
| 1 | Spot Price | Binance | BTC Preis, 24h Aenderung, Volumen |
| 2 | Fear & Greed Index | Alternative.me | FGI Wert + Klassifikation |
| 3 | News Sentiment | GDELT | Nachrichtenartikel-Tone (24h) |

### Derivatives & Positionierung

| # | Quelle | API | Inhalt |
|---|--------|-----|--------|
| 4 | Funding Rate | Binance Futures | Aktuelle Finanzierungsrate |
| 5 | Open Interest | Binance Futures | Offene Positionen |
| 6 | Long/Short Ratio | Binance Futures | Account-Verhaeltnis + Interpretation |
| 7 | Order Book | Binance | Bid/Ask Tiefe |
| 8 | Liquidations | Binance Futures | Aktuelle Liquidationen + Risiko-Score |

### Technische Indikatoren

| # | Quelle | Berechnet aus | Inhalt |
|---|--------|---------------|--------|
| 9 | Supertrend | Klines | Trend-Richtung, ATR |
| 10 | VWAP | Klines | Volume-Weighted Average Price |
| 11 | OIWAP | Klines + OI | Open-Interest-Weighted Average Price |
| 12 | Spot Volume | Klines | Buy/Sell Ratio, Akkumulation/Distribution |
| 13 | Realized Volatility | Klines | 24h Volatilitaet in % |
| 14 | CVD | Klines | Cumulative Volume Delta + Trend |

### Cross-Exchange

| # | Quelle | API | Inhalt |
|---|--------|-----|--------|
| 15 | Coinbase Premium | Coinbase + Binance | US-Institutionen Kauf-/Verkaufsdruck |
| 16 | Bybit Futures | Bybit V5 | OI, Funding, Volume von Bybit |

### Options-Daten

| # | Quelle | API | Inhalt |
|---|--------|-----|--------|
| 17 | Deribit Options Extended | Deribit | Implied Volatility, Skew, Put/Call Ratio |
| 18 | Deribit DVOL | Deribit | Crypto Volatilitaets-Index |

### Berechnete Metriken

| # | Quelle | Inhalt |
|---|--------|--------|
| 19 | Market Cap (CoinGecko) | BTC Dominanz, Gesamt-Marktkapitalisierung |

---

## V.3 Der System-Prompt

Der Prompt ist **fest und nicht aenderbar**:

```
You are an elite crypto trader competing in a prediction arena.
Your goal is to predict the movement of Bitcoin (BTC) over the next hour.

CRITICAL RULES:
1. You MUST choose a direction: 'LONG' (Bullish) or 'SHORT' (Bearish).
2. NEUTRAL stances are STRICTLY FORBIDDEN. You must make a decisive call.
3. Provide a confidence score (0-100) based on the strength of the signals.
4. Predict a specific closing price for 1 hour from now.
5. Provide a concise reasoning (max 3 sentences).

Your response MUST follow this exact format:
DIRECTION: [LONG or SHORT]
CONFIDENCE: [number from 0 to 100]
REASONING: [2-3 sentences explaining your analysis]
```

**Wichtig:** NEUTRAL ist verboten. Der LLM muss sich immer entscheiden.

---

## V.4 Datenaufbereitung fuer den LLM

Die 19 Datenquellen werden in ein strukturiertes JSON umgewandelt. Jede Quelle enthaelt:

- **Rohdaten** (Zahlen, Verhaeltnisse)
- **Interpretations-Text** (z.B. "High long bias — contrarian SHORT signal")

Beispiel-Auszug:

```json
{
  "bitcoin": {
    "usd": 65000.00,
    "usd_24h_vol": 28000000000,
    "usd_24h_change": -1.234
  },
  "fearGreed": {
    "value": "18",
    "value_classification": "Extreme Fear"
  },
  "derivatives": {
    "longShortRatio": {
      "current": 2.85,
      "trend": "bullish",
      "interpretation": "Long/short ratio: 2.85. High long bias — contrarian SHORT signal."
    },
    "premiumIndex": {
      "fundingRate": "0.00082000",
      "markPrice": "65000.00"
    }
  },
  "supertrend": {
    "trend": "DOWN",
    "value": 66500.00,
    "signal": "Price 2.26% below Supertrend at $66,500"
  },
  "coinbasePremium": {
    "premiumPct": -0.0012,
    "signal": "bearish",
    "interpretation": "Coinbase premium: -0.0012%. US selling pressure."
  }
}
```

Dieses JSON wird als User-Message an den LLM geschickt. Der LLM analysiert es und gibt DIRECTION, CONFIDENCE und REASONING zurueck.

---

## V.5 Trade-Gate

```
1. Konfidenz ≥ 55% (hoeher als bei anderen Strategien)
2. Entry-Preis > 0
```

Die hoehere Mindestkonfidenz (55% statt 40%) reflektiert, dass LLM-Entscheidungen weniger deterministisch sind als algorithmische.

---

## V.6 Vergleich mit LLM Signal

| Aspekt | Degen | LLM Signal |
|--------|-------|------------|
| Datenquellen | 19 (fest) | User waehlbar |
| System-Prompt | Fest (nicht aenderbar) | User schreibt eigenen Prompt |
| Zielhorizont | 1h BTC (optimiert) | Frei waehlbar |
| User-Konfiguration | Nur Provider/Modell/Temp | Alles konfigurierbar |
| Min. Konfidenz | 55% | Variabel |
| Komplexitaet | Einfach fuer User | Erfordert Prompt-Engineering |

---

---

# VI. Parameter-Referenz

## Edge Indicator

| Parameter | Standard | Beschreibung |
|-----------|---------|--------------|
| EMA Fast | 8 | Schnelle EMA-Periode |
| EMA Slow | 21 | Langsame EMA-Periode |
| ADX Periode | 14 | ADX Berechnungsperiode |
| ADX Schwelle | 18.0 | Unter diesem Wert = choppy |
| MACD | 12/26/9 | MACD Fast/Slow/Signal |
| RSI Periode | 14 | RSI Berechnungsperiode |
| Min. Konfidenz | 40% | Unter diesem Wert kein Trade |
| Kline Intervall | 1h | Kerzen-Zeitrahmen |

## Claude Edge Indicator (zusaetzlich)

| Parameter | Standard | Beschreibung |
|-----------|---------|--------------|
| ATR Periode | 14 | ATR Berechnungsperiode |
| ATR TP Multiplier | 2.5 | TP = ATR × Multiplier |
| ATR SL Multiplier | 1.5 | SL = ATR × Multiplier |
| HTF Intervall | 4h | Hoeherer Zeitrahmen |
| HTF Filter aktiv | Ja | 4h-Abgleich einschalten |
| Trailing Stop | Ja | Trailing mit Breakeven |
| Divergenz Lookback | 20 | Kerzen fuer Divergenz |
| Min Position Scale | 0.5 | 50% bei schwachem Signal |
| Max Position Scale | 1.0 | 100% bei starkem Signal |

## Liquidation Hunter

| Parameter | Standard | Beschreibung |
|-----------|---------|--------------|
| L/S Crowded Longs | 2.5 | Ab hier SHORT-Signal |
| L/S Crowded Shorts | 0.4 | Unter hier LONG-Signal |
| FGI Extreme Angst | 20 | Unter hier contrarian LONG |
| FGI Extreme Gier | 80 | Ueber hier contrarian SHORT |
| Funding High | 0.05% | Verstaerkt SHORT |
| Funding Low | -0.02% | Verstaerkt LONG |
| Min. Konfidenz | 60% | Hoeher als andere Strategien |

## Sentiment Surfer

| Parameter | Standard | Beschreibung |
|-----------|---------|--------------|
| Supertrend ATR | 10/3.0 | Periode/Multiplikator |
| VWAP Periode | 24h | Fair-Value-Berechnung |
| News Lookback | 24h | Nachrichtenzeitraum |
| Gewicht News | 1.0x | Scoring-Gewicht |
| Gewicht FGI | 1.0x | Scoring-Gewicht |
| Gewicht VWAP | 1.2x | Scoring-Gewicht (erhoht) |
| Gewicht Supertrend | 1.2x | Scoring-Gewicht (erhoht) |
| Gewicht Volume | 0.8x | Scoring-Gewicht (reduziert) |
| Gewicht Momentum | 0.8x | Scoring-Gewicht (reduziert) |
| Min Agreement | 3/6 | Quellen muessen zustimmen |
| Min. Konfidenz | 40% | Unter diesem Wert kein Trade |

## Degen

| Parameter | Standard | Beschreibung |
|-----------|---------|--------------|
| LLM Provider | Groq | KI-Anbieter |
| Temperatur | 0.3 | 0 = deterministisch, 1 = kreativ |
| Min. Konfidenz | 55% | Hoeher wegen LLM-Varianz |
| Datenquellen | 19 (fest) | Nicht konfigurierbar |
| Prompt | Fest | Nicht konfigurierbar |
