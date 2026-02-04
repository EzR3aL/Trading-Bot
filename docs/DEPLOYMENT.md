# Cloud Deployment Anleitung (DigitalOcean)

Diese Anleitung zeigt dir, wie du den Bitget Trading Bot auf einem DigitalOcean Droplet einrichtest, damit er 24/7 laeuft.

**Version:** 2.1.0

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

## Architektur (v2.0+)

```
                    Internet
                       |
                   [Nginx :443]
                    SSL/HTTPS
                       |
              [FastAPI Backend :8000]
              /        |        \
         [React UI]  [REST API]  [SQLite DB]
              |        |
         [Recharts]  [JWT Auth]
```

**Komponenten:**
- **FastAPI Backend** (Port 8000): REST API + statische React-Dateien
- **React Frontend**: Wird beim Docker-Build kompiliert und vom Backend ausgeliefert
- **SQLite**: Datenbank fuer Trades, User, Configs (in `data/bot.db`)
- **Nginx**: Reverse Proxy mit SSL-Terminierung

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

- [ ] DigitalOcean Account ([Anmelden](https://www.digitalocean.com/))
- [ ] SSH Key-Pair
- [ ] Domain (optional, fuer HTTPS)
- [ ] Bitget API Credentials (Demo und/oder Live)
- [ ] Discord Webhook URL

---

## Schritt 1: Droplet erstellen

1. Gehe zu [DigitalOcean Console](https://cloud.digitalocean.com/) → "Create" → "Droplets"

2. **Region:** Frankfurt (fra1) oder Amsterdam (ams3)

3. **Image:** Ubuntu 22.04 (LTS) x64

4. **Size:** $12/mo - 2 GB RAM / 1 vCPU / 50 GB SSD (empfohlen)

5. **Authentication:** SSH Key (empfohlen)

6. **Hostname:** `bitget-trading-bot`

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
git clone https://github.com/EzR3aL/Bitget-Trading-Bot.git
cd Bitget-Trading-Bot
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

# Logging
LOG_LEVEL=INFO
```

**Hinweis:** API-Keys, Discord-Webhook und Bitget-Credentials werden ueber die Web-Oberflaeche konfiguriert (Settings-Seite), nicht ueber die .env Datei. Die `ENCRYPTION_KEY` wird beim ersten Start automatisch generiert.

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

# Erwartete Ausgabe:
# NAME                  STATUS       PORTS
# bitget-trading-bot    Up 2 min     127.0.0.1:8000->8000/tcp
```

### 4.6 Web-UI einrichten

1. Oeffne `http://<IP>:8000` (temporaer, spaeter via HTTPS)
2. Logge dich mit dem Admin-User ein
3. Gehe zu **Settings**:
   - Trage Bitget API-Keys ein (Demo und/oder Live)
   - Trage Discord Webhook URL ein
4. Gehe zu **Bot Control**:
   - Waehle Exchange und Modus (Demo/Live)
   - Starte den Bot

---

## Schritt 5: Auto-Start einrichten

```bash
sudo nano /etc/systemd/system/trading-bot.service
```

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

```bash
nano ~/backup-db.sh
```

```bash
#!/bin/bash
BACKUP_DIR="$HOME/backups"
DB_PATH="$HOME/Bitget-Trading-Bot/data/bot.db"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR
sqlite3 $DB_PATH ".backup '$BACKUP_DIR/bot_$DATE.db'"
find $BACKUP_DIR -name "bot_*.db" -mtime +30 -delete
echo "Backup: bot_$DATE.db"
```

```bash
chmod +x ~/backup-db.sh

# Cronjob (taeglich 3 Uhr)
crontab -e
# 0 3 * * * /home/trading/backup-db.sh >> /home/trading/backup.log 2>&1
```

### Bot-Status Heartbeat

```bash
nano ~/check-bot-status.sh
```

```bash
#!/bin/bash
WEBHOOK_URL="https://discord.com/api/webhooks/..."

if ! curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
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
cd ~/Bitget-Trading-Bot
git pull origin main
docker compose down
docker compose up -d --build
docker compose logs -f
```

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
sqlite3 data/bot.db "VACUUM;"
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
curl http://localhost:8000/api/health      # Backend erreichbar?
sudo nginx -t && sudo systemctl reload nginx
```

### Login funktioniert nicht

```bash
# Passwort zuruecksetzen
docker compose exec trading-bot python main.py --create-admin --username admin --password neues_passwort
```

### Bitget API "exchange environment is incorrect"

- **Ursache:** Demo-Header falsch. Muss `paptrading: 1` sein (NICHT `X-SIMULATED-TRADING`)
- **Fix:** Ist seit v2.1.0 behoben. Falls alte Version: `git pull && docker compose up -d --build`

### TP/SL wird als "Partial" gesetzt

- **Ursache:** Alte Version nutzte `presetStopSurplusPrice` auf Place-Order (erstellt Partial TP/SL)
- **Fix:** Seit v2.1.0 wird `/api/v2/mix/order/place-pos-tpsl` fuer Entire TP/SL verwendet

### Discord Notifications kommen nicht

1. Pruefen ob Webhook URL in Settings gesetzt ist
2. Pruefen ob Trade ueber die API eroeffnet wurde (direkte Scripts senden keine Notifications)
3. Logs pruefen: `docker compose logs | grep -i discord`

---

## Zusammenfassung

### Checkliste: Deployment abgeschlossen

- [ ] Droplet erstellt und konfiguriert
- [ ] Non-root User `trading` eingerichtet
- [ ] Firewall (UFW) aktiv
- [ ] Docker installiert
- [ ] Repository geklont und `.env` konfiguriert
- [ ] Admin-User erstellt
- [ ] Container laeuft (`docker compose ps`)
- [ ] Systemd-Service aktiviert (Auto-Start)
- [ ] Bitget API-Keys ueber Settings-Seite eingetragen
- [ ] Discord Webhook ueber Settings-Seite eingetragen
- [ ] Domain + Nginx + SSL konfiguriert (optional)
- [ ] Backups eingerichtet
- [ ] Fail2Ban aktiv

### Wichtige Befehle

```bash
docker compose ps                         # Status
docker compose logs -f                    # Logs
docker compose restart                    # Neustarten
git pull && docker compose up -d --build  # Update
sudo systemctl status trading-bot         # Systemd-Status
sudo systemctl reload nginx               # Nginx neu laden
sudo certbot renew                        # SSL erneuern
```

---

**Version:** 2.1.0 | **Letzte Aktualisierung:** 2026-02-04
