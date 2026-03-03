# WhatsApp-Benachrichtigungen & Bitunix/BingX Exchange-Setup

## Inhaltsverzeichnis / Table of Contents

- [Deutsch](#deutsch)
- [English](#english)

---

## Deutsch

### 1. WhatsApp-Benachrichtigungen einrichten

Der Trading-Bot unterstuetzt jetzt WhatsApp-Benachrichtigungen neben Discord und Telegram. Du erhaeltst Trade-Entries, Exits, Daily Summaries und Risiko-Alerts direkt auf WhatsApp.

#### Voraussetzungen

1. **Meta Business Account** — Erstelle ein kostenloses Konto unter [business.facebook.com](https://business.facebook.com)
2. **WhatsApp Business API Zugang** — Aktiviere die WhatsApp Business Platform in der Meta Developer Console
3. **Permanenter Access Token** — Erstelle einen System-Benutzer-Token mit `whatsapp_business_messaging`-Berechtigung
4. **Phone Number ID** — Findest du im WhatsApp-Bereich der Meta Developer Console

#### Schritt-fuer-Schritt Konfiguration

1. **Meta Developer Console oeffnen**
   - Gehe zu [developers.facebook.com](https://developers.facebook.com)
   - Erstelle eine neue App (Typ: "Business")
   - Fuege das Produkt "WhatsApp" hinzu

2. **Phone Number ID und Access Token notieren**
   - Im WhatsApp-Dashboard unter "API Setup"
   - Die Phone Number ID ist eine numerische ID (z.B. `123456789012345`)
   - Erstelle einen permanenten Token ueber System-Benutzer (nicht den temporaeren Test-Token!)

3. **Im Bot Builder konfigurieren**
   - Oeffne den Bot Builder (Schritt 4: Benachrichtigungen)
   - Trage die drei Felder ein:
     - **Phone Number ID**: Die ID deiner WhatsApp Business Telefonnummer
     - **Access Token**: Der permanente System-Benutzer-Token
     - **Empfaenger-Nummer**: Deine Telefonnummer im internationalen Format (z.B. `491701234567`)

4. **Test-Nachricht senden**
   - In der Bot-Detailansicht findest du den Button "Test WhatsApp"
   - Klicke darauf, um eine Testnachricht zu erhalten

#### Hinweise

- WhatsApp-Nachrichten werden als Plain-Text mit Emojis gesendet (kein HTML)
- Rate-Limits: Meta erlaubt standardmaessig 250 Nachrichten pro Tag (erweiterbar)
- Die Credentials werden verschluesselt in der Datenbank gespeichert
- WhatsApp ist **optional** — du kannst Discord, Telegram und/oder WhatsApp gleichzeitig nutzen

---

### 2. Bitunix Exchange einrichten

Bitunix ist eine Krypto-Futures-Boerse mit USDT-Margined Perpetual Contracts.

#### API-Keys erstellen

1. **Konto erstellen** unter [bitunix.com](https://www.bitunix.com)
2. **API-Bereich oeffnen**: Profil -> API Management -> API Key erstellen
3. **Berechtigungen setzen**:
   - Futures Trading: Aktivieren
   - Read: Aktivieren
   - IP-Whitelist: Empfohlen (trage die IP deines Servers ein)
4. **Notiere**: API Key, Secret Key, Passphrase

#### Im Bot Builder verwenden

1. Waehle **Bitunix** als Exchange im Bot Builder (Schritt 1)
2. Trage API Key, Secret und Passphrase ein
3. Trading Pairs sind im Format `BTCUSDT` (ohne Trennzeichen)
4. Symbol-Konvertierung erfolgt automatisch

#### Affiliate-Verknuepfung

1. Gehe zu **Settings** -> **Affiliate Links**
2. Trage deine Bitunix-UID ein (numerisch, z.B. `12345678`)
3. Die UID wird validiert und gespeichert

---

### 3. BingX Exchange einrichten

BingX ist eine globale Krypto-Boerse mit Perpetual Swap Contracts und VST-Demo-Modus.

#### API-Keys erstellen

1. **Konto erstellen** unter [bingx.com](https://bingx.com)
2. **API-Bereich oeffnen**: Account -> API Management -> Create API
3. **Berechtigungen setzen**:
   - Perpetual Futures: Aktivieren
   - Read: Aktivieren
4. **Notiere**: API Key und Secret Key (kein Passphrase noetig)

#### Demo-Modus (VST)

BingX bietet einen separaten Demo-Trading-Bereich (Virtual Simulated Trading):
- Aktiviere "Demo Mode" im Bot Builder
- Der Bot verbindet sich automatisch mit der VST-Domain (`open-api-vst.bingx.com`)
- Perfekt zum risikofreien Testen von Strategien

#### Im Bot Builder verwenden

1. Waehle **BingX** als Exchange im Bot Builder (Schritt 1)
2. Trage API Key und Secret ein (kein Passphrase)
3. Trading Pairs sind im Format `BTC-USDT` (mit Bindestrich)
4. Symbol-Konvertierung erfolgt automatisch

#### Affiliate-Verknuepfung

1. Gehe zu **Settings** -> **Affiliate Links**
2. Trage deine BingX-UID ein (numerisch, z.B. `87654321`)
3. Die UID wird validiert und gespeichert

---

## English

### 1. Setting Up WhatsApp Notifications

The Trading Bot now supports WhatsApp notifications alongside Discord and Telegram. Receive trade entries, exits, daily summaries, and risk alerts directly on WhatsApp.

#### Prerequisites

1. **Meta Business Account** — Create a free account at [business.facebook.com](https://business.facebook.com)
2. **WhatsApp Business API Access** — Activate WhatsApp Business Platform in the Meta Developer Console
3. **Permanent Access Token** — Create a system user token with `whatsapp_business_messaging` permission
4. **Phone Number ID** — Found in the WhatsApp section of the Meta Developer Console

#### Step-by-Step Configuration

1. **Open Meta Developer Console**
   - Go to [developers.facebook.com](https://developers.facebook.com)
   - Create a new app (type: "Business")
   - Add the "WhatsApp" product

2. **Note Phone Number ID and Access Token**
   - In the WhatsApp dashboard under "API Setup"
   - The Phone Number ID is a numeric ID (e.g. `123456789012345`)
   - Create a permanent token via system user (not the temporary test token!)

3. **Configure in Bot Builder**
   - Open Bot Builder (Step 4: Notifications)
   - Fill in the three fields:
     - **Phone Number ID**: Your WhatsApp Business phone number ID
     - **Access Token**: The permanent system user token
     - **Recipient Number**: Your phone number in international format (e.g. `491701234567`)

4. **Send Test Message**
   - In the bot detail view, find the "Test WhatsApp" button
   - Click it to receive a test message

#### Notes

- WhatsApp messages are sent as plain text with emojis (no HTML)
- Rate limits: Meta allows 250 messages per day by default (expandable)
- Credentials are stored encrypted in the database
- WhatsApp is **optional** — you can use Discord, Telegram, and/or WhatsApp simultaneously

---

### 2. Setting Up Bitunix Exchange

Bitunix is a crypto futures exchange with USDT-margined perpetual contracts.

#### Creating API Keys

1. **Create account** at [bitunix.com](https://www.bitunix.com)
2. **Open API section**: Profile -> API Management -> Create API Key
3. **Set permissions**:
   - Futures Trading: Enable
   - Read: Enable
   - IP Whitelist: Recommended (add your server IP)
4. **Note**: API Key, Secret Key, Passphrase

#### Using in Bot Builder

1. Select **Bitunix** as exchange in Bot Builder (Step 1)
2. Enter API Key, Secret, and Passphrase
3. Trading pairs use format `BTCUSDT` (no separator)
4. Symbol conversion happens automatically

#### Affiliate Linking

1. Go to **Settings** -> **Affiliate Links**
2. Enter your Bitunix UID (numeric, e.g. `12345678`)
3. The UID is validated and saved

---

### 3. Setting Up BingX Exchange

BingX is a global crypto exchange with perpetual swap contracts and VST demo mode.

#### Creating API Keys

1. **Create account** at [bingx.com](https://bingx.com)
2. **Open API section**: Account -> API Management -> Create API
3. **Set permissions**:
   - Perpetual Futures: Enable
   - Read: Enable
4. **Note**: API Key and Secret Key (no passphrase needed)

#### Demo Mode (VST)

BingX offers a separate demo trading environment (Virtual Simulated Trading):
- Enable "Demo Mode" in Bot Builder
- The bot automatically connects to the VST domain (`open-api-vst.bingx.com`)
- Perfect for risk-free strategy testing

#### Using in Bot Builder

1. Select **BingX** as exchange in Bot Builder (Step 1)
2. Enter API Key and Secret (no passphrase)
3. Trading pairs use format `BTC-USDT` (with hyphen)
4. Symbol conversion happens automatically

#### Affiliate Linking

1. Go to **Settings** -> **Affiliate Links**
2. Enter your BingX UID (numeric, e.g. `87654321`)
3. The UID is validated and saved
