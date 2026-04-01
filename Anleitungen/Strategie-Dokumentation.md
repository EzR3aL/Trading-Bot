# Trading-Strategien — Vollstaendige Dokumentation

Dieses Dokument erklaert fuer jede der 2 verfuegbaren Strategien im Detail, **wie der Bot tatsaechlich tradet** — die zugrundeliegende Logik, die Datenquellen, die Entscheidungsregeln und die Konfidenz-Berechnung. Benutzer-Einstellungen wie Stop Loss, Take Profit, Leverage usw. werden hier nicht behandelt, da diese unabhaengig von der Strategie konfiguriert werden.

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

**II. Liquidation Hunter**
1. [Ueberblick](#ii1-ueberblick)
2. [Analyse 1: Leverage (Long/Short Ratio)](#ii2-analyse-1-leverage-longshort-ratio)
3. [Analyse 2: Sentiment (Fear & Greed Index)](#ii3-analyse-2-sentiment-fear--greed-index)
4. [Analyse 3: Funding Rate](#ii4-analyse-3-funding-rate)
5. [Signal-Kombination](#ii5-signal-kombination)
6. [Konfidenz-Berechnung](#ii6-konfidenz-berechnung)
7. [Trade-Gate](#ii7-trade-gate)
8. [Beispiel-Szenarien](#ii8-beispiel-szenarien)

**III. Parameter-Referenz**

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

# II. Liquidation Hunter

## II.1 Ueberblick

Contrarian-Strategie, die **gegen die Masse wettet**. Wenn zu viele Trader in eine Richtung positioniert sind, nimmt der Bot die Gegenposition ein — in der Erwartung, dass ueberfuellte Positionen liquidiert werden und den Preis in die andere Richtung treiben.

**Datenquellen:** Binance Futures (L/S Ratio, Funding Rate), Fear & Greed Index, 24h Ticker

| Staerken | Schwaechen |
|----------|-----------|
| Keine API-Kosten | Braucht extreme Marktbedingungen |
| Profitiert von Liquidations-Kaskaden | Bei neutralem Markt schwache Signale |
| Contrarian-Logik historisch profitabel | Kann gegen starke Trends verlieren |
| Klare Entscheidungsregeln | Abhaengig von Binance Futures-Daten |

---

## II.2 Analyse 1: Leverage (Long/Short Ratio)

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

## II.3 Analyse 2: Sentiment (Fear & Greed Index)

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

## II.4 Analyse 3: Funding Rate

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

## II.5 Signal-Kombination

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

## II.6 Konfidenz-Berechnung

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

## II.7 Trade-Gate

```
1. Konfidenz ≥ 60%
2. Entry-Preis > 0
3. TP muss auf der richtigen Seite des Einstiegs liegen
4. SL muss auf der richtigen Seite des Einstiegs liegen
```

**Wichtig:** Diese Strategie hat eine hoehere Mindestkonfidenz (60%) als Edge Indicator (40%), weil schwache Contrarian-Signale besonders riskant sind.

---

## II.8 Beispiel-Szenarien

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

# III. Parameter-Referenz

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

