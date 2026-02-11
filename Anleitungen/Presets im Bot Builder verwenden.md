# Presets im Bot Builder verwenden

Eine Anleitung zum Erstellen und Verwenden von Presets beim Erstellen eines neuen Bots.

---

## Inhaltsverzeichnis

1. [Was sind Presets?](#1-was-sind-presets)
2. [Preset erstellen](#2-preset-erstellen)
3. [Preset beim Bot-Erstellen laden](#3-preset-beim-bot-erstellen-laden)
4. [Einstellungen nach dem Laden anpassen](#4-einstellungen-nach-dem-laden-anpassen)
5. [Exchange-übergreifende Presets](#5-exchange-übergreifende-presets)

---

## 1. Was sind Presets?

Presets sind **gespeicherte Konfigurationsvorlagen** für deine Bots. Statt bei jedem neuen Bot alle Einstellungen manuell einzugeben, kannst du ein Preset laden und die Werte automatisch übernehmen.

### Was wird im Preset gespeichert?

| Einstellung | Beispiel |
|-------------|----------|
| Hebel (Leverage) | 10x |
| Positionsgröße | 100 USDT |
| Take Profit | 2% |
| Stop Loss | 1% |
| Maximale Trades | 5 |
| Tägliches Verlustlimit | 50 USDT |
| Trading Pairs | BTC, ETH, SOL |
| Strategie-Einstellungen | Timeframe, Indikatoren |

### Vorteile

- **Zeitersparnis** — Einmal konfigurieren, beliebig oft verwenden
- **Konsistenz** — Gleiche Einstellungen für mehrere Bots
- **Exchange-übergreifend** — Ein Preset für Bitget UND Hyperliquid
- **Flexibel** — Nach dem Laden jederzeit anpassbar

---

## 2. Preset erstellen

### Schritt 1: Presets-Seite öffnen

1. Öffne das Web Dashboard
2. Klicke im Seitenmenü auf **Presets**
3. Klicke auf **"Neues Preset erstellen"**

### Schritt 2: Preset konfigurieren

1. **Name** — Gib deinem Preset einen aussagekräftigen Namen
   - Beispiel: `Konservativ BTC/ETH`, `Aggressiv Altcoins`, `Scalping 5min`

2. **Exchange** — Wähle eine Exchange oder **"Alle Exchanges"**
   - "Alle Exchanges" macht das Preset für Bitget und Hyperliquid nutzbar
   - Trading Pairs werden automatisch konvertiert (siehe Abschnitt 5)

3. **Trading-Einstellungen** — Lege die Standardwerte fest:
   - Hebel, Positionsgröße, TP/SL, etc.

4. **Trading Pairs** — Wähle die Paare aus, die du handeln möchtest

5. **Strategie** — Konfiguriere die Strategie-Parameter

### Schritt 3: Speichern

Klicke auf **"Speichern"**. Das Preset erscheint jetzt in deiner Liste und kann beim Bot-Erstellen geladen werden.

---

## 3. Preset beim Bot-Erstellen laden

### So lädst du ein Preset

1. Gehe zu **Bots** → **Neuen Bot erstellen**
2. In **Schritt 1 (Name)** siehst du das Dropdown **"Von Preset laden"**
3. Wähle ein Preset aus der Liste
4. Die Felder werden automatisch ausgefüllt:
   - Hebel, Positionsgröße, TP/SL
   - Maximale Trades, Verlustlimit
   - Trading Pairs
   - Strategie-Einstellungen
5. Eine Bestätigungsmeldung erscheint: *"Preset geladen — Einstellungen nach Bedarf anpassen"*

### Kein Preset vorhanden?

Wenn du noch keine Presets erstellt hast, wird dir ein Link angezeigt:
**"Erstelle zuerst ein Preset"** → Leitet dich zur Presets-Seite weiter.

---

## 4. Einstellungen nach dem Laden anpassen

Das Laden eines Presets füllt nur die Felder aus — du kannst danach **alles ändern**:

- **Bot-Name** — Wird nicht vom Preset übernommen (immer manuell eingeben)
- **Exchange** — Wird separat gewählt
- **Einzelne Werte** — Hebel, TP/SL, etc. können nachträglich angepasst werden
- **Pairs hinzufügen/entfernen** — Die geladenen Pairs sind nur ein Vorschlag

### Beispiel-Workflow

1. Preset "Konservativ BTC/ETH" laden
2. Bot-Name eingeben: `BTC Konservativ Bitget`
3. Exchange wählen: Bitget
4. Leverage von 5x auf 3x reduzieren (für noch konservativeres Trading)
5. Bot erstellen

---

## 5. Exchange-übergreifende Presets

### Was bedeutet "Exchange-übergreifend"?

Ein Preset mit Exchange-Typ **"Alle Exchanges"** kann sowohl für Bitget als auch für Hyperliquid verwendet werden. Die Trading Pairs werden dabei automatisch angepasst:

### Automatische Pair-Konvertierung

| Preset-Pair | Bitget | Hyperliquid |
|-------------|--------|-------------|
| BTC | BTCUSDT | BTC |
| ETH | ETHUSDT | ETH |
| SOL | SOLUSDT | SOL |

- **Bitget** verwendet das Format `SYMBOLUSDT` (z.B. `BTCUSDT`)
- **Hyperliquid** verwendet das Basis-Symbol (z.B. `BTC`)
- Die Konvertierung passiert **automatisch** beim Laden des Presets

### Empfehlung

Wenn du Bots auf verschiedenen Exchanges betreibst, erstelle deine Presets mit **"Alle Exchanges"**. So kannst du dieselbe Strategie auf beiden Plattformen nutzen, ohne die Pairs manuell anpassen zu müssen.

---

> **Tipp:** Erstelle verschiedene Presets für verschiedene Marktbedingungen — z.B. ein konservatives Preset für Seitwärtsmärkte und ein aggressives für Trendmärkte. So kannst du schnell zwischen Strategien wechseln.
