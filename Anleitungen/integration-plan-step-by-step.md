# Schritt-für-Schritt: Trading-Bot Integration in trading-department.com

## Was ist das Ziel?

Der Trading-Bot ("Edge Bots") soll über die Hauptwebsite trading-department.com erreichbar sein. Ein User loggt sich auf der Hauptseite ein und klickt auf "Trading Bots" — ein neuer Tab öffnet sich und der User ist automatisch eingeloggt im Bot-Dashboard unter `bots.trading-department.com`.

## Wichtigste Regel

**Nichts darf kaputt gehen.** Das ist ein Live-Produkt. Alle Änderungen sind **additiv** — wir fügen Neues hinzu, ohne Bestehendes zu entfernen. Alte Funktionen werden erst entfernt, wenn die neuen nachweislich funktionieren.

---

## Übersicht: 6 Phasen

```
Phase 0: Infrastruktur       → Server vorbereiten (DNS, SSL)
Phase 1: Auth Backend         → Brücke zwischen den zwei Systemen bauen
Phase 2: Auth Frontend        → Benutzeroberfläche für den Login-Flow
Phase 3: Hauptseite anpassen  → Button und Widget auf trading-department.com
Phase 4: CI/CD & Staging      → Test-Umgebung und automatisches Deployment
Phase 5: Claude Automation    → Entwicklungs-Workflow automatisieren
Phase 6: Cleanup              → Aufräumen und Sicherheitsprüfung
```

**Reihenfolge ist wichtig!** Jede Phase baut auf der vorherigen auf. Nicht überspringen.

---

## Phase 0: Infrastruktur (1-2 Tage)

### Was passiert hier?

Der Trading-Bot läuft aktuell unter `trading-department.duckdns.org`. Wir richten eine professionelle Subdomain ein: `bots.trading-department.com`. Das ist wie eine neue Adresse für den gleichen Server.

### Schritt 0.1: DNS-Eintrag bei GoDaddy

**Was ist DNS?** DNS ist wie ein Telefonbuch für das Internet. Es sagt: "Wenn jemand `bots.trading-department.com` eingibt, schicke ihn zum Server mit IP `46.101.130.50`."

**Wer muss das machen?** Die Person, die Zugang zum GoDaddy-Konto hat (dort wurde die Domain `trading-department.com` gekauft).

**Anleitung:**
1. Gehe zu https://dcc.godaddy.com und logge dich ein
2. Klicke auf die Domain `trading-department.com`
3. Gehe zum Tab "DNS" oder "DNS verwalten"
4. Klicke auf "Hinzufügen" / "Add"
5. Fülle aus:
   - **Typ:** `A`
   - **Name:** `bots` (NUR "bots", NICHT "bots.trading-department.com")
   - **Wert:** `46.101.130.50`
   - **TTL:** `600`
6. Klicke "Speichern"

**Wie lange dauert das?** Meist 5-10 Minuten, maximal 48 Stunden.

**Wie teste ich ob es funktioniert?**
```
nslookup bots.trading-department.com
```
Erwartetes Ergebnis: IP `46.101.130.50`

**Risiko:** Keins. Du fügst nur einen neuen Eintrag hinzu. Die bestehende Website (`www.trading-department.com`) wird nicht berührt.

**Was beachten:**
- Den bestehenden DNS-Eintrag für `www` oder `@` NICHT ändern oder löschen
- Nur EINEN neuen Eintrag hinzufügen

---

### Schritt 0.2: Nginx-Konfiguration auf dem Server

**Was ist Nginx?** Nginx ist der "Türsteher" auf dem Server. Er empfängt alle Anfragen und leitet sie an den richtigen Dienst weiter. Aktuell kennt er nur die alte Adresse (`duckdns.org`). Wir sagen ihm, dass er auch die neue Adresse (`bots.trading-department.com`) akzeptieren soll.

**Was passiert genau?** Wir fügen einen zweiten Server-Block in die Nginx-Konfiguration hinzu. Der alte Block bleibt bestehen — so funktioniert beides gleichzeitig.

**Was beachten:**
- Die alte `duckdns.org`-Konfiguration NICHT löschen — sie bleibt als Fallback
- Nach jeder Änderung: `nginx -t` ausführen (testet ob die Konfiguration gültig ist)
- Erst wenn der Test grün ist: `systemctl reload nginx` (lädt die neue Config, KEIN Neustart)

**Risiko:** Niedrig. `nginx -t` prüft die Config bevor sie aktiv wird. Bei einem Fehler passiert nichts.

**Was kann schiefgehen?**
- Tippfehler in der Config → `nginx -t` fängt das ab
- Nginx-Reload schlägt fehl → alte Config bleibt aktiv, keine Downtime

---

### Schritt 0.3: SSL-Zertifikat (HTTPS)

**Was ist SSL?** SSL verschlüsselt die Verbindung zwischen Browser und Server. Ohne SSL zeigt der Browser "Nicht sicher" an. Wir nutzen Let's Encrypt — kostenlose Zertifikate, die alle 90 Tage automatisch erneuert werden.

**Wie?** Auf dem Server:
```bash
sudo certbot --nginx -d bots.trading-department.com
```

Certbot erkennt automatisch den Nginx-Server-Block und konfiguriert SSL.

**Voraussetzung:** Schritt 0.1 muss abgeschlossen sein (DNS muss auf den Server zeigen, sonst schlägt die Verifizierung fehl).

**Was beachten:**
- Der DNS-Eintrag MUSS bereits aktiv sein, sonst schlägt Certbot fehl
- Certbot modifiziert die Nginx-Config automatisch (fügt SSL-Zeilen hinzu)
- Auto-Renewal ist standardmäßig eingerichtet (kein manuelles Erneuern nötig)

**Risiko:** Keins für bestehende Dienste. Certbot fügt nur SSL-Konfiguration für die NEUE Subdomain hinzu.

---

### Schritt 0.4: Testen

```bash
# Vom eigenen Computer aus:
curl -I https://bots.trading-department.com/api/health

# Erwartet:
# HTTP/2 200
# {"status": "healthy", ...}
```

**Wenn es NICHT funktioniert:**
- DNS noch nicht propagiert → Warten (bis zu 48h, meist unter 1h)
- SSL-Fehler → Certbot nochmal ausführen
- 502 Bad Gateway → Nginx-Config prüfen (Proxy-Pass auf localhost:8000?)

**Was NICHT passiert sein darf:**
- Die alte URL (`trading-department.duckdns.org`) darf NICHT aufhören zu funktionieren
- Bestehende User dürfen NICHT ausgesperrt sein
- Kein Container darf gestoppt worden sein

---

## Phase 1: Auth Bridge Backend (3-5 Tage)

### Was passiert hier?

Das ist das Herzstück der Integration. Wir bauen eine "Brücke" zwischen zwei Login-Systemen:
- **Hauptseite:** Supabase Auth (Google Login, Email/Passwort)
- **Trading-Bot:** Eigenes JWT-System (Username/Passwort)

Die Brücke funktioniert so: Die Hauptseite gibt dem User einen "Einmal-Code" (wie ein Zugticket), und der Bot akzeptiert dieses Ticket und lässt den User rein.

### Warum nicht einfach ein Login-System nutzen?

1. **Sicherheit:** Der Bot verwaltet echtes Geld und Exchange-API-Keys. Diese Daten bleiben auf dem Bot-Server und werden nie an Supabase geschickt.
2. **Unabhängigkeit:** Wenn Supabase mal down ist, können Admins sich trotzdem direkt einloggen.
3. **Bestehende User:** Die aktuellen Bot-User behalten ihren Zugang.

---

### Schritt 1.1: Datenbank erweitern

**Was?** Wir fügen der `users`-Tabelle im Bot zwei neue Spalten hinzu:
- `supabase_user_id` — die UUID des Users auf der Hauptseite
- `auth_provider` — ob der User über die Hauptseite kam ("supabase") oder sich direkt registriert hat ("local")

**Wie?** Eine Alembic-Migration (automatisches Datenbank-Update-Skript). Beim nächsten Start des Bot-Containers wird die Migration automatisch ausgeführt.

**Was beachten:**
- Die neuen Spalten sind `nullable` (optional) — bestehende User bekommen einfach `NULL` und funktionieren weiterhin
- Kein User-Datenverlust möglich — wir FÜGEN Spalten HINZU, löschen keine
- Vor der Migration immer ein DB-Backup machen (passiert automatisch durch den Backup-Container)

**Risiko:** Sehr niedrig. `ALTER TABLE ADD COLUMN` ist eine der sichersten Datenbank-Operationen.

---

### Schritt 1.2: Supabase JWT Validation

**Was?** Ein neues Python-Modul, das Supabase-Tokens (Login-Beweise von der Hauptseite) verifizieren kann.

**Wie funktioniert das technisch?**
- Die Hauptseite gibt dem User einen JWT-Token (eine lange verschlüsselte Zeichenkette)
- Dieser Token enthält: Wer der User ist (UUID), Email, wann der Token abläuft
- Der Bot-Server kann mit dem `SUPABASE_JWT_SECRET` (ein gemeinsames Geheimnis) prüfen, ob der Token echt ist
- Das Secret kommt aus dem Supabase-Dashboard: Settings → API → JWT Secret

**Was beachten:**
- Das `SUPABASE_JWT_SECRET` ist GEHEIM und darf nie im Code stehen
- Es wird als Umgebungsvariable auf dem VPS gespeichert (in der `.env`-Datei)
- Dieses Secret ändert sich normalerweise nie — aber wenn Supabase es rotiert, muss es auch auf dem Bot-Server aktualisiert werden

**Risiko:** Keins für bestehende User. Das ist ein neues Modul, das den bestehenden Login nicht berührt.

---

### Schritt 1.3: One-Time Auth Code System

**Was?** Ein System das Einmal-Codes generiert. Wie ein Einlass-Armband bei einem Festival — es gilt nur einmal und läuft nach 60 Sekunden ab.

**Wie funktioniert der Flow?**
```
1. Hauptseite fragt: "Gib mir einen Code für User XYZ"
2. Bot generiert: "Hier ist Code ABC123, gültig für 60 Sekunden"
3. Hauptseite öffnet neuen Tab: bots.trading-department.com/auth/callback?code=ABC123
4. Bot prüft: "Code ABC123 existiert, ist nicht abgelaufen, wurde noch nicht benutzt"
5. Bot gibt dem User einen eigenen Login-Token
6. Code ABC123 wird als "benutzt" markiert und kann nie wieder verwendet werden
```

**Warum so kompliziert? Warum nicht einfach den Supabase-Token direkt verwenden?**
- Einmal-Codes sind sicherer: Sie sind nur 60 Sekunden gültig und funktionieren nur einmal
- Der Bot bleibt unabhängig von Supabase: Wenn Supabase down ist, funktionieren alle bestehenden Bot-Sessions weiter
- Der Bot kann eigene Berechtigungen und Token-Laufzeiten verwalten

**Was beachten:**
- Codes werden im Arbeitsspeicher gespeichert (nicht in der DB) — bei einem Neustart des Bot-Containers gehen offene Codes verloren (kein Problem, sie sind nur 60s gültig)
- Rate Limiting: Max 5 Code-Anfragen pro Minute pro IP (gegen Missbrauch)
- Hintergrund-Task räumt abgelaufene Codes alle 5 Minuten auf

**Risiko:** Keins für bestehende User. Komplett neuer, isolierter Code.

---

### Schritt 1.4: Auto-Provisioning (Automatische User-Erstellung)

**Was?** Wenn ein User von der Hauptseite zum Bot kommt, wird automatisch ein Bot-Account erstellt (falls noch keiner existiert).

**Der Ablauf:**
```
1. User kommt mit Supabase-Token (enthält UUID + Email)
2. Bot sucht: "Kenne ich diese Supabase-UUID?"
   → JA: User einloggen, fertig
   → NEIN: Weiter zu Schritt 3

3. Bot sucht: "Kenne ich diese Email-Adresse?"
   → JA: Bestehenden Account mit der Supabase-UUID verknüpfen, einloggen
   → NEIN: Weiter zu Schritt 4

4. Neuen Bot-Account erstellen:
   - Username aus Email generiert
   - Zufälliges Passwort (User braucht es nicht — Login geht über die Hauptseite)
   - Supabase-UUID wird gespeichert
   - User ist sofort eingeloggt
```

**Was beachten:**
- Email-Verknüpfung (Schritt 3) passiert NUR mit verifizierten Emails
  - Warum? Sonst könnte jemand sich auf der Hauptseite mit einer fremden Email registrieren und den Bot-Account übernehmen
- Bestehende User werden NICHT überschrieben, nur verknüpft
- Das alte Passwort bleibt erhalten

**Risiko:** Niedrig. Unique Constraint auf `supabase_user_id` verhindert doppelte Zuordnung. IntegrityError wird abgefangen.

---

### Schritt 1.5: Umgebungsvariablen auf dem VPS

Folgende Werte müssen in die `.env`-Datei auf dem Server:

```
SUPABASE_JWT_SECRET=<aus Supabase Dashboard → Settings → API → JWT Secret>
SUPABASE_PROJECT_URL=https://khlodzeemynxxfdnxzhg.supabase.co
CORS_ORIGINS=https://www.trading-department.com,https://trading-department.com
```

**Was ist CORS?** CORS bestimmt, welche Websites auf den Bot-API zugreifen dürfen. Aktuell darf nur der Bot-Frontend selbst zugreifen. Wir fügen die Hauptseite hinzu, damit sie den Code-Generierungs-Endpoint aufrufen kann.

**Was beachten:**
- NIEMALS `*` (alle Websites) als CORS-Origin setzen — nur die expliziten Domains
- Die URLs MÜSSEN mit `https://` beginnen
- Nach dem Ändern der `.env`: Container neu starten (`docker compose up -d`)

---

### Wichtig: Dual Auth (beide Login-Wege funktionieren gleichzeitig)

**Das alte Login (`/login` mit Username + Passwort) bleibt VOLLSTÄNDIG erhalten.**

Warum?
- Bestehende User, die noch nicht über die Hauptseite kamen, können sich weiter einloggen
- Admins können sich immer direkt einloggen (Notfall-Zugang)
- Wenn die Auth-Bridge mal nicht funktioniert, ist niemand ausgesperrt
- Wir entfernen das alte Login FRÜHESTENS, wenn alle User erfolgreich verknüpft sind (und selbst dann behalten wir es als Fallback)

---

## Phase 2: Auth Bridge Frontend (2-3 Tage)

### Was passiert hier?

Wir bauen die Benutzeroberfläche für den Login-Flow: Der Button auf der Hauptseite und die "Empfangsseite" im Bot-Frontend.

---

### Schritt 2.1: Supabase Edge Function (auf der Hauptseite)

**Was ist eine Edge Function?** Ein kleines Server-Programm, das auf Supabase läuft. Es ist der Vermittler zwischen Hauptseite und Bot-Server.

**Warum nicht direkt vom Browser zum Bot-Server?** Sicherheit. Die Edge Function hat Zugang zum Supabase-Session und kann sicher mit dem Bot-Server kommunizieren, ohne dass der Token im Browser sichtbar ist.

**Was die Edge Function tut:**
1. Prüft: Ist der User eingeloggt auf der Hauptseite? (Supabase Session)
2. Ruft auf: `POST https://bots.trading-department.com/api/auth/bridge/generate` mit dem Supabase-Token
3. Bekommt zurück: Einen Einmal-Code
4. Gibt den Code an das Hauptseiten-Frontend zurück

**Was beachten:**
- Die Edge Function läuft auf Supabase-Infrastruktur, nicht auf unserem Server
- Sie muss in Repo A (trading-department) erstellt werden, nicht in Repo B (Trading-Bot)

---

### Schritt 2.2: Callback-Seite im Bot-Frontend

**Was?** Eine neue Seite im Bot-Frontend unter `/auth/callback`. Diese Seite ist die "Empfangshalle" für User, die von der Hauptseite kommen.

**Was die Seite tut:**
1. Liest den Code aus der URL (`?code=ABC123`)
2. Schickt den Code an den Bot-Server: `POST /api/auth/bridge/exchange`
3. Bekommt zurück: Einen Bot-Login-Token + User-Daten
4. Speichert den Token (genau wie beim normalen Login)
5. Leitet weiter zum Dashboard

**Was der User sieht:** Einen kurzen Ladebildschirm ("Anmeldung läuft..."), dann das Bot-Dashboard. Der ganze Prozess dauert unter 2 Sekunden.

**Was beachten:**
- Diese Route muss AUSSERHALB des `ProtectedRoute`-Wrappers sein (der User ist ja noch nicht eingeloggt, wenn er ankommt)
- Bei ungültigem Code: Klare Fehlermeldung mit Link zur Hauptseite
- Der Code wird aus der URL entfernt nach erfolgreicher Anmeldung (Sicherheit)

---

### Schritt 2.3: "Trading Bots" Button auf der Hauptseite

**Was?** Der Button auf der Hauptseite, der den ganzen Flow auslöst.

**Technisches Detail — Popup-Blocker vermeiden:**
```
FALSCH (wird geblockt):
  Button klick → API-Call → warte auf Antwort → window.open()

RICHTIG (wird NICHT geblockt):
  Button klick → window.open() sofort (mit Ladeseite) → API-Call → URL im geöffneten Fenster ändern
```

Browser blocken Popups, die nicht direkt durch einen User-Klick ausgelöst werden. Deshalb öffnen wir das Fenster SOFORT beim Klick und ändern die URL erst, wenn der Code bereit ist.

**Was beachten:**
- Das neue Fenster muss SOFORT im Click-Handler geöffnet werden
- Zunächst eine Lade-Animation zeigen, dann die richtige URL laden
- Fehlerfall: Wenn die Code-Generierung fehlschlägt, das Fenster schließen und Toast-Nachricht auf der Hauptseite zeigen

---

### Schritt 2.4: Altes Login behalten

Die bestehende Login-Seite (`/login`) im Bot-Frontend bleibt exakt wie sie ist. Keine Änderung. Kein Hinweis. Kein Redirect. Sie funktioniert weiterhin für alle bestehenden User und Admins.

**Erst in Phase 6** (frühestens 2-4 Wochen nach Go-Live) fügen wir einen Hinweis hinzu: "Bitte über trading-department.com anmelden."

---

## Phase 3: Hauptseite anpassen (2-3 Tage)

### Schritt 3.1: VIP-Gate entfernen

**Was?** Aktuell ist der "Trading Bots"-Bereich nur für Ultimate-Tier User (€79/Monat) sichtbar. Das wird geändert: JEDER registrierte User sieht den Bereich.

**Was beachten:**
- Nur die Zugangsbeschränkung entfernen, nicht die Seite selbst
- In `subscription-tiers.ts` den Eintrag für `tradingBots` von Ultimate auf Free setzen

---

### Schritt 3.2: Bot Status Widget

**Was?** Ein kleines Widget auf dem Dashboard der Hauptseite, das zeigt:
- "Du hast 3 aktive Bots"
- "Gesamt-PnL: +$42.50"
- Button: "Bots verwalten" (öffnet den Bot in neuem Tab)

**Wie kommen die Daten?** Über eine Supabase Edge Function, die den Bot-Server nach den Daten fragt. So muss der Browser des Users nicht direkt mit dem Bot-Server kommunizieren.

**Was beachten:**
- Wenn der Bot-Server nicht erreichbar ist: "Bot-Status nicht verfügbar" anzeigen (NICHT die Seite crashen)
- Daten werden gecacht (nicht bei jedem Seitenaufruf neu laden)
- User ohne Bot-Account sehen: "Starte jetzt deinen ersten Bot"

---

## Phase 4: CI/CD & Staging (3-5 Tage)

### Was ist CI/CD?

**CI (Continuous Integration):** Automatische Tests bei jedem Code-Push. Haben wir bereits.
**CD (Continuous Deployment):** Automatisches Deployment nach bestandenen Tests. Das richten wir ein.

### Schritt 4.1: Staging-Server (Test-Umgebung)

**Was?** Ein zweiter, kleinerer Server ($6/Monat bei DigitalOcean) zum Testen. Hier können wir neue Features ausprobieren, ohne den Live-Server zu gefährden.

**Warum nicht auf dem gleichen Server testen?** Der Live-Server hat nur 2 GB RAM und läuft bereits am Limit. Ein zweiter Bot-Container würde den Server überlasten.

**Setup:**
- Eigene IP-Adresse
- Eigene Subdomain: `staging-bots.trading-department.com`
- Eigene Datenbank (separate PostgreSQL-Instanz im Container)
- Eigenes Supabase-Projekt (Free-Tier, keine Kosten)

**Was beachten:**
- Der Staging-Server hat KEINE echten User-Daten
- Der Staging-Server handelt NICHT mit echtem Geld
- Staging-Umgebung und Live-Umgebung teilen sich NICHTS

---

### Schritt 4.2: Automatisches Deployment

**Was?** Wenn Code auf GitHub gepusht wird und alle Tests bestanden sind, wird der Code automatisch auf dem Server deployed.

**Ablauf:**
```
Push zu "staging" Branch
    → GitHub Actions: Tests laufen
    → Tests bestanden?
        → JA: SSH zum Staging-Server → Pull → Build → Restart → Healthcheck
        → NEIN: Stopp, Entwickler wird benachrichtigt

Push zu "main" Branch
    → GitHub Actions: Tests laufen
    → Tests bestanden?
        → JA: WARTEN auf manuelle Freigabe (ein Mensch muss auf "Approve" klicken)
        → Freigabe erteilt: SSH zum Live-Server → Backup → Pull → Build → Restart → Healthcheck
        → Healthcheck fehlgeschlagen? → AUTOMATISCHER ROLLBACK
```

**Was beachten:**
- Live-Deployment IMMER mit manueller Freigabe (kein automatisches Deployment auf Production!)
- VOR jedem Live-Deployment: Automatisches Datenbank-Backup
- NACH jedem Deployment: Automatischer Healthcheck
- Bei fehlgeschlagenem Healthcheck: Automatischer Rollback auf die vorherige Version

**Downtime beim Deployment:** ~15-30 Sekunden. Während dieser Zeit werden keine neuen Trades ausgeführt. Bestehende Positionen auf den Exchanges sind davon NICHT betroffen (die leben auf der Exchange, nicht auf unserem Server). Nach dem Neustart werden alle Bots automatisch wieder gestartet.

---

## Phase 5: Claude Automation (2-3 Tage)

### Was wird automatisiert?

| Automatisiert | Was |
|---|---|
| PR-Reviews | Claude prüft jeden Pull Request automatisch auf Bugs und Sicherheitslücken |
| Healthchecks | Custom Commands um den Server-Status zu prüfen |
| Test-Enforcement | Hooks die verhindern, dass Code ohne Tests committed wird |

### Was wird NIEMALS automatisiert?

| NICHT automatisiert | Warum |
|---|---|
| Bot Start/Stop | Echtes Geld, menschliche Entscheidung erforderlich |
| API Key Änderungen | Zu sensibel für Automatisierung |
| Fund-Operationen | Finanzoperationen brauchen menschliche Aufsicht |
| Datenbank-Löschungen | Irreversibel, zu riskant |
| Server Rebuild/Löschung | Irreversibel |

---

## Phase 6: Cleanup & Hardening (3-5 Tage)

### Erst nach 2-4 Wochen erfolgreichem Betrieb!

**Schritt 6.1:** Alte DuckDNS-Domain entfernen
- Erst wenn ALLE User die neue Subdomain nutzen
- Monitoring zeigt keine Zugriffe mehr auf die alte URL

**Schritt 6.2:** Hinweis auf der alten Login-Seite
- "Bitte melde dich über trading-department.com an"
- Das alte Login NICHT entfernen — es bleibt als Admin-Zugang

**Schritt 6.3:** Sicherheitsprüfung
- CORS-Konfiguration überprüfen
- Rate Limits testen
- Auth-Flow Penetrationstest

**Schritt 6.4:** Dokumentation
- Alles in `Anleitungen/` dokumentieren (Deutsch + Englisch)
- Notfall-Playbook: Was tun wenn die Auth-Bridge ausfällt?

---

## Checkliste: Vor jedem Schritt prüfen

```
[ ] Backup vorhanden? (DB-Backup, Code committed)
[ ] Laufende Bots weiterhin aktiv? (docker ps)
[ ] API Health OK? (curl .../api/health)
[ ] Alle bestehenden User können sich einloggen?
[ ] Kein Container wurde gestoppt?
[ ] Keine bestehende Config wurde gelöscht?
```

## Notfall-Plan: Was tun wenn etwas schiefgeht?

| Problem | Lösung |
|---|---|
| Neue Subdomain funktioniert nicht | Alte DuckDNS-URL funktioniert weiterhin — User sind nicht betroffen |
| Auth-Bridge liefert Fehler | Altes Login (`/login`) funktioniert weiterhin — alle User können sich einloggen |
| Deployment schlägt fehl | Auto-Rollback auf vorherige Version |
| Server überlastet | Monitoring-Alerts warnen frühzeitig |
| Supabase ist down | Bot läuft unabhängig weiter — nur neue Logins über die Hauptseite sind temporär nicht möglich |

**Grundprinzip: Es gibt IMMER einen Fallback. Kein Single Point of Failure.**

---

## Zeitplan

| Phase | Dauer | Kann parallel? |
|---|---|---|
| Phase 0: DNS + SSL | 1-2 Tage | Nein (muss zuerst) |
| Phase 1: Auth Backend | 3-5 Tage | Nein (braucht Phase 0) |
| Phase 2: Auth Frontend | 2-3 Tage | Teilweise mit Phase 1 |
| Phase 3: Hauptseite | 2-3 Tage | Nein (braucht Phase 2) |
| Phase 4: CI/CD | 3-5 Tage | Ja (unabhängig) |
| Phase 5: Claude Automation | 2-3 Tage | Ja (unabhängig) |
| Phase 6: Cleanup | 3-5 Tage | Erst nach 2-4 Wochen |

**MVP (Phase 0-2): ~2 Wochen** — Auth-Bridge funktioniert
**Vollständig: ~4-6 Wochen** — inkl. CI/CD, Automation, Hardening

---

## Glossar

| Begriff | Erklärung |
|---|---|
| **DNS** | Domain Name System — übersetzt Domainnamen in IP-Adressen |
| **A-Record** | Ein DNS-Eintrag der einen Namen auf eine IP-Adresse zeigt |
| **SSL/TLS** | Verschlüsselung für sichere HTTPS-Verbindungen |
| **Certbot** | Programm das kostenlose SSL-Zertifikate von Let's Encrypt holt |
| **Nginx** | Web-Server der als Reverse-Proxy vor dem Bot-Server sitzt |
| **JWT** | JSON Web Token — ein verschlüsselter "Ausweis" für eingeloggte User |
| **Supabase** | Cloud-Dienst für Datenbank, Authentifizierung und Edge Functions |
| **Edge Function** | Kleines Server-Programm das bei Supabase in der Cloud läuft |
| **CORS** | Cross-Origin Resource Sharing — bestimmt welche Websites auf eine API zugreifen dürfen |
| **One-Time Code** | Einmal-Code der nach 60 Sekunden abläuft und nur einmal benutzt werden kann |
| **Auto-Provisioning** | Automatische Erstellung eines Bot-Accounts beim ersten Besuch |
| **Dual Auth** | Zwei Login-Wege funktionieren gleichzeitig (alt + neu) |
| **CI/CD** | Automatisches Testen (CI) und Deployen (CD) von Code |
| **Staging** | Test-Umgebung die die Live-Umgebung simuliert |
| **Rollback** | Rückgängigmachen eines Deployments zur vorherigen Version |
| **Rate Limiting** | Begrenzung wie oft eine API pro Minute aufgerufen werden darf |
| **Healthcheck** | Automatische Prüfung ob ein Dienst funktioniert |

---

# Step-by-Step: Trading-Bot Integration into trading-department.com

(English version — see German section above for detailed explanations)

## Goal

Make the Trading Bot accessible via `bots.trading-department.com` with seamless SSO login from the main website `trading-department.com`.

## Golden Rule

**Nothing must break.** All changes are additive. Old functionality is only removed after new functionality is proven to work.

## Phases Overview

| Phase | What | Duration | Risk to Users |
|---|---|---|---|
| 0 | DNS + SSL Setup | 1-2 days | None |
| 1 | Auth Bridge Backend | 3-5 days | None (additive) |
| 2 | Auth Bridge Frontend | 2-3 days | None (additive) |
| 3 | Main Site Integration | 2-3 days | None (additive) |
| 4 | CI/CD + Staging | 3-5 days | None |
| 5 | Claude Automation | 2-3 days | None |
| 6 | Cleanup (after 2-4 weeks) | 3-5 days | Minimal |

## Key Safety Principles

1. **Dual Auth:** Both old login and new SSO work simultaneously
2. **Fallback:** If the auth bridge fails, old login still works
3. **No deletion:** Nothing is removed until new systems are proven
4. **Pre-deploy backups:** Database backed up before every deployment
5. **Auto-rollback:** Failed deployments automatically revert
6. **Independent systems:** Bot continues running even if Supabase is down

## Emergency Contacts

| System | Dashboard |
|---|---|
| DigitalOcean VPS | cloud.digitalocean.com |
| Supabase | supabase.com/dashboard |
| GoDaddy DNS | dcc.godaddy.com |
| Vercel | vercel.com/dashboard |
| Grafana Monitoring | trading-department.duckdns.org:3000 |
