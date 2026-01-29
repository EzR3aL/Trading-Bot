# Häufig gestellte Fragen (FAQ)

## Allgemein

### Was macht dieser Bot genau?

Der Bot analysiert Kryptomärkte (BTC, ETH) und sucht nach Situationen, in denen die Mehrheit der Trader falsch positioniert ist. Er wettet dann gegen die Masse und profitiert von Liquidations-Kaskaden.

### Ist der Bot profitabel?

Der Bot ist auf eine **60%+ Win Rate** mit einem **1.75:1 Risk/Reward** Verhältnis ausgelegt. Dies bedeutet theoretisch profitables Trading, aber:
- Vergangene Performance garantiert keine Zukunft
- Marktbedingungen ändern sich
- Teste immer erst auf Testnet

### Wie viel Geld brauche ich?

**Empfohlen:** Mindestens $500-1000 für sinnvolles Trading mit dem Standard-Setup. Mit kleineren Beträgen werden die Fees prozentual zu hoch.

---

## Setup & Installation

### Warum brauche ich Python 3.10+?

Der Bot verwendet moderne Python-Features wie:
- `match` Statements
- Type Hints mit `|` Union Syntax
- Async/Await Patterns

Ältere Versionen unterstützen diese nicht.

### Kann ich den Bot auf Windows laufen lassen?

Ja, aber Linux/macOS wird empfohlen für:
- Bessere Stabilität im 24/7 Betrieb
- Einfacheres Deployment
- Weniger Encoding-Probleme

### Wie halte ich den Bot 24/7 am Laufen?

**Empfohlen:** Verwende einen VPS (Virtual Private Server) oder Cloud-Instanz:
- AWS EC2 (Free Tier möglich)
- DigitalOcean Droplet ($5/Monat)
- Hetzner Cloud (€3.29/Monat)

Dann mit `systemd` als Service einrichten (siehe [SETUP.md](SETUP.md)).

---

## Trading & Strategie

### Warum nur BTC und ETH?

- **Höchste Liquidität** = Geringerer Slippage
- **Beste Datenverfügbarkeit** für L/S Ratio, Funding, etc.
- **ETF-Flows** betreffen hauptsächlich BTC
- Andere Assets haben oft zu wenig Volumen für die Strategie

### Kann ich andere Coins hinzufügen?

Ja, in der `.env`:
```env
TRADING_PAIRS=BTCUSDT,ETHUSDT,SOLUSDT
```

**Aber beachte:**
- Nicht alle Coins haben L/S Ratio Daten
- Geringere Liquidität = Höherer Slippage
- Die Strategie ist für BTC/ETH optimiert

### Warum nur 3 Trades pro Tag?

- **Overtrading vermeiden** - Mehr Trades ≠ Mehr Profit
- **Qualität vor Quantität** - Nur bei starken Signalen traden
- **Fees sparen** - Jeder Trade kostet Gebühren
- **Emotionale Stabilität** - Weniger Entscheidungen = Weniger Stress

### Was bedeutet "NO NEUTRALITY"?

Der Bot **muss** immer eine Richtung wählen. Wenn alle Signale neutral sind:
1. Er folgt dem 24h-Trend
2. Mit niedriger Confidence (55-65%)
3. Mit kleinerer Position Size

**Warum?** Neutralität = Verpasste Chancen. Selbst ein leichter Edge ist besser als kein Trade.

### Warum Leverage 3x und nicht höher?

| Leverage | Liquidations-Risiko | Position Size Effekt |
|----------|--------------------|--------------------|
| 1x | Sehr niedrig | Kleine Gewinne |
| 3x | Moderat | Gutes Verhältnis |
| 5x | Erhöht | Größere Gewinne, aber... |
| 10x+ | Hoch | Schnelle Liquidation möglich |

Mit 3x und 2% Stop Loss verlierst du maximal ~6% pro Trade. Mit 10x wären es ~20%.

---

## Risiko & Sicherheit

### Was passiert wenn der Bot abstürzt?

- **Offene Positionen bleiben offen** auf Bitget
- **TP/SL Orders bleiben aktiv** auf der Exchange
- Der Bot erkennt offene Trades beim Neustart

**Empfehlung:** Richte Monitoring ein (z.B. mit UptimeRobot).

### Was ist die "Daily Loss Limit"?

Wenn der Bot am Tag mehr als X% verliert (Standard: 5%), stoppt er automatisch:
- Keine neuen Trades
- Offene Positionen bleiben (mit TP/SL)
- Nächster Tag = Neustart

**Warum?** Verhindert Spirale aus Verlusten und emotionalem Trading.

### Kann jemand mein Geld stehlen mit dem API Key?

**Nein**, wenn du richtig konfiguriert hast:
- ❌ Keine Withdrawal-Berechtigung geben
- ✅ IP-Whitelist aktivieren
- ✅ API Key sicher aufbewahren (.env nie committen!)

Mit nur Trade-Berechtigung kann der Schlimmstfall ein schlechter Trade sein - aber kein Geld kann abgehoben werden.

### Wie sicher ist die Discord-Webhook-URL?

Die URL sollte geheim bleiben, aber:
- Jemand mit der URL kann nur **Nachrichten senden**
- Kein Zugriff auf Server/Channel-Einstellungen
- Keine Leseberechtigung

**Trotzdem:** Nicht öffentlich teilen.

---

## Performance & Monitoring

### Wo sehe ich meine Trade-Historie?

1. **Discord** - Alle Trades werden gepostet
2. **Datenbank** - `data/trades.db` (SQLite)
3. **Logs** - `logs/trading_bot.log`

### Wie berechne ich meine Win Rate?

```bash
python main.py --status
```

Zeigt 30-Tage Statistiken inkl. Win Rate.

### Der Bot macht keine Trades - warum?

Mögliche Gründe:

| Problem | Lösung |
|---------|--------|
| Daily Limit erreicht | Warte bis morgen |
| Confidence zu niedrig | Normale Marktbedingungen, kein Signal |
| Bereits offene Position | Warte auf Schließung |
| API-Fehler | Prüfe Logs |
| Testnet aktiv | Prüfe BITGET_TESTNET in .env |

### Wie oft sollte der Bot profitabel sein?

**Erwartung bei 60% Win Rate:**
- 10 Trades → 6 Wins, 4 Losses
- Monatlich bei 3 Trades/Tag → ~60 Trades
- Davon ~36 Wins, ~24 Losses

**Aber:** Varianz existiert. Du kannst 5 Losses in Folge haben und trotzdem langfristig profitabel sein.

---

## Technische Fragen

### Wie ändere ich die Trading-Zeiten?

In `src/bot/trading_bot.py`, Methode `_setup_scheduled_jobs()`:

```python
self.scheduler.add_job(
    self.analyze_and_trade,
    CronTrigger(hour="1,8,14,21", minute=0),  # Ändere hier
    ...
)
```

### Wie füge ich einen neuen Indikator hinzu?

1. Daten holen in `src/data/market_data.py`
2. Analyse in `src/strategy/liquidation_hunter.py`
3. Signal-Logik anpassen

### Kann ich die Strategie backtesten?

Aktuell nicht eingebaut. Geplant für zukünftige Versionen.

**Workaround:** Sammle Daten über Zeit und analysiere manuell.

### Wie debugge ich Probleme?

```bash
# Ausführliche Logs
python main.py --log-level DEBUG

# Nur Analyse, kein Trading
python main.py --test

# Logs live verfolgen
tail -f logs/trading_bot.log
```

---

## Kosten & Gebühren

### Welche Gebühren fallen an?

| Gebührenart | Typischer Wert |
|-------------|----------------|
| Trading Fee (Maker) | 0.02% |
| Trading Fee (Taker) | 0.06% |
| Funding (alle 8h) | -0.03% bis +0.03% |

**Bei $1000 Position:**
- Entry: ~$0.60 (Taker)
- Exit: ~$0.60 (Taker)
- Funding: ~$0.30 pro 8h
- **Total pro Trade:** ~$1.50-3.00

### Lohnt sich das bei kleinen Beträgen?

| Balance | Position (10%) | Fees | Mindest-Gewinn für Break-Even |
|---------|----------------|------|------------------------------|
| $100 | $10 | ~$0.15 | 1.5% |
| $500 | $50 | ~$0.75 | 1.5% |
| $1000 | $100 | ~$1.50 | 1.5% |
| $5000 | $500 | ~$7.50 | 1.5% |

Mit TP bei 3.5% und ~1.5% Fees bleibt ~2% Netto-Gewinn.

---

## Updates & Wartung

### Wie update ich den Bot?

```bash
git pull origin main
pip install -r requirements.txt
# Bot neustarten
```

### Wo sehe ich neue Features?

Siehe [CHANGELOG.md](../CHANGELOG.md) für alle Änderungen.

### Kann ich zur Entwicklung beitragen?

Ja! Fork das Repository, erstelle einen Branch, und öffne einen Pull Request.
