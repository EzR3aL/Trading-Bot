# Auth-Key-Rotation (RS256 + Dual-Validate)

## Deutsch

### Was ist neu?

Ab Issue **#256** unterstützt der Bot **zwei Signatur-Verfahren** für JWT-Tokens:

| Verfahren | Wann verwenden | Env-Variablen |
|---|---|---|
| **RS256** (empfohlen) | Produktion, Key-Rotation möglich | `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY` |
| **HS256** (Legacy) | Nur Entwicklung / Rollover-Fenster | `JWT_SECRET_KEY` |

Wenn **beide** Verfahren gesetzt sind, signiert der Server neue Tokens mit RS256, akzeptiert aber bei der Validierung beide. Damit können bestehende HS256-Sessions 14 Tage lang weiterleben, während neue Sessions bereits RS256 nutzen.

### Schritt 1 — Key-Pair erzeugen

```bash
openssl genpkey -algorithm RSA -out jwt_private.pem -pkeyopt rsa_keygen_bits:2048
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem
```

### Schritt 2 — Keys in `.env` eintragen

Die PEM-Dateien haben mehrere Zeilen. Pack sie in Anführungszeichen und ersetze echte Zeilenumbrüche durch `\n`, oder nutze Docker-Secrets.

```bash
JWT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg...\n-----END PRIVATE KEY-----"
JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkq...\n-----END PUBLIC KEY-----"
```

### Schritt 3 — Rollover

14 Tage nachdem RS256 aktiv ist, kann `JWT_SECRET_KEY` entfernt werden. Alle Refresh-Tokens wurden bis dahin einmal rotiert und sind dann RS256.

Zum harten Erzwingen eines Relog aller User: `JWT_SECRET_KEY` sofort entfernen. Bestehende Tokens werden abgelehnt, User müssen neu einloggen.

### Rotation der RS256-Keys

1. Neues Pair erzeugen, in Env-Staging als `JWT_PRIVATE_KEY_NEW` / `JWT_PUBLIC_KEY_NEW` ablegen.
2. Deploy: Server signiert bereits mit neuem Private-Key, akzeptiert aber beide Public-Keys während einer 14-Tage-Periode.
3. Nach 14 Tagen: alten Private-Key entfernen.

### Warum RS256 + 14-Tage-Refresh?

- **Vorher**: HS256 (ein Secret für alles). Kompromittiert = alle Tokens gefälscht. 90 Tage Refresh-Gültigkeit.
- **Jetzt**: Private-Key signiert, Public-Key validiert. Kompromittierter Public-Key erlaubt keine Fälschung. 14 Tage Refresh + Rotation bei jedem Request.

---

## English

### What's new?

From Issue **#256**, the bot supports **two signing algorithms** for JWT tokens:

| Algorithm | When to use | Env variables |
|---|---|---|
| **RS256** (recommended) | Production, key rotation | `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY` |
| **HS256** (legacy) | Development / rollover window | `JWT_SECRET_KEY` |

When **both** are set, the server signs new tokens with RS256 but accepts either on verification. This lets existing HS256 sessions survive for 14 days while new ones already use RS256.

### Step 1 — Generate a key-pair

```bash
openssl genpkey -algorithm RSA -out jwt_private.pem -pkeyopt rsa_keygen_bits:2048
openssl rsa -in jwt_private.pem -pubout -out jwt_public.pem
```

### Step 2 — Add keys to `.env`

PEM files are multi-line. Wrap them in quotes and replace real newlines with `\n`, or use Docker secrets.

```bash
JWT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg...\n-----END PRIVATE KEY-----"
JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkq...\n-----END PUBLIC KEY-----"
```

### Step 3 — Rollover

14 days after RS256 goes live, `JWT_SECRET_KEY` can be removed. By then, all refresh tokens have rotated at least once and are signed with RS256.

To force-log-out all users: remove `JWT_SECRET_KEY` immediately. Existing HS256 tokens will be rejected.

### Rotating the RS256 keys

1. Generate a new pair, stage it as `JWT_PRIVATE_KEY_NEW` / `JWT_PUBLIC_KEY_NEW`.
2. Deploy: server signs with the new private key but accepts both public keys during a 14-day window.
3. After 14 days: remove the old private key.

### Why RS256 + 14-day refresh?

- **Before**: HS256 (one secret for everything). Leaked secret = all tokens forgeable. 90-day refresh expiry.
- **Now**: Private key signs, public key verifies. A leaked public key cannot forge tokens. 14-day refresh + rotation on every request.
