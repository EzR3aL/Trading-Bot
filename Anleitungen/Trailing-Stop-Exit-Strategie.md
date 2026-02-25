# Trailing Stop & Breakeven Exit-Strategie

## Uebersicht

Jede Strategie (Edge Indicator + Claude-Edge) verfuegt ueber ein zweistufiges Exit-System,
das Gewinne automatisch schuetzt und Verlust-Trades minimiert.

## Wie funktioniert es?

### Stufe 1: ATR Trailing Stop

Der Bot merkt sich den **hoechsten Preis** seit dem Trade-Entry (bei Short: den tiefsten).
Sobald der Trade genug Gewinn erreicht hat, wird ein dynamischer Stop gesetzt:

```
Stop = Hoechstpreis - (1.5 x ATR)
```

- **ATR** (Average True Range) misst die aktuelle Volatilitaet ueber 14 Kerzen
- Der Stop **steigt mit** wenn der Preis steigt, faellt aber **nie** zurueck
- Wird der Stop unterschritten → Position wird geschlossen

**Beispiel (Long-Trade):**
```
Entry:         $67,307
Hoechstpreis:  $69,000
ATR(14):       $640
Trail (1.5x):  $960

Stop = $69,000 - $960 = $68,040
→ Preis faellt auf $68,040 → Exit mit +$733 Gewinn (+1.09%)
```

### Stufe 2: Breakeven-Schutz

Der Trailing Stop wird erst **aktiviert**, nachdem der Trade einen Mindestgewinn erreicht hat:

```
Aktivierung ab: Gewinn >= 1.0 x ATR (ca. $640 bei BTC)
```

**Vor Aktivierung:** Nur Indikator-Exits (EMA Ribbon, Momentum) sind aktiv.
**Nach Aktivierung:** Der Stop wird nie unter den Entry-Preis gesetzt — ein
Gewinn-Trade kann nicht mehr zum Verlust werden.

Zusaetzlich: Wenn ein **Indikator-Exit** (bear_trend, regime_flip) ausgeloest wird,
aber der aktuelle Preis unter dem Entry liegt und der Trade zuvor profitabel war,
wird der Exit **blockiert**. Der Bot wartet stattdessen auf den Trailing Stop.

## Parameter

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `trailing_stop_enabled` | `true` | Trailing Stop ein/aus |
| `trailing_breakeven_atr` | `1.0` | ATR-Vielfaches fuer Aktivierung (ab wann der Stop greift) |
| `trailing_trail_atr` | `1.5` | ATR-Vielfaches fuer Trail-Abstand (wie eng der Stop folgt) |
| `atr_period` | `14` | Anzahl Kerzen fuer ATR-Berechnung |

## Exit-Logik im Detail

Bei jedem Monitor-Zyklus (1 Minute) wird geprueft:

```
1. Hoechstpreis aktualisieren (falls neues Hoch)
2. Trailing Stop pruefen:
   - War Trade profitabel genug? (>= breakeven_atr x ATR)
   - Preis unter Stop? → EXIT
3. Indikator-Exit pruefen:
   - bear_trend / bull_trend?
   - neutral + baerisches/bullisches Regime?
   - Regime-Flip?
   → Falls ja UND Breakeven-Schutz aktiv UND Preis im Verlust: BLOCKIERT
   → Falls ja UND kein Breakeven-Schutz: EXIT
4. Keine Bedingung erfuellt → Position halten
```

## Szenarien

### Szenario A: Trade laeuft gut
```
Entry $67,307 → Preis steigt auf $70,000 → Stop bei $69,040
→ Preis faellt auf $69,040 → Exit mit +2.57% Gewinn
```

### Szenario B: Trade laeuft schlecht (kein Gewinn erreicht)
```
Entry $67,307 → Preis steigt nur auf $67,500 (unter Aktivierung)
→ Trailing Stop noch NICHT aktiv
→ Indikator-Exit greift normal → Exit mit kleinem Verlust
```

### Szenario C: Trade war profitabel, Preis dreht
```
Entry $67,307 → Preis steigt auf $68,500 (Aktivierung!)
→ Stop bei max($68,500 - $960, $67,307) = $67,540
→ Preis faellt → Indikator sagt "Exit" bei $67,200
→ BLOCKIERT (unter Entry, aber Trade war profitabel)
→ Stop bei $67,540 greift → Exit mit +0.35% Gewinn
```

## Hinweise

- Die Werte koennen pro Bot in den `strategy_params` angepasst werden
- Fuer engeren Stop: `trailing_trail_atr` senken (z.B. 1.0)
- Fuer spaetere Aktivierung: `trailing_breakeven_atr` erhoehen (z.B. 1.5)
- Der Hoechstpreis wird in der Datenbank gespeichert und ueberlebt Bot-Neustarts
