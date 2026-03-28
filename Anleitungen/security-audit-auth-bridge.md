# Security Audit: Auth Bridge

## Deutsch

### Datum
28.03.2026

### Gepruefte Komponenten
- Auth Bridge Backend (`/api/auth/bridge/generate` und `/exchange`)
- Supabase JWT-Validierung (JWKS/ES256)
- One-Time-Code System
- Nginx Konfiguration (TLS, Headers, Rate Limiting)
- Edge Function (`generate-bot-code`)
- Frontend AuthCallback und Token-Speicherung

### Ergebnis
10 positive Befunde, 2 kritische, 5 hohe, 7 mittlere, 4 niedrige Schwachstellen gefunden.
Alle kritischen und hohen Schwachstellen wurden sofort behoben.

### Behobene Schwachstellen

| # | Schwere | Problem | Fix |
|---|---------|---------|-----|
| C1 | Kritisch | Rate-Limiting erkannte echte IPs nicht (alle User = 127.0.0.1) | `BEHIND_PROXY=true` in .env gesetzt |
| C2 | Kritisch | Auth Bridge Endpoints hatten kein eigenes Rate-Limit | `@limiter.limit("10/minute")` auf beide Endpoints |
| H1 | Hoch | JWT akzeptierte HS256 obwohl Supabase ES256 nutzt | Nur ES256 als Algorithmus erlaubt |
| H2 | Hoch | JWT pruefte nicht ob Token vom eigenen Supabase-Projekt kommt | `issuer`-Validierung gegen SUPABASE_PROJECT_URL |
| H3 | Hoch | Nginx erlaubte TLS 1.0/1.1 | Nur TLS 1.2+ erlaubt |
| H4 | Hoch | Email-Verknuepfung ohne Pruefung ob Email bestaetigt ist | `email_confirmed_at` Claim wird validiert |
| H5 | Hoch | Nginx zeigte Server-Version | `server_tokens off` aktiviert |
| M3 | Mittel | Edge Function gab interne Fehlerdetails an Client | Generische Fehlermeldung statt error.message |

### Positive Befunde (was bereits gut ist)
- One-Time-Codes: 192 Bit Entropie (unknackbar)
- Codes werden sofort nach Einloesung geloescht (Replay-Schutz)
- Supabase JWT wird bei Code-Exchange nochmals validiert (Defense-in-Depth)
- Refresh Token in httpOnly Cookie (XSS-geschuetzt)
- Content Security Policy und Security Headers vorhanden
- Frontend entfernt Code aus URL nach Exchange
- Swagger/Redoc in Production deaktiviert
- CORS Origin-Validation in Edge Function

### Bekannte akzeptierte Risiken
- **Access Token in localStorage**: Standard-Praxis, CSP schuetzt vor XSS. Alternative (in-memory) wuerde Logout bei Tab-Wechsel bedeuten.
- **User-Provisioning Race Condition**: Bei doppeltem Exchange wird eine DB-Unique-Constraint verletzt → 500 Error. Tritt bei normalem Betrieb nicht auf.
- **Code-Store im Speicher**: Kein Max-Limit, aber bei 192 Bit Entropie und 60s TTL ist Brute-Force unmoeglich. Rate-Limiting schuetzt zusaetzlich.

---

## English

### Date
2026-03-28

### Components Audited
- Auth Bridge Backend (`/api/auth/bridge/generate` and `/exchange`)
- Supabase JWT validation (JWKS/ES256)
- One-time code system
- Nginx configuration (TLS, headers, rate limiting)
- Edge Function (`generate-bot-code`)
- Frontend AuthCallback and token storage

### Result
10 positive findings, 2 critical, 5 high, 7 medium, 4 low vulnerabilities found.
All critical and high vulnerabilities were fixed immediately.

### Fixed Vulnerabilities

| # | Severity | Problem | Fix |
|---|----------|---------|-----|
| C1 | Critical | Rate limiting used proxy IP for all users (127.0.0.1) | Set `BEHIND_PROXY=true` in .env |
| C2 | Critical | Auth bridge endpoints had no application-level rate limit | Added `@limiter.limit("10/minute")` to both endpoints |
| H1 | High | JWT accepted HS256 although Supabase uses ES256 | Only ES256 allowed as algorithm |
| H2 | High | JWT did not verify token was from own Supabase project | Added `issuer` validation against SUPABASE_PROJECT_URL |
| H3 | High | Nginx allowed TLS 1.0/1.1 | Only TLS 1.2+ allowed |
| H4 | High | Email linking without checking if email is verified | `email_confirmed_at` claim is now validated |
| H5 | High | Nginx exposed server version | Enabled `server_tokens off` |
| M3 | Medium | Edge Function returned internal error details to client | Generic error message instead of error.message |

### Positive Findings (already well-implemented)
- One-time codes: 192 bits of entropy (unguessable)
- Codes are immediately deleted after exchange (replay protection)
- Supabase JWT is re-validated during code exchange (defense-in-depth)
- Refresh token in httpOnly cookie (XSS-protected)
- Content Security Policy and security headers in place
- Frontend removes code from URL after exchange
- Swagger/Redoc disabled in production
- CORS origin validation in Edge Function

### Accepted Risks
- **Access token in localStorage**: Standard practice, CSP protects against XSS. In-memory alternative would cause logout on tab switch.
- **User provisioning race condition**: Double exchange triggers DB unique constraint → 500 error. Does not occur under normal operation.
- **In-memory code store**: No max capacity limit, but with 192-bit entropy and 60s TTL, brute force is impossible. Rate limiting provides additional protection.
