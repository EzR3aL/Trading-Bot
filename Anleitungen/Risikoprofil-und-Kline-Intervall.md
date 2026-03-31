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

## Die zwei Risikoprofile

### Konservativ — "Weniger Trades, weite Stops"

- **Fuer wen:** Anfaenger, kleinere Konten, wer Verluste minimieren will
- **Verhalten:** Der Bot ist waehlerisch und oeffnet nur Positionen bei sehr klaren Signalen. Laeuft ein Trade, hat er viel Luft durch weite Trailing Stops.
- **Typisch:** 1–3 Trades pro Woche bei BTC

### Standard — "Ausgewogen"

- **Fuer wen:** Die meisten Nutzer, mittlere Konten
- **Verhalten:** Guter Kompromiss zwischen Aktivitaet und Qualitaet. Der Bot tradet regelmaessig, filtert aber choppy Maerkte noch zuverlaessig heraus.
- **Typisch:** 3–7 Trades pro Woche bei BTC

> **Hinweis:** Das Aggressiv-Profil (15m) wurde in v4.6.2 entfernt. Simulationen zeigten eine Winrate von nur 27% und einen PnL von -7.27%. Es stehen nur noch Standard (1h) und Konservativ (4h) zur Verfuegung.

---

## Parameter-Vergleich (alle Unterschiede)

| Parameter | Konservativ | Standard |
|---|---|---|
| **Kline Intervall** | 4h | 1h |
| **EMA Fast / Slow** | 8 / 21 | 8 / 21 |
| **ADX Chop-Schwelle** | 22.0 | 18.0 |
| **Momentum Bull-Schwelle** | +0.40 | +0.35 |
| **Momentum Bear-Schwelle** | -0.40 | -0.35 |
| **Momentum Smoothing** | 7 Perioden | 5 Perioden |
| **Trailing Stop Trail** | 3.0x ATR | 2.5x ATR |
| **Trailing Breakeven** | 2.0x ATR | 1.5x ATR |

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
| **1h** | 24 | Mittel (Stunden) | Gut | Mittel |
| **4h** | 6 | Langsam (halber Tag) | Sehr gut | Niedrig |

### Auswirkung auf den Bot

- **1h Kerzen (Standard):** Der Klassiker. Filtert Noise gut heraus, reagiert trotzdem innerhalb weniger Stunden.
- **4h Kerzen (Konservativ):** Nur die grossen Bewegungen werden erkannt. Wenige aber hochwertige Signale.

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

---

## Wichtige Hinweise

### Kline Intervall manuell aendern

Das Risikoprofil setzt das Kline Intervall automatisch. Du kannst es aber manuell ueberschreiben:

- **Konservativ + 1h:** Mehr Analysen als das reine Konservativ-Profil, aber mit den strengen Filtern. Guter Mittelweg.
- **Standard + 4h:** Weniger Trades als Standard, aber mit den Standard-Filtern. Fuer ruhigere Phasen.

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

**Welches Profil hat die beste Winrate?**
Konservativ hat typischerweise die hoechste Winrate (weniger Trades, aber qualitativ besser). Standard hat mehr Trades mit etwas niedrigerer Winrate, kann aber durch hoehere Frequenz trotzdem profitabler sein.

**Gilt das nur fuer Edge Indicator?**
Ja, Risikoprofile gibt es aktuell nur fuer die Edge Indicator Strategie. LiquidationHunter verwendet eigene Parameter.
