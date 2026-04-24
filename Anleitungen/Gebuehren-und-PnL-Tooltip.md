# Gebuehren-Tracking und PnL-Tooltip

Anleitung, wo und wie Edge Bots Handelsgebuehren und Funding-Zahlungen
darstellt, und wie der gemeldete PnL sich daraus zusammensetzt.

---

## DE

### 1. Warum ein eigenes Gebuehren-Tracking?

Bei Perpetual-Futures-Trades entstehen pro Position mehrere Kosten:

- **Trading-Gebuehren** (Maker/Taker) beim Oeffnen und Schliessen
- **Funding-Zahlungen** alle 1 oder 8 Stunden, abhaengig von der Exchange
- Bei Hyperliquid zusaetzlich die **Builder-Fee**, wenn du einen Builder
  konfiguriert hast

Ohne konsequente Trennung wuerde dein PnL entweder zu optimistisch
aussehen (brutto) oder die Gebuehren waeren unsichtbar. Edge Bots
persistiert pro Trade die Summen und zeigt sie auf mehreren Seiten.

### 2. Voraussetzungen

- Mindestens ein abgeschlossener Trade auf einer verbundenen Exchange
- Aktuelle App-Version (Fee-Breakdown ist seit v4.4 aktiv)

### 3. Wo werden Gebuehren angezeigt?

| Ort | Sichtbar | Quelle |
|-----|---------|-------|
| **Dashboard** | Subtitel der Gesamt-PnL-Kachel | `GET /api/dashboard/stats` |
| **Dashboard** | "Builder-Fee Einnahmen"-Sektion | `stats.total_builder_fees` |
| **Portfolio** | Karten pro Exchange + Total-Zeile | `GET /api/portfolio/summary` |
| **Trades** | Tooltip auf der PnL-Zelle | `trade.fees`, `trade.funding_paid` |
| **Steuerbericht** | Eigene Spalte "Transaktionsgebuehr" | `GET /api/reports/tax` |

Der wichtigste Ort fuer den Detailblick ist der Tooltip auf der
Trades-Seite.

### 4. Der PnL-Tooltip auf der Trades-Seite

Komponente `frontend/src/components/ui/PnlCell.tsx`. Die PnL-Zelle einer
**geschlossenen** Position ist hover- und focus-fuehlig. Beim Hover oder
Keyboard-Focus erscheint oben rechts ein Tooltip mit:

```
Transaktionsgebuehr:   $0.42
Funding:               $0.08
---
Summe:                 $0.50
```

Labels im Tooltip:
- `trades.fees` -> "Transaktionsgebuehr"
- `dashboard.funding` -> "Funding"
- `common.total` -> "Summe"

Die Summe erscheint nur, wenn `fees + funding_paid > 0` ist.
Einzel-Werte unter 0.01 werden als `--` angezeigt.

Wichtig: Der Tooltip ist nur fuer `status = "closed"` aktiv. Bei offenen
Positionen (`open`) wird weder Hover-Listener noch Tab-Index gesetzt -
das verhindert missverstaendliche Zahlen, solange die Position noch
laeuft.

![PnL-Tooltip auf der Trades-Seite](./screenshots/trades-pnl-tooltip.png)
<!-- Screenshot manuell erstellen: Trades-Seite, mit Maus ueber eine "Closed"-PnL-Zelle hovern und den Tooltip abfotografieren. -->

### 5. Wie werden die Zahlen aggregiert?

Im Backend laeuft der Aggregator in
`src/services/portfolio_service.py` / `src/services/trades_service.py`.
Das zentrale Feld auf dem Trade-Record ist `fees` (Summe aus Entry- und
Exit-Gebuehren). Funding-Zahlungen werden separat in `funding_paid`
gehalten. Builder-Fees stehen in `builder_fee` (nur relevant, wenn du
selbst Builder bist).

Beim Schliessen einer Position ruft `TradeCloser` die Exchange-API nach
dem Netto-Trade-Result auf. Die Exchange liefert Fee und Funding als
eigene Felder - Edge Bots speichert sie *so, wie die Exchange sie
zurueckgibt*, ohne eigene Umrechnung. Daher stimmen die Zahlen im Bot
mit den Exchange-Abrechnungen ueberein.

### 6. Netto vs. brutto

Der angezeigte `total_pnl` (Dashboard, Portfolio) ist **netto**: die
Fee-Summe und die Funding-Summe sind bereits vom realisierten Gewinn
abgezogen. Die Untertitel / Tooltips listen die Abzuege transparent
darunter, aber sie werden nicht doppelt verrechnet.

Das heisst:

- Im Dashboard: `Gesamt-PnL = realisierter_pnl - fees - funding`
- Im Trades-Tooltip: Summe = was du an die Exchange bezahlt hast
- Im Portfolio: `PnL` pro Exchange ist ebenfalls netto

### 7. Sonderfall: Builder-Fee

Builder-Fees sind kein Verlust, sondern eine *Einnahme*, die du von der
Exchange fuer geroutetes Volumen bekommst. Deshalb erscheinen sie nicht
im PnL-Tooltip (der nur Kosten zeigt), sondern auf dem Dashboard in der
Sektion **Builder-Fee Einnahmen** (siehe
[Dashboard und Revenue](./Dashboard-und-Revenue.md)).

### 8. Haeufige Fragen

- **"Wieso zeigt der Tooltip nichts an?"** - Die Position ist noch
  offen (`status = "open"`). Der Tooltip wird erst nach Close aktiv.
- **"Fee = 0, aber ich habe bezahlt"** - Manche Demo-Exchanges liefern
  Fees nicht ueber die API. Im Live-Modus sollte der Wert stimmen.
- **"Funding ist positiv, obwohl ich Funding erhalten habe"** - Der
  gespeicherte Wert ist die **gezahlte** Summe. Erhaltenes Funding
  (negativer Cashflow) gehoert mit in `funding_paid`, aber als
  negativer Betrag. Die Anzeige prueft `> 0`, also werden positive
  Zahlungen angezeigt, erhaltene Betraege bleiben unsichtbar.
- **"Steuerbericht zeigt andere Gebuehren"** - Der Steuerbericht
  aggregiert pro Trade auf Basis derselben Felder, filtert aber nach
  anderem Zeitraum. Mit identischem `date_from` / `date_to` passen die
  Summen zusammen.

---

## EN

### 1. Why dedicated fee tracking?

Every perpetual-futures trade incurs multiple costs:

- **Trading fees** (maker/taker) on open and close.
- **Funding payments** every 1 or 8 hours, depending on the exchange.
- On Hyperliquid additionally the **builder fee** if you have configured
  a builder.

Without proper separation PnL would either look too optimistic (gross)
or the fees would hide completely. Edge Bots persists the per-trade
totals and surfaces them on multiple pages.

### 2. Prerequisites

- At least one closed trade on a connected exchange.
- Current app version (fee breakdown has been active since v4.4).

### 3. Where are fees shown?

| Location | Visible as | Source |
|----------|-----------|-------|
| **Dashboard** | Subtitle on the Total PnL tile | `GET /api/dashboard/stats` |
| **Dashboard** | "Builder Fee Revenue" section | `stats.total_builder_fees` |
| **Portfolio** | Per-exchange cards + total row | `GET /api/portfolio/summary` |
| **Trades** | Tooltip on the PnL cell | `trade.fees`, `trade.funding_paid` |
| **Tax report** | Own "Transaction fee" column | `GET /api/reports/tax` |

The main detail view is the tooltip on the Trades page.

### 4. The PnL tooltip on the Trades page

Component `frontend/src/components/ui/PnlCell.tsx`. The PnL cell of a
**closed** position is hover- and focus-sensitive. On hover or keyboard
focus a tooltip appears top-right:

```
Transaction fee:       $0.42
Funding:               $0.08
---
Total:                 $0.50
```

Labels:
- `trades.fees` -> "Transaction fee"
- `dashboard.funding` -> "Funding"
- `common.total` -> "Total"

The total line only renders when `fees + funding_paid > 0`. Individual
values below 0.01 are rendered as `--`.

Important: the tooltip is only active for `status = "closed"`. For open
positions (`open`) no hover listener and no tab index is attached -
that prevents misleading numbers while a position is still running.

### 5. How are the numbers aggregated?

The backend aggregator lives in `src/services/portfolio_service.py` and
`src/services/trades_service.py`. The central field on the trade record
is `fees` (sum of entry and exit fees). Funding payments are kept
separately in `funding_paid`. Builder fees are in `builder_fee` (only
relevant when you act as the builder yourself).

When closing a position, `TradeCloser` queries the exchange API for the
net trade result. The exchange returns fee and funding as separate
fields - Edge Bots stores them *exactly as returned*, without any
re-computation. That is why the numbers in the bot match the exchange
statements.

### 6. Net vs. gross

The displayed `total_pnl` (Dashboard, Portfolio) is **net**: fees and
funding have already been subtracted from realised profit. Subtitles /
tooltips list the deductions transparently, but they are not subtracted
twice.

Concretely:

- Dashboard: `Total PnL = realized_pnl - fees - funding`.
- Trades tooltip: the total is what you paid to the exchange.
- Portfolio: per-exchange `PnL` is also net.

### 7. Special case: builder fee

Builder fees are not a cost but a *revenue* the exchange pays for
routed volume. That is why they do not appear in the PnL tooltip (which
only covers costs) but instead on the dashboard in the
**Builder Fee Revenue** section (see
[Dashboard and Revenue](./Dashboard-und-Revenue.md)).

### 8. FAQ

- **"Why does the tooltip not show anything?"** - The position is still
  open (`status = "open"`). The tooltip activates only after close.
- **"Fee = 0 but I paid"** - Some demo exchanges do not return fees via
  API. In live mode the value should be correct.
- **"Funding is positive but I received funding"** - The stored value
  is the **paid** amount. Received funding (negative cashflow) belongs
  in `funding_paid` as a negative number. The UI only renders when
  `> 0`, so received amounts stay invisible.
- **"Tax report shows different fees"** - The tax report aggregates
  per trade using the same fields but with a different period filter.
  Match `date_from` / `date_to` and the totals align.
