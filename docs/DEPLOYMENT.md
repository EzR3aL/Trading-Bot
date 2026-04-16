# Cloud Deployment Anleitung

> **Letzte Aktualisierung:** 2026-04-16 (v4.14.x)

Diese Anleitung zeigt dir, wie du den Trading Bot auf einem VPS (z.B. DigitalOcean, Hetzner) einrichtest, damit er 24/7 laeuft.

---

## Inhaltsverzeichnis

1. [Warum Cloud-Deployment?](#warum-cloud-deployment)
2. [Kosten-Uebersicht](#kosten-uebersicht)
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

## Architektur (v4.x)

```
                    Internet
                       |
                   [Nginx :443]
                    SSL/HTTPS
                       |
              [FastAPI Backend :8000]
              /        |        \
         [React UI]  [REST API]  [PostgreSQL :5432]
              |        |
         [Recharts]  [JWT Auth]
              
    [Prometheus :9090] → [Alertmanager :9093]
              |
    [Grafana :3000]        [pg-backup]
```

**Docker Compose Services (6 Container):**
- **trading-bot** (Port 8000): FastAPI Backend + React Frontend (kompiliert beim Build)
- **postgres** (Port 5432): PostgreSQL 16 Datenbank (Trades, User, Configs)
- **prometheus** (Port 9090): Metriken-Sammlung
- **alertmanager** (Port 9093): Alert-Routing (Discord, etc.)
- **grafana** (Port 3000): Dashboards und Visualisierung
- **pg-backup**: Automatisches taegliches PostgreSQL-Backup (7 Tage Retention)

---

## Warum Cloud-Deployment?

### Vorteile

**24/7 Verfuegbarkeit:**
- Bot laeuft kontinuierlich, auch wenn dein Rechner aus ist
- Keine verpassten Trading-Signale
- Kontinuierliches Monitoring von Positionen

**Zuverlaessigkeit:**
- 99.99% Uptime bei DigitalOcean
- Automatische Neustarts bei Abstuerzen
- Professionelle Infrastruktur

**Sicherheit:**
- Dedicated Server mit Firewall
- SSL/HTTPS fuer Dashboard
- Regelmaessige Backups
- Isoliert vom lokalen Netzwerk

---

## Kosten-Uebersicht

| Komponente | Kosten/Monat | Beschreibung |
|------------|--------------|--------------|
| **Droplet (Basic)** | $6.00 | 1 GB RAM, 1 vCPU, 25 GB SSD |
| **Droplet (Empfohlen)** | $12.00 | 2 GB RAM, 1 vCPU, 50 GB SSD |
| **Backups** | +20% | Automatische woechentliche Backups |
| **Domain (optional)** | ~$1/Monat | Fuer HTTPS-Zugang |

**Empfohlen:** ~$15/Monat (2 GB Droplet + Backups)

---

## Voraussetzungen

- [ ] VPS Account (DigitalOcean, Hetzner, etc.)
- [ ] SSH Key-Pair
- [ ] Domain (optional, fuer HTTPS)
- [ ] Exchange API Credentials (Bitget, Weex, Hyperliquid, Bitunix oder BingX)
- [ ] Discord Webhook URL (optional)

---

## Schritt 1: Droplet erstellen

1. Gehe zu [DigitalOcean Console](https://cloud.digitalocean.com/) → "Create" → "Droplets"

2. **Region:** Frankfurt (fra1) oder Amsterdam (ams3)

3. **Image:** Ubuntu 22.04 (LTS) x64

4. **Size:** $12/mo - 2 GB RAM / 1 vCPU / 50 GB SSD (empfohlen)

5. **Authentication:** SSH Key (empfohlen)

6. **Hostname:** `trading-bot`

7. **Create Droplet** klicken

---

## Schritt 2: Server einrichten

### 2.1 Mit SSH verbinden

```bash
ssh root@<IP-ADRESSE>
```

### 2.2 System aktualisieren

```bash
apt update && apt upgrade -y
apt install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades
```

### 2.3 Non-Root User erstellen

```bash
adduser trading
usermod -aG sudo trading

mkdir -p /home/trading/.ssh
cp ~/.ssh/authorized_keys /home/trading/.ssh/
chown -R trading:trading /home/trading/.ssh
chmod 700 /home/trading/.ssh
chmod 600 /home/trading/.ssh/authorized_keys
```

### 2.4 Zu neuem User wechseln

```bash
su - trading
sudo whoami  # Sollte "root" ausgeben
```

**Ab jetzt arbeiten wir als `trading` User!**

### 2.5 Firewall einrichten

```bash
sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw enable
```

---

## Schritt 3: Docker installieren

```bash
# Docker's GPG key und Repository
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# User zu docker-Gruppe
sudo usermod -aG docker trading
newgrp docker

# Test
docker --version
docker compose version
```

---

## Schritt 4: Bot deployen

### 4.1 Repository klonen

```bash
cd ~
git clone <REPO_URL> Trading-Bot
cd Trading-Bot
```

### 4.2 .env Datei erstellen

```bash
cp .env.example .env
nano .env
```

**Wichtige Werte setzen:**

```env
# Sicherheit (MUSS gesetzt werden!)
JWT_SECRET_KEY=<generiere mit: python3 -c "import secrets; print(secrets.token_urlsafe(64))">

# PostgreSQL (MUSS in Production geaendert werden!)
POSTGRES_PASSWORD=<sicheres_passwort>

# Grafana (MUSS in Production geaendert werden!)
GF_ADMIN_PASSWORD=<sicheres_passwort>

# Umgebung
ENVIRONMENT=production
LOG_LEVEL=INFO
```

**Wichtig:** Die App verweigert den Start mit Standard-Passwoertern wenn `ENVIRONMENT=production` gesetzt ist.

**Hinweis:** Exchange API-Keys, Discord-Webhook und Credentials werden ueber die Web-Oberflaeche konfiguriert (Settings-Seite), nicht ueber die .env Datei. Die `ENCRYPTION_KEY` wird beim ersten Start automatisch generiert.

### 4.3 Admin-User erstellen

```bash
# Einmalig: Docker-Image bauen
docker compose build

# Admin-User erstellen (interaktiv im Container)
docker compose run --rm trading-bot python main.py --create-admin --username admin --password <DEIN_PASSWORT>
```

### 4.4 Bot starten

```bash
docker compose up -d
docker compose logs -f
```

### 4.5 Status pruefen

```bash
docker compose ps

# Erwartete Ausgabe (6 Container):
# NAME                       STATUS       PORTS
# bitget-trading-bot         Up 2 min     127.0.0.1:8000->8000/tcp
# tradingbot-postgres        Up 2 min     127.0.0.1:5432->5432/tcp
# tradingbot-prometheus      Up 1 min     127.0.0.1:9090->9090/tcp
# tradingbot-alertmanager    Up 1 min     127.0.0.1:9093->9093/tcp
# tradingbot-grafana         Up 1 min     127.0.0.1:3000->3000/tcp
# tradingbot-pg-backup       Up 1 min
```

### 4.6 Web-UI einrichten

1. Oeffne `http://<IP>:8000` (temporaer, spaeter via HTTPS)
2. Logge dich mit dem Admin-User ein
3. Gehe zu **Settings**:
   - Trage Exchange API-Keys ein (Bitget, Weex, Hyperliquid, Bitunix oder BingX)
   - Trage Discord/Telegram Webhook URL ein (optional)
4. Gehe zu **Bot Control**:
   - Erstelle einen neuen Bot (Exchange, Strategie, Parameter)
   - Starte den Bot

---

## Schritt 5: Auto-Start einrichten

```bash
sudo nano /etc/systemd/system/trading-bot.service
```

```ini
[Unit]
Description=Trading Bot
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
User=trading
WorkingDirectory=/home/trading/Trading-Bot
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-bot
sudo systemctl start trading-bot
```

---

## Schritt 6: Dashboard mit HTTPS

### 6.1 Domain konfigurieren

Erstelle einen A-Record: `trading.deinedomain.com` → `<Droplet-IP>`

### 6.2 Nginx installieren

```bash
sudo apt install -y nginx
sudo ufw allow 'Nginx Full'
sudo systemctl enable nginx
```

### 6.3 Nginx-Konfiguration

```bash
sudo rm /etc/nginx/sites-enabled/default
sudo nano /etc/nginx/sites-available/trading-bot
```

```nginx
server {
    listen 80;
    server_name trading.deinedomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/trading-bot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 6.4 SSL mit Let's Encrypt

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d trading.deinedomain.com
sudo certbot renew --dry-run
```

**Dashboard erreichbar unter:** `https://trading.deinedomain.com`

---

## Schritt 7: Firewall konfigurieren

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw status numbered
```

### SSH haerten (empfohlen)

```bash
sudo nano /etc/ssh/sshd_config
```

```
PermitRootLogin no
PasswordAuthentication no
AllowUsers trading
```

```bash
sudo systemctl restart ssh
```

### Fail2Ban

```bash
sudo apt install -y fail2ban
sudo nano /etc/fail2ban/jail.local
```

```ini
[DEFAULT]
bantime = 1h
findtime = 10m
maxretry = 5

[sshd]
enabled = true
```

```bash
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

---

## Schritt 8: Monitoring & Backups

### Datenbank-Backup

Das PostgreSQL-Backup wird automatisch vom `pg-backup` Container durchgefuehrt:
- **Frequenz:** Alle 24 Stunden
- **Retention:** 7 Tage (aeltere Dumps werden geloescht)
- **Speicherort:** `./backups/tradingbot_YYYYMMDD_HHMMSS.dump`
- **Format:** pg_dump custom format (komprimiert)

```bash
# Backup-Status pruefen
docker compose logs pg-backup --tail=5

# Manuelles Backup
docker compose exec postgres pg_dump -U tradingbot -Fc tradingbot > backups/manual_$(date +%Y%m%d).dump

# Restore
docker compose exec -T postgres pg_restore -U tradingbot -d tradingbot < backups/tradingbot_YYYYMMDD.dump
```

Fuer Off-Host-Backups (z.B. auf S3/Object Storage) siehe `deploy/backup-offhost.sh`.

### Bot-Status Heartbeat

```bash
nano ~/check-bot-status.sh
```

```bash
#!/bin/bash
WEBHOOK_URL="https://discord.com/api/webhooks/..."

if ! curl -sf http://localhost:8000/api/health 2>&1 | grep -q '"status":"healthy"'; then
    curl -H "Content-Type: application/json" \
         -X POST \
         -d "{\"content\":\"ALERT: Trading Bot ist nicht erreichbar! $(date)\"}" \
         $WEBHOOK_URL
fi
```

```bash
chmod +x ~/check-bot-status.sh

# Cronjob (alle 5 Minuten)
crontab -e
# */5 * * * * /home/trading/check-bot-status.sh
```

---

## Wartung

### Updates installieren

```bash
cd ~/Trading-Bot
git pull origin main
docker compose down
docker compose up -d --build --no-cache
docker compose logs -f
```

**Hinweis:** Bei Frontend-Aenderungen immer `--no-cache` verwenden, damit das React-Frontend neu kompiliert wird.

### Logs einsehen

```bash
docker compose logs -f                    # Alle Logs
docker compose logs --tail=100            # Letzte 100 Zeilen
docker compose logs --since 30m           # Letzte 30 Minuten
```

### Docker aufraeumen

```bash
docker system prune -a                    # Alte Images entfernen
docker stats                              # Container-Ressourcen
```

### Datenbank optimieren

```bash
docker compose exec postgres psql -U tradingbot -c "VACUUM ANALYZE;"
```

---

## Fehlerbehebung

### Bot startet nicht

```bash
docker compose logs trading-bot           # Logs pruefen
ls -la .env                               # .env vorhanden?
docker compose down && docker compose up -d --build  # Neu bauen
```

### Dashboard nicht erreichbar

```bash
sudo systemctl status nginx               # Nginx laeuft?
sudo tail -f /var/log/nginx/error.log     # Nginx-Fehler
docker compose ps                         # Container laeuft?
curl -s http://localhost:8000/api/health    # Backend erreichbar?
sudo nginx -t && sudo systemctl reload nginx
```

### Login funktioniert nicht

```bash
# Passwort zuruecksetzen
docker compose exec trading-bot python main.py --create-admin --username admin --password neues_passwort
```

### Notifications kommen nicht (Discord/Telegram)

1. Pruefen ob Webhook URL / Bot Token in Settings gesetzt ist
2. Pruefen ob Trade ueber die API eroeffnet wurde (direkte Scripts senden keine Notifications)
3. Logs pruefen: `docker compose logs | grep -i discord` oder `grep -i telegram`
4. Test-Notification senden: Settings > Notifications > Test

### PostgreSQL startet nicht

```bash
docker compose logs postgres                      # Fehler pruefen
docker volume ls                                  # Volume vorhanden?
docker compose down -v && docker compose up -d    # Nur wenn Datenverlust akzeptabel!
```

### Grafana nicht erreichbar

```bash
docker compose logs grafana                       # Fehler pruefen
# Grafana laeuft auf Port 3000 (nur localhost)
curl http://localhost:3000/api/health
```

---

## Zusammenfassung

### Checkliste: Deployment abgeschlossen

- [ ] VPS erstellt und konfiguriert
- [ ] Non-root User `trading` eingerichtet
- [ ] Firewall (UFW) aktiv
- [ ] Docker installiert
- [ ] Repository geklont und `.env` konfiguriert
- [ ] POSTGRES_PASSWORD und GF_ADMIN_PASSWORD geaendert
- [ ] ENVIRONMENT=production gesetzt
- [ ] Admin-User erstellt
- [ ] Alle 6 Container laufen (`docker compose ps`)
- [ ] Systemd-Service aktiviert (Auto-Start)
- [ ] Exchange API-Keys ueber Settings-Seite eingetragen
- [ ] Notifications konfiguriert (Discord/Telegram, optional)
- [ ] Domain + Nginx + SSL konfiguriert (optional)
- [ ] pg-backup Container laeuft (automatische Backups)
- [ ] Grafana-Dashboard erreichbar (Port 3000)
- [ ] Fail2Ban aktiv

### Wichtige Befehle

```bash
docker compose ps                                 # Status aller 6 Container
docker compose logs -f trading-bot                # Bot-Logs
docker compose logs -f postgres                   # DB-Logs
docker compose logs pg-backup --tail=5            # Backup-Status
docker compose restart trading-bot                # Bot neustarten
git pull && docker compose up -d --build --no-cache  # Update
sudo systemctl status trading-bot                 # Systemd-Status
sudo systemctl reload nginx                       # Nginx neu laden
sudo certbot renew                                # SSL erneuern
```
