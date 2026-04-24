# Bot Builder Wizard

Anleitung zum 6-Schritte-Wizard, mit dem du in Edge Bots einen Trading-Bot
anlegst oder bearbeitest.

---

## DE

### 1. Was ist der Bot Builder?

Der Bot Builder ist der gefuehrte Einrichtungs-Flow hinter dem Button
**"Neuen Bot erstellen"** auf der Seite *Meine Bots*. Er ersetzt das alte
Formular und stellt sicher, dass du jede Pflicht-Entscheidung (Strategie,
Exchange, Risiko) bewusst triffst, bevor ein Bot auf dein Kapital zugreift.

Der Wizard hat je nach Strategie **5 bis 6 Schritte**. Copy-Trading laesst
den Zeitplan-Schritt aus (fester 1-Minuten-Takt), Strategien mit freier
Datenquellen-Wahl fuegen einen Daten-Schritt dazu.

### 2. Voraussetzungen

- Eingeloggter Account
- Mindestens eine Exchange-Verbindung in *Einstellungen -> API-Schluessel*
  (Bitget, Hyperliquid, Weex, Bitunix oder BingX). Fuer Hyperliquid zusaetzlich
  Builder-Fee-Genehmigung (siehe
  [Hyperliquid Builder Fee genehmigen](./Hyperliquid%20Builder%20Fee%20genehmigen.md))
- Ausreichendes Guthaben auf der Ziel-Exchange im gewaehlten Modus
  (Demo oder Live)

### 3. Die Schritte im Ueberblick

Die Schritt-Reihenfolge wird im Code in `frontend/src/components/bots/BotBuilder.tsx`
dynamisch zusammengesetzt. Jeder Schritt ist im Header als Pill klickbar;
vorherige Schritte kannst du direkt wieder anspringen.

| Schritt | Titel (DE) | Pflicht |
|---------|-----------|---------|
| 1 | **Name** | Ja |
| 2 | **Strategie** | Ja |
| 2b | **Daten** (nur bei freien Datenquellen) | Ja |
| 3 | **Exchange & Assets** | Ja |
| 4 | **Benachrichtigungen** | Nein |
| 5 | **Zeitplan** (entfaellt bei Copy-Trading) | Ja |
| 6 | **Uebersicht** | Ja (inkl. Risikohinweis) |

![Schritt-Pills oben im Builder](./screenshots/bot-builder-wizard-steps.png)
<!-- Screenshot manuell erstellen: Seite "Neuen Bot erstellen" oeffnen und die Schritt-Pills im Header abfotografieren. -->

### 4. Schritt 1 - Name

- **Bot-Name** (Pflichtfeld) - z. B. `Alpha Bot`
- **Beschreibung** (optional) - z. B. `BTC Scalper auf Bitget Demo`

Der Name erscheint auf der Bots-Liste, in Benachrichtigungen und im
Audit-Log. Keine Sonderzeichen noetig, aber eindeutige Namen erleichtern
die Fehlersuche.

### 5. Schritt 2 - Strategie

Waehle eine der registrierten Strategien (Ansicht **Kacheln** oder
**Liste**). Fuer jede Strategie werden die Parameter unten ausgeklappt.

Typische Parameter:

- **Risikoprofil** - `Konservativ` (4h, weite Stops), `Standard` (1h,
  ausgewogen), `Aggressiv` (15 min).  Wechselst du das Profil, passt der
  Wizard den Zeitplan-Standardwert automatisch an.
- Strategie-spezifisch: EMA-Perioden, MACD-Settings, Volatilitaetsfilter,
  ...

Der **Pro Mode** Toggle schaltet fuer Strategien mit festen Datenquellen
zusaetzlich die manuelle Datenquellen-Auswahl frei. Zustand wird in
`localStorage` (`botBuilder_proMode`) persistiert.

### 6. Schritt 2b - Daten (nur freie Strategien)

Nur sichtbar, wenn die Strategie `data_sources` deklariert und keine
`FIXED_STRATEGY_SOURCES`-Liste hat. Datenquellen sind nach Kategorien
gruppiert:

- **Sentiment & News**
- **Futures-Daten**
- **Optionsdaten**
- **Spot-Markt**
- **Technische Indikatoren**
- **TradFi / CME**

Pro Kategorie gibt es die Buttons **Alle auswaehlen** / **Leeren**. Der
Validator erzwingt mindestens eine Quelle, sonst blockiert der Wizard
den *Weiter*-Button mit der Meldung "Datenquellen auswaehlen".

### 7. Schritt 3 - Exchange & Assets

Kern-Schritt mit mehreren Bloecken:

1. **Exchange** - Bitget, Hyperliquid, Weex, Bitunix, BingX
2. **Modus** - `DEMO` oder `LIVE` (nur Exchanges mit `EXCHANGE_SUPPORTS_DEMO`)
3. **Margin-Modus** - `cross` oder `isolated`
4. **Trading-Paare** - bis zu 20 Perpetuals, Suche per Symbol-Feld
5. **Balance-Verteilung pro Asset** (optional) - Budget, Hebel, TP/SL,
   Max Trades, Loss Limit je Symbol. Leer lassen = gleichmaessige Aufteilung
6. **Risiko-Limits** (optional) - *Max Trades / Tag*, *Tagesverlust-Limit*

Live-Daten:
- **Balance-Vorschau** holt das Guthaben deiner Exchange-Verbindung
- **Symbol-Konflikte** zeigt an, wenn ein aktiver Bot bereits dasselbe
  Symbol auf derselben Exchange+Modus handelt. Konflikte blockieren das
  Speichern (HTTP 409 vom Backend).

Bei Hyperliquid wird zusaetzlich der Gate-Status abgefragt
(`needs_approval`, `needs_referral`). Fehlt etwas, zeigt der Wizard die
entsprechenden Hinweise.

### 8. Schritt 4 - Benachrichtigungen

Drei Sektionen als Accordion:

- **Discord Webhook** - Webhook-URL + *Test-Nachricht senden*
- **Telegram** - Bot Token + Chat-ID + *Test-Nachricht senden*
- **PnL-Alerts** - Schwellenwerte als Chips. Dollar- oder Prozent-Modus,
  Richtung *Profit / Loss / Beide*, bis zu 10 Thresholds.

Fuer bestehende Bots zeigt der Edit-Modus an, ob Discord/Telegram bereits
konfiguriert sind (`discord_configured`, `telegram_configured`). Leere
Felder im Edit-Modus bedeuten "nicht aendern" - das Backend behaelt die
gespeicherten Geheimnisse.

Details zur Telegram-Einrichtung:
[Telegram Benachrichtigungen einrichten](./Telegram%20Benachrichtigungen%20einrichten.md).

### 9. Schritt 5 - Zeitplan

Zwei Varianten:

- **Eigenes Intervall** - in Minuten. Minimum 5 Minuten. Warnung, wenn
  das Intervall kuerzer als das Kline-Intervall der Strategie ist
  (sonst wuerde dieselbe Kerze mehrfach analysiert).
- **Eigene Uhrzeiten** - eine oder mehrere feste Uhrzeiten. Der Wizard
  konvertiert lokale Zeiten in UTC, bevor das Backend sie speichert.

Copy-Trading ueberspringt diesen Schritt komplett und zwingt intern
`interval_minutes = 1`.

### 10. Schritt 6 - Uebersicht & Risikohinweis

- Zusammenfassung aller Eingaben
- **Risikohinweis** mit Pflicht-Checkbox (`riskAccept`). Ohne Haken bleibt
  der Speichern-Button disabled.
- Im Edit-Modus: Eine *neue* Risikobestaetigung ist nur noetig, wenn du
  das Risikoprofil gegenueber dem gespeicherten Wert **erhoehst**
  (`conservative -> standard -> aggressive`).
- Zwei Buttons:
  - **Bot erstellen** / **Aenderungen speichern**
  - **Erstellen & Starten** (nur im Create-Modus) - ruft nach dem POST
    zusaetzlich `POST /api/bots/{id}/start` auf.

![Uebersichts-Schritt mit Risikohinweis](./screenshots/bot-builder-wizard-review.png)
<!-- Screenshot manuell erstellen: letzten Schritt mit Risk-Checkbox aufnehmen. -->

### 11. Haeufige Fallstricke

- **"Datenquellen auswaehlen"** - Schritt 2b uebersprungen. Zurueck auf
  2b, mindestens eine Quelle aktivieren.
- **Symbol-Konflikt** - ein anderer aktiver Bot handelt dasselbe Symbol
  auf derselben Exchange+Modus. Entweder den Konflikt-Bot stoppen oder
  ein anderes Symbol waehlen.
- **Hyperliquid: needs_approval** - Builder-Fee-Genehmigung fehlt. Erst
  die Setup-Anleitung abarbeiten, dann zurueck in den Wizard.
- **Intervall < 5 Minuten** - Validator lehnt ab. Minimum ist 5.
- **Risikoprofil erhoeht, aber "Speichern" ausgegraut** - Checkbox fuer
  Risikohinweis erneut anhaken (erwarteter Re-Ack-Flow).

---

## EN

### 1. What is the Bot Builder?

The Bot Builder is the guided setup flow behind the **"Create new bot"**
button on the *My Bots* page. It replaces the old flat form and makes
sure every required decision (strategy, exchange, risk) is explicit before
a bot touches your capital.

Depending on the strategy the wizard has **5 to 6 steps**. Copy trading
skips the schedule step (fixed 1-minute cadence), strategies with free
data source choice add a data step.

### 2. Prerequisites

- A logged-in account.
- At least one exchange connection in *Settings -> API Keys*
  (Bitget, Hyperliquid, Weex, Bitunix, or BingX). For Hyperliquid the
  builder-fee approval (see
  [Hyperliquid Builder Fee Approval](./en/Hyperliquid-Builder-Fee-Approval.md)).
- Sufficient balance on the target exchange in the chosen mode
  (Demo or Live).

### 3. Step overview

The step order is assembled dynamically in
`frontend/src/components/bots/BotBuilder.tsx`. Each step appears as a
clickable pill in the header, so you can jump back to any completed step.

| Step | Title | Required |
|------|-------|----------|
| 1 | **Name** | Yes |
| 2 | **Strategy** | Yes |
| 2b | **Data** (only for strategies with free sources) | Yes |
| 3 | **Exchange & Assets** | Yes |
| 4 | **Notifications** | No |
| 5 | **Schedule** (skipped for copy trading) | Yes |
| 6 | **Review** | Yes (incl. risk disclaimer) |

### 4. Step 1 - Name

- **Bot name** (required) - e.g. `Alpha Bot`.
- **Description** (optional) - e.g. `BTC scalper on Bitget demo`.

The name shows up in the bots list, in notifications and in the audit
log. Unique names make debugging easier.

### 5. Step 2 - Strategy

Pick a registered strategy (grid or list view). Parameters render below:

- **Risk profile** - `Conservative` (4h, wide stops), `Standard` (1h,
  balanced), `Aggressive` (15 min). Switching the profile auto-adjusts
  the default schedule interval.
- Strategy-specific: EMA periods, MACD settings, volatility filters...

The **Pro Mode** toggle unlocks manual data source selection even for
fixed-source strategies. Stored in `localStorage` (`botBuilder_proMode`).

### 6. Step 2b - Data sources (free strategies only)

Only shown when the strategy declares `data_sources` and has no
`FIXED_STRATEGY_SOURCES` list. Sources are grouped by category
(Sentiment & News, Futures, Options, Spot, Technical, TradFi / CME).

Per category you have **Select all** / **Clear**. The validator requires
at least one source.

### 7. Step 3 - Exchange & Assets

Main configuration block:

1. **Exchange** - Bitget, Hyperliquid, Weex, Bitunix, BingX.
2. **Mode** - `DEMO` or `LIVE` (demo only for exchanges where
   `EXCHANGE_SUPPORTS_DEMO` is true).
3. **Margin mode** - `cross` or `isolated`.
4. **Trading pairs** - up to 20 perpetuals, with a symbol search box.
5. **Per-asset balance distribution** (optional) - budget, leverage,
   TP/SL, max trades, loss limit per symbol. Empty = even split.
6. **Risk limits** (optional) - *Max trades / day*, *Daily loss limit*.

Live data:
- **Balance preview** pulls balance from your connected exchange.
- **Symbol conflicts** flag any active bot already trading the same
  symbol on the same exchange+mode. Conflicts block saving (backend
  returns HTTP 409).

On Hyperliquid the gate status (`needs_approval`, `needs_referral`) is
fetched and shown inline.

### 8. Step 4 - Notifications

Three accordion sections:

- **Discord webhook** - webhook URL + *Send test message*.
- **Telegram** - bot token + chat ID + *Send test message*.
- **PnL alerts** - thresholds as chips. Dollar or percent mode,
  direction *Profit / Loss / Both*, up to 10 thresholds.

In edit mode a badge shows whether Discord/Telegram are already
configured. Leaving the secret fields empty on edit means "do not
change" - the backend keeps the stored secrets.

### 9. Step 5 - Schedule

Two variants:

- **Custom interval** (minutes). Minimum 5. Warning if the interval is
  shorter than the strategy's kline interval (would re-analyze the same
  candle repeatedly).
- **Custom hours** - one or more fixed hours. The wizard converts local
  times to UTC before sending to the backend.

Copy trading skips this step entirely and internally forces
`interval_minutes = 1`.

### 10. Step 6 - Review & risk acknowledgement

- Summary of all inputs.
- **Risk disclaimer** with a required checkbox. Without the checkbox
  the save button stays disabled.
- In edit mode: a fresh acknowledgement is only required when you
  **raise** the risk profile above the stored value
  (`conservative -> standard -> aggressive`).
- Two buttons:
  - **Create bot** / **Save changes**.
  - **Create & start** (create mode only) - additionally calls
    `POST /api/bots/{id}/start` after the create.

### 11. Common pitfalls

- **"Select data sources"** - step 2b skipped. Go back and pick at least
  one source.
- **Symbol conflict** - another active bot trades the same symbol on
  the same exchange+mode. Stop that bot or pick a different symbol.
- **Hyperliquid: needs_approval** - builder-fee approval missing. Run
  the setup guide first, then return to the wizard.
- **Interval < 5 minutes** - validator rejects. Minimum is 5.
- **Raised risk profile but Save is greyed out** - tick the risk
  acknowledgement again (expected re-ack flow).
