# Weex Exchange Setup

Anleitung zur Einrichtung der Weex Exchange im Trading Bot.

---

## Inhaltsverzeichnis

1. [Ueberblick](#1-ueberblick)
2. [Weex Account erstellen](#2-weex-account-erstellen)
3. [API Key erstellen](#3-api-key-erstellen)
4. [Im Bot konfigurieren](#4-im-bot-konfigurieren)
5. [Demo vs. Live Modus](#5-demo-vs-live-modus)
6. [Troubleshooting](#6-troubleshooting)

---

## 1. Ueberblick

**Weex** ist eine Krypto-Futures-Exchange, die im Trading Bot als Alternative zu Bitget und Hyperliquid unterstuetzt wird.

### Weex im Vergleich

| Feature | Weex | Bitget | Hyperliquid |
|---------|------|--------|-------------|
| Auth-Typ | API Key | API Key | Wallet |
| Passphrase | Ja | Ja | Nein |
| Demo-Modus | Ja | Ja | Ja |
| Futures-Handel | Ja (USDT-M) | Ja (USDT-M) | Ja (Perp) |

---

## 2. Weex Account erstellen

### Schritt 1: Registrierung

1. Gehe zu [www.weex.com](https://www.weex.com)
2. Klicke auf **"Registrieren"** / **"Sign Up"**
3. Gib deine E-Mail-Adresse ein
4. Erstelle ein sicheres Passwort
5. Bestaetige deine E-Mail-Adresse

### Schritt 2: Verifizierung (KYC)

1. Melde dich bei Weex an
2. Navigiere zu **Profil** -> **Verifizierung**
3. Lade ein Ausweisdokument hoch
4. Warte auf die Genehmigung (normalerweise innerhalb von 24h)

### Schritt 3: Futures-Trading aktivieren

1. Navigiere zu **Futures** -> **USDT-M Futures**
2. Akzeptiere die Nutzungsbedingungen
3. Ueberweise USDT auf dein Futures-Konto

---

## 3. API Key erstellen

### Schritt 1: API-Verwaltung oeffnen

1. Klicke auf dein Profil-Icon (oben rechts)
2. Gehe zu **"API Management"** / **"API-Verwaltung"**
3. Klicke auf **"API erstellen"** / **"Create API"**

### Schritt 2: Berechtigungen setzen

**WICHTIG -- Setze die Berechtigungen genau so:**

| Berechtigung | Status | Warum |
|--------------|--------|-------|
| Read (Lesen) | Aktivieren | Bot muss Kontodaten lesen |
| Trade (Handeln) | Aktivieren | Bot muss Trades ausfuehren |
| **Withdraw (Abheben)** | **NIEMALS aktivieren!** | Schutz vor Diebstahl |

### Schritt 3: Passphrase festlegen

Waehle eine **sichere Passphrase**. Diese wird zusaetzlich zu API Key und Secret benoetigt.

### Schritt 4: IP-Whitelist (empfohlen)

Fuer maximale Sicherheit:
1. Finde deine IP-Adresse: [whatismyip.com](https://www.whatismyip.com/)
2. Trage die IP bei Weex unter **"IP Whitelist"** ein

### Schritt 5: Daten sicher speichern

Nach dem Erstellen erhaeltst du drei wichtige Daten:

```
API Key:      wx_xxxxxxxxxxxxxxxx
API Secret:   xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Passphrase:   dein_gewaehltes_passwort
```

**Bewahre diese Daten sicher auf!** Der API Secret wird nur einmal angezeigt.

---

## 4. Im Bot konfigurieren

### Schritt 1: Settings oeffnen

Im Dashboard navigiere zu **Settings** (Zahnrad-Icon).

### Schritt 2: Tab "API Keys" waehlen

Klicke auf den Tab **"API Keys"**.

### Schritt 3: Weex hinzufuegen

1. Waehle **"Weex"** als Exchange
2. Trage ein:
   - **API Key**: Dein Weex API Key
   - **API Secret**: Dein Weex API Secret
   - **Passphrase**: Deine gewaehlte Passphrase
3. Klicke auf **"Speichern"**

Die API-Daten werden **verschluesselt** in der Datenbank gespeichert.

### Schritt 4: Verbindung testen

Klicke auf **"Verbindung testen"**. Du solltest eine Erfolgsmeldung sehen.

### Schritt 5: Bot erstellen

Im **Bot Builder**:
1. Waehle als Exchange **"Weex"**
2. Waehle den Modus: **Demo** oder **Live**
3. Konfiguriere die restlichen Einstellungen (Strategie, Pairs, etc.)
4. Erstelle und starte den Bot

---

## 5. Demo vs. Live Modus

### Demo-Modus

- **Keine echten Trades** -- alles wird simuliert
- Verwendet die **Demo-Trading API** von Weex
- Perfekt zum Testen einer neuen Strategie
- **Empfohlen fuer mindestens 1-2 Wochen** vor dem Live-Trading

### Live-Modus

- **Echte Trades** auf Weex
- **Echtes Geld** ist involviert
- Alle Sicherheitsmechanismen aktiv (TP/SL, Daily Loss Limit)

### Modus im Bot Builder waehlen

Beim Erstellen eines Bots (Schritt 4):
- **Demo**: Waehle `demo` als Modus
- **Live**: Waehle `live` als Modus
- **Both**: Bot laeuft in beiden Modi parallel

### Von Demo zu Live wechseln

1. Stoppe den Bot
2. Bearbeite den Bot (Stift-Icon)
3. Aendere den Modus von `demo` zu `live`
4. Speichere und starte neu

---

## 6. Troubleshooting

### Problem: "API credentials invalid"

| Ursache | Loesung |
|---------|--------|
| Falsche Daten | Pruefe API Key, Secret und Passphrase |
| Leerzeichen | Entferne Leerzeichen am Anfang/Ende |
| Key abgelaufen | Erstelle einen neuen API Key auf Weex |
| IP nicht gewhitelisted | Fuege deine aktuelle IP zur Whitelist hinzu |

### Problem: "Insufficient balance"

| Ursache | Loesung |
|---------|--------|
| Kein USDT auf Futures-Konto | Ueberweise USDT von Spot zu Futures |
| Position Size zu gross | Reduziere `position_size_percent` |
| Falsches Konto | Pruefe ob USDT auf dem USDT-M Futures-Konto liegt |

### Problem: "Order rejected"

| Ursache | Loesung |
|---------|--------|
| Symbol nicht unterstuetzt | Pruefe ob das Trading Pair auf Weex verfuegbar ist |
| Zu kleine Order | Mindest-Ordergroesse beachten |
| Leverage nicht gesetzt | Bot setzt Leverage automatisch |

### Problem: "Connection timeout"

| Ursache | Loesung |
|---------|--------|
| Weex API nicht erreichbar | Warte und versuche erneut |
| Netzwerkproblem | Pruefe deine Internetverbindung |
| Rate Limit | Bot hat eingebauten Rate Limiter |

### Problem: Demo-Modus funktioniert nicht

1. Pruefe ob die API Keys fuer Demo-Trading berechtigt sind
2. Manche Weex-Regionen haben eingeschraenkten Demo-Zugang
3. Versuche alternativ den Bitget Demo-Modus

### Logs pruefen

```bash
# Letzte Log-Eintraege ansehen
tail -f logs/trading_bot.log

# Nach Weex-spezifischen Fehlern suchen
grep -i "weex" logs/trading_bot.log
```

---

---

# Weex Exchange Setup (English)

Guide for setting up the Weex exchange in the Trading Bot.

---

## Overview

**Weex** is a crypto futures exchange supported in the Trading Bot as an alternative to Bitget and Hyperliquid.

| Feature | Weex | Bitget | Hyperliquid |
|---------|------|--------|-------------|
| Auth Type | API Key | API Key | Wallet |
| Passphrase | Yes | Yes | No |
| Demo Mode | Yes | Yes | Yes |
| Futures | Yes (USDT-M) | Yes (USDT-M) | Yes (Perp) |

---

## Creating a Weex Account

1. Go to [www.weex.com](https://www.weex.com)
2. Click **"Sign Up"**
3. Enter email and create password
4. Complete email verification
5. Complete KYC verification (usually within 24h)
6. Activate Futures trading and deposit USDT

---

## Creating an API Key

1. Click profile icon -> **"API Management"**
2. Click **"Create API"**
3. Set permissions:
   - **Read**: Enable
   - **Trade**: Enable
   - **Withdraw**: **NEVER enable!**
4. Set a **secure passphrase**
5. Optionally add IP whitelist
6. Save your credentials:

```
API Key:      wx_xxxxxxxxxxxxxxxx
API Secret:   xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Passphrase:   your_chosen_password
```

**Important:** The API Secret is only shown once!

---

## Configuring in the Bot

1. Go to **Settings** > **API Keys** tab
2. Select **"Weex"** as exchange
3. Enter API Key, API Secret, and Passphrase
4. Click **"Save"** (credentials are encrypted)
5. Click **"Test Connection"** to verify

Then create a bot in the Bot Builder with Weex as the exchange.

---

## Demo vs. Live Mode

| Mode | Description |
|------|-------------|
| **Demo** | Simulated trades, no real money. Recommended for 1-2 weeks first. |
| **Live** | Real trades on Weex with real funds. All safety mechanisms active. |
| **Both** | Bot runs in both modes in parallel. |

To switch: Stop bot -> Edit -> Change mode -> Save -> Restart.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "API credentials invalid" | Check key, secret, passphrase. Remove extra spaces. |
| "Insufficient balance" | Transfer USDT from Spot to Futures account. |
| "Order rejected" | Check if trading pair is available on Weex. |
| "Connection timeout" | Wait and retry. Check internet connection. |
| Demo not working | Check if API keys have demo trading permission. |

### Check Logs

```bash
tail -f logs/trading_bot.log
grep -i "weex" logs/trading_bot.log
```
