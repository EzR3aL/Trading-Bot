# PostgreSQL Migration

## Overview

Starting with version 3.4.0, Trading Department supports PostgreSQL as a production database.
SQLite remains as a fallback for local development.

**Why PostgreSQL?**
- True concurrency (multiple simultaneous users)
- Connection pooling (20+ connections)
- Scalable for 10,000+ users
- More robust under high load

---

## Quick Start with Docker

1. **Start Docker Compose:**
   ```bash
   docker compose up --build -d
   ```
   This automatically starts PostgreSQL + Trading Department. The database is created automatically.

2. **Create admin user:**
   ```bash
   docker compose exec trading-bot python main.py --create-admin --username EzR3aL --password YourPassword
   ```

3. **Done!** Open the frontend at `http://localhost:8000`

---

## Local Development (without Docker)

1. **Install PostgreSQL:**
   - Windows: [PostgreSQL Installer](https://www.postgresql.org/download/windows/)
   - Linux: `sudo apt install postgresql`
   - macOS: `brew install postgresql`

2. **Create the database:**
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

5. **Start the backend:**
   ```bash
   python main.py
   ```
   Tables are created automatically.

---

## Adjusting Pool Parameters

For large installations, connection pool parameters can be adjusted in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_POOL_SIZE` | 20 | Base number of persistent connections |
| `DB_MAX_OVERFLOW` | 30 | Extra connections allowed beyond pool size |
| `DB_POOL_RECYCLE` | 1800 | Recycle connections after N seconds |

**Recommendations:**
- Up to 1,000 users: Default values are sufficient
- 1,000-5,000 users: `DB_POOL_SIZE=30`, `DB_MAX_OVERFLOW=50`
- 5,000+ users: `DB_POOL_SIZE=50`, `DB_MAX_OVERFLOW=80`

---

## Switching Back to SQLite

To use SQLite again, simply remove `DATABASE_URL` from `.env` or set it to SQLite:

```env
DATABASE_URL=sqlite+aiosqlite:///data/bot.db
```

---

## Running Tests with PostgreSQL

```bash
TEST_DATABASE_URL=postgresql+asyncpg://tradingbot:tradingbot_dev@localhost:5432/tradingbot_test pytest tests/
```
