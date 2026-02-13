# Anleitung: Telegram Benachrichtigungen einrichten

Eine Schritt-fuer-Schritt Anleitung, um Telegram-Benachrichtigungen fuer deinen Trading Bot zu aktivieren.

---

## Inhaltsverzeichnis

1. [Ueberblick](#1-ueberblick)
2. [Telegram Bot erstellen](#2-telegram-bot-erstellen)
3. [Chat-ID herausfinden](#3-chat-id-herausfinden)
4. [Im Bot Builder konfigurieren](#4-im-bot-builder-konfigurieren)
5. [Test-Nachricht senden](#5-test-nachricht-senden)
6. [Benachrichtigungen verstehen](#6-benachrichtigungen-verstehen)
7. [Haeufige Probleme & Loesungen](#7-haeufige-probleme--loesungen)

---

## 1. Ueberblick

Jeder Trading Bot kann eigene Telegram-Benachrichtigungen erhalten. Du bekommst Nachrichten bei:

- **Trade Entry** - Wenn eine neue Position geoeffnet wird
- **Trade Exit** - Wenn eine Position geschlossen wird (mit PnL)
- **Bot-Status** - Start, Stop, Fehler
- **Fehler-Meldungen** - Wenn etwas schief laeuft

### Warum Telegram?

| Vorteil | Beschreibung |
|---------|--------------|
| **Sofort** | Push-Benachrichtigungen auf dem Handy |
| **Kostenlos** | Keine Gebuehren |
| **Pro Bot** | Jeder Bot hat seinen eigenen Kanal |
| **Kombination** | Funktioniert zusaetzlich zu Discord |

---

## 2. Telegram Bot erstellen

### Schritt 2.1: BotFather oeffnen

1. Oeffne Telegram auf deinem Handy oder Desktop
2. Suche nach **@BotFather** (der offizielle Bot-Ersteller von Telegram)
3. Starte einen Chat mit BotFather

### Schritt 2.2: Neuen Bot erstellen

1. Sende die Nachricht: `/newbot`
2. BotFather fragt: **"Alright, a new bot. How are we going to call it?"**
3. Gib deinem Bot einen Namen, z.B.: `Mein Trading Bot`
4. BotFather fragt: **"Good. Now let's choose a username..."**
5. Gib einen eindeutigen Benutzernamen ein, z.B.: `mein_trading_alert_bot`
   - Muss auf `_bot` enden
   - Darf noch nicht vergeben sein

### Schritt 2.3: Token kopieren

Nach dem Erstellen erhaeltst du eine Nachricht mit deinem **Bot Token**:

```
Done! Congratulations on your new bot.
...
Use this token to access the HTTP API:
7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Kopiere diesen Token!** Du brauchst ihn im Bot Builder.

> **Sicherheitshinweis:** Teile diesen Token NIEMALS mit anderen! Wer den Token hat, kann Nachrichten ueber deinen Bot senden.

---

## 3. Chat-ID herausfinden

Die Chat-ID sagt dem Bot, wohin die Nachrichten geschickt werden sollen.

### Option A: Persoenliche Nachrichten (Empfohlen)

1. Oeffne Telegram und suche nach dem Bot, den du gerade erstellt hast
2. Klicke auf **"Starten"** oder sende `/start`
3. Oeffne jetzt im Browser:
   ```
   https://api.telegram.org/bot<DEIN_TOKEN>/getUpdates
   ```
   Ersetze `<DEIN_TOKEN>` mit deinem Bot Token.

4. Du siehst eine Antwort wie:
   ```json
   {
     "result": [{
       "message": {
         "chat": {
           "id": 123456789,
           "type": "private"
         }
       }
     }]
   }
   ```

5. Die Zahl bei `"id"` ist deine **Chat-ID** (z.B. `123456789`)

### Option B: Gruppen-Chat

Wenn du Benachrichtigungen in einer Gruppe empfangen moechtest:

1. Erstelle eine Telegram-Gruppe
2. Fuege deinen Bot als Mitglied hinzu
3. Sende eine Nachricht in der Gruppe
4. Oeffne `https://api.telegram.org/bot<DEIN_TOKEN>/getUpdates`
5. Die Gruppen-Chat-ID beginnt mit `-` (z.B. `-1001234567890`)

---

## 4. Im Bot Builder konfigurieren

### Schritt 4.1: Bot erstellen oder bearbeiten

1. Gehe zu **Meine Bots**
2. Klicke auf **"Neuer Bot"** oder bearbeite einen bestehenden Bot

### Schritt 4.2: Exchange-Schritt (Schritt 4 im Builder)

Im Schritt **"Exchange"** des Bot Builders findest du die Telegram-Felder:

| Feld | Wert | Beispiel |
|------|------|----------|
| **Telegram Bot Token** | Der Token aus Schritt 2.3 | `7123456789:AAHxxx...` |
| **Telegram Chat ID** | Die ID aus Schritt 3 | `123456789` |

### Schritt 4.3: Eingeben und speichern

1. Trage den **Bot Token** ein
2. Trage die **Chat-ID** ein
3. Fahre mit den naechsten Schritten fort oder speichere den Bot

> **Hinweis:** Telegram-Felder sind optional. Wenn du sie leer laesst, werden keine Telegram-Nachrichten gesendet. Du kannst sie jederzeit nachtraeglich hinzufuegen.

---

## 5. Test-Nachricht senden

Nach dem Erstellen des Bots kannst du die Telegram-Verbindung testen:

1. Gehe zur **Bot-Detailseite** (klicke auf den Bot-Namen)
2. Unter der Konfiguration siehst du **"Telegram konfiguriert"**
3. Klicke auf **"Telegram testen"**
4. Du solltest eine Test-Nachricht in deinem Telegram-Chat erhalten

Falls keine Nachricht ankommt:
- Pruefe, ob du den Bot in Telegram gestartet hast (`/start`)
- Pruefe Token und Chat-ID auf Tippfehler
- Stelle sicher, dass der Bot-Token gueltig ist

---

## 6. Benachrichtigungen verstehen

### Trade Entry

```
TRADE OPENED

Bot: Alpha Bot
Symbol: BTCUSDT
Direction: LONG
Entry Price: $95,000.00
Size: 0.015
Leverage: 3x
Take Profit: $98,325.00
Stop Loss: $93,100.00
Confidence: 85%
Mode: DEMO
```

### Trade Exit

```
TRADE CLOSED - PROFIT

Bot: Alpha Bot
Symbol: BTCUSDT
Direction: LONG
Entry: $95,000.00
Exit: $97,500.00
PnL: +$106.87 (+2.63%)
Fees: $2.85
Duration: 4h 23m
Mode: DEMO
```

### Bot Status

```
BOT STATUS: STARTED

Bot: Alpha Bot
Exchange: bitget
Mode: DEMO
```

### Fehler

```
BOT ERROR

Bot: Alpha Bot
Error: Connection timeout
Details: Exchange API not responding
```

---

## 7. Haeufige Probleme & Loesungen

### Problem: Keine Nachrichten kommen an

| Pruefpunkt | Loesung |
|------------|---------|
| Bot in Telegram gestartet? | Oeffne den Bot und sende `/start` |
| Token korrekt? | Vergleiche mit BotFather-Nachricht |
| Chat-ID korrekt? | Nochmal ueber `/getUpdates` pruefen |
| Bot laeuft? | Bot muss gestartet sein fuer Nachrichten |

### Problem: "Unauthorized" Fehler

**Ursache:** Bot Token ist ungueltig oder abgelaufen.

**Loesung:**
1. Gehe zu @BotFather
2. Sende `/mybots`
3. Waehle deinen Bot
4. Klicke auf "API Token" > "Revoke current token"
5. Kopiere den neuen Token
6. Aktualisiere den Token im Bot Builder

### Problem: "Chat not found" Fehler

**Ursache:** Chat-ID ist falsch oder Bot wurde nicht gestartet.

**Loesung:**
1. Oeffne den Bot in Telegram
2. Sende `/start`
3. Hole die Chat-ID erneut ueber `/getUpdates`

### Problem: Nachrichten kommen doppelt

**Ursache:** Sowohl Discord als auch Telegram sind konfiguriert.

**Loesung:** Das ist normal! Beide Kanaele arbeiten unabhaengig. Wenn du nur einen Kanal moechtest, lasse die Felder des anderen leer.

---

## Zusammenfassung: Quick Setup

1. **@BotFather** in Telegram oeffnen
2. `/newbot` senden und Bot erstellen
3. **Token kopieren**
4. Bot in Telegram **starten** (`/start`)
5. **Chat-ID** ueber `/getUpdates` herausfinden
6. Im **Bot Builder** Token + Chat-ID eintragen
7. **Test-Nachricht** ueber Bot-Detailseite senden

---

*Fertig! Dein Bot sendet jetzt Benachrichtigungen direkt auf dein Handy.*
