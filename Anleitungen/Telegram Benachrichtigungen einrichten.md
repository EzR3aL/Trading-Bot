# Telegram Benachrichtigungen einrichten

Eine Schritt-für-Schritt Anleitung zum Einrichten von Telegram-Benachrichtigungen für deinen Trading Bot.

---

## Inhaltsverzeichnis

1. [Was sind Telegram-Benachrichtigungen?](#1-was-sind-telegram-benachrichtigungen)
2. [Telegram-Bot erstellen via @BotFather](#2-telegram-bot-erstellen-via-botfather)
3. [Chat-ID herausfinden](#3-chat-id-herausfinden)
4. [Token & Chat-ID im Bot Builder eintragen](#4-token--chat-id-im-bot-builder-eintragen)
5. [Test-Nachricht senden](#5-test-nachricht-senden)
6. [Häufige Probleme & Lösungen](#6-häufige-probleme--lösungen)

---

## 1. Was sind Telegram-Benachrichtigungen?

Dein Trading Bot kann dich per Telegram über wichtige Ereignisse informieren:

- **Trade eröffnet** — Symbol, Richtung, Einstiegspreis, Hebel
- **Trade geschlossen** — Gewinn/Verlust, Dauer
- **Bot-Status** — Gestartet, Gestoppt
- **Fehler** — Wenn etwas schiefgeht

### Vorteile gegenüber Discord

| | Telegram | Discord |
|--|----------|---------|
| Mobile Push-Benachrichtigungen | Sofort | Manchmal verzögert |
| Einrichtung | Einfach | Einfach |
| Datenschutz | Privater Chat | Server nötig |
| Geschwindigkeit | Sehr schnell | Schnell |

> **Hinweis:** Du kannst Telegram und Discord gleichzeitig nutzen! Beide Kanäle funktionieren unabhängig voneinander pro Bot.

---

## 2. Telegram-Bot erstellen via @BotFather

Der @BotFather ist der offizielle Telegram-Bot zum Erstellen neuer Bots. So gehst du vor:

### Schritt 1: BotFather öffnen

1. Öffne Telegram auf deinem Handy oder Desktop
2. Suche nach **@BotFather** in der Suchleiste
3. Klicke auf den verifizierten Bot (blauer Haken)
4. Klicke auf **"Start"**

### Schritt 2: Neuen Bot erstellen

1. Sende die Nachricht: `/newbot`
2. BotFather fragt nach einem **Namen** für deinen Bot
   - Beispiel: `Mein Trading Bot`
3. BotFather fragt nach einem **Benutzernamen** (muss auf `bot` enden)
   - Beispiel: `mein_trading_alerts_bot`

### Schritt 3: Token kopieren

Nach der Erstellung erhältst du eine Nachricht wie:

```
Done! Congratulations on your new bot.
...
Use this token to access the HTTP API:
6123456789:ABCdefGhIjKlMnOpQrStUvWxYz123456789
```

> **WICHTIG:** Kopiere diesen Token und bewahre ihn sicher auf! Teile ihn mit niemandem — wer den Token hat, kann Nachrichten über deinen Bot senden.

---

## 3. Chat-ID herausfinden

Die Chat-ID sagt dem Bot, wohin er die Nachrichten senden soll.

### Option A: Persönlicher Chat (empfohlen)

1. Öffne einen Chat mit deinem neu erstellten Bot
2. Sende ihm eine beliebige Nachricht (z.B. "Hallo")
3. Öffne diese URL in deinem Browser (ersetze `DEIN_TOKEN`):
   ```
   https://api.telegram.org/botDEIN_TOKEN/getUpdates
   ```
4. In der Antwort findest du deine Chat-ID:
   ```json
   "chat": {
     "id": 123456789,
     ...
   }
   ```
5. Die Zahl bei `"id"` ist deine **Chat-ID**

### Option B: Über @userinfobot

1. Suche in Telegram nach **@userinfobot**
2. Klicke auf **"Start"**
3. Der Bot antwortet mit deiner User-ID — das ist gleichzeitig deine Chat-ID

### Option C: Gruppen-Chat

Wenn du Benachrichtigungen in eine Gruppe senden möchtest:

1. Erstelle eine Telegram-Gruppe
2. Füge deinen Bot als Mitglied hinzu
3. Sende eine Nachricht in die Gruppe
4. Rufe `https://api.telegram.org/botDEIN_TOKEN/getUpdates` auf
5. Die Gruppen-Chat-ID beginnt mit `-` (z.B. `-1001234567890`)

---

## 4. Token & Chat-ID im Bot Builder eintragen

1. Öffne das Web Dashboard unter `http://localhost:5173`
2. Gehe zu **Bots** → **Neuen Bot erstellen** (oder bestehenden Bot bearbeiten)
3. Navigiere zu **Schritt 4: Exchange & Modus**
4. Scrolle zum Abschnitt **Benachrichtigungen**
5. Trage ein:
   - **Telegram Bot Token**: Den Token von @BotFather
   - **Telegram Chat-ID**: Deine Chat-ID von Schritt 3
6. Fahre mit der Bot-Erstellung fort oder speichere die Änderungen

> **Tipp:** Du kannst für verschiedene Bots unterschiedliche Telegram-Kanäle verwenden!

---

## 5. Test-Nachricht senden

Nach dem Speichern kannst du testen, ob alles funktioniert:

1. Gehe zur **Bot-Detail-Seite** des entsprechenden Bots
2. Klicke auf **"Test Telegram"**
3. Du solltest eine Testnachricht in deinem Telegram-Chat erhalten:

```
✅ Telegram Notification Test

Your Telegram notifications are configured correctly!
🕐 2026-02-11 15:30 UTC
```

Wenn die Nachricht ankommt, ist alles korrekt eingerichtet!

---

## 6. Häufige Probleme & Lösungen

### "Failed to send Telegram message"

| Ursache | Lösung |
|---------|--------|
| Token ist falsch | Prüfe den Token bei @BotFather mit `/mybots` |
| Chat-ID ist falsch | Wiederhole Schritt 3 zur Ermittlung der Chat-ID |
| Bot nicht gestartet | Öffne einen Chat mit deinem Bot und sende `/start` |
| Bot nicht in Gruppe | Füge den Bot als Mitglied zur Gruppe hinzu |

### "Unauthorized" Fehler

- Der Token ist ungültig oder wurde widerrufen
- Erstelle bei @BotFather einen neuen Token: `/mybots` → Wähle Bot → **API Token** → **Revoke**

### Keine Benachrichtigungen im Live-Betrieb

- Stelle sicher, dass der Bot **gestartet** ist (grüner Status)
- Prüfe, ob sowohl Token als auch Chat-ID eingetragen sind
- Teste mit dem "Test Telegram" Button

### Nachrichten kommen verzögert an

- Telegram liefert Nachrichten normalerweise in unter 1 Sekunde
- Prüfe deine Internetverbindung
- Bei Gruppenchats: Stelle sicher, dass der Bot Admin-Rechte hat

---

> **Sicherheitshinweis:** Dein Telegram Bot Token wird verschlüsselt in der Datenbank gespeichert. Trotzdem gilt: Teile deinen Token niemals mit Dritten und verwende den Bot ausschließlich für Trading-Benachrichtigungen.
