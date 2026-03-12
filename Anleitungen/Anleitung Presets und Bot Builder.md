# Anleitung: Presets und Bot Builder

Eine Schritt-fuer-Schritt Anleitung zum Erstellen und Verwenden von Konfigurations-Presets im Bot Builder.

---

## Inhaltsverzeichnis

1. [Was sind Presets?](#1-was-sind-presets)
2. [Preset erstellen](#2-preset-erstellen)
3. [Preset im Bot Builder verwenden](#3-preset-im-bot-builder-verwenden)
4. [Preset wechseln](#4-preset-wechseln)
5. [Presets verwalten](#5-presets-verwalten)
6. [Exchange-Kompatibilitaet](#6-exchange-kompatibilitaet)
7. [Beispiel-Presets](#7-beispiel-presets)
8. [Tipps & Best Practices](#8-tipps--best-practices)

---

## 1. Was sind Presets?

Presets sind **gespeicherte Konfigurationen** fuer deine Trading Bots. Statt bei jedem neuen Bot alle Parameter einzeln einzugeben, kannst du ein Preset laden und die Werte werden automatisch uebernommen.

### Vorteile

| Vorteil | Beschreibung |
|---------|--------------|
| **Zeitersparnis** | Parameter mit einem Klick laden |
| **Konsistenz** | Gleiche Einstellungen fuer mehrere Bots |
| **Experimentieren** | Verschiedene Konfigurationen speichern und vergleichen |
| **Exchange-agnostisch** | Ein Preset funktioniert auf Bitget, Weex, Hyperliquid, Bitunix und BingX |

### Was wird im Preset gespeichert?

- Hebel (Leverage)
- Positionsgroesse (%)
- Take Profit (%)
- Stop Loss (%)
- Max Trades pro Tag
- Taegliches Verlustlimit
- Trading-Paare (z.B. BTCUSDT, ETHUSDT)
- Strategie-Parameter (z.B. Fear & Greed Schwellwerte)

---

## 2. Preset erstellen

### Schritt 2.1: Presets-Seite oeffnen

1. Klicke in der Navigation auf **"Presets"**
2. Du siehst die Liste aller gespeicherten Presets

### Schritt 2.2: Neues Preset anlegen

1. Klicke auf **"Neues Preset"** (oben rechts)
2. Fulle das Formular aus:

| Feld | Beschreibung | Beispiel |
|------|--------------|----------|
| **Name** | Eindeutiger Name fuer das Preset | "Konservativ BTC" |
| **Beschreibung** | Kurze Beschreibung | "Niedrig-Risiko BTC-Strategie" |
| **Hebel** | Leverage (1-20x) | 3 |
| **Position %** | Anteil des Kontostands pro Trade | 5.0 |
| **TP %** | Take Profit in Prozent | 3.5 |
| **SL %** | Stop Loss in Prozent | 1.5 |

3. Klicke auf **"Speichern"**

### Schritt 2.3: Preset aktivieren (optional)

- Ein aktives Preset wird als Standard fuer neue Bots markiert
- Klicke auf **"Aktivieren"** bei dem gewuenschten Preset
- Das aktive Preset wird mit einem **"AKTIV"** Badge angezeigt

---

## 3. Preset im Bot Builder verwenden

### Schritt 3.1: Neuen Bot erstellen

1. Gehe zu **"Meine Bots"**
2. Klicke auf **"Neuer Bot"**

### Schritt 3.2: Preset laden

Im ersten Schritt des Bot Builders ("Name") findest du unterhalb der Name/Beschreibung-Felder die Option **"Von Preset laden"**:

1. Klicke auf das Dropdown-Menue
2. Waehle ein Preset aus der Liste
3. Die Trading-Parameter werden automatisch uebernommen:
   - Hebel
   - Positionsgroesse
   - Take Profit / Stop Loss
   - Trading-Paare
   - Strategie-Parameter

4. Du siehst die Bestaetigung: **"Preset geladen — Einstellungen nach Bedarf anpassen"**

### Schritt 3.3: Werte anpassen

Nach dem Laden kannst du alle Werte noch individuell aendern. Das Preset dient als Startpunkt — du bist nicht an die Werte gebunden.

### Schritt 3.4: Bot fertigstellen

Gehe die restlichen Schritte des Bot Builders durch:
1. **Strategie** - Waehle oder bestatige die Strategie
2. **Trading** - Pruefe/aendere die geladenen Parameter
3. **Exchange** - Waehle Exchange und Modus
4. **Zeitplan** - Konfiguriere den Handelsrhythmus
5. **Uebersicht** - Pruefe alles und erstelle den Bot

---

## 4. Preset wechseln

Du kannst das Preset eines bestehenden Bots auch nachtraeglich aendern:

1. Gehe zu **"Meine Bots"**
2. Finde den Bot, dessen Preset du aendern moechtest
3. **Wichtig:** Der Bot muss gestoppt sein!
4. Klicke auf **"Preset wechseln"**
5. Waehle das neue Preset aus
6. Die Konfiguration wird aktualisiert

> **Hinweis:** Beim Preset-Wechsel werden die Trading-Parameter ueberschrieben. Exchange und Zeitplan bleiben unveraendert.

---

## 5. Presets verwalten

### Preset bearbeiten

1. Gehe zu **Presets**
2. Klicke auf **"Bearbeiten"** beim gewuenschten Preset
3. Aendere die Werte
4. Klicke auf **"Speichern"**

> **Hinweis:** Bestehende Bots, die dieses Preset verwenden, werden NICHT automatisch aktualisiert. Du musst das Preset bei jedem Bot neu laden.

### Preset duplizieren

- Klicke auf **"Duplizieren"** um eine Kopie zu erstellen
- Nuetzlich, um Varianten einer Konfiguration zu testen

### Preset loeschen

- Klicke auf **"Loeschen"** und bestatige
- Bestehende Bots werden davon nicht beeinflusst

---

## 6. Exchange-Kompatibilitaet

Presets sind **exchange-agnostisch** — sie funktionieren auf allen unterstuetzten Exchanges:

| Exchange | Pair-Format | Automatische Konvertierung |
|----------|-------------|---------------------------|
| **Bitget** | BTCUSDT | Preset: BTCUSDT -> Bot: BTCUSDT |
| **Weex** | BTCUSDT | Preset: BTCUSDT -> Bot: BTCUSDT |
| **Hyperliquid** | BTC | Preset: BTCUSDT -> Bot: BTC (automatisch) |
| **Bitunix** | BTCUSDT | Preset: BTCUSDT -> Bot: BTCUSDT |
| **BingX** | BTC-USDT | Preset: BTCUSDT -> Bot: BTC-USDT (automatisch) |

### Wie funktioniert die Konvertierung?

Wenn du ein Preset mit Paar `BTCUSDT` auf Hyperliquid laeadst, wird es automatisch zu `BTC` konvertiert. Bei BingX wird es zu `BTC-USDT` konvertiert. Umgekehrt wird bei Bitget/Weex/Bitunix das Suffix `USDT` angehaengt, falls es fehlt.

---

## 7. Beispiel-Presets

### Konservativ (Einsteiger)

| Parameter | Wert |
|-----------|------|
| Hebel | 2x |
| Position | 5% |
| Take Profit | 3% |
| Stop Loss | 1.5% |
| Max Trades/Tag | 2 |
| Verlustlimit | 3% |

### Moderat (Fortgeschritten)

| Parameter | Wert |
|-----------|------|
| Hebel | 4x |
| Position | 7.5% |
| Take Profit | 4% |
| Stop Loss | 2% |
| Max Trades/Tag | 3 |
| Verlustlimit | 5% |

### Aggressiv (Erfahren)

| Parameter | Wert |
|-----------|------|
| Hebel | 8x |
| Position | 10% |
| Take Profit | 5% |
| Stop Loss | 2.5% |
| Max Trades/Tag | 5 |
| Verlustlimit | 8% |

> **Warnung:** Aggressive Einstellungen erhoehen das Risiko erheblich. Nur verwenden, wenn du die Risiken verstehst!

---

## 8. Tipps & Best Practices

### Namenskonvention

Verwende beschreibende Namen fuer deine Presets:

```
Konservativ BTC         <- klar, was es tut
Aggressiv Multi-Asset   <- Risikoprofil + Umfang
Rotation 4h ETH         <- Strategie + Zeitintervall
```

### Preset-Strategie

1. **Starte konservativ** — Niedrige Hebel, kleine Positionen
2. **Teste im Demo-Modus** — Jedes neue Preset zuerst simulieren
3. **Vergleiche Presets** — Erstelle mehrere Bots mit verschiedenen Presets
4. **Dokumentiere** — Nutze das Beschreibungsfeld fuer Notizen

### Haeufige Fehler vermeiden

| Fehler | Loesung |
|--------|---------|
| Zu hoher Hebel | Maximal 4x fuer Einsteiger |
| Zu grosse Positionen | Maximal 10% pro Trade |
| Kein Stop Loss | IMMER einen Stop Loss setzen |
| Preset nie getestet | Immer zuerst im Demo-Modus testen |

---

*Viel Erfolg beim Konfigurieren deiner Trading Bots!*
