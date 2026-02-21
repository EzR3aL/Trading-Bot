# Alerts einrichten

Anleitung zum Einrichten und Verwalten von Preis-, Strategie- und Portfolio-Alerts mit Discord- und Telegram-Benachrichtigungen.

---

## Inhaltsverzeichnis

1. [Ueberblick](#1-ueberblick)
2. [Price Alerts](#2-price-alerts)
3. [Strategy Alerts](#3-strategy-alerts)
4. [Portfolio Alerts](#4-portfolio-alerts)
5. [Cooldown konfigurieren](#5-cooldown-konfigurieren)
6. [Discord-Benachrichtigungen](#6-discord-benachrichtigungen)
7. [Telegram-Benachrichtigungen](#7-telegram-benachrichtigungen)
8. [Alerts verwalten](#8-alerts-verwalten)

---

## 1. Ueberblick

Das Alert-System benachrichtigt dich ueber wichtige Ereignisse in deinem Trading. Du kannst bis zu **50 Alerts** pro Benutzer erstellen.

### Drei Alert-Typen

| Typ | Beschreibung | Beispiel |
|-----|-------------|---------|
| **Price** | Preis ueber/unter einem Schwellenwert | "BTC ueber $100,000" |
| **Strategy** | Signal verpasst, niedrige Confidence, Verlustserien | "3 Verluste in Folge" |
| **Portfolio** | Tagesverlust, Drawdown, Gewinnziel | "Tagesverlust > 5%" |

### Benachrichtigungskanaele

- **Discord** (Webhook pro Bot)
- **Telegram** (Bot Token + Chat ID pro Bot)

---

## 2. Price Alerts

Preis-Alerts informieren dich, wenn ein Asset einen bestimmten Preis erreicht.

### Alert erstellen

1. Navigiere zu **Alerts** im Dashboard
2. Klicke auf **"Neuer Alert"**
3. Waehle den Typ **"Price"**
4. Konfiguriere:

| Feld | Beschreibung | Beispiel |
|------|-------------|---------|
| **Symbol** | Trading Pair | BTCUSDT |
| **Richtung** | `above` (ueber) oder `below` (unter) | above |
| **Schwellenwert** | Preis in USD | 100000 |
| **Cooldown** | Minuten bis zur naechsten Benachrichtigung | 60 |

### Beispiel: BTC ueber $100,000

```
Typ:          Price
Symbol:       BTCUSDT
Richtung:     above
Schwellenwert: 100000
Cooldown:     60 Minuten
```

### Beispiel: ETH unter $3,000

```
Typ:          Price
Symbol:       ETHUSDT
Richtung:     below
Schwellenwert: 3000
Cooldown:     30 Minuten
```

---

## 3. Strategy Alerts

Strategy Alerts informieren dich ueber wichtige Ereignisse deiner Trading-Strategien.

### Verfuegbare Kategorien

| Kategorie | Beschreibung | Wann sinnvoll |
|-----------|-------------|---------------|
| **signal_missed** | Signal wurde generiert, aber nicht ausgefuehrt | Pruefe ob Bot laeuft |
| **low_confidence** | Confidence unter einem Schwellenwert | Marktbedingungen aendern sich |
| **consecutive_losses** | Aufeinanderfolgende Verlust-Trades | Strategie ueberpruefen |

### Beispiel: 3 Verluste in Folge

```
Typ:          Strategy
Kategorie:    consecutive_losses
Schwellenwert: 3
Cooldown:     240 Minuten (4 Stunden)
Bot:          (optional) Spezifischer Bot
```

### Beispiel: Confidence unter 40%

```
Typ:          Strategy
Kategorie:    low_confidence
Schwellenwert: 40
Cooldown:     60 Minuten
```

---

## 4. Portfolio Alerts

Portfolio Alerts ueberwachen dein gesamtes Trading-Portfolio.

### Verfuegbare Kategorien

| Kategorie | Beschreibung | Schwellenwert |
|-----------|-------------|---------------|
| **daily_loss** | Tagesverlust ueberschreitet Limit | Verlust in % (z.B. 5) |
| **drawdown** | Maximaler Rueckgang vom Hoechststand | Drawdown in % (z.B. 10) |
| **profit_target** | Gewinnziel erreicht | Gewinn in % (z.B. 20) |

### Beispiel: Tagesverlust > 5%

```
Typ:          Portfolio
Kategorie:    daily_loss
Schwellenwert: 5
Cooldown:     1440 Minuten (24 Stunden)
```

### Beispiel: Gewinnziel 20% erreicht

```
Typ:          Portfolio
Kategorie:    profit_target
Schwellenwert: 20
Cooldown:     1440 Minuten (24 Stunden)
```

### Beispiel: Drawdown > 10%

```
Typ:          Portfolio
Kategorie:    drawdown
Schwellenwert: 10
Cooldown:     480 Minuten (8 Stunden)
```

---

## 5. Cooldown konfigurieren

Der **Cooldown** verhindert, dass du mit Benachrichtigungen ueberflutet wirst.

### Wie funktioniert der Cooldown?

Nach dem Ausloesen eines Alerts wird er fuer die angegebene Zeit **stumm geschaltet**. Erst danach kann er erneut ausloesen.

### Empfohlene Cooldown-Werte

| Alert-Typ | Empfohlener Cooldown | Begruendung |
|-----------|---------------------|-------------|
| Price Alert (volatile Assets) | 60 Minuten | Vermeidet Spam bei schnellen Schwankungen |
| Price Alert (Zielpreis) | 1440 Minuten (24h) | Einmalige Benachrichtigung pro Tag |
| Strategy Alerts | 240 Minuten (4h) | Genuegend Zeit zur Analyse |
| Daily Loss | 1440 Minuten (24h) | Einmal pro Tag reicht |
| Drawdown | 480 Minuten (8h) | Regelmaessige Updates |
| Profit Target | 1440 Minuten (24h) | Einmalige Erfolgsmeldung |

### Grenzwerte

- Minimum: **1 Minute**
- Maximum: **1440 Minuten** (24 Stunden)

---

## 6. Discord-Benachrichtigungen

Alerts werden ueber den **Bot-spezifischen Discord Webhook** gesendet.

### Voraussetzungen

- Discord Server mit Admin-Rechten
- Webhook fuer den Kanal erstellt

### Webhook einrichten

1. Rechtsklick auf den gewuenschten Discord-Kanal
2. **Kanal bearbeiten** -> **Integrationen** -> **Webhooks**
3. **Neuer Webhook** erstellen
4. **Webhook-URL kopieren**
5. Im **Bot Builder** (Schritt 4) die URL eintragen

### Benachrichtigungsformat

Discord-Alerts enthalten:
- **Alert-Typ** und Kategorie
- **Aktueller Wert** (z.B. aktueller Preis)
- **Schwellenwert** der ausgeloest hat
- **Zeitstempel**

---

## 7. Telegram-Benachrichtigungen

Alerts koennen auch per Telegram gesendet werden.

### Voraussetzungen

- Telegram Account
- Eigener Telegram Bot (erstellt ueber @BotFather)

### Telegram Bot erstellen

1. Oeffne Telegram und suche nach **@BotFather**
2. Sende `/newbot`
3. Folge den Anweisungen (Name und Username waehlen)
4. Du erhaeltst einen **Bot Token** (z.B. `123456:ABC-DEF1234...`)
5. Sende dem neuen Bot eine Nachricht
6. Finde deine **Chat ID**:
   - Oeffne `https://api.telegram.org/bot<DEIN_TOKEN>/getUpdates`
   - Die `chat.id` ist deine Chat ID

### Im Bot konfigurieren

Im **Bot Builder** (Schritt 4: Exchange & Modus):
1. Trage den **Bot Token** ein
2. Trage die **Chat ID** ein
3. Klicke auf **"Test senden"** um die Verbindung zu pruefen

Fuer eine ausfuehrliche Anleitung siehe: [Telegram Benachrichtigungen einrichten.md](Telegram%20Benachrichtigungen%20einrichten.md)

---

## 8. Alerts verwalten

### Alert-Liste

Unter **Alerts** im Dashboard siehst du alle deine Alerts mit:
- Status (aktiv / pausiert)
- Typ und Kategorie
- Schwellenwert
- Anzahl der Ausloesungen
- Letzte Ausloesung

### Alert aktivieren/deaktivieren

Klicke auf den **Toggle-Button** neben einem Alert, um ihn zu aktivieren oder zu deaktivieren, ohne ihn zu loeschen.

### Alert bearbeiten

Klicke auf einen Alert, um die Einstellungen zu aendern:
- Schwellenwert anpassen
- Cooldown aendern
- Richtung aendern (bei Price Alerts)

### Alert loeschen

Klicke auf das **Loeschen-Symbol** und bestaetige.

### Alert-Verlauf

Unter **Alerts** -> **Verlauf** siehst du eine Chronologie aller ausgeloesten Alerts mit:
- Zeitstempel
- Aktueller Wert zum Zeitpunkt der Ausloesung
- Nachrichtentext

---

---

# Setting Up Alerts (English)

Guide for setting up and managing price, strategy, and portfolio alerts with Discord and Telegram notifications.

---

## Overview

The alert system notifies you about important events in your trading. You can create up to **50 alerts** per user.

### Three Alert Types

| Type | Description | Example |
|------|-------------|---------|
| **Price** | Price above/below a threshold | "BTC above $100,000" |
| **Strategy** | Missed signal, low confidence, loss streaks | "3 consecutive losses" |
| **Portfolio** | Daily loss, drawdown, profit target | "Daily loss > 5%" |

### Notification Channels

- **Discord** (webhook per bot)
- **Telegram** (bot token + chat ID per bot)

---

## Price Alerts

1. Navigate to **Alerts** in the dashboard
2. Click **"New Alert"**
3. Select type **"Price"**
4. Configure:

| Field | Description | Example |
|-------|-------------|---------|
| **Symbol** | Trading pair | BTCUSDT |
| **Direction** | `above` or `below` | above |
| **Threshold** | Price in USD | 100000 |
| **Cooldown** | Minutes until next notification | 60 |

---

## Strategy Alerts

| Category | Description |
|----------|-------------|
| **signal_missed** | Signal generated but not executed |
| **low_confidence** | Confidence below threshold |
| **consecutive_losses** | Consecutive losing trades |

---

## Portfolio Alerts

| Category | Description | Threshold |
|----------|-------------|-----------|
| **daily_loss** | Daily loss exceeds limit | Loss in % |
| **drawdown** | Maximum decline from peak | Drawdown in % |
| **profit_target** | Profit target reached | Profit in % |

---

## Cooldown Configuration

Cooldown prevents notification flooding. After triggering, an alert is muted for the specified duration.

| Alert Type | Recommended Cooldown |
|-----------|---------------------|
| Price (volatile) | 60 minutes |
| Price (target) | 1440 minutes (24h) |
| Strategy | 240 minutes (4h) |
| Daily Loss | 1440 minutes (24h) |
| Drawdown | 480 minutes (8h) |
| Profit Target | 1440 minutes (24h) |

Range: 1 minute (min) to 1440 minutes (max).

---

## Discord Setup

1. Right-click on the desired Discord channel
2. **Edit Channel** -> **Integrations** -> **Webhooks**
3. Create a **New Webhook**
4. Copy the **Webhook URL**
5. Enter it in the **Bot Builder** (Step 4)

---

## Telegram Setup

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow instructions
3. Get your **Bot Token**
4. Send a message to your bot
5. Get your **Chat ID** from `https://api.telegram.org/bot<TOKEN>/getUpdates`
6. Enter both in the **Bot Builder** (Step 4)

---

## Managing Alerts

- **Toggle**: Enable/disable alerts without deleting
- **Edit**: Change threshold, cooldown, or direction
- **Delete**: Remove an alert permanently
- **History**: View chronological log of all triggered alerts with timestamps and values
