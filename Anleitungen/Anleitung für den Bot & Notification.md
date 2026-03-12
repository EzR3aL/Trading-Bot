# Anleitung für den Bot & Notifications

Eine einfache Schritt-für-Schritt Anleitung für Einsteiger.

---

## Inhaltsverzeichnis

1. [Was macht dieser Bot?](#1-was-macht-dieser-bot)
2. [Voraussetzungen](#2-voraussetzungen)
3. [Bitget Account & API einrichten](#3-bitget-account--api-einrichten)
4. [Discord Benachrichtigungen einrichten](#4-discord-benachrichtigungen-einrichten)
5. [Bot herunterladen & installieren](#5-bot-herunterladen--installieren)
6. [Konfiguration (.env Datei)](#6-konfiguration-env-datei)
7. [Bot starten](#7-bot-starten)
8. [Das Web Dashboard](#8-das-web-dashboard)
9. [Benachrichtigungen verstehen](#9-benachrichtigungen-verstehen)
10. [Demo Mode vs. Live Mode](#10-demo-mode-vs-live-mode)
11. [Häufige Probleme & Lösungen](#11-häufige-probleme--lösungen)
12. [Sicherheits-Tipps](#12-sicherheits-tipps)

---

## 1. Was macht dieser Bot?

Der Bitget Trading Bot ist ein automatisierter Handelsassistent für Kryptowährungen. Er:

- **Analysiert den Markt** automatisch (Bitcoin, Ethereum)
- **Erkennt Handelssignale** basierend auf Marktdaten
- **Führt Trades aus** auf deinem Bitget-Konto (wenn du möchtest)
- **Benachrichtigt dich** per Discord, Telegram oder WhatsApp über alle Aktivitäten

### Für wen ist der Bot geeignet?

- Du möchtest automatisiert handeln, ohne ständig den Markt zu beobachten
- Du hast grundlegende Kenntnisse über Kryptowährungen
- Du verstehst, dass Trading Risiken birgt

### Wichtiger Hinweis

> **Trading birgt erhebliche Risiken!** Investiere nur Geld, dessen Verlust du verkraften kannst. Teste den Bot zuerst im Demo-Modus, bevor du echtes Geld verwendest.

---

## 2. Voraussetzungen

Bevor du startest, stelle sicher, dass du folgendes hast:

### Was du brauchst:

| Was | Warum | Schwierigkeit |
|-----|-------|---------------|
| Computer mit Internet | Bot läuft lokal | - |
| Bitget Account | Hier wird gehandelt | Einfach |
| Discord, Telegram oder WhatsApp | Für Benachrichtigungen (mind. 1 Kanal) | Einfach |
| Python 3.10+ | Bot-Software | Mittel |

### Python installieren (falls noch nicht vorhanden)

**Windows:**
1. Gehe zu [python.org/downloads](https://www.python.org/downloads/)
2. Klicke auf "Download Python 3.11"
3. Starte die Installation
4. **WICHTIG:** Setze den Haken bei "Add Python to PATH"
5. Klicke "Install Now"

**Mac:**
```bash
# Im Terminal eingeben:
brew install python
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
```

### Python-Installation prüfen

Öffne ein Terminal (Windows: "cmd" oder "PowerShell") und tippe:

```bash
python --version
```

Du solltest etwas wie `Python 3.11.x` sehen.

---

## 3. Bitget Account & API einrichten

### Schritt 3.1: Bitget Account erstellen

1. Gehe zu [www.bitget.com](https://www.bitget.com)
2. Klicke auf "Registrieren"
3. Gib deine E-Mail-Adresse ein
4. Erstelle ein sicheres Passwort
5. Bestätige deine E-Mail-Adresse
6. **Wichtig:** Aktiviere die 2-Faktor-Authentifizierung (2FA)

### Schritt 3.2: Futures-Trading aktivieren

1. Melde dich bei Bitget an
2. Gehe zu "Futures" → "USDT-M Futures"
3. Akzeptiere die Nutzungsbedingungen für Futures-Trading
4. Überweise etwas USDT auf dein Futures-Konto

### Schritt 3.3: API Key erstellen

Der API Key ermöglicht dem Bot, auf deinem Konto zu handeln.

1. Klicke auf dein Profil (oben rechts)
2. Gehe zu **"API Management"** oder **"API-Verwaltung"**
3. Klicke auf **"API erstellen"** oder **"Create API"**

### Schritt 3.4: API Berechtigungen setzen

**SEHR WICHTIG - Setze die Berechtigungen genau so:**

| Berechtigung | Status | Warum |
|--------------|--------|-------|
| Read (Lesen) | ✅ Aktivieren | Bot muss Kontodaten lesen können |
| Trade (Handeln) | ✅ Aktivieren | Bot muss Trades ausführen können |
| **Withdraw (Abheben)** | ❌ **NIEMALS aktivieren!** | Schutz vor Diebstahl |

### Schritt 3.5: IP-Whitelist einrichten (Empfohlen)

Für zusätzliche Sicherheit:

1. Finde deine IP-Adresse: Gehe zu [whatismyip.com](https://www.whatismyip.com/)
2. Trage diese IP bei Bitget unter "IP Whitelist" ein
3. Nur von dieser IP kann der Bot handeln

### Schritt 3.6: API Daten notieren

Nach dem Erstellen erhältst du drei wichtige Daten:

```
API Key:        bg_xxxxxxxxxxxxxxxx
API Secret:     xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Passphrase:     dein_gewähltes_passwort
```

**Bewahre diese Daten sicher auf!** Du brauchst sie später für die Konfiguration.

> **Sicherheitshinweis:** Teile diese Daten NIEMALS mit anderen! Wer diese Daten hat, kann auf deinem Konto handeln.

---

## 4. Discord Benachrichtigungen einrichten

Discord ist eine Chat-App, über die der Bot dir Nachrichten schickt.

### Schritt 4.1: Discord Account erstellen (falls noch nicht vorhanden)

1. Gehe zu [discord.com](https://discord.com)
2. Klicke auf "Registrieren"
3. Erstelle deinen Account

### Schritt 4.2: Server erstellen oder auswählen

Du brauchst einen Discord-Server, auf den du Adminrechte hast:

**Neuen Server erstellen:**
1. Öffne Discord
2. Klicke links auf das **"+"** Symbol
3. Wähle "Eigenen Server erstellen"
4. Gib dem Server einen Namen (z.B. "Mein Trading Bot")
5. Klicke "Erstellen"

### Schritt 4.3: Kanal für Bot-Nachrichten erstellen

1. Rechtsklick auf deinen Server (linke Seite)
2. Wähle "Kanal erstellen"
3. Nenne ihn z.B. `#trading-alerts`
4. Klicke "Erstellen"

### Schritt 4.4: Webhook erstellen

Ein Webhook ist wie eine "Telefonnummer" für den Kanal:

1. Rechtsklick auf den Kanal `#trading-alerts`
2. Wähle **"Kanal bearbeiten"**
3. Klicke links auf **"Integrationen"**
4. Klicke auf **"Webhooks"**
5. Klicke auf **"Neuer Webhook"**
6. Gib dem Webhook einen Namen (z.B. "Trading Bot")
7. Klicke auf **"Webhook-URL kopieren"**

Die URL sieht so aus:
```
https://discord.com/api/webhooks/1234567890/abcdefghijklmnop...
```

**Speichere diese URL!** Du brauchst sie für die Konfiguration.

---

## 5. Bot herunterladen & installieren

### Schritt 5.1: Bot-Dateien herunterladen

**Option A: Mit Git (empfohlen)**

Öffne ein Terminal und tippe:

```bash
git clone https://github.com/yourusername/Bitget-Trading-Bot.git
cd Bitget-Trading-Bot
```

**Option B: Als ZIP herunterladen**

1. Gehe zur GitHub-Seite des Bots
2. Klicke auf den grünen Button "Code"
3. Wähle "Download ZIP"
4. Entpacke die ZIP-Datei in einen Ordner deiner Wahl

### Schritt 5.2: Terminal im Bot-Ordner öffnen

Navigiere zum Bot-Ordner:

```bash
cd /pfad/zu/Bitget-Trading-Bot
```

### Schritt 5.3: Python-Umgebung erstellen

Eine "virtuelle Umgebung" hält die Bot-Software getrennt von anderen Programmen:

```bash
# Umgebung erstellen
python -m venv venv

# Umgebung aktivieren (Windows)
venv\Scripts\activate

# Umgebung aktivieren (Mac/Linux)
source venv/bin/activate
```

Nach der Aktivierung siehst du `(venv)` am Anfang der Zeile.

### Schritt 5.4: Benötigte Pakete installieren

```bash
pip install -r requirements.txt
```

Warte, bis alle Pakete installiert sind. Das kann einige Minuten dauern.

---

## 6. Konfiguration (.env Datei)

Die `.env` Datei enthält alle wichtigen Einstellungen für den Bot.

### Schritt 6.1: Beispieldatei kopieren

```bash
# Windows
copy .env.example .env

# Mac/Linux
cp .env.example .env
```

### Schritt 6.2: .env Datei bearbeiten

Öffne die Datei `.env` mit einem Texteditor (Notepad, VS Code, etc.) und fülle die Werte aus:

```env
# ============ BITGET API CREDENTIALS ============
# Deine API-Daten von Schritt 3.6
BITGET_API_KEY=bg_xxxxxxxxxxxxxxxx
BITGET_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
BITGET_PASSPHRASE=dein_passwort_hier
BITGET_TESTNET=false

# ============ DISCORD CONFIGURATION ============
# Deine Webhook-URL von Schritt 4.4
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# ============ TRADING CONFIGURATION ============
# Maximale Trades pro Tag (empfohlen: 3)
MAX_TRADES_PER_DAY=3

# Tägliches Verlustlimit in Prozent (empfohlen: 5)
DAILY_LOSS_LIMIT_PERCENT=5.0

# Positionsgröße in Prozent des Kontostands (empfohlen: 10)
POSITION_SIZE_PERCENT=10.0

# Hebel (empfohlen: 3, maximal 5)
LEVERAGE=3

# Take Profit in Prozent (empfohlen: 3.5)
TAKE_PROFIT_PERCENT=3.5

# Stop Loss in Prozent (empfohlen: 2.0)
STOP_LOSS_PERCENT=2.0

# ============ ASSETS TO TRADE ============
# Welche Kryptowährungen gehandelt werden sollen
TRADING_PAIRS=BTCUSDT,ETHUSDT

# ============ TRADING MODE ============
# Demo-Modus: true = keine echten Trades, false = echte Trades
DEMO_MODE=true
```

### Was bedeuten die Einstellungen?

| Einstellung | Bedeutung | Empfehlung |
|-------------|-----------|------------|
| `MAX_TRADES_PER_DAY` | Wie viele Trades maximal pro Tag | 3 |
| `DAILY_LOSS_LIMIT_PERCENT` | Bot stoppt, wenn Verlust diesen Wert erreicht | 5% |
| `POSITION_SIZE_PERCENT` | Wie viel vom Konto pro Trade verwendet wird | 10% |
| `LEVERAGE` | Hebel (multipliziert Gewinn UND Verlust!) | 3x |
| `TAKE_PROFIT_PERCENT` | Gewinnmitnahme bei diesem Prozentsatz | 3.5% |
| `STOP_LOSS_PERCENT` | Automatischer Verkauf bei diesem Verlust | 2% |
| `DEMO_MODE` | `true` = Simulation, `false` = echtes Trading | true (zum Start!) |

### Schritt 6.3: Konfiguration prüfen

```bash
python main.py --status
```

Dies zeigt dir, ob alle Einstellungen korrekt sind.

---

## 7. Bot starten

### Demo-Modus (Empfohlen zum Start!)

Im Demo-Modus werden keine echten Trades ausgeführt. Perfekt zum Testen!

```bash
python main.py
```

Du solltest sehen:
```
============================================================
BITGET TRADING BOT - STARTING
============================================================
Mode: DEMO (No real trades)
Trading Pairs: BTCUSDT, ETHUSDT
...
Bot is running. Press Ctrl+C to stop.
```

### Mit Dashboard (Web-Oberfläche)

```bash
python main.py --dashboard
```

Öffne dann deinen Browser und gehe zu: http://localhost:8080

### Bot im Hintergrund laufen lassen (Linux/Mac)

```bash
nohup python main.py > /dev/null 2>&1 &
```

### Bot stoppen

Drücke `Ctrl + C` im Terminal.

---

## 8. Das Web Dashboard

Das Dashboard zeigt dir alle wichtigen Informationen auf einen Blick.

### Dashboard starten

```bash
python main.py --dashboard
```

### Dashboard öffnen

Gehe zu: **http://localhost:8080**

### Was du im Dashboard siehst:

| Bereich | Was es zeigt |
|---------|--------------|
| **Equity Curve** | Entwicklung deines Kontostands über 30 Tage |
| **Open Positions** | Aktuell offene Trades |
| **Trade History** | Vergangene Trades mit Gewinn/Verlust |
| **Funding Rates** | Markt-Finanzierungsraten |
| **Configuration** | Aktuelle Einstellungen |
| **Mode Toggle** | Umschalten zwischen Demo/Live |

### Dashboard absichern (für fortgeschrittene Nutzer)

Wenn du das Dashboard von außen erreichbar machen möchtest:

1. Generiere einen sicheren Schlüssel:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. Trage ihn in `.env` ein:
   ```env
   DASHBOARD_API_KEY=dein_generierter_schluessel
   ```

---

## 9. Benachrichtigungen verstehen

Der Bot schickt verschiedene Nachrichten an deine konfigurierten Kanaele (Discord, Telegram und/oder WhatsApp):

### Trade Entry (Neue Position eröffnet)

```
📈 NEW LONG POSITION OPENED

Asset: BTCUSDT
Direction: LONG
Leverage: 3x
Entry Price: $95,000.00
Position Size: 0.015 BTC
Position Value: $1,425.00

Take Profit: $98,325.00 (+3.5%)
Stop Loss: $93,100.00 (-2.0%)

Strategy: Crowded Shorts detected
Confidence: 85%
```

**Was bedeutet das?**
- Der Bot hat Bitcoin gekauft (LONG = auf steigende Kurse setzen)
- Hebel 3x = Gewinne und Verluste werden verdreifacht
- Take Profit = Bei diesem Preis wird automatisch verkauft (Gewinn)
- Stop Loss = Bei diesem Preis wird automatisch verkauft (Verlust begrenzen)

### Trade Exit (Position geschlossen)

```
✅ POSITION CLOSED - PROFIT

Asset: BTCUSDT
Direction: LONG
Duration: 4h 23m

Entry: $95,000.00
Exit: $97,500.00

Gross PnL: +$106.87 (+2.63%)
Fees: -$2.85
Funding: +$1.20
Net PnL: +$105.22
```

**Was bedeutet das?**
- Der Trade wurde mit Gewinn geschlossen
- Gross PnL = Gewinn vor Gebühren
- Fees = Handelsgebühren
- Funding = Finanzierungsrate (kann positiv oder negativ sein)
- Net PnL = Tatsächlicher Gewinn nach allen Abzügen

### Tägliche Zusammenfassung

```
📊 DAILY SUMMARY

Date: 2025-01-30
Total Trades: 2
Wins: 1 | Losses: 1
Win Rate: 50%

Total PnL: +$52.30
Max Drawdown: -$48.50
```

### Warnungen

```
⚠️ DAILY LOSS LIMIT REACHED

Current Loss: -5.2%
Limit: -5.0%

Trading halted for today.
```

---

## 10. Demo Mode vs. Live Mode

### Demo Mode (Sicher zum Testen)

- **Keine echten Trades** werden ausgeführt
- Alle Berechnungen und Benachrichtigungen funktionieren normal
- Perfekt um die Strategie zu beobachten
- **Empfohlen für mindestens 1-2 Wochen** bevor du live gehst

**Aktivieren:**
```env
DEMO_MODE=true
```

### Live Mode (Echtes Trading)

- **Echte Trades** werden auf Bitget ausgeführt
- **Echtes Geld** ist involviert
- Nur verwenden, wenn du die Strategie verstehst

**Aktivieren:**
```env
DEMO_MODE=false
```

### Modus wechseln

**Option 1: Im Dashboard**
1. Öffne http://localhost:8080
2. Klicke auf den Mode-Button (DEMO/LIVE)
3. Bestätige die Warnung

**Option 2: In der .env Datei**
1. Öffne `.env`
2. Ändere `DEMO_MODE=true` zu `DEMO_MODE=false`
3. Starte den Bot neu

### Empfohlene Vorgehensweise

1. **Woche 1-2:** Demo Mode aktiviert lassen
2. **Beobachten:** Trades und Performance im Dashboard prüfen
3. **Verstehen:** Warum wurden welche Trades gemacht?
4. **Entscheiden:** Bist du zufrieden mit der Performance?
5. **Live gehen:** Nur wenn du verstehst, was der Bot tut

---

## 11. Häufige Probleme & Lösungen

### Problem: "Bitget API credentials not configured"

**Ursache:** API-Daten fehlen oder sind falsch.

**Lösung:**
1. Prüfe, ob die `.env` Datei existiert
2. Prüfe, ob alle drei Werte korrekt sind:
   - `BITGET_API_KEY`
   - `BITGET_API_SECRET`
   - `BITGET_PASSPHRASE`
3. Keine Leerzeichen oder Anführungszeichen um die Werte!

### Problem: "Discord webhook error: 401"

**Ursache:** Webhook-URL ist ungültig.

**Lösung:**
1. Erstelle einen neuen Webhook in Discord (Schritt 4.4)
2. Kopiere die neue URL
3. Ersetze die alte URL in `.env`

### Problem: "ModuleNotFoundError: No module named 'xyz'"

**Ursache:** Python-Pakete fehlen.

**Lösung:**
```bash
pip install -r requirements.txt
```

### Problem: Bot startet nicht

**Lösungsschritte:**

1. **Python-Version prüfen:**
   ```bash
   python --version
   ```
   Muss 3.10 oder höher sein!

2. **Virtuelle Umgebung aktiviert?**
   Du solltest `(venv)` am Anfang der Zeile sehen.

3. **Logs prüfen:**
   ```bash
   cat logs/trading_bot.log
   ```

### Problem: Keine Trades werden ausgeführt

**Mögliche Ursachen:**

| Ursache | Prüfen | Lösung |
|---------|--------|--------|
| Tägliches Limit erreicht | Dashboard → Daily Stats | Warte bis morgen |
| Keine starken Signale | Ist normal | Bot wartet auf gute Gelegenheit |
| Offene Position | Dashboard → Positions | Bot wartet auf Schließung |
| Demo Mode aktiv | `.env` prüfen | `DEMO_MODE=true` ist gewollt! |

### Problem: Dashboard nicht erreichbar

1. Läuft der Bot mit `--dashboard`?
   ```bash
   python main.py --dashboard
   ```

2. Richtiger Port?
   Standard: http://localhost:8080

3. Firewall blockiert?
   Erlaube Port 8080 in deiner Firewall

---

## 12. Sicherheits-Tipps

### API Key Sicherheit

| Regel | Warum |
|-------|-------|
| **NIEMALS** Withdraw-Berechtigung aktivieren | Schutz vor Diebstahl |
| IP-Whitelist verwenden | Nur dein Computer kann handeln |
| API-Daten NIEMALS teilen | Wer sie hat, kann dein Geld handeln |
| `.env` Datei NIEMALS hochladen | Enthält sensible Daten |

### Trading Sicherheit

| Regel | Warum |
|-------|-------|
| Demo Mode zuerst nutzen | Verstehe den Bot, bevor du Geld riskierst |
| Kleine Positionen am Anfang | `POSITION_SIZE_PERCENT=5` zum Start |
| Niedrigen Hebel verwenden | `LEVERAGE=3` oder weniger |
| Nur Geld verwenden, das du verlieren kannst | Trading ist riskant! |

### Regelmäßige Checks

- [ ] Kontostand auf Bitget prüfen
- [ ] Bot-Logs auf Fehler überprüfen
- [ ] Dashboard regelmäßig ansehen
- [ ] Benachrichtigungen lesen (Discord/Telegram/WhatsApp)

---

## Zusammenfassung: Quick Start

1. **Bitget Account** erstellen und API Key erstellen
2. **Discord Webhook** erstellen
3. **Bot herunterladen** und installieren
4. **.env Datei** konfigurieren mit deinen Daten
5. **Bot starten** mit `python main.py --dashboard`
6. **Dashboard öffnen** unter http://localhost:8080
7. **1-2 Wochen im Demo Mode** beobachten
8. **Live Mode aktivieren** wenn du bereit bist

---

## Hilfe & Support

Bei Problemen:

1. **Logs prüfen:** `cat logs/trading_bot.log`
2. **Diese Anleitung** nochmal durchgehen
3. **GitHub Issue** öffnen für technische Probleme

---

*Viel Erfolg mit dem Trading Bot!*
