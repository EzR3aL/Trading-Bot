# Strategie-Dokumentation

## Contrarian Liquidation Hunter

### Überblick

Der Bot agiert als **"Institutional Market Maker"** - er wettet gegen die Masse, wenn Leverage und Sentiment extreme Werte erreichen.

**Kernprinzip:** Wenn zu viele Trader auf einer Seite sind, wird eine Liquidation-Kaskade wahrscheinlich. Der Bot positioniert sich auf der Gegenseite.

---

## Entscheidungslogik

### Schritt 1: Leverage-Analyse (Long/Short Ratio)

Die Long/Short Ratio zeigt das Verhältnis von Long- zu Short-Positionen aller Accounts.

```
Ratio > 2.0  →  Zu viele Longs  →  SHORT Signal
Ratio < 0.5  →  Zu viele Shorts →  LONG Signal
Ratio 0.5-2.0 → Neutral         →  Kein Signal
```

**Warum funktioniert das?**
- Bei extremem Ungleichgewicht werden Liquidationen wahrscheinlicher
- Ein kleiner Preisrückgang bei vielen Longs → Kaskaden-Liquidationen → Preis fällt weiter
- Der Bot nutzt diese Kaskade aus

### Schritt 2: Sentiment-Analyse (Fear & Greed Index)

Der Fear & Greed Index misst die Marktstimmung von 0 (Extreme Fear) bis 100 (Extreme Greed).

```
Index > 75  →  Extreme Greed  →  SHORT Bias
Index < 25  →  Extreme Fear   →  LONG Bias
Index 25-75 →  Neutral        →  Kein Bias
```

**Warum funktioniert das?**
- Extreme Greed = Markt-Top Signal (alle sind euphorisch)
- Extreme Fear = Markt-Bottom Signal (Kapitulation)
- Historisch sind Extremwerte gute Kontraindikatoren

### Schritt 3: Funding Rate Kosten-Analyse

Die Funding Rate zeigt die Kosten für das Halten einer Position.

```
Rate > 0.05%   →  Teuer für Longs   →  SHORT Confidence +20
Rate < -0.02%  →  Teuer für Shorts  →  LONG Confidence +20
```

**Warum funktioniert das?**
- Hohe positive Funding = viele Longs zahlen Shorts
- Irgendwann werden Longs ihre teuren Positionen schließen
- Dies verstärkt den Druck in die Gegenrichtung

---

## Entscheidungsmatrix

| Leverage Signal | Sentiment Signal | Ergebnis |
|-----------------|------------------|----------|
| Crowded Longs | Extreme Greed | **HIGH Confidence SHORT (85-95%)** |
| Crowded Shorts | Extreme Fear | **HIGH Confidence LONG (85-95%)** |
| Crowded Longs | Neutral/Fear | Medium Confidence SHORT (70-80%) |
| Crowded Shorts | Neutral/Greed | Medium Confidence LONG (70-80%) |
| Neutral | Extreme Greed | Low Confidence SHORT (60-70%) |
| Neutral | Extreme Fear | Low Confidence LONG (60-70%) |
| Neutral | Neutral | **Follow 24h Trend (55-65%)** |

---

## Confidence-System

Die Confidence bestimmt:
1. **Ob getradet wird** (Minimum: 55%)
2. **Die Position Size** (höhere Confidence = größere Position)

### Position Sizing nach Confidence

| Confidence | Multiplier | Effektive Position |
|------------|------------|-------------------|
| 90%+ | 1.5x | 15% des Balances |
| 80-89% | 1.25x | 12.5% des Balances |
| 70-79% | 1.0x | 10% des Balances |
| 60-69% | 0.75x | 7.5% des Balances |
| 55-59% | 0.5x | 5% des Balances |
| <55% | - | Kein Trade |

---

## NO NEUTRALITY Prinzip

**Der Bot muss IMMER eine Richtung wählen.**

Wenn alle Signale neutral sind:
1. Analysiere den 24h-Preistrend
2. Folge dem Trend mit niedriger Confidence (55-65%)
3. Verwende kleinere Position Size

**Begründung:**
- Märkte bewegen sich immer
- Neutralität = verpasste Chancen
- Niedrige Confidence = kleines Risiko

---

## Risk/Reward Verhältnis

### Standard-Konfiguration
- **Take Profit:** 3.5%
- **Stop Loss:** 2.0%
- **Risk/Reward Ratio:** 1.75:1

### Break-Even Berechnung

Mit R/R von 1.75:1 brauchen wir folgende Win Rate für Break-Even:

```
Break-Even Win Rate = 1 / (1 + R/R)
                    = 1 / (1 + 1.75)
                    = 36.4%
```

**Unser Ziel: 60% Win Rate** → deutlich über Break-Even

### Erwarteter Gewinn pro Trade

```
Expected Value = (Win Rate × TP) - (Loss Rate × SL)
               = (0.60 × 3.5%) - (0.40 × 2.0%)
               = 2.1% - 0.8%
               = 1.3% pro Trade (vor Fees)
```

---

## Trading-Zeitplan

### Optimierte Sessions (v1.1.0)

| Zeit (UTC) | Session | Strategie-Relevanz |
|------------|---------|-------------------|
| **01:00** | Asia | Liquidations nach US-Close |
| **08:00** | EU Open | Frisches Kapital, mögliche Reversals |
| **14:00** | US Open | ETF-Flows, höchste Volatilität |
| **21:00** | US Close | Profit-Taking, Position-Adjustments |

### Warum diese Zeiten?

1. **Session-Übergänge** haben die höchste Liquidations-Wahrscheinlichkeit
2. **ETF-Handel** (14:00 UTC) bringt institutionelle Flows
3. **4 Analyse-Fenster** ermöglichen bis zu 3 Trades pro Tag

---

## Datenquellen

| Metrik | Quelle | Endpoint |
|--------|--------|----------|
| Fear & Greed | Alternative.me | `/fng/` |
| L/S Ratio | Binance Futures | `/futures/data/globalLongShortAccountRatio` |
| Funding Rate | Binance Futures | `/fapi/v1/premiumIndex` |
| Ticker | Binance Futures | `/fapi/v1/ticker/24hr` |
| Open Interest | Binance Futures | `/fapi/v1/openInterest` |

---

## Beispiel-Szenarien

### Szenario 1: Idealer Short-Trade

**Marktbedingungen:**
- L/S Ratio: 2.8 (Crowded Longs)
- Fear & Greed: 82 (Extreme Greed)
- Funding Rate: 0.08% (Teuer für Longs)
- BTC Preis: $100,000

**Bot-Entscheidung:**
- Signal: **SHORT**
- Confidence: **92%** (Alignment + Funding Boost)
- Position Size: 1.5x = 15% des Balances
- Entry: $100,000
- Take Profit: $96,500 (-3.5%)
- Stop Loss: $102,000 (+2.0%)

### Szenario 2: Konträrer Long-Trade

**Marktbedingungen:**
- L/S Ratio: 0.4 (Crowded Shorts)
- Fear & Greed: 18 (Extreme Fear)
- Funding Rate: -0.05% (Teuer für Shorts)
- BTC Preis: $80,000

**Bot-Entscheidung:**
- Signal: **LONG**
- Confidence: **95%** (Perfektes Alignment)
- Position Size: 1.5x = 15% des Balances
- Entry: $80,000
- Take Profit: $82,800 (+3.5%)
- Stop Loss: $78,400 (-2.0%)

### Szenario 3: Trend-Following (Neutral)

**Marktbedingungen:**
- L/S Ratio: 1.2 (Neutral)
- Fear & Greed: 55 (Neutral)
- Funding Rate: 0.01% (Neutral)
- 24h Change: +2.5%

**Bot-Entscheidung:**
- Signal: **LONG** (folgt dem Trend)
- Confidence: **58%** (Niedrig - keine extremen Signale)
- Position Size: 0.5x = 5% des Balances
- Kleinere Position wegen Unsicherheit

---

## Limitationen

1. **Nicht für Seitwärtsmärkte optimiert** - Strategie braucht Volatilität
2. **Abhängig von externen APIs** - Alternative.me, Binance können ausfallen
3. **Keine Fundamentalanalyse** - Ignoriert News, Halving-Events, etc.
4. **Historische Korrelationen** - Vergangene Muster garantieren keine Zukunft

---

## Weiterentwicklung

### Geplante Verbesserungen
- [ ] Funding Rate Tracking über Zeit (Trend erkennen)
- [ ] Open Interest Änderungsrate einbeziehen
- [ ] Liquidation Heatmaps integrieren
- [ ] Machine Learning für Threshold-Optimierung
