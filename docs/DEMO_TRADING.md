# Bitget Demo Trading Integration

Diese Anleitung erklärt, wie du den Bot mit dem **Bitget Demo Trading Account** verbindest, um realitätsnahes Paper Trading mit echtem Order-Flow durchzuführen.

## 📋 Inhaltsverzeichnis

1. [Was ist Bitget Demo Trading?](#was-ist-bitget-demo-trading)
2. [Vorteile](#vorteile)
3. [Demo API Keys einrichten](#demo-api-keys-einrichten)
4. [Konfiguration](#konfiguration)
5. [Demo vs. Live Mode](#demo-vs-live-mode)
6. [Discord-Benachrichtigungen](#discord-benachrichtigungen)
7. [Troubleshooting](#troubleshooting)

---

## Was ist Bitget Demo Trading?

Bitget Demo Trading ist ein **separates Konto** mit virtuellem Geld (Paper Money), das:
- Den **echten Bitget Order-Flow** nutzt
- Trades im **Bitget Web-Interface** sichtbar macht
- **Realistische Ausführung** mit echten Marktdaten bietet
- **Keine echten Kosten** verursacht

**Unterschied zu lokalem Demo-Modus:**
| Feature | Lokaler Demo-Modus (alt) | Bitget Demo Trading (neu) |
|---------|--------------------------|---------------------------|
| Order-Platzierung | ❌ Nur simuliert | ✅ Echte API-Calls |
| Im Bitget sichtbar | ❌ Nein | ✅ Ja, im Demo Account |
| Realitätsnähe | ⚠️ Mittel | ✅ Sehr hoch |
| API Keys benötigt | ❌ Nein | ✅ Ja (Demo Keys) |

---

## Vorteile

✅ **Realitätsnahes Testing**: Teste die Strategie mit echten Order-Flows
✅ **Sichtbar im Bitget**: Alle Demo-Trades erscheinen in deinem Bitget Demo Account
✅ **Kein Risiko**: Nur virtuelles Geld, keine echten Verluste möglich
✅ **Volle Integration**: Discord-Benachrichtigungen, Dashboard, Statistiken funktionieren normal
✅ **Easy Switch**: Wechsel zwischen Demo und Live mit einem Parameter

---

## Demo API Keys einrichten

### Schritt 1: Bitget Demo Trading Account aktivieren

1. Gehe zu [Bitget Demo Trading](https://www.bitget.com/demo-trading)
2. Aktiviere den Demo Trading Modus
3. Du erhältst virtuelles Startkapital (z.B. $10,000 USDT)

### Schritt 2: Demo API Keys erstellen

1. Gehe zu **Demo Trading → Account → API Management**
2. Klicke auf **"Create API"** (im Demo-Bereich!)
3. Wähle folgende Berechtigungen:
   - ✅ **Read** - Kontoinformationen lesen
   - ✅ **Trade** - Futures Trading
   - ❌ **Withdraw** - NICHT aktivieren!

4. **Wichtig**: Setze IP-Whitelist (optional aber empfohlen)
5. Notiere die folgenden Werte:
   - **API Key**
   - **API Secret**
   - **Passphrase**

⚠️ **ACHTUNG**: Dies sind **DEMO API Keys**, NICHT deine Live API Keys!

### Schritt 3: Keys in `.env` eintragen

Öffne deine `.env` Datei und füge die Demo API Keys hinzu:

```env
# ============ BITGET DEMO API CREDENTIALS (DEMO TRADING) ============
# Für Paper Trading im Bitget Demo Account
BITGET_DEMO_API_KEY=your_demo_api_key_here
BITGET_DEMO_API_SECRET=your_demo_api_secret_here
BITGET_DEMO_PASSPHRASE=your_demo_passphrase_here
```

**Beispiel** (mit Fake-Werten):
```env
BITGET_DEMO_API_KEY=bg_3a7f9e2c4b8d1a6f
BITGET_DEMO_API_SECRET=A9F2E7B3C5D8E1F4A6B9C2D5E8F1A4B7C0D3E6F9
BITGET_DEMO_PASSPHRASE=MyDemoPass123
```

---

## Konfiguration

### Demo-Modus aktivieren

Setze in deiner `.env`:

```env
# ============ TRADING MODE ============
# true = Demo Trading (Paper Money auf Bitget Demo Account)
# false = Live Trading (Echtes Geld auf Bitget Live Account)
DEMO_MODE=true
```

### Live-Modus aktivieren

Wenn du echtes Geld handeln möchtest:

1. **Erstelle Live API Keys** im normalen Bitget Account
2. Trage sie in die **Live API Credentials** Felder ein:

```env
# ============ BITGET API CREDENTIALS (LIVE TRADING) ============
BITGET_API_KEY=your_live_api_key_here
BITGET_API_SECRET=your_live_api_secret_here
BITGET_PASSPHRASE=your_live_passphrase_here
```

3. Setze `DEMO_MODE=false`

⚠️ **Warnung**: Im Live-Modus werden **echte Trades** mit **echtem Geld** ausgeführt!

---

## Demo vs. Live Mode

### Automatische Credential-Auswahl

Der Bot wählt automatisch die korrekten API Keys basierend auf `DEMO_MODE`:

| DEMO_MODE | Verwendete API Keys | Account | Geld |
|-----------|---------------------|---------|------|
| `true` | `BITGET_DEMO_*` | Bitget Demo Account | Paper Money |
| `false` | `BITGET_API_*` | Bitget Live Account | Echtes Geld |

### Wo werden Trades ausgeführt?

**Demo-Modus (`DEMO_MODE=true`)**:
- ✅ Trades erscheinen in **Bitget Demo Trading Account**
- ✅ Echte Order-Platzierung über Bitget API
- ✅ Virtuelles Geld (kein Risiko)
- ✅ Im Bitget Web-Interface sichtbar unter "Demo Trading"

**Live-Modus (`DEMO_MODE=false`)**:
- ⚠️ Trades erscheinen in **Bitget Live Account**
- ⚠️ Echte Order-Platzierung
- ⚠️ Echtes Geld (Risiko!)
- ⚠️ Im normalen Bitget Trading sichtbar

---

## Discord-Benachrichtigungen

### Mode Labels

Alle Discord-Benachrichtigungen zeigen jetzt den Trading-Modus:

**Demo-Modus**:
```
🧪 DEMO - NEW TRADE OPENED - SHORT BTCUSDT
```

**Live-Modus**:
```
⚡ LIVE - NEW TRADE OPENED - SHORT BTCUSDT
```

### Embed Fields

Das **erste Field** in jeder Benachrichtigung zeigt den Modus:

```
🔸 Mode: DEMO
```

Oder:

```
🔸 Mode: LIVE
```

### Footer

Auch der Footer enthält den Modus:

```
Order ID: DEMO_1234567890 | Mode: DEMO
```

---

## Troubleshooting

### "API Error: Apikey does not exist"

**Ursache**: Die Demo API Keys sind falsch oder nicht gesetzt.

**Lösung**:
1. Prüfe, ob du die Keys aus dem **Demo Trading Bereich** kopiert hast
2. Verifiziere die Keys in `.env`:
   ```bash
   cat .env | grep BITGET_DEMO
   ```
3. Stelle sicher, dass `DEMO_MODE=true` gesetzt ist

### "Trades erscheinen nicht im Bitget Demo Account"

**Ursache**: Möglicherweise wird der falsche Modus verwendet.

**Lösung**:
1. Prüfe `DEMO_MODE` in `.env`:
   ```bash
   cat .env | grep DEMO_MODE
   ```
2. Stelle sicher, dass es `DEMO_MODE=true` ist (nicht `false`)
3. Prüfe die Logs:
   ```bash
   tail -f logs/trading_bot.log | grep "DEMO"
   ```
4. Du solltest sehen: `"BitgetClient initialized in DEMO mode (paper trading)"`

### "Wie switche ich von Demo zu Live?"

**Schritt-für-Schritt**:

1. **Erstelle Live API Keys** im normalen Bitget Account
2. **Trage Live Keys ein** in `.env`:
   ```env
   BITGET_API_KEY=your_live_api_key
   BITGET_API_SECRET=your_live_api_secret
   BITGET_PASSPHRASE=your_live_passphrase
   ```
3. **Wechsle den Modus**:
   ```env
   DEMO_MODE=false
   ```
4. **Starte Bot neu**:
   ```bash
   python main.py
   ```

⚠️ **Warnung**: Stelle sicher, dass du die Strategie ausreichend im Demo-Modus getestet hast!

### "Discord zeigt noch 'DEMO', obwohl ich auf LIVE gewechselt bin"

**Ursache**: Bot wurde nicht neu gestartet.

**Lösung**:
1. Stoppe den Bot (Ctrl+C)
2. Starte neu: `python main.py`
3. Prüfe die Logs: "BitgetClient initialized in LIVE mode (real trading)"

---

## Best Practices

✅ **Teste immer zuerst im Demo-Modus** (1-2 Wochen)
✅ **Überwache die Performance** im Bitget Demo Account
✅ **Verifiziere Discord-Benachrichtigungen** zeigen korrekten Modus
✅ **Separate API Keys** für Demo und Live verwenden
✅ **Nie Withdraw-Permission** aktivieren (weder Demo noch Live!)
✅ **IP-Whitelist** verwenden für zusätzliche Sicherheit

---

## Support

Bei Problemen:
- 📖 [SETUP.md](SETUP.md) - Allgemeine Setup-Anleitung
- 📖 [FAQ.md](FAQ.md) - Häufig gestellte Fragen
- 🐛 [GitHub Issues](https://github.com/yourusername/Bitget-Trading-Bot/issues)
- 📝 Logs prüfen: `logs/trading_bot.log`
