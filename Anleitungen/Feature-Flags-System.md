# Feature Flags System

## Deutsch

### Übersicht

Der Trading-Bot nutzt **Feature Flags**, um neue oder riskante Code-Pfade
schrittweise auszurollen. Ein Flag ist eine Umgebungsvariable in der
`.env`-Datei auf dem Server, die beim Container-Start gelesen wird. Ist
das Flag aus (Default), läuft der Bot im bewährten Verhalten — ist es an,
wird der neue Code-Pfad aktiviert.

**Warum?** Wir können so Refactorings (z. B. den RiskStateManager aus
Epic #188) in Produktion deployen, ohne sie sofort scharf zu schalten.
Bei Problemen reicht das Zurücksetzen des Flags und ein Neustart, statt
ein Rollback-Deploy.

**Ehrlicher Hinweis:** Es gibt **kein zentrales Feature-Flags-Modul**.
Die Flags werden ad-hoc an ihrer Verwendungsstelle gelesen —
entweder über `os.getenv(...)` direkt oder über das
`Settings.risk`-Dataclass in `config/settings.py`. Beide Varianten
prüfen sinngemäß auf die Werte `"1"`, `"true"`, `"yes"`, `"on"`
(case-insensitive) → alles andere (inkl. leer/unset) zählt als
ausgeschaltet.

### Verfügbare Flags

| Flag (Env Var) | Default | Status Prod (2026-04-23) | Gelesen in | Zweck |
|---|---|---|---|---|
| `AUTO_AUDIT_ENABLED` | off | **ON** | `src/bot/audit_scheduler.py:389` | Startet den stündlichen Audit-Scheduler (TP/SL-Drift, Position-Size-Check, Preis-Sanity, Classify-Method). Admin-Report via Discord/Telegram. |
| `EXCHANGE_WEBSOCKETS_ENABLED` | off | **OFF** (Wiring live seit `fd77ba9`) | `src/bot/ws_manager.py:62` | Startet die Exchange-WebSocket-Listener (Bitget, Hyperliquid) und leitet Events in den RiskStateManager. `start_for_user` ist no-op, solange das Flag aus ist. |
| `RISK_STATE_MANAGER_ENABLED` | off | off | `config/settings.py:223` (→ `settings.risk.risk_state_manager_enabled`) | Aktiviert den 2-Phase-Commit RiskStateManager für TP/SL-Änderungen. Betrifft `PUT /api/trades/{id}/tp-sl`, `bot_worker.py:130` und `position_monitor.py:672`. |
| `HL_SOFTWARE_TRAILING_ENABLED` | off | off | `config/settings.py:226` (→ `settings.risk.hl_software_trailing_enabled`) | Startet den Software-Trailing-Stop-Emulator für Hyperliquid (HL hat keinen nativen Trailing-Primitive). Erfordert, dass der Bot permanent online ist. |
| `ENABLE_HSTS` | off (prod: auto-on) | auto | `src/api/main_app.py:113` | Erzwingt den HSTS-Header. In `ENVIRONMENT=production` automatisch an, sonst opt-in. |
| `BEHIND_PROXY` | off | on | `src/api/rate_limit.py:10` | Nutzt `X-Forwarded-For` für Rate-Limit/Audit-Logs, wenn der Bot hinter Nginx/Caddy läuft. |
| `SQL_ECHO` | false | off | `src/models/session.py:29` | Loggt alle SQL-Statements — nur zum Debuggen. |
| `DEMO_MODE` | true | — (per Bot) | `config/settings.py:101` | Globaler Demo-Modus-Default. Pro Bot wird der Wert in der DB überschrieben; die Env-Variable ist nur der Initial-Default. |

> Hinweis: Es existieren weitere `ENABLED`-artige Variablen wie
> `ENVIRONMENT=production` — das ist kein boolean-Flag, sondern ein
> Modus-Schalter und gehört in eine eigene Betriebsanleitung.

### Flag umschalten

Alle Flags werden beim Container-Start aus `/root/Trading-Bot/.env`
geladen. Zur Laufzeit umschalten geht **nicht** — der Container muss
neu gestartet werden. Ausnahme: `EXCHANGE_WEBSOCKETS_ENABLED` wird
bei jedem `start_for_user`-Aufruf neu gelesen, aber aktive Sessions
übernehmen die Änderung erst nach Neustart.

**Schritt für Schritt (am Beispiel `RISK_STATE_MANAGER_ENABLED`):**

```bash
# 1) Per SSH auf den VPS
ssh root@46.101.130.50
cd /root/Trading-Bot

# 2) .env bearbeiten
nano .env

#    Zeile anhängen oder ändern:
#    RISK_STATE_MANAGER_ENABLED=true
#
#    Akzeptierte truthy-Werte: 1, true, yes, on
#    Alles andere (inkl. unset) = OFF

# 3) Container neu starten (ohne Rebuild, weil nur Env-Var geändert)
docker compose restart bitget-trading-bot

# 4) Verify — Log sollte das neue Verhalten zeigen
docker logs --tail 100 bitget-trading-bot | grep -i "risk_state_manager\|RiskStateManager"
```

**Flag wieder ausschalten:** Zeile in `.env` löschen oder auf `false`
setzen und erneut `docker compose restart bitget-trading-bot` laufen
lassen.

**Eine ganze Session-Kette neu deployen** (z. B. wenn auch Code-Änderungen
dabei sind):

```bash
git pull
docker compose build --no-cache bitget-trading-bot
docker compose up -d
```

### Neues Flag hinzufügen

Wenn du im Code ein neues Flag gatest, halte dich an eine der zwei
etablierten Varianten:

**Variante A — direkt per `os.getenv`** (wenn das Flag nur an einer
oder zwei Stellen gelesen wird):

```python
# Beispiel aus src/bot/ws_manager.py
def is_enabled() -> bool:
    raw = os.getenv("MEIN_NEUES_FLAG", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}
```

**Variante B — über die Settings-Dataclass** (wenn das Flag an mehreren
Stellen gelesen wird oder thematisch zu einer Config-Gruppe gehört):

```python
# in config/settings.py
@dataclass
class RiskConfig:
    mein_neues_flag: bool = field(
        default_factory=lambda: get_env("MEIN_NEUES_FLAG", "false", bool)
    )

# Verwendung:
from config.settings import settings
if settings.risk.mein_neues_flag:
    ...
```

**Pflicht-Schritte nach dem Hinzufügen:**

1. In `.env.example` dokumentieren (auskommentiert + Default-Hinweis).
2. Diese Anleitung (`Anleitungen/Feature-Flags-System.md`) in der Tabelle
   `Verfügbare Flags` ergänzen.
3. CHANGELOG.md updaten — laut Projektregel bei jeder Änderung Pflicht.
4. Default **off** lassen, bis Rollout geplant ist.

### Troubleshooting

| Symptom | Ursache / Fix |
|---|---|
| Flag auf `true` gesetzt, Bot ignoriert es | Container nicht neu gestartet. `docker compose restart bitget-trading-bot`. |
| Tippfehler im Wert (z. B. `True` oder `"true"` mit Quotes) | Nur `true`/`1`/`yes`/`on` werden akzeptiert. Keine Anführungszeichen in `.env`. |
| Änderung an `.env` wird nicht übernommen | `docker-compose.yml` muss die `.env` per `env_file` einbinden. Prüfen mit `docker compose config \| grep -A5 environment`. |
| Flag ist an, alter Code läuft trotzdem | Der Code liest das Flag evtl. nur beim App-Start. Restart reicht oft nicht bei long-running Worker-Loops — in dem Fall `docker compose up -d --force-recreate` nutzen. |
| `AUTO_AUDIT_ENABLED=true`, aber keine Reports | Siehe `Anleitungen/audit-scripts.md` — Scheduler läuft nur, wenn FastAPI-Lifespan sauber bootet. `docker logs bitget-trading-bot \| grep audit_scheduler` zeigt "disabled" oder "started". |
| `EXCHANGE_WEBSOCKETS_ENABLED=true`, keine WS-Events | Credentials-Provider liefert evtl. `None`. Check: `docker logs bitget-trading-bot \| grep ws_manager`. Außerdem: WS-Wiring wurde in Commit `fd77ba9` scharf geschaltet — Image muss neuer als dieser Commit sein. |
| Rollback nach Fehlversuch | Flag in `.env` auf `false` (oder Zeile löschen), `docker compose restart` — kein Code-Revert nötig. |

---

## English

### Overview

The Trading Bot uses **feature flags** to roll out new or risky code
paths gradually. A flag is an environment variable in the server's
`.env` file, read at container start. When the flag is off (default),
the bot runs the proven behaviour — when it's on, the new code path
activates.

**Why?** This lets us deploy refactors (like the RiskStateManager from
Epic #188) to production without enabling them immediately. If problems
surface, flipping the flag off and restarting is enough — no rollback
deploy needed.

**Honest note:** There is **no central feature-flags module**. Flags
are read ad-hoc at their consumption site — either directly via
`os.getenv(...)` or via the `Settings.risk` dataclass in
`config/settings.py`. Both variants accept the values `"1"`, `"true"`,
`"yes"`, `"on"` (case-insensitive) as truthy → anything else (including
empty/unset) counts as off.

### Available Flags

| Flag (env var) | Default | Prod status (2026-04-23) | Read in | Purpose |
|---|---|---|---|---|
| `AUTO_AUDIT_ENABLED` | off | **ON** | `src/bot/audit_scheduler.py:389` | Starts the hourly audit scheduler (TP/SL drift, position-size check, price sanity, classify-method). Admin report via Discord/Telegram. |
| `EXCHANGE_WEBSOCKETS_ENABLED` | off | **OFF** (wiring live since `fd77ba9`) | `src/bot/ws_manager.py:62` | Starts the exchange WebSocket listeners (Bitget, Hyperliquid) and routes events to the RiskStateManager. `start_for_user` is a no-op while the flag is off. |
| `RISK_STATE_MANAGER_ENABLED` | off | off | `config/settings.py:223` (→ `settings.risk.risk_state_manager_enabled`) | Enables the 2-Phase-Commit RiskStateManager for TP/SL changes. Affects `PUT /api/trades/{id}/tp-sl`, `bot_worker.py:130` and `position_monitor.py:672`. |
| `HL_SOFTWARE_TRAILING_ENABLED` | off | off | `config/settings.py:226` (→ `settings.risk.hl_software_trailing_enabled`) | Starts the software trailing-stop emulator for Hyperliquid (HL has no native trailing primitive). Requires the bot to stay online. |
| `ENABLE_HSTS` | off (prod: auto-on) | auto | `src/api/main_app.py:113` | Forces the HSTS header. Automatically on in `ENVIRONMENT=production`, opt-in otherwise. |
| `BEHIND_PROXY` | off | on | `src/api/rate_limit.py:10` | Uses `X-Forwarded-For` for rate-limit/audit logs when the bot runs behind Nginx/Caddy. |
| `SQL_ECHO` | false | off | `src/models/session.py:29` | Logs every SQL statement — debugging only. |
| `DEMO_MODE` | true | — (per bot) | `config/settings.py:101` | Global demo-mode default. Each bot overrides this in the DB; the env var is only the initial default. |

> Note: Other `ENABLED`-style variables exist (e.g. `ENVIRONMENT=production`).
> That's a mode switch, not a boolean flag, and belongs in a separate
> ops runbook.

### Toggling a Flag

All flags are loaded from `/root/Trading-Bot/.env` at container start.
Runtime toggling is **not** supported — the container must restart.
Exception: `EXCHANGE_WEBSOCKETS_ENABLED` is re-read on every
`start_for_user` call, but active sessions only pick up the change
after a restart.

**Step by step (example: `RISK_STATE_MANAGER_ENABLED`):**

```bash
# 1) SSH into the VPS
ssh root@46.101.130.50
cd /root/Trading-Bot

# 2) Edit .env
nano .env

#    Append or change the line:
#    RISK_STATE_MANAGER_ENABLED=true
#
#    Accepted truthy values: 1, true, yes, on
#    Anything else (including unset) = OFF

# 3) Restart the container (no rebuild needed, env-only change)
docker compose restart bitget-trading-bot

# 4) Verify — logs should show the new behaviour
docker logs --tail 100 bitget-trading-bot | grep -i "risk_state_manager\|RiskStateManager"
```

**Turn a flag back off:** delete the line in `.env` or set it to
`false`, then `docker compose restart bitget-trading-bot` again.

**Full re-deploy** (if code changes are included too):

```bash
git pull
docker compose build --no-cache bitget-trading-bot
docker compose up -d
```

### Adding a New Flag

When you gate new code behind a flag, follow one of the two established
patterns:

**Variant A — directly via `os.getenv`** (when the flag is read in
only one or two places):

```python
# Example from src/bot/ws_manager.py
def is_enabled() -> bool:
    raw = os.getenv("MY_NEW_FLAG", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}
```

**Variant B — via the Settings dataclass** (when the flag is read
from multiple call sites or belongs to a config group):

```python
# in config/settings.py
@dataclass
class RiskConfig:
    my_new_flag: bool = field(
        default_factory=lambda: get_env("MY_NEW_FLAG", "false", bool)
    )

# Usage:
from config.settings import settings
if settings.risk.my_new_flag:
    ...
```

**Mandatory follow-ups after adding a flag:**

1. Document it in `.env.example` (commented out, with default hint).
2. Add a row to the `Available Flags` table in this file.
3. Update `CHANGELOG.md` — required by project rule on every change.
4. Leave the default **off** until rollout is planned.

### Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| Flag set to `true`, bot ignores it | Container wasn't restarted. `docker compose restart bitget-trading-bot`. |
| Typo in the value (e.g. `True` or `"true"` with quotes) | Only `true`/`1`/`yes`/`on` are accepted. No quotes in `.env`. |
| `.env` change not picked up | `docker-compose.yml` must mount `.env` via `env_file`. Verify with `docker compose config \| grep -A5 environment`. |
| Flag is on, old code still runs | The flag may be read only at app start. A plain restart isn't always enough for long-running worker loops — use `docker compose up -d --force-recreate`. |
| `AUTO_AUDIT_ENABLED=true` but no reports | See `Anleitungen/audit-scripts.md` — the scheduler only starts if FastAPI lifespan boots cleanly. `docker logs bitget-trading-bot \| grep audit_scheduler` shows "disabled" or "started". |
| `EXCHANGE_WEBSOCKETS_ENABLED=true`, no WS events | The credentials provider may return `None`. Check `docker logs bitget-trading-bot \| grep ws_manager`. Also: the WS wiring only went live in commit `fd77ba9` — the image must be newer than that commit. |
| Rollback after a failed attempt | Set the flag to `false` in `.env` (or delete the line), `docker compose restart` — no code revert needed. |
