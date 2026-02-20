# Portfolio View

Anleitung zur Multi-Exchange Portfolio-Uebersicht.

---

## Inhaltsverzeichnis

1. [Ueberblick](#1-ueberblick)
2. [Portfolio Summary](#2-portfolio-summary)
3. [Live-Positionen](#3-live-positionen)
4. [Taegliche PnL-Charts](#4-taegliche-pnl-charts)
5. [Allocation View](#5-allocation-view)
6. [Filter und Einstellungen](#6-filter-und-einstellungen)

---

## 1. Ueberblick

Die Portfolio View zeigt eine **Exchange-uebergreifende Uebersicht** ueber alle deine Trading-Aktivitaeten. Statt jede Exchange einzeln zu pruefen, siehst du alles auf einer Seite.

### Voraussetzungen

- Mindestens eine Exchange verbunden (Settings -> API Keys)
- Mindestens ein abgeschlossener Trade (fuer Statistiken)

### Features

| Feature | Beschreibung |
|---------|-------------|
| **Portfolio Summary** | Aggregiertes PnL pro Exchange |
| **Live-Positionen** | Echtzeit-Positionen von allen Exchanges |
| **Taegliche PnL-Charts** | Gestapelter Balkenchart pro Exchange |
| **Allocation View** | Kapitalverteilung ueber Exchanges |

---

## 2. Portfolio Summary

### Was zeigt die Summary?

Die Portfolio Summary aggregiert alle abgeschlossenen Trades und zeigt:

| Metrik | Beschreibung |
|--------|-------------|
| **Total PnL** | Gesamtgewinn/-verlust ueber alle Exchanges |
| **Total Trades** | Gesamtanzahl der Trades |
| **Win Rate** | Gewonnene Trades / Gesamte Trades in % |
| **Total Fees** | Gesamte Trading-Gebuehren |
| **Total Funding** | Gesamte Funding-Zahlungen |

### Exchange Cards

Fuer jede verbundene Exchange siehst du eine eigene Karte mit:

- **Exchange-Name** und Logo
- **PnL** fuer den gewaehlten Zeitraum
- **Trade-Anzahl** (total und gewonnen)
- **Win Rate** der Exchange
- **Fees** und **Funding** Summen

### Beispiel

```
Gesamtportfolio:  +$2,340.50  |  210 Trades  |  58.1% Win Rate

Bitget:           +$1,580.30  |  140 Trades  |  60.0% Win Rate
Hyperliquid:      +$760.20    |  70 Trades   |  54.3% Win Rate
```

---

## 3. Live-Positionen

### Was zeigt die Positionstabelle?

Alle aktuell offenen Positionen von **allen verbundenen Exchanges** in einer einzigen Tabelle:

| Spalte | Beschreibung |
|--------|-------------|
| **Exchange** | Auf welcher Exchange die Position ist |
| **Symbol** | Trading Pair (z.B. BTCUSDT) |
| **Richtung** | LONG oder SHORT |
| **Groesse** | Positionsgroesse |
| **Entry Price** | Einstiegspreis |
| **Current Price** | Aktueller Marktpreis |
| **Unrealized PnL** | Noch nicht realisierter Gewinn/Verlust |
| **Leverage** | Verwendeter Hebel |
| **Margin** | Hinterlegte Margin |

### Echtzeit-Updates

Die Positionen werden bei jedem Seitenaufruf frisch von den Exchanges geladen. Pro Exchange gibt es ein Timeout von 10 Sekunden -- wenn eine Exchange nicht antwortet, werden die anderen trotzdem angezeigt.

---

## 4. Taegliche PnL-Charts

### Gestapelter Balkenchart

Der Chart zeigt den **taeglichen PnL pro Exchange** als gestapelte Balken:

- **Positive Tage**: Balken nach oben
- **Negative Tage**: Balken nach unten
- **Farben**: Jede Exchange hat eine eigene Farbe

### Zeitraum waehlen

Du kannst den Zeitraum filtern:
- 7 Tage
- 14 Tage
- 30 Tage (Standard)
- 90 Tage
- 365 Tage

### Was kann ich daraus lesen?

- **Welche Exchange performt am besten?** -> Groesste positive Balken
- **Gibt es Verlust-Serien?** -> Mehrere rote Tage hintereinander
- **Diversifikation** -> Sind die Exchanges korreliert oder unabhaengig?

---

## 5. Allocation View

### Kapitalverteilung

Die Allocation View zeigt, wie dein Kapital ueber die verschiedenen Exchanges verteilt ist:

- **PnL-Anteil** pro Exchange
- **Trade-Anteil** pro Exchange
- **Prozentualer Anteil** am Gesamtportfolio

### Wann ist die Allocation wichtig?

- **Zu viel auf einer Exchange?** -> Risiko durch Exchange-Ausfall
- **Ungleichmaessige Performance?** -> Strategie oder Exchange wechseln
- **Diversifikation pruefen** -> Ideal: Kapital ueber mehrere Exchanges verteilt

---

## 6. Filter und Einstellungen

### Demo/Live Filter

Du kannst zwischen verschiedenen Modi filtern:

| Filter | Zeigt |
|--------|-------|
| **All** | Alle Trades (Demo + Live) |
| **Live** | Nur echte Trades |
| **Demo** | Nur simulierte Trades |

### Zeitraum

Waehle den Zeitraum fuer die Statistiken:
- Standard: 30 Tage
- Minimum: 1 Tag
- Maximum: 365 Tage

---

---

# Portfolio View (English)

Guide for the multi-exchange portfolio overview.

---

## Overview

The Portfolio View provides a **cross-exchange overview** of all your trading activities. Instead of checking each exchange separately, you see everything on one page.

### Prerequisites

- At least one exchange connected (Settings -> API Keys)
- At least one completed trade (for statistics)

---

## Portfolio Summary

Aggregated metrics across all exchanges:

| Metric | Description |
|--------|-------------|
| **Total PnL** | Total profit/loss across all exchanges |
| **Total Trades** | Total number of trades |
| **Win Rate** | Winning trades / Total trades in % |
| **Total Fees** | Total trading fees |
| **Total Funding** | Total funding payments |

Each connected exchange gets its own card showing PnL, trade count, win rate, fees, and funding.

---

## Live Positions

All currently open positions from **all connected exchanges** in a single table:

| Column | Description |
|--------|-------------|
| Exchange | Which exchange the position is on |
| Symbol | Trading pair |
| Side | LONG or SHORT |
| Size | Position size |
| Entry Price | Entry price |
| Current Price | Current market price |
| Unrealized PnL | Unrealized profit/loss |
| Leverage | Leverage used |
| Margin | Margin deposited |

Positions are fetched live from exchanges on each page load (10s timeout per exchange).

---

## Daily PnL Charts

Stacked bar chart showing **daily PnL per exchange**:

- Positive days: bars upward
- Negative days: bars downward
- Colors: each exchange has its own color

Configurable time periods: 7, 14, 30 (default), 90, or 365 days.

---

## Allocation View

Shows capital distribution across exchanges:

- PnL share per exchange
- Trade share per exchange
- Percentage of total portfolio

Use this to check diversification and identify risk concentration.

---

## Filters

| Filter | Shows |
|--------|-------|
| **All** | All trades (demo + live) |
| **Live** | Only real trades |
| **Demo** | Only simulated trades |

Time period: 1 day (min) to 365 days (max), default 30 days.
