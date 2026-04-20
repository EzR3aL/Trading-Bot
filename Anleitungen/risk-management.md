# Risk Management — Take Profit, Stop Loss, Trailing Stop

Diese Anleitung erklärt, wie der Bot deine offenen Positionen absichert:
Take Profit (TP), Stop Loss (SL) und Trailing Stop. Du lernst, wann ein
Trigger **nativ auf der Exchange** läuft und wann **im Bot** emuliert wird,
was die Badges im Dashboard bedeuten, und wie du Trigger manuell setzt,
änderst oder entfernst.

> **Hinweis (#216):** Echtzeit-Updates auf Dashboard und Portfolio laufen
> jetzt über Server-Sent Events (`/api/trades/stream`) statt über 5-Sekunden-
> Polling. Fällt die SSE-Verbindung aus, wechselt die UI automatisch auf
> Polling zurück — keine Konfiguration nötig.

---

## Die drei Risk-Legs

Jeder offene Trade hat bis zu drei voneinander unabhängige Trigger:

| Leg | Was es macht | Wann es feuert |
|-----|--------------|----------------|
| **Take Profit (TP)** | Schließt die Position mit Gewinn | Preis erreicht das TP-Level |
| **Stop Loss (SL)** | Schließt die Position mit Verlust | Preis erreicht das SL-Level |
| **Trailing Stop** | Zieht den Stop nach, wenn der Preis sich positiv bewegt | Preis gibt um den Callback-Anteil nach |

Alle drei können gleichzeitig aktiv sein. Wer zuerst triggert, gewinnt.

---

## Native vs. Software-Trailing

Nicht jede Exchange kann alle drei Legs selbst verwalten. Der Bot
unterscheidet zwei Quellen:

- **Native (`native_exchange`)** — Die Exchange hält den Trigger und
  feuert ihn auch dann, wenn der Bot offline ist. Immer bevorzugt.
  Exchange-Support: Bitget ✓, BingX ✓, Weex (nur TP/SL, kein Trailing),
  Bitunix (nur TP/SL, kein Trailing), Hyperliquid (nur TP/SL).

- **Software (`software_bot`)** — Der Bot poll't den Preis und schließt
  die Position selbst, wenn das Level erreicht ist. Nur für Hyperliquid-
  Trailing nötig (HL hat keinen nativen Trailing-Stop). **Der Bot muss
  laufen**, sonst feuert der Trigger nicht.

Welche Quelle aktuell hält, siehst du am Badge neben dem Leg.

---

## Badge-Legende

Im Dashboard (Portfolio + Trade-Detail) zeigt jedes Leg ein Badge:

| Badge | Bedeutung |
|-------|-----------|
| `TP • 2311.9 • Exchange` | TP liegt auf der Exchange, wird nativ ausgelöst |
| `SL • 2306 • Bot` | SL wird vom Bot emuliert (Software-Fallback) |
| `Trailing • 0.8 % • Exchange` | Trailing wird nativ verwaltet |
| `SL • pending` | Request unterwegs — Exchange hat noch nicht bestätigt |
| `TP • rejected` | Exchange hat abgelehnt (z. B. Trigger < Markt) |
| `SL • cancel failed` | Cancel der alten Order hat nicht durchgegriffen — Bot wird beim nächsten Cycle erneut versuchen |

**pending** wird nach spätestens 30 s entweder zu `Exchange`/`Bot` oder zu
`rejected`/`cancel failed`. Wenn ein Leg länger als 30 s auf `pending`
steht, prüfe die Logs — siehe „Troubleshooting" unten.

---

## Exit-Gründe verstehen

Wenn eine Position schließt, protokolliert der Bot präzise, **wer den
Close ausgelöst hat**:

| Exit-Reason | Bedeutung |
|-------------|-----------|
| `TAKE_PROFIT_NATIVE` | TP hat auf der Exchange gefeuert |
| `STOP_LOSS_NATIVE` | SL hat auf der Exchange gefeuert |
| `TRAILING_STOP_NATIVE` | Native Trailing hat gefeuert |
| `TRAILING_STOP_SOFTWARE` | Bot hat den Trailing-Close selbst ausgeführt (HL) |
| `STRATEGY_EXIT` | Strategie-Signal wollte die Position raus (kein Trigger) |
| `MANUAL_CLOSE_UI` | Du hast im Dashboard „Close" gedrückt |
| `MANUAL_CLOSE_EXCHANGE` | Close über die Exchange-App / externe API |
| `LIQUIDATION` | Exchange hat zwangsliquidiert |
| `EXTERNAL_CLOSE_UNKNOWN` | Position verschwand, aber kein Readback — sollte nach Epic #188 praktisch nie mehr vorkommen |

Legacy-Codes (`TRAILING_STOP`, `MANUAL_CLOSE`, `EXTERNAL_CLOSE`) stammen
aus der Umstellungsphase vor Frühjahr 2026 und rendern äquivalent zu den
präzisen Codes via i18n-Alias.

---

## So änderst du TP/SL/Trailing

1. Klick auf eine offene Position (Dashboard oder Portfolio)
2. Im Modal: Ziffer ins TP- oder SL-Feld eintragen, oder Trailing-
   Toggle aktivieren + Callback in Prozent eingeben
3. „Speichern" — der Bot führt ein 2-Phase-Commit aus:
   - **Phase A**: Intent in die DB schreiben (Status `pending`)
   - **Phase B**: Alte Order canceln → neue Order platzieren
   - **Phase C**: Exchange-Readback prüft das Ergebnis
   - **Phase D**: DB-Status auf `confirmed` setzen, Badge aktualisieren
4. Badge zeigt `pending` während Phase B läuft, dann `Exchange` bzw.
   `Bot` bei Erfolg.

**Wichtig**: ein geänderter Wert ersetzt den alten vollständig. Ein TP-
Change cancelt nur den TP-Leg — SL und Trailing bleiben unberührt.

### Leg entfernen

- TP-Feld leer lassen + Speichern → TP-Leg wird gecancelt
- Gleiches für SL
- Trailing: Toggle deaktivieren → Trailing wird gecancelt

### Callback-Rounding bei Trailing (Bitget)

Bitget rundet den `callbackRatio` auf **0,01 %** (zwei Nachkommastellen).
Ein Eintrag wie `0,867 %` wird serverseitig auf `0,87 %` gerundet — das
Modal zeigt nach dem Speichern den tatsächlich aktiven Wert.

---

## FAQ

**F: Warum zeigt mein SL `pending` länger als 30 s?**
A: Die Exchange hat die Cancel-Response wahrscheinlich nicht geschickt.
Der Bot versucht beim nächsten Monitor-Cycle (ca. 60 s) erneut. Bleibt
es bei `cancel failed`, siehe Troubleshooting.

**F: Was passiert, wenn der Bot offline geht?**
A: Native TPs, SLs und Trailing (bei unterstützter Exchange) **feuern
weiter** — sie sind auf der Exchange gespeichert. Software-Trailing
(nur Hyperliquid) feuert **nicht**; der Bot muss laufen.

**F: Ich habe TP/SL direkt in der Bitget-App gesetzt. Sieht der Bot das?**
A: Ja, der Bot liest beim nächsten Reconcile-Cycle den Exchange-State
und schreibt ihn in die DB zurück. Die Quelle wird dann als
`native_exchange` markiert.

**F: Kann ich TP und Trailing gleichzeitig haben?**
A: Ja, alle drei Legs sind unabhängig. Wer zuerst triggert, schließt
die Position — die anderen werden automatisch gecancelt.

**F: Warum ist der Trailing-Callback nicht auf 0 %?**
A: Bitget akzeptiert minimal 0,1 % Callback. Kleinere Werte lehnt die
Exchange ab — der Bot rundet auf das Minimum auf.

---

## Troubleshooting

### „Trigger price < market" / „Insufficient position"

- SL für einen LONG wurde **über** dem aktuellen Preis gesetzt (sollte
  darunter sein).
- TP für einen LONG wurde **unter** dem Preis gesetzt (sollte darüber
  sein).
- Für SHORT ist beides umgekehrt.
- Prüfe die Einheit: der Bot erwartet den **Trigger-Preis** (z. B.
  `68500`), nicht eine Prozent-Abweichung.

### Badge zeigt `cancel failed`

Die alte Exchange-Order existiert noch, und der Bot konnte sie nicht
canceln. Möglich wenn:
- Die Order wurde manuell über die Exchange-UI gelöscht → Bot-Retry
  erkennt sie beim nächsten Cycle als weg und setzt den Status auf
  `cleared`.
- Auth-/Netzwerk-Fehler — im Server-Log steht eine `WARN`-Zeile mit
  dem genauen Grund (seit #225 werden diese nie mehr stumm geschluckt).

### Exit-Reason ist `EXTERNAL_CLOSE_UNKNOWN`

Selten, sollte nach Epic #188 (Phase 1, April 2026) praktisch nicht mehr
vorkommen. Bedeutet: die Position wurde geschlossen, aber der Exchange-
Readback konnte den Trigger nicht identifizieren (z. B. Plan-History
wurde bereits GC'd, oder das war ein unüblicher Close-Typ). Details im
Bot-Log beim betroffenen Trade.

---

## Weiterlesen

- Entwickler-Doku für die Anti-Patterns, die die Phase-1-Fixes
  verhindert haben: `docs/risk-state-anti-patterns.md` *(englisch,
  intern)*.
- Release-Historie der Risk-State-Features: `CHANGELOG.md`, Suchbegriff
  „Epic #188".
- Issue-Tracker-Epics: #216 (Roadmap), #188 (Risk-State Truth).
