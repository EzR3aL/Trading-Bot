# Setup-Anleitung

Diese Anleitung führt dich durch die vollständige Installation und Konfiguration des Bitget Trading Bots.

---

## Voraussetzungen

### System-Anforderungen
- **Python:** 3.10 oder höher
- **Betriebssystem:** Linux, macOS oder Windows
- **RAM:** Mindestens 512 MB
- **Speicher:** 100 MB für Bot + Logs

### Accounts & API-Zugang
- [ ] Bitget Account mit Futures-Trading aktiviert
- [ ] Bitget API Key mit Trading-Berechtigung
- [ ] Discord Server mit Webhook-Zugang

---

## Schritt 1: Repository klonen

```bash
git clone https://github.com/yourusername/Bitget-Trading-Bot.git
cd Bitget-Trading-Bot
```

---

## Schritt 2: Python-Umgebung einrichten

### Option A: Virtual Environment (empfohlen)

```bash
# Virtual Environment erstellen
python -m venv venv

# Aktivieren (Linux/macOS)
source venv/bin/activate

# Aktivieren (Windows)
venv\Scripts\activate
```

### Option B: Conda

```bash
conda create -n trading-bot python=3.11
conda activate trading-bot
```

### Dependencies installieren

```bash
pip install -r requirements.txt
```

---

## Schritt 3: Bitget API einrichten

### 3.1 API Key erstellen

1. Gehe zu [Bitget](https://www.bitget.com) → Account → API Management
2. Klicke auf "Create API"
3. Wähle folgende Berechtigungen:
   - ✅ **Read** - Kontoinformationen lesen
   - ✅ **Trade** - Futures Trading
   - ❌ Withdraw - NICHT aktivieren!
4. Setze IP-Whitelist (empfohlen für Sicherheit)
5. Notiere:
   - API Key
   - API Secret
   - Passphrase

### 3.2 Testnet (optional aber empfohlen)

Für Tests ohne echtes Geld:
1. Gehe zu [Bitget Testnet](https://www.bitget.com/en/testnet)
2. Erstelle einen separaten API Key für Testnet
3. Setze `BITGET_TESTNET=true` in der `.env`

---

## Schritt 4: Discord Webhook einrichten

### 4.1 Webhook erstellen

1. Öffne Discord → Server Settings → Integrations
2. Klicke auf "Webhooks" → "New Webhook"
3. Wähle den Channel für Bot-Nachrichten
4. Kopiere die Webhook URL

### 4.2 Channel-Empfehlung

Erstelle separate Channels für:
- `#trading-signals` - Für Trade-Alerts
- `#daily-summary` - Für tägliche Zusammenfassungen
- `#bot-errors` - Für Fehlermeldungen

---

## Schritt 5: Konfiguration

### 5.1 Environment-Datei erstellen

```bash
cp .env.example .env
```

### 5.2 .env bearbeiten

Öffne `.env` mit einem Texteditor und fülle alle Werte aus:

```env
# ============ BITGET API CREDENTIALS ============
BITGET_API_KEY=dein_api_key_hier
BITGET_API_SECRET=dein_api_secret_hier
BITGET_PASSPHRASE=deine_passphrase_hier
BITGET_TESTNET=false

# ============ DISCORD CONFIGURATION ============
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# ============ TRADING CONFIGURATION ============
MAX_TRADES_PER_DAY=3
DAILY_LOSS_LIMIT_PERCENT=5.0
POSITION_SIZE_PERCENT=10.0
LEVERAGE=3
TAKE_PROFIT_PERCENT=3.5
STOP_LOSS_PERCENT=2.0

# ============ ASSETS TO TRADE ============
TRADING_PAIRS=BTCUSDT,ETHUSDT
```

### 5.3 Konfiguration validieren

```bash
python main.py --status
```

Dies zeigt dir die aktuelle Konfiguration und ob alle Credentials gültig sind.

---

## Schritt 6: Erster Test

### 6.1 Test-Analyse (ohne echtes Trading)

```bash
python main.py --test
```

Dies führt eine Analyse durch und zeigt die Signale an, **ohne Orders zu platzieren**.

Erwartete Ausgabe:
```
============================================================
TEST ANALYSIS RESULTS
============================================================

Symbol: BTCUSDT
Direction: LONG
Confidence: 72%
Entry Price: $95,000.00
Take Profit: $98,325.00
Stop Loss: $93,100.00
Reason: Crowded Shorts detected (L/S Ratio: 0.45 < 0.5)...
----------------------------------------
```

### 6.2 Logs prüfen

```bash
tail -f logs/trading_bot.log
```

---

## Schritt 7: Bot starten

### Produktiv-Start

```bash
python main.py
```

### Mit Debug-Ausgabe

```bash
python main.py --log-level DEBUG
```

### Im Hintergrund (Linux)

```bash
nohup python main.py > /dev/null 2>&1 &
```

### Mit systemd (empfohlen für Server)

Erstelle `/etc/systemd/system/trading-bot.service`:

```ini
[Unit]
Description=Bitget Trading Bot
After=network.target

[Service]
Type=simple
User=deinuser
WorkingDirectory=/pfad/zu/Bitget-Trading-Bot
Environment=PATH=/pfad/zu/venv/bin
ExecStart=/pfad/zu/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Dann:
```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-bot
sudo systemctl start trading-bot
```

---

## Schritt 8: Monitoring

### Status prüfen

```bash
python main.py --status
```

### Logs ansehen

```bash
# Echtzeit-Logs
tail -f logs/trading_bot.log

# Letzte 100 Zeilen
tail -n 100 logs/trading_bot.log

# Nach Fehlern suchen
grep ERROR logs/trading_bot.log
```

### Trades ansehen

Die Trades werden in `data/trades.db` (SQLite) gespeichert.

```bash
# Mit sqlite3
sqlite3 data/trades.db "SELECT * FROM trades ORDER BY entry_time DESC LIMIT 10;"
```

---

## Fehlerbehebung

### "Bitget API credentials not configured"

**Lösung:** Prüfe ob `.env` existiert und alle BITGET_* Variablen gesetzt sind.

```bash
cat .env | grep BITGET
```

### "Discord webhook error: 401"

**Lösung:** Die Webhook URL ist ungültig. Erstelle einen neuen Webhook.

### "ModuleNotFoundError: No module named 'xyz'"

**Lösung:** Dependencies neu installieren:

```bash
pip install -r requirements.txt
```

### Bot startet nicht

1. Prüfe Python-Version: `python --version` (muss ≥3.10 sein)
2. Prüfe ob Virtual Environment aktiv ist
3. Prüfe Logs: `cat logs/trading_bot.log`

### Keine Trades werden ausgeführt

Mögliche Gründe:
1. **Daily Limit erreicht** - Warte bis morgen
2. **Keine starken Signale** - Confidence unter Minimum
3. **Bereits offene Position** - Bot wartet auf Schließung
4. **Testnet aktiv** - Prüfe `BITGET_TESTNET` in `.env`

---

## Sicherheits-Checkliste

- [ ] API Key hat **KEINE** Withdrawal-Berechtigung
- [ ] IP-Whitelist auf Bitget aktiviert
- [ ] `.env` Datei ist in `.gitignore`
- [ ] Nie API Keys committen oder teilen
- [ ] Regelmäßige Balance-Kontrolle
- [ ] Daily Loss Limit angemessen gesetzt

---

## Nächste Schritte

1. **Teste auf Testnet** bevor du echtes Geld verwendest
2. **Starte mit kleinen Positionen** (POSITION_SIZE_PERCENT=5)
3. **Beobachte die ersten Trades** genau
4. **Passe Parameter an** basierend auf Performance

---

## Support

Bei Problemen:
1. Prüfe die [FAQ](FAQ.md)
2. Öffne ein [GitHub Issue](https://github.com/yourusername/Bitget-Trading-Bot/issues)
3. Checke die Logs in `logs/trading_bot.log`
