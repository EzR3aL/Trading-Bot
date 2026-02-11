# Hyperliquid Builder Fee genehmigen

## Was ist die Builder Fee?

Die Builder Fee ist eine kleine zusaetzliche Gebuehr (0.01%) auf jeden Trade, der ueber
unsere Bots auf Hyperliquid ausgefuehrt wird. Diese Gebuehr geht zu 100% an den
Bot-Betreiber und ist **zusaetzlich** zur normalen Hyperliquid-Handelsgebuehr.

Du musst diese Gebuehr **einmalig** genehmigen, bevor du einen Hyperliquid Bot starten
kannst. Es werden dabei **keine Funds bewegt oder abgezogen** — es handelt sich nur um
eine Signatur (Genehmigung).

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
bestehenden Hyperliquid-Bot auf "Start".

Wenn die Builder Fee noch nicht genehmigt ist, oeffnet sich automatisch das
**Builder Fee Approval Fenster**.

### 2. Wallet verbinden

Klicke auf **"Connect Wallet"** — es oeffnet sich ein Auswahlfenster mit
allen unterstuetzten Wallets:

- **MetaMask** (Browser-Extension)
- **WalletConnect** (QR-Code fuer Mobile Wallets wie Trust, Rainbow, etc.)
- **Coinbase Wallet**
- **Und viele weitere...**

Waehle deine Wallet aus und bestaetige die Verbindung.

> **Wichtig:** Verbinde die gleiche Wallet-Adresse, die du als Hyperliquid
> Main Wallet in den Exchange-Einstellungen hinterlegt hast!
> Falls die Adressen nicht uebereinstimmen, wird eine Warnung angezeigt.

### 3. Builder Fee signieren

Nach der Wallet-Verbindung siehst du die Details der Builder Fee:
- **Fee**: 0.01% (1 Basispunkt) pro Trade
- **Builder-Adresse**: Die Adresse des Bot-Betreibers

Klicke auf **"Builder Fee genehmigen"**. Deine Wallet oeffnet sich und zeigt
die Signatur-Anfrage. Dies ist eine **EIP-712 Typed Data Signatur** — es werden
keine Transaktionen ausgefuehrt und keine Funds bewegt.

Bestaetige die Signatur in deiner Wallet.

### 4. Bestaetigung

Nach erfolgreicher Signatur wird die Genehmigung automatisch bei Hyperliquid
ueberprueft und in deinem Account gespeichert. Du siehst einen gruenen Haken
mit der Meldung **"Builder Fee genehmigt!"**.

Der Bot wird anschliessend automatisch gestartet.

---

## Haeufige Probleme

### "Connected wallet does not match..."
Du hast eine andere Wallet verbunden als deine Hyperliquid Main Wallet.
Wechsle in deiner Wallet-Extension zur richtigen Adresse.

### "Signature failed"
Die Signatur wurde in der Wallet abgelehnt. Versuche es erneut und bestaetige
die Signatur-Anfrage.

### "Verification failed"
Die Signatur wurde zwar erstellt, konnte aber nicht bei Hyperliquid verifiziert
werden. Moegliche Ursachen:
- Falsche Wallet-Adresse
- Netzwerkprobleme
Warte einen Moment und versuche es erneut.

### Keine Wallet installiert?
Ohne Browser-Wallet kannst du trotzdem mobile Wallets nutzen:
Waehle **WalletConnect** und scanne den QR-Code mit deiner Mobile Wallet App
(Trust Wallet, Rainbow, MetaMask Mobile, etc.).

### MetaMask installieren
1. Gehe zu [metamask.io](https://metamask.io/download/)
2. Installiere die Browser-Extension
3. Importiere deine Hyperliquid Wallet mit dem Private Key oder Seed Phrase
4. Kehre zum Bot-Dashboard zurueck und starte den Genehmigungsprozess erneut
