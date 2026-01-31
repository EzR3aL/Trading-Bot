# Setup-Anleitung

Diese Anleitung führt dich durch die vollständige Installation und Konfiguration des Bitget Trading Bots.

**Version:** 1.8.0

---

## 🚀 Cloud Deployment (24/7 Betrieb)

**Möchtest du den Bot auf einem Server laufen lassen?**

Für 24/7-Betrieb des Bots empfehlen wir Cloud-Deployment. Eine vollständige Schritt-für-Schritt-Anleitung findest du hier:

👉 **[Cloud Deployment Guide (DigitalOcean)](DEPLOYMENT.md)**

Beinhaltet:
- DigitalOcean Droplet Setup (~$12/Monat)
- Docker-Installation und Bot-Deployment
- HTTPS mit SSL (Let's Encrypt)
- Automatische Backups und Monitoring
- Firewall und Security-Hardening

**Diese Anleitung hier** ist für lokale Entwicklung und Tests gedacht.

---

## Inhaltsverzeichnis

1. [Voraussetzungen](#voraussetzungen)
2. [Installation](#installation)
   - [Option A: Python](#option-a-python-empfohlen-für-entwicklung)
   - [Option B: Docker](#option-b-docker-empfohlen-für-produktion)
3. [Bitget API einrichten](#schritt-3-bitget-api-einrichten)
4. [Discord Webhook einrichten](#schritt-4-discord-webhook-einrichten)
5. [Konfiguration](#schritt-5-konfiguration)
6. [Bot starten](#schritt-6-bot-starten)
7. [Web Dashboard](#schritt-7-web-dashboard)
8. [Demo/Live Mode](#schritt-8-demolive-mode)
9. [Monitoring](#schritt-9-monitoring)
10. [Sicherheit](#sicherheit)
11. [Fehlerbehebung](#fehlerbehebung)

---

## Voraussetzungen

### System-Anforderungen
- **Python:** 3.10 oder höher (oder Docker)
- **Betriebssystem:** Linux, macOS oder Windows
- **RAM:** Mindestens 512 MB
- **Speicher:** 100 MB für Bot + Logs

### Accounts & API-Zugang
- [ ] Bitget Account mit Futures-Trading aktiviert
- [ ] Bitget API Key mit Trading-Berechtigung
- [ ] Discord Server mit Webhook-Zugang

---

## Installation

### Option A: Python (empfohlen für Entwicklung)

#### Schritt 1: Repository klonen

```bash
git clone https://github.com/yourusername/Bitget-Trading-Bot.git
cd Bitget-Trading-Bot
```

#### Schritt 2: Python-Umgebung einrichten

**Virtual Environment (empfohlen):**

```bash
# Virtual Environment erstellen
python -m venv venv

# Aktivieren (Linux/macOS)
source venv/bin/activate

# Aktivieren (Windows)
venv\Scripts\activate

# Dependencies installieren
pip install -r requirements.txt
```

**Oder mit Conda:**

```bash
conda create -n trading-bot python=3.11
conda activate trading-bot
pip install -r requirements.txt
```

### Option B: Docker (empfohlen für Produktion)

#### Schritt 1: Repository klonen

```bash
git clone https://github.com/yourusername/Bitget-Trading-Bot.git
cd Bitget-Trading-Bot
```

#### Schritt 2: Konfiguration erstellen

```bash
cp .env.example .env
# Bearbeite .env mit deinen Credentials (siehe Schritt 5)
```

#### Schritt 3: Container starten

```bash
# Bauen und starten
docker-compose up -d

# Logs anzeigen
docker-compose logs -f

# Stoppen
docker-compose down
```

**Docker Features:**
- Multi-Stage Build für kleinere Images
- Läuft als non-root User
- Health Checks integriert
- Resource Limits konfiguriert
- Daten persistent in `./data` und `./logs`

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

## Schritt 6: Bot starten

### Demo Mode (Standard, empfohlen zum Testen)

```bash
python main.py
```

Der Bot startet standardmäßig im **Demo Mode** - keine echten Trades werden ausgeführt!

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

## Schritt 7: Web Dashboard

Das Web Dashboard bietet eine grafische Oberfläche zur Überwachung und Steuerung des Bots.

### Dashboard starten

```bash
# Standard-Port 8080
python main.py --dashboard

# Oder mit custom Port
python main.py --dashboard --dashboard-port 3000
```

Öffne dann http://localhost:8080 im Browser.

### Dashboard Features

- **Equity Curve**: 30-Tage Performance-Graph
- **Live Positionen**: Offene Trades mit TP/SL
- **Trade History**: Letzte Trades mit PnL
- **Funding Rates**: 30-Tage Funding-Übersicht
- **Konfiguration**: Aktuelle Einstellungen
- **Demo/Live Toggle**: Modus wechseln (mit Bestätigung)

### Dashboard absichern (Produktion)

Für Produktions-Deployments solltest du das Dashboard mit einem API-Key schützen:

```bash
# API Key generieren
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

In `.env` eintragen:

```env
# Dashboard Security
DASHBOARD_API_KEY=dein_generierter_key_hier
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8080
```

**Mit API Key aktiv:**
- Der Mode-Toggle erfordert den Header: `X-API-Key: dein_key`
- Alle anderen Endpoints bleiben öffentlich (Read-Only)

### Dashboard mit Docker

Das Dashboard ist automatisch im Docker Container verfügbar:

```bash
# Bot + Dashboard starten
docker-compose up -d

# Nur Dashboard (Read-Only, kein Trading)
docker-compose --profile dashboard-only up -d dashboard
```

---

## Schritt 8: Demo/Live Mode

Der Bot hat zwei Betriebsmodi:

### Demo Mode (Standard)

- **Keine echten Trades** werden ausgeführt
- Alle Statistiken und Tracking funktionieren normal
- Perfekt zum Testen von Strategie-Änderungen
- Empfohlen für Tage/Wochen vor dem Live-Gang

### Live Mode

- **Echte Trades** werden auf Bitget ausgeführt
- Echtes Geld ist involviert!

### Modus wechseln

**Option 1: Über Dashboard**

1. Öffne http://localhost:8080
2. Klicke auf den Mode-Button (DEMO/LIVE)
3. Bestätige im Dialog

**Option 2: Über API**

```bash
# Aktuellen Modus abfragen
curl http://localhost:8080/api/mode

# Modus wechseln (ohne API Key)
curl -X POST http://localhost:8080/api/mode/toggle

# Modus wechseln (mit API Key)
curl -X POST -H "X-API-Key: dein_key" http://localhost:8080/api/mode/toggle
```

**Option 3: Über Environment**

```env
# In .env setzen
DEMO_MODE=false
```

Dann Bot neu starten.

### Empfehlung

1. **Starte immer in Demo Mode**
2. Beobachte die simulierten Trades für mindestens 1-2 Wochen
3. Prüfe die Performance im Dashboard
4. Erst wenn zufrieden → Live Mode aktivieren

---

## Schritt 9: Monitoring

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

## Sicherheit

### Sicherheits-Checkliste

**Bitget API:**
- [ ] API Key hat **KEINE** Withdrawal-Berechtigung
- [ ] IP-Whitelist auf Bitget aktiviert
- [ ] Separate API Keys für Testnet und Mainnet

**Lokale Sicherheit:**
- [ ] `.env` Datei ist in `.gitignore`
- [ ] Nie API Keys committen oder teilen
- [ ] Regelmäßige Balance-Kontrolle

**Dashboard Security (v1.7.0+):**
- [ ] `DASHBOARD_API_KEY` gesetzt für Produktion
- [ ] `DASHBOARD_HOST=127.0.0.1` (nur localhost)
- [ ] Reverse Proxy (nginx) mit HTTPS wenn extern erreichbar

**Trading:**
- [ ] Demo Mode für Tests verwendet
- [ ] Daily Loss Limit angemessen gesetzt
- [ ] Leverage konservativ (≤5x empfohlen)

### Dashboard API Key einrichten

```bash
# Sicheren Key generieren
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Ausgabe z.B.: Ky3mN_xR2vB8qL5wH1pT9sD6fA4jE0uI7cO3nZ
```

In `.env` eintragen:

```env
DASHBOARD_API_KEY=Ky3mN_xR2vB8qL5wH1pT9sD6fA4jE0uI7cO3nZ
```

### Externe Erreichbarkeit (nicht empfohlen)

Falls das Dashboard extern erreichbar sein muss:

1. **API Key setzen** (Pflicht!)
2. **Reverse Proxy** mit nginx und HTTPS
3. **Firewall** konfigurieren

Beispiel nginx Config:

```nginx
server {
    listen 443 ssl;
    server_name trading.example.com;

    ssl_certificate /etc/letsencrypt/live/trading.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/trading.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

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
