#!/bin/bash
# Smart deploy script — only uses --no-cache when dependencies changed
# Usage: ./scripts/deploy.sh [--force-clean]

set -e

cd /root/Trading-Bot

echo "=== Pulling latest code ==="
BEFORE=$(git rev-parse HEAD)
git pull origin main
AFTER=$(git rev-parse HEAD)

if [ "$BEFORE" = "$AFTER" ] && [ "$1" != "--force-clean" ]; then
    echo "No changes to deploy."
    exit 0
fi

# Check if dependency files changed since last deploy
DEPS_CHANGED=false
CHANGED_FILES=$(git diff --name-only "$BEFORE" "$AFTER" 2>/dev/null || echo "")

if echo "$CHANGED_FILES" | grep -qE "requirements\.txt|frontend/package\.json|frontend/package-lock\.json|Dockerfile"; then
    DEPS_CHANGED=true
fi

# Build with or without cache
if [ "$DEPS_CHANGED" = true ] || [ "$1" = "--force-clean" ]; then
    echo "=== Dependencies changed or --force-clean — building WITHOUT cache ==="
    docker compose build --no-cache trading-bot
else
    echo "=== Code-only change — building WITH cache (fast) ==="
    docker compose build trading-bot
fi

# Restart container
echo "=== Restarting container ==="
docker compose up -d

# Wait for healthy
echo "=== Waiting for health check ==="
for i in $(seq 1 30); do
    if docker inspect --format='{{.State.Health.Status}}' bitget-trading-bot 2>/dev/null | grep -q healthy; then
        echo "=== Deploy complete! Container is healthy ==="
        docker ps --format '{{.Names}} {{.Status}}' | grep trading-bot

        # Clean up old images to prevent disk fill
        docker image prune -f --filter "until=24h" > /dev/null 2>&1 || true

        exit 0
    fi
    sleep 2
done

echo "WARNING: Container not healthy after 60s"
docker logs bitget-trading-bot --tail 20
exit 1
