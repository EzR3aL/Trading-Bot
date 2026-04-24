# PostgreSQL Migration

## Deutsch

### Ueberblick

Ab Version 3.4.0 unterstuetzen Edge Bots by Trading Department PostgreSQL als Produktionsdatenbank.
SQLite bleibt als Fallback fuer lokale Entwicklung erhalten.

**Warum PostgreSQL?**
- Echte Concurrency (mehrere Benutzer gleichzeitig)
- Connection Pooling (20+ Verbindungen)
- Skalierbar fuer 10.000+ Benutzer
- Robuster bei hoher Last

### Schnellstart mit Docker

1. **Docker Compose starten:**
   ```bash
   docker compose up --build -d
   ```
   Dies startet automatisch PostgreSQL + Edge Bots. Die Datenbank wird automatisch erstellt.

2. **Admin-User erstellen:**
   ```bash
   docker compose exec trading-bot python main.py --create-admin --username EzR3aL --password DeinPasswort
   ```

3. **Fertig!** Frontend oeffnen unter `http://localhost:8000`

### Lokale Entwicklung (ohne Docker)

1. **PostgreSQL installieren:**
   - Windows: [PostgreSQL Installer](https://www.postgresql.org/download/windows/)
   - Linux: `sudo apt install postgresql`
   - macOS: `brew install postgresql`

2. **Datenbank erstellen:**
   ```sql
   CREATE USER tradingbot WITH PASSWORD 'tradingbot_dev';
   CREATE DATABASE tradingbot OWNER tradingbot;
   ```

3. **asyncpg installieren:**
   ```bash
   pip install asyncpg
   ```

4. **`.env` konfigurieren:**
   ```env
   DATABASE_URL=postgresql+asyncpg://tradingbot:tradingbot_dev@localhost:5432/tradingbot
   ```

5. **Backend starten:**
   ```bash
   python main.py
   ```
   Die Tabellen werden automatisch erstellt.

### Pool-Parameter anpassen

Fuer grosse Installationen koennen die Connection-Pool-Parameter in `.env` angepasst werden:

| Variable | Default | Beschreibung |
|----------|---------|-------------|
| `DB_POOL_SIZE` | 20 | Basis-Anzahl persistenter Verbindungen |
| `DB_MAX_OVERFLOW` | 30 | Zusaetzliche Verbindungen ueber Pool-Groesse hinaus |
| `DB_POOL_RECYCLE` | 1800 | Verbindungen nach N Sekunden erneuern |

**Empfehlung:**
- Bis 1.000 User: Default-Werte ausreichend
- 1.000-5.000 User: `DB_POOL_SIZE=30`, `DB_MAX_OVERFLOW=50`
- 5.000+ User: `DB_POOL_SIZE=50`, `DB_MAX_OVERFLOW=80`

### Zurueck zu SQLite

Um wieder SQLite zu verwenden, einfach `DATABASE_URL` aus `.env` entfernen oder auf SQLite setzen:

```env
DATABASE_URL=sqlite+aiosqlite:///data/bot.db
```

### Tests mit PostgreSQL

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tradingbot:tradingbot_dev@localhost:5432/tradingbot_test pytest tests/
```

---

## English

### Overview

Starting with version 3.4.0, Edge Bots by Trading Department supports PostgreSQL as a production database.
SQLite remains as a fallback for local development.

**Why PostgreSQL?**
- True concurrency (multiple simultaneous users)
- Connection pooling (20+ connections)
- Scalable for 10,000+ users
- More robust under high load

### Quick Start with Docker

1. **Start Docker Compose:**
   ```bash
   docker compose up --build -d
   ```
   This automatically starts PostgreSQL + Edge Bots. The database is created automatically.

2. **Create admin user:**
   ```bash
   docker compose exec trading-bot python main.py --create-admin --username EzR3aL --password YourPassword
   ```

3. **Done!** Open the frontend at `http://localhost:8000`

### Local Development (without Docker)

1. **Install PostgreSQL:**
   - Windows: [PostgreSQL Installer](https://www.postgresql.org/download/windows/)
   - Linux: `sudo apt install postgresql`
   - macOS: `brew install postgresql`

2. **Create database:**
   ```sql
   CREATE USER tradingbot WITH PASSWORD 'tradingbot_dev';
   CREATE DATABASE tradingbot OWNER tradingbot;
   ```

3. **Install asyncpg:**
   ```bash
   pip install asyncpg
   ```

4. **Configure `.env`:**
   ```env
   DATABASE_URL=postgresql+asyncpg://tradingbot:tradingbot_dev@localhost:5432/tradingbot
   ```

5. **Start backend:**
   ```bash
   python main.py
   ```
   Tables are created automatically.

### Adjusting Pool Parameters

For large installations, connection pool parameters can be adjusted in `.env`:

| Variable | Default | Description |
|----------|---------|------------|
| `DB_POOL_SIZE` | 20 | Base number of persistent connections |
| `DB_MAX_OVERFLOW` | 30 | Extra connections allowed beyond pool size |
| `DB_POOL_RECYCLE` | 1800 | Recycle connections after N seconds |

**Recommendations:**
- Up to 1,000 users: Default values are sufficient
- 1,000-5,000 users: `DB_POOL_SIZE=30`, `DB_MAX_OVERFLOW=50`
- 5,000+ users: `DB_POOL_SIZE=50`, `DB_MAX_OVERFLOW=80`

### Switching Back to SQLite

To use SQLite again, simply remove `DATABASE_URL` from `.env` or set it to SQLite:

```env
DATABASE_URL=sqlite+aiosqlite:///data/bot.db
```

### Running Tests with PostgreSQL

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tradingbot:tradingbot_dev@localhost:5432/tradingbot_test pytest tests/
```
