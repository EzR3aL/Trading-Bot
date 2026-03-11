# Risikoprofil & Kline Intervall — Anleitung fuer den Edge Indicator

Diese Anleitung erklaert, wie **Risikoprofil** und **Kline Intervall** das Verhalten des Edge Indicator Bots beeinflussen, und gibt Empfehlungen fuer die richtige Wahl.

---

## Kurzfassung

| Einstellung | Was sie steuert |
|---|---|
| **Risikoprofil** | Wie viele Trades der Bot eingeht und wie weit die Stops entfernt sind |
| **Kline Intervall** | Welchen Kerzen-Zeitrahmen der Bot fuer seine Indikatoren benutzt |
| **Zeitplan** | Wie oft der Bot eine neue Analyse durchfuehrt |

Alle drei haengen zusammen. Die richtige Kombination entscheidet ueber Ergebnis und Risiko.

---

## Die drei Risikoprofile

### Konservativ — "Weniger Trades, weite Stops"

- **Fuer wen:** Anfaenger, kleinere Konten, wer Verluste minimieren will
- **Verhalten:** Der Bot ist waehlerisch und oeffnet nur Positionen bei sehr klaren Signalen. Laeuft ein Trade, hat er viel Luft durch weite Trailing Stops.
- **Typisch:** 1–3 Trades pro Woche bei BTC

### Standard — "Ausgewogen"

- **Fuer wen:** Die meisten Nutzer, mittlere Konten
- **Verhalten:** Guter Kompromiss zwischen Aktivitaet und Qualitaet. Der Bot tradet regelmaessig, filtert aber choppy Maerkte noch zuverlaessig heraus.
- **Typisch:** 3–7 Trades pro Woche bei BTC

### Aggressiv — "Mehr Trades, enge Stops"

- **Fuer wen:** Erfahrene Trader, groessere Konten, wer hoehere Frequenz und schnellere Gewinne will
- **Verhalten:** Der Bot reagiert sehr schnell auf Preisbewegungen. Engere Stops sichern Gewinne frueher, aber es gibt auch mehr Fehlsignale.
- **Typisch:** 5–15+ Trades pro Woche bei BTC

---

## Parameter-Vergleich (alle Unterschiede)

| Parameter | Konservativ | Standard | Aggressiv |
|---|---|---|---|
| **Kline Intervall** | 4h | 1h | 15m |
| **EMA Fast / Slow** | 8 / 21 | 8 / 21 | 5 / 13 |
| **ADX Chop-Schwelle** | 22.0 | 18.0 | 15.0 |
| **Momentum Bull-Schwelle** | +0.40 | +0.35 | +0.25 |
| **Momentum Bear-Schwelle** | -0.40 | -0.35 | -0.25 |
| **Momentum Smoothing** | 7 Perioden | 5 Perioden | 3 Perioden |
| **Trailing Stop Trail** | 3.0x ATR | 2.5x ATR | 2.0x ATR |
| **Trailing Breakeven** | 2.0x ATR | 1.5x ATR | 1.0x ATR |

### Was bedeuten diese Werte?

| Parameter | Hoeher = | Niedriger = |
|---|---|---|
| **ADX Chop-Schwelle** | Strengerer Trend-Filter, weniger Trades | Lockerer, mehr Trades auch in unsicheren Maerkten |
| **Momentum-Schwelle** | Nur bei starkem Momentum wird reagiert | Schon bei leichter Bewegung wird reagiert |
| **Momentum Smoothing** | Ruhigeres Signal, weniger Noise | Schnellere Reaktion, mehr Noise |
| **Trailing Stop Trail** | Mehr Luft, laesst Gewinne laufen | Enger, sichert Gewinne frueher |
| **Trailing Breakeven** | Position muss weiter im Plus sein bevor der Trailing Stop aktiv wird | Trailing Stop wird frueher aktiviert |
| **EMA Perioden** | Langsamere Trendfindung | Schnellere Trendfindung, mehr Signale |

---

## Kline Intervall im Detail

Das Kline Intervall bestimmt den Kerzen-Zeitrahmen fuer **alle** Indikatoren (EMA, ADX, MACD, RSI, ATR).

| Intervall | Kerzen pro Tag | Reaktionszeit | Signal-Qualitaet | Noise |
|---|---|---|---|---|
| **15m** | 96 | Sehr schnell (Minuten) | Mittel | Hoch |
| **30m** | 48 | Schnell (30 Min) | Mittel-gut | Mittel-hoch |
| **1h** | 24 | Mittel (Stunden) | Gut | Mittel |
| **4h** | 6 | Langsam (halber Tag) | Sehr gut | Niedrig |

### Auswirkung auf den Bot

- **15m Kerzen:** Der Bot sieht jede kleine Preisbewegung. Viele Signale, aber auch viele Fehlsignale. Geeignet fuer schnelle Scalps.
- **30m Kerzen:** Kompromiss zwischen Geschwindigkeit und Zuverlaessigkeit.
- **1h Kerzen:** Der Klassiker. Filtert Noise gut heraus, reagiert trotzdem innerhalb weniger Stunden.
- **4h Kerzen:** Nur die grossen Bewegungen werden erkannt. Wenige aber hochwertige Signale.

---

## Zeitplan (Schedule) — Das dritte Puzzleteil

Der Zeitplan bestimmt, **wie oft** der Bot eine Analyse durchfuehrt. Er muss zum Kline Intervall passen.

### Warum ist das wichtig?

Wenn der Zeitplan kueerzer ist als das Kline Intervall, analysiert der Bot dieselbe Kerze mehrfach — ohne neue Informationen. Das ist Verschwendung und kann zu doppelten Trades fuehren.

### Empfohlene Kombinationen

| Risikoprofil | Kline Intervall | Empfohlener Zeitplan | Warum |
|---|---|---|---|
| **Konservativ** | 4h | Market Sessions (4x/Tag) | Sessions passen perfekt zum 4h-Takt |
| **Konservativ** | 4h | Intervall 4h | Gleichmaessige Analyse alle 4 Stunden |
| **Standard** | 1h | Market Sessions (4x/Tag) | 4 Analysen/Tag reichen fuer 1h-Kerzen |
| **Standard** | 1h | Intervall 1h | Jede neue Kerze wird analysiert |
| **Aggressiv** | 15m | Intervall 15m | Maximale Reaktionsgeschwindigkeit |
| **Aggressiv** | 15m | Intervall 30m | Etwas weniger Noise, jede 2. Kerze |

### Was sind "Market Sessions"?

Der Bot analysiert zu den 4 wichtigsten Handelszeiten:

| Zeit (UTC) | Session | Warum wichtig |
|---|---|---|
| **01:00** | Asien | Liquidierungen nach US-Schluss |
| **08:00** | Europa Open | Frisches Kapital, moegliche Reversals |
| **14:00** | US Open | ETF-Flows, hoechste Volatilitaet |
| **21:00** | US Close | Gewinnmitnahmen, Anpassungen |

---

## Empfehlungen nach Erfahrungslevel

### Einsteiger

| Einstellung | Empfehlung |
|---|---|
| Risikoprofil | **Konservativ** |
| Kline Intervall | **4h** (wird automatisch gesetzt) |
| Zeitplan | **Market Sessions** |
| Leverage | 3x–5x |
| Position Size | 5%–10% |

**Warum:** Wenige, hochwertige Trades. Man lernt den Bot kennen, ohne staendig eingreifen zu muessen. Die weiten Stops verhindern, dass man bei normaler Volatilitaet ausgestoppt wird.

### Fortgeschrittene

| Einstellung | Empfehlung |
|---|---|
| Risikoprofil | **Standard** |
| Kline Intervall | **1h** (wird automatisch gesetzt) |
| Zeitplan | **Market Sessions** oder **Intervall 1h** |
| Leverage | 5x–10x |
| Position Size | 10%–20% |

**Warum:** Guter Kompromiss. Genug Aktivitaet um den Bot sinnvoll einzusetzen, aber nicht so viel Noise dass man staendig ueberwachen muss.

### Erfahrene Trader

| Einstellung | Empfehlung |
|---|---|
| Risikoprofil | **Aggressiv** |
| Kline Intervall | **15m** (wird automatisch gesetzt) |
| Zeitplan | **Intervall 15m** oder **30m** |
| Leverage | 10x–20x |
| Position Size | 15%–25% |

**Warum:** Maximale Trade-Frequenz. Erfordert ein groesseres Konto (wegen mehr Fees) und Verstaendnis fuer die Signalqualitaet. Nicht empfohlen ohne vorheriges Backtesting.

---

## Wichtige Hinweise

### Kline Intervall manuell aendern

Das Risikoprofil setzt das Kline Intervall automatisch. Du kannst es aber manuell ueberschreiben:

- **Konservativ + 1h:** Mehr Analysen als das reine Konservativ-Profil, aber mit den strengen Filtern. Guter Mittelweg.
- **Standard + 4h:** Weniger Trades als Standard, aber mit den Standard-Filtern. Fuer ruhigere Phasen.
- **Aggressiv + 1h:** Aggressivere Filter auf 1h-Kerzen. Mehr Trades als Standard, weniger Noise als 15m.

### Profil aendert nur Defaults

Wenn du einzelne Parameter manuell ueberschreibst (z.B. ADX-Schwelle), hat deine Einstellung **immer Vorrang** vor dem Profil. Das Profil ist nur der Startpunkt.

### Backtesting empfohlen

Bevor du ein Profil im Live-Modus verwendest, teste es im **Backtest** mit dem gleichen Asset und Zeitraum. Der Backtest zeigt dir:

- Wie viele Trades das Profil generiert haette
- Die Winrate und den Gesamt-PnL
- Ob die Trailing Stops sinnvoll gegriffen haben

### Demo-Modus zuerst

Starte jeden neuen Bot immer im **Demo-Modus**. Beobachte 1–2 Wochen, ob die Trade-Frequenz und die Ergebnisse zu deinen Erwartungen passen. Erst dann auf Live wechseln.

---

## FAQ

**Kann ich das Risikoprofil aendern waehrend ein Trade offen ist?**
Nein, aendere das Profil nur wenn der Bot gestoppt ist und keine offene Position hat. Der neue Trailing Stop wuerde sonst nicht auf den laufenden Trade angewendet.

**Was passiert wenn ich Aggressiv waehle aber Market Sessions als Zeitplan?**
Der Bot analysiert 4x am Tag statt 96x. Du bekommst die aggressiven Filter (enge Stops, lockere Schwellen) aber nur 4 Analysen pro Tag. Das kann funktionieren, nutzt aber das Aggressiv-Profil nicht voll aus.

**Welches Profil hat die beste Winrate?**
Konservativ hat typischerweise die hoechste Winrate (weniger Trades, aber qualitativ besser). Aggressiv hat mehr Trades mit niedrigerer Winrate, kann aber durch Volumen trotzdem profitabler sein.

**Gilt das nur fuer Edge Indicator?**
Ja, Risikoprofile gibt es aktuell nur fuer die Edge Indicator Strategie. Andere Strategien (Liquidation Hunter, Sentiment Surfer etc.) verwenden eigene Parameter.
