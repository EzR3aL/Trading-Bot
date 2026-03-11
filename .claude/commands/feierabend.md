# Feierabend

End-of-day wrap-up: test, commit, changelog, push, deploy, verify, summarize.

## Context
$ARGUMENTS

## Execute

Run all steps in order. Stop on critical failures.

### Step 1: Status Check

```bash
git status --short
git diff --stat
```

Report what changed. If nothing to commit, skip to Step 5.

### Step 2: Run Tests

Run backend tests (quick mode):
```bash
python -m pytest tests/unit/ -q --tb=short 2>&1 | tail -30
```

Run frontend tests:
```bash
cd frontend && npx vitest run --reporter=verbose 2>&1 | tail -30
```

**If tests fail:** Show failures and ask user whether to continue or fix first.

### Step 3: Update CHANGELOG

Check if CHANGELOG.md covers today's changes:
```bash
head -30 CHANGELOG.md
git log --oneline $(git log --oneline CHANGELOG.md | head -1 | cut -d' ' -f1)..HEAD
```

If new commits exist since last CHANGELOG update:
- Bump version (patch for fixes, minor for features)
- Add entry with today's date
- Categorize: Hinzugefuegt / Geaendert / Behoben / Entfernt
- One line per change, concise

### Step 4: Commit & Push

```bash
git add -A
git diff --cached --stat
git commit -m "[type]: [description]"
git push origin main
```

**Rules:**
- No `Co-Authored-By: Claude` in commits
- Separate commits for unrelated changes
- Check for secrets before staging (.env, API keys, passwords)
- If CHANGELOG was updated, include it in the commit

### Step 5: Deploy

Determine what changed and deploy accordingly:

```bash
# Check what files changed since last deploy
CHANGED=$(git diff --name-only HEAD~$(git log --oneline $(ssh trading-bot "cd /home/trading/Trading-Bot && git rev-parse HEAD" 2>/dev/null)..HEAD 2>/dev/null | wc -l) 2>/dev/null || echo "unknown")
```

**Frontend changed** (`frontend/` files modified):
```bash
ssh trading-bot "cd /home/trading/Trading-Bot && git pull && docker compose build --no-cache trading-bot && docker compose up -d trading-bot"
```

**Backend only** (`.py` files, no frontend):
```bash
ssh trading-bot "cd /home/trading/Trading-Bot && git pull && docker compose up -d --force-recreate trading-bot"
```

**Tests/docs only** (no runtime code):
```bash
ssh trading-bot "cd /home/trading/Trading-Bot && git pull"
```

Wait for container to start, then verify.

### Step 6: Verify Deployment

```bash
# Container status
ssh trading-bot "cd /home/trading/Trading-Bot && docker compose ps trading-bot"

# Health check (wait up to 30s for healthy)
ssh trading-bot "sleep 15 && curl -s localhost:8000/api/health"

# Error check
ssh trading-bot "cd /home/trading/Trading-Bot && docker compose logs trading-bot --tail 10 2>&1 | grep -iE 'error|exception|traceback'"
```

**If unhealthy or errors:** Show logs, diagnose, fix. Do NOT leave with a broken server.

### Step 7: Save Session

```bash
# Save session for tomorrow
```
Run `/save-session feierabend-[date]`

### Step 8: Summary

Output this report:

```
## Feierabend-Report

### Server Status
- Health: [healthy/unhealthy]
- Container: [status]
- Version: [from CHANGELOG]

### Heute erledigt
- [bullet list of commits/changes today]

### Tests
- Backend: [X passed, Y failed]
- Frontend: [X passed, Y failed]

### Offene Punkte / Morgen
- [anything left undone]
- [known issues]
- [planned next steps]

Schoenen Feierabend! 🍺
```

## Quick Mode

If `$ARGUMENTS` contains "quick" or "schnell":
- Skip tests
- Skip session save
- Just: commit → push → deploy → verify → summary

Execute the Feierabend process now.
