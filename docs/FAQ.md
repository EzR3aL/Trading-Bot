# Haeufig gestellte Fragen (FAQ)

## Allgemein

### Was macht dieser Bot genau?

Der Bot ist ein Multi-Exchange Trading System, das Kryptomaerkte analysiert und automatisch handelt. Er unterstuetzt **6 verschiedene Strategien** und **3 Exchanges** (Bitget, Weex, Hyperliquid). Du kannst mehrere Bots parallel laufen lassen, jeden mit einer eigenen Strategie, eigenem Trading-Paar und eigener Exchange.

### Welche Strategien stehen zur Verfuegung?

| # | Strategie | Typ | Beschreibung |
|---|-----------|-----|-------------|
| 1 | **LiquidationHunter** | Contrarian | Wettet gegen ueberladene Positionen, nutzt L/S Ratio + Fear & Greed |
| 2 | **LLM Signal** | KI-gesteuert | Konfigurierbarer LLM-Provider analysiert Marktdaten und generiert Signale |
| 3 | **Sentiment Surfer** | Hybrid | Kombiniert 6 Datenquellen (News, Sentiment, VWAP, Supertrend, Volume, Momentum) |
| 4 | **Degen** | KI-Arena | Fester Prompt mit 19 Datenquellen fuer aggressive 1h BTC-Predictions |
| 5 | **Edge Indicator** | Technisch | EMA Ribbon + ADX Filter + Predator Momentum Score (nur Kline-Daten) |
| 6 | **Claude Edge Indicator** | Technisch+ | Edge Indicator erweitert um ATR-TP/SL, Volume, Multi-TF, Trailing Stop |

### Welche Exchanges werden unterstuetzt?

| Exchange | Demo-Modus | Auth-Typ | Passphrase |
|----------|------------|----------|------------|
| **Bitget** | Ja | API Key | Ja |
| **Weex** | Ja | API Key | Ja |
| **Hyperliquid** | Ja | Wallet | Nein |

### Ist der Bot profitabel?

Der Bot bietet mehrere Strategien mit unterschiedlichen Risikoprofilen. Backtest-Ergebnisse (90 Tage, BTCUSDT, $10k):

| Strategie | Return | Win Rate | Max DD | Sharpe |
|-----------|--------|----------|--------|--------|
| LiquidationHunter | +26.2% | 53.9% | 4.7% | 5.51 |
| Edge Indicator | +18.6% | 47.1% | 9.8% | 2.91 |
| Claude Edge Indicator | +18.6% | 47.1% | 9.8% | 2.91 |

**Vergangene Performance garantiert keine zukuenftige Rendite.** Teste immer erst im Demo-Modus.

### Wie viel Geld brauche ich?

**Empfohlen:** Mindestens $500-1000 fuer sinnvolles Trading. Mit kleineren Betraegen werden die Fees prozentual zu hoch.

---

## Setup & Installation

### Warum brauche ich Python 3.10+?

Der Bot verwendet moderne Python-Features wie `match` Statements, `|` Union Syntax und Async/Await Patterns. Aeltere Versionen unterstuetzen diese nicht.

### Kann ich den Bot auf Windows laufen lassen?

Ja, aber Linux/macOS wird empfohlen fuer:
- Bessere Stabilitaet im 24/7 Betrieb
- Einfacheres Deployment
- Weniger Encoding-Probleme

### Wie halte ich den Bot 24/7 am Laufen?

**Empfohlen:** Verwende einen VPS (Virtual Private Server) oder Cloud-Instanz:
- AWS EC2 (Free Tier moeglich)
- DigitalOcean Droplet ($5/Monat)
- Hetzner Cloud (3.29 EUR/Monat)

Dann mit Docker Compose deployen (siehe [DEPLOYMENT.md](DEPLOYMENT.md)).

### Unterstuetzt der Bot mehrere Benutzer?

**Ja.** Seit v3.0.0 gibt es ein vollstaendiges Multi-User-System:
- JWT-basierte Authentifizierung
- Rollenbasierte Zugriffskontrolle (User / Admin)
- Jeder User hat eigene Bots, Trades und Einstellungen
- Admin kann Benutzer verwalten

---

## Trading & Strategie

### Kann ich Backtesting verwenden?

**Ja!** Seit v3.3.1 ist ein vollstaendiges Backtesting-System eingebaut:
- Im Frontend unter "Backtest" erreichbar
- Alle 6 Strategien koennen getestet werden
- Konfigurierbare Zeitraeume, Timeframes und Parameter
- Equity Curve, Trade Log und Metriken
- Siehe [Anleitungen/Backtesting.md](../Anleitungen/Backtesting.md)

### Welche Coins kann ich handeln?

Unterstuetzte Trading Pairs: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, AVAXUSDT.

**Empfohlen:** BTCUSDT und ETHUSDT wegen:
- Hoechste Liquiditaet = geringerer Slippage
- Beste Datenverfuegbarkeit fuer Indikatoren
- Strategien sind primaer dafuer optimiert

### Warum nur 3 Trades pro Tag?

- **Overtrading vermeiden** - Mehr Trades bedeuten nicht mehr Profit
- **Qualitaet vor Quantitaet** - Nur bei starken Signalen traden
- **Fees sparen** - Jeder Trade kostet Gebuehren
- **Emotionale Stabilitaet** - Weniger Entscheidungen

### Warum Leverage 3x und nicht hoeher?

| Leverage | Liquidations-Risiko | Bei 2% Stop Loss |
|----------|--------------------|--------------------|
| 1x | Sehr niedrig | ~2% Verlust |
| 3x | Moderat | ~6% Verlust |
| 5x | Erhoeht | ~10% Verlust |
| 10x+ | Hoch | ~20% Verlust |

### Kann ich mehrere Bots gleichzeitig laufen lassen?

**Ja!** Das Multi-Bot-System (v3.0.0+) erlaubt bis zu 10 Bots pro User. Jeder Bot kann:
- Eine eigene Strategie verwenden
- Auf einer anderen Exchange handeln
- Unterschiedliche Trading Pairs handeln
- Im Demo- oder Live-Modus laufen

---

## Alerts & Benachrichtigungen

### Gibt es ein Alert-System?

**Ja.** Es gibt drei Typen von Alerts:

| Alert-Typ | Beispiele |
|-----------|-----------|
| **Price Alerts** | Preis ueber/unter einem Schwellenwert |
| **Strategy Alerts** | Signal verpasst, niedrige Confidence, aufeinanderfolgende Verluste |
| **Portfolio Alerts** | Tagesverlust, Drawdown, Gewinnziel erreicht |

Alerts koennen per **Discord** und **Telegram** gesendet werden. Siehe [Anleitungen/Alerts-einrichten.md](../Anleitungen/Alerts-einrichten.md).

### Wie richte ich Telegram-Benachrichtigungen ein?

Siehe [Anleitungen/Telegram Benachrichtigungen einrichten.md](../Anleitungen/Telegram%20Benachrichtigungen%20einrichten.md).

---

## Portfolio & Dashboard

### Gibt es eine Portfolio-Uebersicht?

**Ja.** Die Portfolio View (v3.6.0+) zeigt:
- Multi-Exchange Uebersicht aller verbundenen Exchanges
- Live-Positionen von allen Exchanges
- Taegliche PnL-Charts pro Exchange
- Kapital-Allokation (Allocation View)

Siehe [Anleitungen/Portfolio-View.md](../Anleitungen/Portfolio-View.md).

### Wo sehe ich meine Trade-Historie?

1. **Dashboard** - Charts und Statistiken
2. **Trades-Seite** - Filterbarer Trade-Log mit Pagination
3. **Discord/Telegram** - Echtzeit-Benachrichtigungen
4. **Tax Report** - Jaehrlicher Steuer-Export (CSV)

### Wie berechne ich meine Win Rate?

Das Dashboard zeigt automatisch:
- Win Rate (gesamt und pro Zeitraum)
- PnL Chart (taeglich und kumulativ)
- Best/Worst Trade
- Fees und Funding

---

## Risiko & Sicherheit

### Was passiert wenn der Bot abstuerzt?

- **Offene Positionen bleiben offen** auf der Exchange
- **TP/SL Orders bleiben aktiv** auf der Exchange
- Der Bot erkennt offene Trades beim Neustart (Auto-Restore)

### Was ist die "Daily Loss Limit"?

Wenn der Bot am Tag mehr als X% verliert (Standard: 5%), stoppt er automatisch:
- Keine neuen Trades
- Offene Positionen bleiben (mit TP/SL)
- Naechster Tag = Neustart

### Kann jemand mein Geld stehlen mit dem API Key?

**Nein**, wenn du richtig konfiguriert hast:
- Keine Withdrawal-Berechtigung geben
- IP-Whitelist aktivieren
- API Key sicher aufbewahren (.env nie committen!)

API Keys werden verschluesselt in der Datenbank gespeichert (Fernet Encryption).

---

## Performance & Monitoring

### Der Bot macht keine Trades - warum?

| Problem | Loesung |
|---------|--------|
| Daily Limit erreicht | Warte bis morgen |
| Confidence zu niedrig | Normale Marktbedingungen, kein Signal |
| Bereits offene Position | Warte auf Schliessung |
| API-Fehler | Pruefe Logs und Health-Check |
| Demo-Modus aktiv | `DEMO_MODE=true` ist gewollt! |
| Exchange nicht verbunden | Pruefe Settings > API Keys |

### Wie oft sollte der Bot profitabel sein?

**Erwartung bei 60% Win Rate mit R/R 1.75:1:**
- 10 Trades: 6 Wins, 4 Losses
- Expected Value: ~1.3% pro Trade (vor Fees)

**Varianz existiert.** Du kannst 5 Losses in Folge haben und trotzdem langfristig profitabel sein.

---

## Kosten & Gebuehren

### Welche Gebuehren fallen an?

| Gebuehrenart | Typischer Wert |
|-------------|----------------|
| Trading Fee (Maker) | 0.02% |
| Trading Fee (Taker) | 0.06% |
| Funding (alle 8h) | -0.03% bis +0.03% |

### Wie kann ich die Kosten tracken?

Das Dashboard zeigt:
- **Fee Tracking** pro Trade und aggregiert
- **Funding Payments** mit Historie
- **Builder Fees** (bei Hyperliquid)
- **Tax Report** mit Jahresuebersicht inkl. aller Kosten

---

## Updates & Wartung

### Wie update ich den Bot?

```bash
git pull origin main
pip install -r requirements.txt
# Bot neustarten
```

Oder mit Docker:
```bash
docker compose pull
docker compose up -d
```

### Wo sehe ich neue Features?

Siehe [CHANGELOG.md](../CHANGELOG.md) fuer alle Aenderungen.
