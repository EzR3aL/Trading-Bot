# Hyperliquid: Affiliate Link & Builder Fee genehmigen

---

## Changelog / Aenderungshinweis

### Deutsch

**Stand 2026-03-17 — Hyperliquid Fixes:**

- **Builder-Fee-Berechnung korrigiert:** Die Builder Fee wurde zuvor 10x zu hoch
  berechnet. Das ist seit dem 2026-03-17 behoben — es gilt jetzt die korrekte
  Rate von 0.01% (1 Basispunkt) pro Trade.
- **Referral-Gate verschaerft:** Die Verifizierung prueft jetzt, ob du dich
  ueber **unseren konkret konfigurierten Affiliate-Code** registriert hast.
  Frueher wurde bereits jeder beliebige Referral-Code akzeptiert.
- **Wallet-Wechsel setzt Flags zurueck:** Wenn du deine Hyperliquid-Wallet in
  den Exchange-Einstellungen aenderst, werden beide Approval-Flags (Affiliate +
  Builder Fee) jetzt **automatisch zurueckgesetzt**. Der Genehmigen-Dialog
  erscheint beim naechsten Bot-Start erneut fuer die neue Wallet.

### English

**As of 2026-03-17 — Hyperliquid Fixes:**

- **Builder fee calculation fixed:** The builder fee was previously calculated
  10x too high. This was fixed on 2026-03-17 — the correct rate of 0.01%
  (1 basis point) per trade now applies.
- **Referral gate tightened:** Verification now checks that you registered via
  **our specifically configured affiliate code**. Previously any referral code
  was accepted.
- **Wallet change resets flags:** When you change your Hyperliquid wallet in
  the exchange settings, both approval flags (affiliate + builder fee) are now
  **automatically reset**. The approval dialog will reappear on the next bot
  start for the new wallet.

---

## Uebersicht

Bevor du einen Hyperliquid Bot starten kannst, sind **zwei einmalige Schritte** noetig:

1. **Affiliate Link nutzen** — Registriere dich ueber unseren Referral-Link bei Hyperliquid
2. **Builder Fee genehmigen** — Signiere eine Genehmigung fuer eine kleine Trade-Gebuehr

Beide Schritte sind **einmalig pro Wallet**. Solange du die gleiche Wallet nutzt, musst du sie nicht wiederholen. Wenn du deine Wallet aenderst, werden beide Schritte erneut erforderlich.

---

## Was ist der Affiliate Link?

Der Affiliate Link ist ein Referral-Link, ueber den du dich bei Hyperliquid registrierst. Dadurch erhaeltst du als neuer User einen **4% Rabatt auf Handelsgebuehren** (fuer die ersten $25M Volumen).

**Wichtig:** Ohne Registrierung ueber unseren Affiliate Link kannst du keinen Hyperliquid Bot starten. Die Verifizierung erfolgt automatisch ueber die Hyperliquid API.

## Was ist die Builder Fee?

Die Builder Fee ist eine kleine zusaetzliche Gebuehr (0.01%) auf jeden Trade, der ueber unsere Bots auf Hyperliquid ausgefuehrt wird. Diese Gebuehr geht zu 100% an den Bot-Betreiber und ist **zusaetzlich** zur normalen Hyperliquid-Handelsgebuehr.

Es werden dabei **keine Funds bewegt oder abgezogen** — es handelt sich nur um eine Signatur (Genehmigung).

---

## Voraussetzungen

1. **Hyperliquid-Konto** mit hinterlegten API-Keys im Bot-Dashboard
2. **Browser-Wallet** (MetaMask, Coinbase Wallet, Rainbow, Trust Wallet, oder andere)
   mit deiner **Hyperliquid Main Wallet** importiert
3. Deine Main Wallet ist die Wallet-Adresse, die du als "API Key" (Wallet Address)
   in den Exchange-Einstellungen hinterlegt hast

---

## Schritt-fuer-Schritt Anleitung

### 1. Bot erstellen oder starten

Erstelle einen neuen Bot mit Hyperliquid als Exchange, oder klicke bei einem
bestehenden Hyperliquid-Bot auf **"Start"**.

Es oeffnet sich automatisch das **Genehmigungs-Fenster** mit dem mehrstufigen Prozess.

### 2. Affiliate Link nutzen (Schritt 1 im Fenster)

Du siehst unseren Affiliate Link:
```
https://app.hyperliquid.xyz/join/DEINCODE
```

- Klicke auf den Link — er oeffnet sich in einem neuen Tab
- Registriere dich oder melde dich bei Hyperliquid an
- Kehre zum Bot-Dashboard zurueck
- Klicke auf **"Verifizieren"**

Die Verifizierung prueft automatisch ueber die Hyperliquid API, ob du dich ueber unseren Link registriert hast.

> **Hinweis:** Wenn du bereits ueber unseren Link registriert bist, wird dieser Schritt automatisch uebersprungen.

### 3. Wallet verbinden (Schritt 2)

Klicke auf **"Connect Wallet"** — es oeffnet sich ein Auswahlfenster:

- **Rabby Wallet** (empfohlen — beste UX fuer DeFi)
- **MetaMask** (Browser-Extension)
- **WalletConnect** (QR-Code fuer Mobile Wallets wie Trust, Rainbow, etc.)
- **Coinbase Wallet**
- **Und viele weitere...**

Waehle deine Wallet aus und bestaetige die Verbindung.

> **Wichtig:** Verbinde die gleiche Wallet-Adresse, die du als Hyperliquid
> Main Wallet in den Exchange-Einstellungen hinterlegt hast!

### 4. Builder Fee signieren (Schritt 3)

Nach der Wallet-Verbindung siehst du die Details:
- **Fee**: 0.01% (1 Basispunkt) pro Trade
- **Builder-Adresse**: Die Adresse des Bot-Betreibers

Klicke auf **"Builder Fee genehmigen"**. Deine Wallet oeffnet sich und zeigt
die Signatur-Anfrage. Dies ist eine **EIP-712 Typed Data Signatur** — es werden
keine Transaktionen ausgefuehrt und keine Funds bewegt.

Bestaetige die Signatur in deiner Wallet.

### 5. Fertig! (Schritt 4)

Nach erfolgreicher Signatur siehst du einen gruenen Haken mit **"Builder Fee genehmigt!"**.
Der Bot wird anschliessend **automatisch gestartet**.

---

## Wallet aendern

Wenn du deine Hyperliquid Wallet-Adresse in den Exchange-Einstellungen aenderst, werden beide Genehmigungen (Affiliate + Builder Fee) **automatisch zurueckgesetzt**. Beim naechsten Bot-Start musst du den Prozess fuer die neue Wallet erneut durchlaufen.

---

## Haeufige Probleme

### "Referral-Verifizierung fehlgeschlagen"
Du hast dich nicht ueber unseren Affiliate Link registriert, oder die Registrierung
wurde ueber einen anderen Referral-Code vorgenommen.
- Oeffne den Affiliate Link und registriere dich erneut
- Klicke dann auf "Verifizieren"

### "Connected wallet does not match..."
Du hast eine andere Wallet verbunden als deine Hyperliquid Main Wallet.
Wechsle in deiner Wallet-Extension zur richtigen Adresse.

### "Signature failed"
Die Signatur wurde in der Wallet abgelehnt. Versuche es erneut und bestaetige
die Signatur-Anfrage.

### "Verification failed"
Die Signatur konnte nicht bei Hyperliquid verifiziert werden. Moegliche Ursachen:
- Falsche Wallet-Adresse
- Netzwerkprobleme
Warte einen Moment und versuche es erneut.

### Keine Wallet installiert?
Ohne Browser-Wallet kannst du mobile Wallets nutzen:
Waehle **WalletConnect** und scanne den QR-Code mit deiner Mobile Wallet App
(Trust Wallet, Rainbow, MetaMask Mobile, etc.).

### MetaMask installieren
1. Gehe zu [metamask.io](https://metamask.io/download/)
2. Installiere die Browser-Extension
3. Importiere deine Hyperliquid Wallet mit dem Private Key oder Seed Phrase
4. Kehre zum Bot-Dashboard zurueck und starte den Prozess erneut
