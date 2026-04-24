# Dashboard und Builder-Fee Einnahmen

Anleitung zur Dashboard-Seite und zur Revenue-Sektion, die Hyperliquid-
Builder-Fee-Einnahmen aggregiert.

---

## DE

### 1. Was ist das Dashboard?

Das Dashboard ist die Startseite nach dem Login
(`/`, `frontend/src/pages/Dashboard.tsx`). Es fasst deine Trading-Statistik
ueber einen konfigurierbaren Zeitraum zusammen, zeigt Charts fuer
PnL-Verlauf und Gewinn/Verlust-Quote und - wenn du bei Hyperliquid als
Builder registriert bist - die Builder-Fee-Einnahmen.

### 2. Voraussetzungen

- Eingeloggter Account
- Mindestens eine Exchange-Verbindung in *Einstellungen -> API-Schluessel*
- Mindestens ein abgeschlossener Trade fuer aussagekraeftige Zahlen
- Fuer die Revenue-Sektion: Hyperliquid mit aktiver Builder-Fee-Genehmigung
  (siehe [Hyperliquid Builder Fee genehmigen](./Hyperliquid%20Builder%20Fee%20genehmigen.md))

### 3. Aufbau der Seite

Von oben nach unten:

1. **Header** - Titel *Dashboard*, Hilfe-Button (GuidedTour), Period-Filter
   und Demo/Live-Filter
2. **Stats-Kacheln** - Gesamt-PnL, Gewinnrate, Bester / Schlechtester Trade
3. **PnL im Zeitverlauf** - Linien-Chart (`PnlChart`)
4. **Gewinn / Verlust** - Donut-Chart (`WinLossChart`)
5. **Builder-Fee Einnahmen** - Revenue-Chart (nur relevant, wenn Builder-
   Fees vorhanden sind)
6. **Offene Positionen** - Live-Tabelle aus `DashboardOpenPositions`

### 4. Zeitraum und Demo/Live-Filter

Der Zeitraum wird ueber die Buttons **7 Tage / 14 Tage / 30 Tage / 90 Tage**
(Labels `dashboard.days7` bis `dashboard.days90`) gewechselt. Default:
30 Tage. Der Wert fliesst als `period`-Query-Parameter in
`GET /api/dashboard/stats` und `GET /api/dashboard/daily`.

Der **Demo/Live-Filter** sitzt im linken Sidebar unten und heisst dort
*Demo/Live-Filter* (`common.demoLiveFilter`). Mit *All* siehst du beide
Kontexte in einer Statistik, *Live* und *Demo* begrenzen den Datensatz
einseitig.

### 5. Stats-Kacheln

Vier identische Tiles, jede mit Label, Hauptwert und optionalem Untertitel.

| Kachel | Label (DE) | Wert | Untertitel |
|--------|-----------|------|-----------|
| 1 | **Gesamt-PnL** | `total_pnl` (USD) | `Gebuehren: $X \| Funding: $Y` |
| 2 | **Gewinnrate** | `winning_trades / total_trades` | - |
| 3 | **Bester Trade** | `best_trade_pnl` | - |
| 4 | **Schlechtester Trade** | `worst_trade_pnl` | - |

Der Untertitel der PnL-Kachel ist die einzige Stelle im Dashboard, an
der du **netto vs. brutto** siehst: der angezeigte Gesamt-PnL ist bereits
netto (Fees + Funding abgezogen), die Sub-Zeile zeigt dir die Summe der
Abzuege separat.

### 6. PnL im Zeitverlauf

`PnlChart` (`frontend/src/components/dashboard/PnlChart.tsx`) zeichnet
den kumulativen PnL-Verlauf ueber die Periode. Datenpunkte kommen aus
`GET /api/dashboard/daily`. Tooltip pro Tag zeigt den Tages-PnL.

### 7. Gewinn / Verlust

`WinLossChart` zeigt die Verteilung gewonnener vs. verlorener Trades als
Donut. Nur abgeschlossene Trades zaehlen. Bei null Trades rendert der
Chart die Leer-Meldung (`dashboard.noData`).

![Dashboard: Stats-Kacheln und PnL-Chart](./screenshots/dashboard-stats-pnl.png)
<!-- Screenshot manuell erstellen: Dashboard-Oberseite inkl. Kacheln und PnL-Chart abfotografieren. -->

### 8. Builder-Fee Einnahmen (Revenue-Sektion)

Die Sektion erscheint unter den Charts. Titel: **Builder-Fee Einnahmen**
(`dashboard.revenueTitle`).

Sie zeigt zwei Werte:

- **Gesamt Builder-Gebuehren** (`dashboard.totalBuilderFees`) -
  `stats.total_builder_fees` mit 4 Nachkommastellen.
- **Gesch. Monatlich** (`dashboard.monthlyEstimate`) - lineare Hochrechnung
  `(total_builder_fees / period_days) * 30` mit 2 Nachkommastellen.

Darunter der `RevenueChart` mit der Tagesverteilung der Builder-Fees.

Wann siehst du echte Werte?

- Du handelst ueber Hyperliquid mit einer aktiven Builder-Fee-Genehmigung.
- Deine Trades haben bei der Exchange die Builder-Fee zu deinem Wallet
  abgerechnet.
- Der Aggregator (`src/services/portfolio_service.py`) rechnet die Summe
  aus `trade_records.builder_fee` zusammen.

Ohne aktive Builder-Rolle bleibt der Wert bei 0 und der Chart ist leer.
Die Sektion selbst wird nicht ausgeblendet - das ist bewusst so, damit
neue Nutzer die Option ueberhaupt sehen.

### 9. Offene Positionen

Ganz unten listet `DashboardOpenPositions` alle aktuell offenen Positionen
ueber alle Exchanges. Spalten entsprechen der Trades-Seite
(Symbol, Seite, Groesse, Entry, aktueller Preis, unrealisierter PnL,
Hebel, TP/SL-Badges).

Die Daten kommen aus `GET /api/portfolio/positions` und werden bei jedem
Seitenaufruf frisch geholt - der WebSocket-Feed
(siehe [WebSocket-Live-Updates](./WebSocket-Live-Updates.md)) aktualisiert
neue Trades inkrementell, aber das Initial-Load bleibt synchron.

### 10. Haeufige Fragen

- **"Mein Total-PnL weicht von der Trades-Seite ab"** - Das Dashboard
  aggregiert pro Zeitraum, die Trades-Seite zeigt Einzel-Eintraege. Mit
  *30 Tage* auf dem Dashboard und dem gleichen Datumsfilter in *Trades*
  passen die Summen ueberein.
- **"Builder-Fees sind 0, obwohl ich Hyperliquid nutze"** - Entweder
  ist die Builder-Fee-Genehmigung noch nicht abgeschlossen, oder du bist
  nicht als Builder fuer deinen eigenen Trade konfiguriert.
  Siehe die Hyperliquid-Anleitung.
- **"Gesch. Monatlich sieht seltsam aus"** - Die Hochrechnung ist linear
  und ignoriert Wochenenden / Volatilitaetsspitzen. Fuer kurze Perioden
  (7 Tage) ist der Wert sehr volatil.

---

## EN

### 1. What is the Dashboard?

The Dashboard is the landing page after login
(`/`, `frontend/src/pages/Dashboard.tsx`). It summarises your trading
statistics over a configurable period, shows charts for the PnL
trajectory and win/loss split, and - if you are registered as a builder
on Hyperliquid - your builder-fee revenue.

### 2. Prerequisites

- Logged-in account.
- At least one exchange connection in *Settings -> API Keys*.
- At least one completed trade for meaningful numbers.
- For the Revenue section: Hyperliquid with active builder-fee approval
  (see [Hyperliquid Builder Fee Approval](./en/Hyperliquid-Builder-Fee-Approval.md)).

### 3. Page layout

Top to bottom:

1. **Header** - title *Dashboard*, help button (GuidedTour), period
   filter and demo/live filter.
2. **Stats tiles** - Total PnL, Win rate, Best / Worst trade.
3. **PnL over time** - line chart (`PnlChart`).
4. **Win / Loss** - donut chart (`WinLossChart`).
5. **Builder fee revenue** - revenue chart (only relevant when you
   actually have builder-fees).
6. **Open positions** - live table from `DashboardOpenPositions`.

### 4. Period and demo/live filter

The period is switched via **7 days / 14 days / 30 days / 90 days**
buttons (labels `dashboard.days7` - `dashboard.days90`). Default 30.
The value flows into `GET /api/dashboard/stats` and
`GET /api/dashboard/daily` as the `period` query parameter.

The **Demo/Live filter** lives in the left sidebar footer and is
labelled *Demo/Live Filter* (`common.demoLiveFilter`). *All* sees both
contexts, *Live* and *Demo* narrow the dataset.

### 5. Stats tiles

Four tiles, each with label, primary value and optional subtitle.

| Tile | Label | Value | Subtitle |
|------|-------|-------|---------|
| 1 | **Total PnL** | `total_pnl` (USD) | `Fees: $X \| Funding: $Y` |
| 2 | **Win Rate** | `winning_trades / total_trades` | - |
| 3 | **Best Trade** | `best_trade_pnl` | - |
| 4 | **Worst Trade** | `worst_trade_pnl` | - |

The subtitle of the PnL tile is the only place where you see the
**net vs. gross** split: the displayed Total PnL is already net (fees +
funding subtracted); the sub-line shows the deductions separately.

### 6. PnL over time

`PnlChart` (`frontend/src/components/dashboard/PnlChart.tsx`) plots
cumulative PnL over the selected period. Data comes from
`GET /api/dashboard/daily`. Tooltip shows the daily PnL per point.

### 7. Win / Loss

`WinLossChart` shows the ratio of winning vs. losing trades as a donut.
Only closed trades count. With zero trades the chart renders the empty
state (`dashboard.noData`).

### 8. Builder fee revenue

The section appears below the charts. Title: **Builder Fee Revenue**
(`dashboard.revenueTitle`).

Two values:

- **Total builder fees** (`dashboard.totalBuilderFees`) -
  `stats.total_builder_fees` with 4 decimals.
- **Monthly estimate** (`dashboard.monthlyEstimate`) - linear projection
  `(total_builder_fees / period_days) * 30` with 2 decimals.

Below that: `RevenueChart` with the per-day breakdown of builder fees.

When do you see real numbers?

- You trade on Hyperliquid with an active builder-fee approval.
- Trades have the builder fee accounted to your wallet on the exchange.
- The aggregator (`src/services/portfolio_service.py`) sums
  `trade_records.builder_fee`.

Without an active builder role the value stays 0 and the chart is empty.
The section itself is not hidden on purpose - new users should see that
the option exists.

### 9. Open positions

At the bottom `DashboardOpenPositions` lists every currently open
position across all exchanges. Columns match the Trades page (symbol,
side, size, entry, current price, unrealised PnL, leverage, TP/SL
badges).

Data comes from `GET /api/portfolio/positions` and is re-fetched on
every page view. The WebSocket feed
(see [WebSocket-Live-Updates](./WebSocket-Live-Updates.md)) updates new
trades incrementally, but the initial load remains synchronous.

### 10. FAQ

- **"My total PnL differs from the Trades page"** - The dashboard
  aggregates per period, the Trades page lists individual records.
  Pick the same date window on both and the totals match.
- **"Builder fees are 0 even though I use Hyperliquid"** - Either the
  builder-fee approval has not completed, or your own trades are not
  routed with you as the builder. See the Hyperliquid guide.
- **"Monthly estimate looks weird"** - The projection is linear and
  ignores weekends / volatility spikes. Short periods (7 days) give
  very volatile estimates.
