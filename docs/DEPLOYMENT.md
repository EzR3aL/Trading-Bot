# Cloud Deployment Anleitung (DigitalOcean)

Diese Anleitung zeigt dir, wie du den Bitget Trading Bot auf einem DigitalOcean Droplet einrichtest, damit er 24/7 läuft.

**Version:** 1.8.0

---

## Inhaltsverzeichnis

1. [Warum Cloud-Deployment?](#warum-cloud-deployment)
2. [Kosten-Übersicht](#kosten-übersicht)
3. [Voraussetzungen](#voraussetzungen)
4. [Droplet erstellen](#schritt-1-droplet-erstellen)
5. [Server einrichten](#schritt-2-server-einrichten)
6. [Docker installieren](#schritt-3-docker-installieren)
7. [Bot deployen](#schritt-4-bot-deployen)
8. [Auto-Start einrichten](#schritt-5-auto-start-einrichten)
9. [Dashboard mit HTTPS](#schritt-6-dashboard-mit-https)
10. [Firewall konfigurieren](#schritt-7-firewall-konfigurieren)
11. [Monitoring & Backups](#schritt-8-monitoring--backups)
12. [Wartung](#wartung)
13. [Fehlerbehebung](#fehlerbehebung)

---

## Warum Cloud-Deployment?

### Vorteile

**24/7 Verfügbarkeit:**
- Bot läuft kontinuierlich, auch wenn dein Rechner aus ist
- Keine verpassten Trading-Signale
- Kontinuierliches Monitoring von Positionen

**Zuverlässigkeit:**
- 99.99% Uptime bei DigitalOcean
- Automatische Neustarts bei Abstürzen
- Professionelle Infrastruktur

**Sicherheit:**
- Dedicated Server mit Firewall
- SSL/HTTPS für Dashboard
- Regelmäßige Backups
- Isoliert vom lokalen Netzwerk

**Performance:**
- Geringe Latenz zu Bitget-Servern
- Schnelle API-Reaktionszeiten
- Unabhängig von lokaler Internet-Verbindung

---

## Kosten-Übersicht

### DigitalOcean Pricing

| Komponente | Kosten/Monat | Beschreibung |
|------------|--------------|--------------|
| **Droplet (Basic)** | $6.00 | 1 GB RAM, 1 vCPU, 25 GB SSD |
| **Droplet (Empfohlen)** | $12.00 | 2 GB RAM, 1 vCPU, 50 GB SSD |
| **Backups** | +20% | Automatische wöchentliche Backups |
| **Monitoring** | Kostenlos | Integriertes Monitoring |
| **Snapshots** | $0.05/GB/Monat | Optional für manuelle Backups |

**Empfohlene Konfiguration:**
```
Droplet (2 GB):      $12.00/Monat
Backups:              $2.40/Monat
Domain (optional):    $12/Jahr (~$1/Monat)
SSL-Zertifikat:       Kostenlos (Let's Encrypt)
────────────────────────────────────
Gesamt:              ~$15/Monat
```

**Abrechnung:**
- Stündliche Abrechnung ($0.018/Stunde für $12-Droplet)
- Nur für tatsächliche Nutzungszeit
- Maximale Kosten gedeckelt auf Monatspreis

### Alternative Anbieter

| Provider | Produkt | RAM | Preis/Monat | Besonderheit |
|----------|---------|-----|-------------|--------------|
| **Hetzner** | CX11 | 2 GB | €4.51 (~$5) | Günstigster, EU-basiert |
| **Linode** | Nanode 1GB | 1 GB | $5.00 | Ähnlich DigitalOcean |
| **AWS** | t3.micro | 1 GB | $7.50 | 12 Monate Free Tier |
| **Vultr** | Regular | 1 GB | $6.00 | Viele Standorte |

**Unsere Empfehlung:** DigitalOcean für beste Docs + Support oder Hetzner für günstigsten Preis.

---

## Voraussetzungen

### Accounts & Zugänge

- [ ] DigitalOcean Account ([Anmelden](https://www.digitalocean.com/))
- [ ] SSH Key-Pair (oder Erstellung während Setup)
- [ ] Domain (optional, für HTTPS)
- [ ] Bitget API Credentials (siehe [SETUP.md](SETUP.md))
- [ ] Discord Webhook URL

### Lokale Tools

**Benötigt auf deinem Rechner:**
- SSH Client (auf Linux/macOS vorinstalliert, Windows: [PuTTY](https://putty.org/))
- Texteditor (z.B. VS Code, nano, vim)
- Optional: [doctl](https://docs.digitalocean.com/reference/doctl/) (DigitalOcean CLI)

---

## Schritt 1: Droplet erstellen

### 1.1 DigitalOcean anmelden

1. Gehe zu [DigitalOcean](https://www.digitalocean.com/)
2. Erstelle einen Account oder melde dich an
3. Verifiziere deine Email
4. Füge eine Zahlungsmethode hinzu

**Promo-Code (falls verfügbar):**
- Neue Accounts erhalten oft $200 Guthaben für 60 Tage
- Suche nach "DigitalOcean promo code" auf Google

### 1.2 SSH Key erstellen (falls noch nicht vorhanden)

**Auf deinem lokalen Rechner:**

```bash
# SSH Key generieren
ssh-keygen -t ed25519 -C "bitget-trading-bot"

# Pfad: ~/.ssh/id_ed25519 (Enter drücken für Standard)
# Passphrase: Leer lassen oder setzen (empfohlen)

# Public Key anzeigen
cat ~/.ssh/id_ed25519.pub
```

Kopiere die Ausgabe (beginnt mit `ssh-ed25519 ...`).

**Windows (PowerShell):**

```powershell
ssh-keygen -t ed25519 -C "bitget-trading-bot"
type $env:USERPROFILE\.ssh\id_ed25519.pub
```

### 1.3 Droplet erstellen

1. **Gehe zu:** [DigitalOcean Console](https://cloud.digitalocean.com/) → "Create" → "Droplets"

2. **Choose Region:**
   - **Europa:** Frankfurt (fra1) oder Amsterdam (ams3)
   - **USA:** New York (nyc1) oder San Francisco (sfo3)
   - Wähle Region nahe deinem Standort für geringe Latenz

3. **Choose Image:**
   - Distribution: **Ubuntu**
   - Version: **22.04 (LTS) x64** (empfohlen)

4. **Choose Size:**
   - **Basic Plan** (CPU options: Regular)
   - **Empfohlen:** $12/mo - 2 GB RAM / 1 vCPU / 50 GB SSD
   - **Minimum:** $6/mo - 1 GB RAM / 1 vCPU / 25 GB SSD

5. **Add Backups** (optional aber empfohlen):
   - ✅ Enable automated backups (+20% Kosten)

6. **Choose Authentication:**
   - ✅ **SSH Key** (empfohlen und sicher)
   - Klicke "New SSH Key" → Füge deinen Public Key ein
   - Name: `my-laptop` oder ähnlich

7. **Finalize Details:**
   - Quantity: 1 Droplet
   - Hostname: `bitget-trading-bot`
   - Tags: `trading`, `production`
   - Project: Default

8. **Create Droplet** klicken

**Warte ~60 Sekunden** bis Droplet bereit ist. Du erhältst eine IP-Adresse (z.B. `157.245.123.45`).

---

## Schritt 2: Server einrichten

### 2.1 Mit SSH verbinden

```bash
# Ersetze <IP-ADRESSE> mit deiner Droplet-IP
ssh root@<IP-ADRESSE>

# Beispiel:
ssh root@157.245.123.45
```

**Beim ersten Mal:**
- Frage: "Are you sure you want to continue connecting?" → Tippe `yes`
- Authentifizierung erfolgt über deinen SSH Key

**Falls du Passwort-Auth verwendet hast:**
- Passwort wurde per Email geschickt
- **WICHTIG:** Ändere sofort das Root-Passwort: `passwd`

### 2.2 System aktualisieren

```bash
# Paketlisten aktualisieren
apt update

# Alle Pakete upgraden
apt upgrade -y

# Automatische Security-Updates aktivieren
apt install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades
# Wähle "Yes" für automatische Security-Updates
```

### 2.3 Non-Root User erstellen (Security Best Practice)

```bash
# Neuen User erstellen
adduser trading

# Folge den Prompts:
# - Passwort setzen (stark und sicher!)
# - Full Name: Trading Bot (oder leer lassen)
# - Restliche Felder: Enter drücken

# User zu sudo-Gruppe hinzufügen
usermod -aG sudo trading

# SSH-Zugriff für neuen User einrichten
mkdir -p /home/trading/.ssh
cp ~/.ssh/authorized_keys /home/trading/.ssh/
chown -R trading:trading /home/trading/.ssh
chmod 700 /home/trading/.ssh
chmod 600 /home/trading/.ssh/authorized_keys
```

### 2.4 Zu neuem User wechseln

```bash
# Wechsel zu trading user
su - trading

# Teste sudo-Zugriff
sudo whoami
# Sollte "root" ausgeben
```

**Ab jetzt arbeiten wir als `trading` User, nicht mehr als `root`!**

### 2.5 Firewall einrichten (UFW)

```bash
# UFW installieren (meist schon vorhanden)
sudo apt install -y ufw

# Standard-Policies setzen
sudo ufw default deny incoming
sudo ufw default allow outgoing

# SSH erlauben (WICHTIG! Sonst wirst du ausgesperrt)
sudo ufw allow ssh

# Firewall aktivieren
sudo ufw enable

# Status prüfen
sudo ufw status
```

Erwartete Ausgabe:
```
Status: active

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW       Anywhere
22/tcp (v6)                ALLOW       Anywhere (v6)
```

---

## Schritt 3: Docker installieren

### 3.1 Docker installieren

```bash
# Docker's offizielles GPG key hinzufügen
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Docker Repository hinzufügen
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Paketlisten aktualisieren
sudo apt update

# Docker installieren
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 3.2 User zu docker-Gruppe hinzufügen

```bash
# Trading user zu docker-Gruppe hinzufügen
sudo usermod -aG docker trading

# Gruppe aktivieren (oder neu einloggen)
newgrp docker

# Test: Docker ohne sudo ausführen
docker --version
docker compose version
```

Erwartete Ausgabe:
```
Docker version 24.0.7, build afdd53b
Docker Compose version v2.23.0
```

### 3.3 Docker testen

```bash
# Hello-World Container ausführen
docker run hello-world
```

Wenn "Hello from Docker!" erscheint, ist Docker korrekt installiert!

---

## Schritt 4: Bot deployen

### 4.1 Repository klonen

```bash
# Git installieren
sudo apt install -y git

# Ins Home-Verzeichnis wechseln
cd ~

# Repository klonen
git clone https://github.com/yourusername/Bitget-Trading-Bot.git

# Ins Verzeichnis wechseln
cd Bitget-Trading-Bot
```

### 4.2 .env Datei erstellen

```bash
# .env.example kopieren
cp .env.example .env

# Mit nano bearbeiten
nano .env
```

**Wichtig:** Trage deine echten Credentials ein:

```env
# ============ BITGET API CREDENTIALS ============
BITGET_API_KEY=dein_echter_api_key
BITGET_API_SECRET=dein_echter_api_secret
BITGET_PASSPHRASE=deine_echte_passphrase
BITGET_TESTNET=false

# ============ DISCORD CONFIGURATION ============
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# ============ TRADING MODE ============
# Starte erstmal in DEMO MODE!
DEMO_MODE=true

# ============ DASHBOARD SECURITY ============
# API Key generieren für Produktion
DASHBOARD_API_KEY=dein_sicherer_api_key_hier
DASHBOARD_HOST=0.0.0.0  # Wichtig für externen Zugriff
DASHBOARD_PORT=8080
```

**API Key generieren:**

```bash
# Sicheren API-Key generieren
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Kopiere die Ausgabe und füge sie bei `DASHBOARD_API_KEY` ein.

**Speichern:** `Ctrl + O` → Enter → `Ctrl + X`

### 4.3 Docker-Compose anpassen (optional)

Falls du den Dashboard-Port ändern möchtest:

```bash
nano docker-compose.yml
```

Suche nach:
```yaml
ports:
  - "8080:8080"
```

Ändere zu (Beispiel: Port 3000):
```yaml
ports:
  - "3000:8080"
```

### 4.4 Bot starten

```bash
# Container bauen und starten
docker compose up -d

# Logs anzeigen
docker compose logs -f
```

Drücke `Ctrl + C` um Logs zu verlassen (Container läuft weiter).

### 4.5 Status prüfen

```bash
# Laufende Container anzeigen
docker compose ps

# Bot-Logs
docker compose logs bot

# Dashboard-Logs
docker compose logs dashboard
```

Erwartete Ausgabe bei `docker compose ps`:
```
NAME                          STATUS       PORTS
bitget-trading-bot-bot-1      Up 2 minutes
bitget-trading-bot-dashboard-1 Up 2 minutes 0.0.0.0:8080->8080/tcp
```

---

## Schritt 5: Auto-Start einrichten

Docker-Compose startet Container automatisch neu nach Crash, aber nicht nach Server-Reboot. Hierfür richten wir einen systemd-Service ein.

### 5.1 Systemd-Service erstellen

```bash
# Service-Datei erstellen
sudo nano /etc/systemd/system/trading-bot.service
```

Füge folgenden Inhalt ein:

```ini
[Unit]
Description=Bitget Trading Bot
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
User=trading
WorkingDirectory=/home/trading/Bitget-Trading-Bot
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

**Speichern:** `Ctrl + O` → Enter → `Ctrl + X`

### 5.2 Service aktivieren

```bash
# Systemd-Daemon neu laden
sudo systemctl daemon-reload

# Service aktivieren (Auto-Start bei Boot)
sudo systemctl enable trading-bot

# Service testen
sudo systemctl start trading-bot

# Status prüfen
sudo systemctl status trading-bot
```

### 5.3 Reboot-Test

```bash
# Server neu starten
sudo reboot
```

**Warte ~2 Minuten**, dann wieder einloggen:

```bash
ssh trading@<IP-ADRESSE>
```

Prüfe ob Bot automatisch gestartet wurde:

```bash
docker compose ps
```

Sollte zeigen: `STATUS: Up X minutes`

---

## Schritt 6: Dashboard mit HTTPS

Um das Dashboard sicher über das Internet erreichbar zu machen, richten wir HTTPS mit nginx und Let's Encrypt ein.

### 6.1 Voraussetzungen

**Du benötigst eine Domain:**
- Kaufe eine Domain (z.B. bei Namecheap, Google Domains, Cloudflare)
- Erstelle einen A-Record: `trading.deinedomain.com` → `<Droplet-IP>`
- Warte ~10 Minuten bis DNS propagiert ist

**Test ob DNS funktioniert:**

```bash
# Auf deinem lokalen Rechner:
ping trading.deinedomain.com

# Sollte deine Droplet-IP anzeigen
```

### 6.2 Nginx installieren

```bash
# Nginx installieren
sudo apt install -y nginx

# Firewall-Regel für HTTP/HTTPS
sudo ufw allow 'Nginx Full'

# Nginx starten
sudo systemctl start nginx
sudo systemctl enable nginx

# Status prüfen
sudo systemctl status nginx
```

### 6.3 Nginx-Konfiguration erstellen

```bash
# Alte Default-Config deaktivieren
sudo rm /etc/nginx/sites-enabled/default

# Neue Config erstellen
sudo nano /etc/nginx/sites-available/trading-bot
```

Füge folgenden Inhalt ein (ersetze `trading.deinedomain.com`):

```nginx
server {
    listen 80;
    server_name trading.deinedomain.com;

    # Temporäre Weiterleitung zu localhost:8080
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }

    # Rate Limiting für API-Endpunkte
    location /api/ {
        limit_req zone=api_limit burst=10 nodelay;
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**Speichern:** `Ctrl + O` → Enter → `Ctrl + X`

### 6.4 Rate Limiting konfigurieren

```bash
# Haupt-Config bearbeiten
sudo nano /etc/nginx/nginx.conf
```

Füge im `http`-Block hinzu (vor den `server`-Blöcken):

```nginx
http {
    # ... existierende Config ...

    # Rate Limiting Zone (10 MB Speicher, ~160k IPs)
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

    # ... restliche Config ...
}
```

### 6.5 Config aktivieren und testen

```bash
# Symlink erstellen
sudo ln -s /etc/nginx/sites-available/trading-bot /etc/nginx/sites-enabled/

# Config-Syntax testen
sudo nginx -t

# Nginx neu laden
sudo systemctl reload nginx
```

**Test im Browser:**
- Öffne `http://trading.deinedomain.com`
- Dashboard sollte erscheinen

### 6.6 SSL mit Let's Encrypt

```bash
# Certbot installieren
sudo apt install -y certbot python3-certbot-nginx

# SSL-Zertifikat erhalten (automatische nginx-Konfiguration)
sudo certbot --nginx -d trading.deinedomain.com

# Folge den Prompts:
# - Email-Adresse eingeben
# - Terms of Service: Yes
# - Email-Updates: Optional
# - HTTP zu HTTPS redirect: 2 (Redirect)
```

Certbot ändert automatisch die nginx-Config für HTTPS!

### 6.7 Auto-Renewal testen

```bash
# Test ob Auto-Renewal funktioniert
sudo certbot renew --dry-run

# Sollte "Congratulations, all renewals succeeded" zeigen
```

Certbot richtet automatisch einen Cronjob ein, der alle 12 Stunden prüft und Zertifikate erneuert.

**Dashboard ist jetzt erreichbar unter:** `https://trading.deinedomain.com`

---

## Schritt 7: Firewall konfigurieren

### 7.1 UFW-Regeln anpassen

```bash
# HTTP erlauben (für Let's Encrypt Challenges)
sudo ufw allow 80/tcp

# HTTPS erlauben (für Dashboard)
sudo ufw allow 443/tcp

# Port 8080 BLOCKIEREN (nur nginx soll zugreifen)
# Bereits standardmäßig blockiert durch "default deny incoming"

# Status prüfen
sudo ufw status numbered
```

Erwartete Regeln:
```
Status: active

     To                         Action      From
     --                         ------      ----
[ 1] 22/tcp                     ALLOW IN    Anywhere
[ 2] Nginx Full                 ALLOW IN    Anywhere
[ 3] 22/tcp (v6)                ALLOW IN    Anywhere (v6)
[ 4] Nginx Full (v6)            ALLOW IN    Anywhere (v6)
```

### 7.2 SSH härten (optional aber empfohlen)

```bash
# SSH-Config bearbeiten
sudo nano /etc/ssh/sshd_config
```

Ändere/Aktiviere folgende Zeilen:

```
# Root-Login verbieten (wir nutzen ja 'trading' user)
PermitRootLogin no

# Passwort-Auth deaktivieren (nur SSH Keys)
PasswordAuthentication no

# Challenge-Response Auth deaktivieren
ChallengeResponseAuthentication no

# Nur spezifische User erlauben
AllowUsers trading
```

**Speichern und SSH neu starten:**

```bash
sudo systemctl restart ssh
```

**WICHTIG:** Behalte eine SSH-Session offen und teste Login in einem neuen Terminal, bevor du die alte Session schließt!

### 7.3 Fail2Ban installieren (Brute-Force Schutz)

```bash
# Fail2Ban installieren
sudo apt install -y fail2ban

# Config erstellen
sudo nano /etc/fail2ban/jail.local
```

Füge ein:

```ini
[DEFAULT]
bantime = 1h
findtime = 10m
maxretry = 5

[sshd]
enabled = true
port = 22
logpath = /var/log/auth.log
```

**Starten:**

```bash
sudo systemctl enable fail2ban
sudo systemctl start fail2ban

# Status
sudo fail2ban-client status sshd
```

---

## Schritt 8: Monitoring & Backups

### 8.1 DigitalOcean Monitoring aktivieren

1. Gehe zu [DigitalOcean Console](https://cloud.digitalocean.com/)
2. Wähle dein Droplet
3. Klicke auf "Monitoring" Tab
4. Aktiviere "Enable Monitoring Agent"

Oder via SSH:

```bash
# Monitoring Agent installieren
curl -sSL https://repos.insights.digitalocean.com/install.sh | sudo bash
```

**Verfügbare Metriken:**
- CPU-Auslastung
- RAM-Nutzung
- Disk I/O
- Netzwerk-Traffic

### 8.2 Alerts einrichten

1. Console → Droplet → Monitoring → Create Alert Policy
2. Beispiel-Alerts:
   - **CPU > 80%** für 5 Minuten
   - **RAM > 90%** für 5 Minuten
   - **Disk > 85%** used
3. Notification: Email oder Slack

### 8.3 Log-Rotation

```bash
# Logrotate-Config erstellen
sudo nano /etc/logrotate.d/trading-bot
```

Füge ein:

```
/home/trading/Bitget-Trading-Bot/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    missingok
    create 0640 trading trading
}
```

**Test:**

```bash
sudo logrotate -f /etc/logrotate.d/trading-bot
```

### 8.4 Automatische Backups

**DigitalOcean Backups (empfohlen):**
- Gehe zu Console → Droplet → Backups
- Enable Backups (+20% Kosten)
- Wöchentliche automatische Backups
- 4 neueste Backups werden behalten

**Manuelle Snapshots:**

```bash
# Via doctl CLI
doctl compute droplet snapshot <DROPLET_ID> --snapshot-name "manual-backup-$(date +%F)"
```

**Datenbank-Backup (SQLite):**

```bash
# Backup-Script erstellen
nano ~/backup-trades.sh
```

Füge ein:

```bash
#!/bin/bash
BACKUP_DIR="$HOME/backups"
DB_PATH="$HOME/Bitget-Trading-Bot/data/trades.db"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# SQLite Backup
sqlite3 $DB_PATH ".backup '$BACKUP_DIR/trades_$DATE.db'"

# Alte Backups löschen (älter als 30 Tage)
find $BACKUP_DIR -name "trades_*.db" -mtime +30 -delete

echo "Backup erstellt: trades_$DATE.db"
```

**Ausführbar machen und Cronjob einrichten:**

```bash
chmod +x ~/backup-trades.sh

# Cronjob hinzufügen (täglich um 3 Uhr nachts)
crontab -e
```

Füge hinzu:

```
0 3 * * * /home/trading/backup-trades.sh >> /home/trading/backup.log 2>&1
```

### 8.5 Discord-Benachrichtigungen überwachen

Der Bot sendet bereits Discord-Notifications. Erstelle zusätzliche Alerts:

**Bot-Status-Check (Heartbeat):**

```bash
# Heartbeat-Script erstellen
nano ~/check-bot-status.sh
```

Füge ein:

```bash
#!/bin/bash
WEBHOOK_URL="https://discord.com/api/webhooks/..." # Deine Webhook URL

# Prüfe ob Bot-Container läuft
if ! docker compose -f /home/trading/Bitget-Trading-Bot/docker-compose.yml ps | grep -q "Up"; then
    # Sende Alert an Discord
    curl -H "Content-Type: application/json" \
         -X POST \
         -d "{\"content\":\"🚨 **ALERT:** Trading Bot ist gestoppt! $(date)\"}" \
         $WEBHOOK_URL
fi
```

**Cronjob (alle 5 Minuten):**

```bash
chmod +x ~/check-bot-status.sh
crontab -e
```

Füge hinzu:

```
*/5 * * * * /home/trading/check-bot-status.sh
```

---

## Wartung

### Updates installieren

```bash
# Ins Bot-Verzeichnis
cd ~/Bitget-Trading-Bot

# Neueste Änderungen pullen
git pull origin main

# Container neu bauen und starten
docker compose down
docker compose up -d --build

# Logs prüfen
docker compose logs -f
```

### Bot neu starten

```bash
cd ~/Bitget-Trading-Bot

# Container stoppen und starten
docker compose restart

# Oder komplett neu bauen
docker compose down
docker compose up -d --build
```

### Logs einsehen

```bash
# Echtzeit-Logs (alle Container)
docker compose logs -f

# Nur Bot-Logs
docker compose logs -f bot

# Nur Dashboard-Logs
docker compose logs -f dashboard

# Letzte 100 Zeilen
docker compose logs --tail=100

# Logs einer bestimmten Zeitspanne
docker compose logs --since 30m
```

### Disk Space prüfen

```bash
# Gesamte Disk-Nutzung
df -h

# Docker-Nutzung
docker system df

# Alte Docker-Images aufräumen
docker system prune -a
```

### Performance-Metriken

```bash
# Container-Ressourcen anzeigen
docker stats

# Nur Trading-Bot
docker stats bitget-trading-bot-bot-1
```

### Database-Wartung

```bash
# Ins Container einsteigen
docker compose exec bot bash

# SQLite-Datenbank optimieren
sqlite3 data/trades.db "VACUUM;"

# Anzahl Trades anzeigen
sqlite3 data/trades.db "SELECT COUNT(*) FROM trades;"

# Exit
exit
```

---

## Fehlerbehebung

### Bot startet nicht

**Problem:** Container startet nicht oder crasht sofort.

**Lösung:**

```bash
# Logs prüfen
docker compose logs bot

# Häufige Ursachen:
# 1. Fehlende .env Datei
ls -la .env

# 2. Ungültige API Credentials
cat .env | grep BITGET

# 3. Port bereits belegt
sudo lsof -i :8080

# Container komplett neu bauen
docker compose down
docker compose up -d --build
```

### Dashboard nicht erreichbar

**Problem:** `https://trading.deinedomain.com` zeigt Fehler.

**Lösung:**

```bash
# Nginx-Status prüfen
sudo systemctl status nginx

# Nginx-Logs
sudo tail -f /var/log/nginx/error.log

# Dashboard läuft?
docker compose ps dashboard

# Port 8080 offen?
sudo netstat -tlnp | grep 8080

# Nginx-Config testen
sudo nginx -t

# Nginx neu laden
sudo systemctl reload nginx
```

### SSL-Zertifikat abgelaufen

**Problem:** Browser zeigt "Certificate expired" Warnung.

**Lösung:**

```bash
# Manuelle Erneuerung
sudo certbot renew

# Nginx neu laden
sudo systemctl reload nginx

# Auto-Renewal testen
sudo certbot renew --dry-run
```

### Hohe CPU-Auslastung

**Problem:** Droplet langsam, CPU bei 100%.

**Lösung:**

```bash
# Top-Prozesse anzeigen
htop

# Docker-Container-Stats
docker stats

# Logs auf Loops prüfen
docker compose logs --tail=200 bot | grep ERROR

# Falls nötig: Bot neu starten
docker compose restart bot
```

### Disk Space voll

**Problem:** Droplet hat keinen freien Speicher mehr.

**Lösung:**

```bash
# Größte Verzeichnisse finden
du -h --max-depth=1 /home/trading | sort -h

# Docker-Images aufräumen
docker system prune -a

# Alte Logs löschen
find ~/Bitget-Trading-Bot/logs -name "*.log" -mtime +30 -delete

# Alte Backups löschen
find ~/backups -name "*.db" -mtime +30 -delete
```

### SSH-Zugriff verloren

**Problem:** Kannst dich nicht mehr per SSH einloggen.

**Lösung:**

1. Gehe zu [DigitalOcean Console](https://cloud.digitalocean.com/)
2. Wähle dein Droplet
3. Klicke auf "Access" → "Launch Droplet Console"
4. Logge dich mit Username `trading` und Passwort ein
5. Prüfe SSH-Config: `sudo nano /etc/ssh/sshd_config`
6. Prüfe Firewall: `sudo ufw status`
7. Restart SSH: `sudo systemctl restart ssh`

### Bot macht keine Trades

**Problem:** Bot läuft, aber führt keine Trades aus.

**Lösung:**

```bash
# Logs prüfen
docker compose logs bot | grep -i trade

# Mögliche Ursachen:

# 1. DEMO_MODE aktiv?
cat .env | grep DEMO_MODE
# Sollte 'false' sein für echte Trades

# 2. Daily Limit erreicht?
# Check Dashboard: http://trading.deinedomain.com

# 3. Keine Signale?
docker compose logs bot | grep -i confidence
# Confidence muss über Minimum sein

# 4. API Credentials ungültig?
docker compose logs bot | grep -i "api\|auth"
```

---

## Zusammenfassung

### Checkliste: Deployment abgeschlossen

- [ ] Droplet erstellt und konfiguriert
- [ ] Non-root User `trading` eingerichtet
- [ ] Firewall (UFW) aktiv und konfiguriert
- [ ] Docker und Docker-Compose installiert
- [ ] Repository geklont und `.env` konfiguriert
- [ ] Bot-Container laufen (`docker compose ps`)
- [ ] Systemd-Service aktiviert (Auto-Start)
- [ ] Domain konfiguriert (DNS A-Record)
- [ ] Nginx installiert und konfiguriert
- [ ] SSL-Zertifikat von Let's Encrypt installiert
- [ ] Dashboard erreichbar via HTTPS
- [ ] Monitoring aktiviert (DigitalOcean + Discord)
- [ ] Backups eingerichtet (automatisch + manuell)
- [ ] Fail2Ban aktiv (Brute-Force Schutz)
- [ ] Log-Rotation konfiguriert

### Wichtige Befehle (Schnellreferenz)

```bash
# Bot-Status
docker compose ps

# Logs anzeigen
docker compose logs -f

# Bot neu starten
docker compose restart

# Updates installieren
git pull && docker compose up -d --build

# Systemd-Service-Status
sudo systemctl status trading-bot

# Nginx neu laden
sudo systemctl reload nginx

# SSL erneuern
sudo certbot renew

# Backups prüfen
ls -lh ~/backups/
```

### Nächste Schritte

1. **Teste im DEMO_MODE** für mindestens 1-2 Wochen
2. **Überwache Discord-Nachrichten** täglich
3. **Prüfe Dashboard** regelmäßig (Performance, Equity Curve)
4. **Erstelle manuelle Backups** vor größeren Änderungen
5. **Upgrade Droplet** falls nötig (bei hoher Last)

---

## Support & Ressourcen

**Dokumentation:**
- [SETUP.md](SETUP.md) - Lokale Installation
- [FAQ.md](FAQ.md) - Häufige Fragen
- [API.md](API.md) - API-Dokumentation
- [STRATEGY.md](STRATEGY.md) - Trading-Strategie

**DigitalOcean:**
- [Community Tutorials](https://www.digitalocean.com/community/tutorials)
- [Support Tickets](https://cloud.digitalocean.com/support/tickets)

**Docker:**
- [Docker Docs](https://docs.docker.com/)
- [Docker-Compose Docs](https://docs.docker.com/compose/)

**Let's Encrypt:**
- [Certbot Docs](https://certbot.eff.org/)
- [Renewal Troubleshooting](https://certbot.eff.org/docs/using.html#renewal)

---

**Version:** 1.8.0 | **Letzte Aktualisierung:** 2026-01-31
