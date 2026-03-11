#!/bin/bash
# SSH-Tunnel zum Trading Bot Postgres
# Verbindet localhost:15432 → Server postgres:5432
#
# Starten: bash scripts/db-tunnel.sh
# Stoppen: Ctrl+C oder: kill $(cat /tmp/trading-bot-db-tunnel.pid)
#
# Wird benoetigt fuer den PostgreSQL MCP Server in .mcp.json

echo "Starting SSH tunnel: localhost:15432 → trading-bot:5432"
ssh -N -L 15432:127.0.0.1:5432 trading-bot &
PID=$!
echo $PID > /tmp/trading-bot-db-tunnel.pid
echo "Tunnel running (PID: $PID). Press Ctrl+C to stop."
trap "kill $PID 2>/dev/null; rm -f /tmp/trading-bot-db-tunnel.pid; echo 'Tunnel stopped.'" EXIT
wait $PID
