# API Reference

> **Last updated:** 2026-04-16 (v4.14.x)

Complete REST API documentation for the Trading Bot.

---

## Architecture Overview

The Trading Bot uses a **FastAPI** backend with:

- **Multi-Exchange Support**: Bitget, Weex, Hyperliquid, Bitunix, BingX
- **Multi-User**: JWT-based authentication with role-based access (user / admin)
- **Multi-Bot**: BotOrchestrator supervises multiple BotWorker instances
- **Database**: PostgreSQL 16 (async via SQLAlchemy + Alembic migrations)
- **Real-Time**: WebSocket for live trade and bot status updates
- **Monitoring**: Prometheus + Alertmanager + Grafana

**Base URL**: `http://localhost:8000/api`

---

## Authentication

All endpoints (except `/api/auth/login`, `/api/exchanges`, and `/metrics`) require a valid JWT Bearer Token.

### JWT Flow

```
1. POST /api/auth/login     --> { access_token, refresh_token }
2. Use access_token in Authorization header for all requests
3. When access_token expires, POST /api/auth/refresh with refresh_token
4. Refresh token rotation: each refresh invalidates the previous token
```

### Authorization Header

```http
Authorization: Bearer <access_token>
```

### Token Details

| Token | Lifetime | Purpose |
|-------|----------|---------|
| Access Token | Short-lived | API request authentication |
| Refresh Token | Long-lived | Obtain new access tokens |

### Example: Login and use token

```bash
# Login
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your_password"}'

# Response:
# { "access_token": "eyJ...", "refresh_token": "eyJ..." }

# Use access token for subsequent requests
curl http://localhost:8000/api/bots \
  -H "Authorization: Bearer eyJ..."
```

---

## Endpoints

### Auth

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `POST` | `/api/auth/login` | Authenticate and receive JWT tokens | No |
| `POST` | `/api/auth/refresh` | Refresh access token (rate limited: 10/min) | No |
| `POST` | `/api/auth/logout` | Invalidate current session | Yes |
| `PUT` | `/api/auth/change-password` | Change user password | Yes |
| `GET` | `/api/auth/me` | Get current user profile | Yes |
| `POST` | `/api/auth/bridge/generate` | Generate auth bridge code (mobile/CLI login) | Yes |
| `POST` | `/api/auth/bridge/exchange` | Exchange bridge code for tokens | No |

#### `POST /api/auth/login`

**Request:**
```json
{
  "username": "admin",
  "password": "secure_password"
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

#### `POST /api/auth/refresh`

**Request:**
```json
{
  "refresh_token": "eyJ..."
}
```

**Response (200):**
```json
{
  "access_token": "eyJ... (new)",
  "refresh_token": "eyJ... (new, old one is invalidated)"
}
```

---

### Bots

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/bots` | List all bots with runtime status | Yes |
| `POST` | `/api/bots` | Create a new bot | Yes |
| `GET` | `/api/bots/{id}` | Get bot details | Yes |
| `PUT` | `/api/bots/{id}` | Update bot configuration | Yes |
| `DELETE` | `/api/bots/{id}` | Delete bot (must be stopped) | Yes |
| `POST` | `/api/bots/{id}/duplicate` | Duplicate a bot configuration | Yes |
| `POST` | `/api/bots/{id}/start` | Start a bot | Yes |
| `POST` | `/api/bots/{id}/stop` | Stop a bot | Yes |
| `POST` | `/api/bots/{id}/restart` | Restart a bot | Yes |
| `POST` | `/api/bots/{id}/close-position/{symbol}` | Force-close a position | Yes |
| `POST` | `/api/bots/stop-all` | Stop all running bots | Yes |
| `GET` | `/api/bots/strategies` | List available strategies with param schemas | Yes |
| `GET` | `/api/bots/data-sources` | List available data sources | Yes |
| `GET` | `/api/bots/balance-preview` | Preview exchange balance for bot config | Yes |
| `GET` | `/api/bots/balance-overview` | Full balance overview across exchanges | Yes |
| `GET` | `/api/bots/budget-info` | Budget info for all bots | Yes |
| `GET` | `/api/bots/symbol-conflicts` | Detect symbol conflicts across bots | Yes |
| `POST` | `/api/bots/{id}/test-discord` | Send test Discord notification | Yes |
| `POST` | `/api/bots/{id}/test-telegram` | Send test Telegram notification | Yes |
| `POST` | `/api/bots/test-telegram-direct` | Test Telegram without a bot | Yes |
| `POST` | `/api/bots/test-discord-direct` | Test Discord without a bot | Yes |
| `GET` | `/api/bots/{id}/pending-trades` | List pending/stuck trades | Yes |
| `POST` | `/api/bots/{id}/pending-trades/{trade_id}/resolve` | Resolve a pending trade | Yes |
| `GET` | `/api/bots/{id}/statistics` | Per-bot trading statistics | Yes |
| `GET` | `/api/bots/compare/performance` | Compare performance across bots | Yes |
| `GET` | `/api/bots/{id}/reconcile` | Reconcile exchange vs DB positions | Yes |

#### `POST /api/bots` (Create Bot)

**Request:**
```json
{
  "name": "BTC Scalper",
  "description": "1h BTC scalping bot",
  "strategy_type": "edge_indicator",
  "exchange_type": "bitget",
  "mode": "demo",
  "trading_pairs": ["BTCUSDT"],
  "leverage": 3,
  "position_size_percent": 10.0,
  "max_trades_per_day": 3,
  "take_profit_percent": 3.5,
  "stop_loss_percent": 2.0,
  "daily_loss_limit_percent": 5.0,
  "strategy_params": {
    "ema_fast_period": 8,
    "ema_slow_period": 21,
    "adx_chop_threshold": 18.0
  },
  "schedule_type": "market_sessions",
  "schedule_config": {}
}
```

**Response (201):**
```json
{
  "id": 1,
  "name": "BTC Scalper",
  "strategy_type": "edge_indicator",
  "exchange_type": "bitget",
  "mode": "demo",
  "is_enabled": true,
  "status": "stopped",
  "...": "..."
}
```

---

### Trades

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/trades` | List trades (filtered, paginated) | Yes |
| `GET` | `/api/trades/{trade_id}` | Get single trade details | Yes |
| `PUT` | `/api/trades/{trade_id}/tp-sl` | Update TP/SL for an open trade | Yes |
| `POST` | `/api/trades/sync` | Sync exchange positions with DB | Yes |

#### `GET /api/trades`

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `status` | string | `open`, `closed`, or `cancelled` |
| `symbol` | string | Filter by trading pair |
| `exchange` | string | Filter by exchange |
| `bot_name` | string | Filter by bot name |
| `date_from` | string | ISO date `YYYY-MM-DD` |
| `date_to` | string | ISO date `YYYY-MM-DD` |
| `demo_mode` | boolean | Filter demo/live trades |
| `page` | int | Page number (default: 1) |
| `per_page` | int | Items per page (default: 50, max: 200) |

**Response (200):**
```json
{
  "trades": [
    {
      "id": 42,
      "symbol": "BTCUSDT",
      "side": "long",
      "size": 0.015,
      "entry_price": 95000.0,
      "exit_price": 98325.0,
      "pnl": 49.88,
      "pnl_percent": 3.5,
      "fees": 1.85,
      "funding_paid": 0.32,
      "status": "closed",
      "demo_mode": false,
      "exchange": "bitget",
      "entry_time": "2026-02-20T14:00:00Z",
      "exit_time": "2026-02-20T18:23:00Z"
    }
  ],
  "total": 156,
  "page": 1,
  "per_page": 50
}
```

---

### Statistics

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/statistics` | Aggregated trading statistics | Yes |
| `GET` | `/api/statistics/daily` | Daily PnL breakdown | Yes |
| `GET` | `/api/statistics/revenue` | Builder fee revenue analytics | Yes |

#### `GET /api/statistics`

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `days` | int | Lookback period (default: 30, max: 365) |
| `demo_mode` | boolean | Filter demo/live |

**Response (200):**
```json
{
  "total_trades": 85,
  "winning_trades": 51,
  "losing_trades": 34,
  "win_rate": 60.0,
  "total_pnl": 1250.50,
  "total_fees": 127.30,
  "total_funding": 45.20,
  "total_builder_fees": 12.50,
  "avg_pnl_percent": 1.47,
  "best_trade": 385.20,
  "worst_trade": -142.80
}
```

---

### Config (General)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/config` | Get user configuration | Yes |
| `PUT` | `/api/config/trading` | Update trading parameters | Yes |
| `PUT` | `/api/config/strategy` | Update strategy parameters | Yes |

### Config (Exchange Connections)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/config/exchange-connections` | List exchange connections | Yes |
| `PUT` | `/api/config/exchange-connections/{exchange}` | Add/update exchange connection | Yes |
| `DELETE` | `/api/config/exchange-connections/{exchange}` | Remove exchange connection | Yes |
| `DELETE` | `/api/config/exchange-connections/{exchange}/keys` | Remove only API keys | Yes |
| `POST` | `/api/config/exchange-connections/{exchange}/test` | Test exchange connection | Yes |
| `GET` | `/api/config/connections` | Overview of all connections | Yes |

#### `PUT /api/config/exchange-connections/{exchange}`

**Request:**
```json
{
  "api_key": "bg_xxxxxxxxxxxxxxxx",
  "api_secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "passphrase": "your_passphrase"
}
```

**Response (200):**
```json
{
  "exchange_type": "bitget",
  "is_connected": true,
  "connected_at": "2026-02-20T10:00:00Z"
}
```

### Config (Hyperliquid)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/config/hyperliquid/admin-settings` | Get HL admin settings | Admin |
| `PUT` | `/api/config/hyperliquid/admin-settings` | Update HL admin settings | Admin |
| `GET` | `/api/config/hyperliquid/builder-config` | Get HL builder fee config | Yes |
| `POST` | `/api/config/hyperliquid/confirm-builder-approval` | Confirm builder fee | Yes |
| `POST` | `/api/config/hyperliquid/verify-referral` | Verify referral status | Yes |
| `GET` | `/api/config/hyperliquid/referral-status` | Get referral status | Yes |
| `GET` | `/api/config/hyperliquid/revenue-summary` | HL revenue summary | Yes |

### Config (Affiliate UIDs)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `PUT` | `/api/config/exchange-connections/{exchange}/affiliate-uid` | Set affiliate UID | Yes |
| `GET` | `/api/config/admin/affiliate-uids` | List all affiliate UIDs | Admin |
| `PUT` | `/api/config/admin/affiliate-uids/{id}/verify` | Verify affiliate UID | Admin |

### Config Changes (Audit)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/config-changes` | List config change history | Yes |

---

### Portfolio

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/portfolio/summary` | Multi-exchange PnL summary | Yes |
| `GET` | `/api/portfolio/positions` | Live positions from all exchanges | Yes |
| `GET` | `/api/portfolio/daily` | Daily PnL per exchange (for stacked charts) | Yes |
| `GET` | `/api/portfolio/allocation` | Capital allocation breakdown | Yes |

#### `GET /api/portfolio/summary`

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `days` | int | Lookback period (default: 30) |
| `demo_mode` | string | `all`, `true`, or `false` |

**Response (200):**
```json
{
  "total_pnl": 2340.50,
  "total_trades": 210,
  "overall_win_rate": 58.1,
  "total_fees": 285.40,
  "total_funding": 92.10,
  "exchanges": [
    {
      "exchange": "bitget",
      "total_pnl": 1580.30,
      "total_trades": 140,
      "winning_trades": 84,
      "win_rate": 60.0,
      "total_fees": 195.20,
      "total_funding": 62.30
    },
    {
      "exchange": "hyperliquid",
      "total_pnl": 760.20,
      "total_trades": 70,
      "winning_trades": 38,
      "win_rate": 54.3,
      "total_fees": 90.20,
      "total_funding": 29.80
    }
  ]
}
```

#### `GET /api/portfolio/positions`

**Response (200):**
```json
[
  {
    "exchange": "bitget",
    "symbol": "BTCUSDT",
    "side": "long",
    "size": 0.015,
    "entry_price": 95000.0,
    "current_price": 96200.0,
    "unrealized_pnl": 18.0,
    "leverage": 3,
    "margin": 475.0
  }
]
```

---

---

### Funding

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/funding` | List funding payments | Yes |
| `GET` | `/api/funding/summary` | Funding summary statistics | Yes |

#### `GET /api/funding`

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `days` | int | Lookback period (default: 30) |
| `symbol` | string | Filter by symbol |

---

### Exchanges

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/exchanges` | List all supported exchanges | No |
| `GET` | `/api/exchanges/{name}/info` | Get exchange details | No |
| `GET` | `/api/exchanges/{name}/symbols` | List tradeable symbols for exchange | No |

**Response (200) for `GET /api/exchanges`:**
```json
{
  "exchanges": [
    {
      "name": "bitget",
      "display_name": "Bitget",
      "supports_demo": true,
      "auth_type": "api_key",
      "requires_passphrase": true
    },
    {
      "name": "weex",
      "display_name": "Weex",
      "supports_demo": true,
      "auth_type": "api_key",
      "requires_passphrase": true
    },
    {
      "name": "hyperliquid",
      "display_name": "Hyperliquid",
      "supports_demo": true,
      "auth_type": "wallet",
      "requires_passphrase": false
    },
    {
      "name": "bitunix",
      "display_name": "Bitunix",
      "supports_demo": false,
      "auth_type": "api_key",
      "requires_passphrase": true
    },
    {
      "name": "bingx",
      "display_name": "BingX",
      "supports_demo": true,
      "auth_type": "api_key",
      "requires_passphrase": false
    }
  ]
}
```

---

### Affiliate

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/affiliate-links` | List active affiliate links | Yes |
| `PUT` | `/api/affiliate-links/{exchange}` | Create/update affiliate link | Admin |
| `DELETE` | `/api/affiliate-links/{exchange}` | Delete affiliate link | Admin |
| `POST` | `/api/affiliate-links/verify-uid` | Verify user UID for exchange | Yes |

---

### Admin (Logs)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/admin/audit-logs` | List audit logs (paginated) | Admin |
| `DELETE` | `/api/admin/audit-logs` | Purge old audit logs | Admin |
| `GET` | `/api/admin/events` | List event logs (paginated) | Admin |
| `GET` | `/api/admin/events/stats` | Event statistics summary | Admin |
| `DELETE` | `/api/admin/events` | Purge old event logs | Admin |

### Admin (Revenue)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/admin/revenue` | List revenue entries (filtered) | Admin |
| `POST` | `/api/admin/revenue/sync` | Trigger manual revenue sync | Admin |

### Admin (Broadcasts)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `POST` | `/api/admin/broadcasts` | Create a broadcast | Admin |
| `GET` | `/api/admin/broadcasts` | List broadcasts | Admin |
| `GET` | `/api/admin/broadcasts/{id}` | Get broadcast details | Admin |
| `GET` | `/api/admin/broadcasts/{id}/targets` | Get broadcast targets | Admin |
| `POST` | `/api/admin/broadcasts/{id}/preview` | Preview broadcast | Admin |
| `POST` | `/api/admin/broadcasts/{id}/send` | Send broadcast | Admin |
| `POST` | `/api/admin/broadcasts/{id}/cancel` | Cancel broadcast | Admin |
| `DELETE` | `/api/admin/broadcasts/{id}` | Delete broadcast | Admin |
| `GET` | `/api/admin/broadcasts/{id}/progress` | Get send progress | Admin |

---

### Users (Admin)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/users` | List all users | Admin |
| `POST` | `/api/users` | Create a new user | Admin |
| `PUT` | `/api/users/{id}` | Update user | Admin |
| `DELETE` | `/api/users/{id}` | Soft-delete user | Admin |

---

### Tax Report

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/tax-report` | Tax report data as JSON (with query filters) | Yes |
| `GET` | `/api/tax-report/csv` | Download tax report as CSV | Yes |

---

### Copy Trading

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `POST` | `/api/copy-trading/validate-source` | Validate a Hyperliquid source wallet | Yes |
| `GET` | `/api/exchanges/{exchange}/leverage-limits` | Get leverage limits for exchange | Yes |

---

### Notifications

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/notifications` | List notifications for current user | Yes |

---

### WebSocket

| Protocol | Path | Description | Auth |
|----------|------|-------------|------|
| `WS` | `/api/ws?token=<jwt>` | Real-time events stream | Yes (via query param) |

**Events received:**

| Event Type | Description |
|------------|-------------|
| `bot_started` | Bot has been started |
| `bot_stopped` | Bot has been stopped |
| `trade_opened` | New trade opened |
| `trade_closed` | Trade has been closed |

**Example (JavaScript):**
```javascript
const ws = new WebSocket(`ws://localhost:8000/api/ws?token=${accessToken}`);

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(`Event: ${data.type}`, data.payload);
};
```

---

### Monitoring

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/metrics` | Prometheus metrics | No |
| `GET` | `/api/health` | System health check | No |
| `GET` | `/api/status` | Basic bot status | Yes |
| `GET` | `/api/version` | Build version info | No |

---

## Rate Limiting

Key endpoints are rate-limited:

| Endpoint | Limit |
|----------|-------|
| `POST /api/auth/login` | 5/minute |
| `POST /api/auth/refresh` | 5/minute |
| `PUT /api/auth/change-password` | 3/minute |

---

## Error Responses

All errors follow a consistent format:

```json
{
  "detail": "Human-readable error message"
}
```

| Status Code | Meaning |
|-------------|---------|
| 400 | Bad request / validation error |
| 401 | Unauthorized (missing/invalid token) |
| 403 | Forbidden (insufficient permissions) |
| 404 | Resource not found |
| 409 | Conflict (e.g., duplicate username) |
| 429 | Too many requests (rate limited) |
| 502 | Exchange API error |
| 503 | Service unavailable (orchestrator not ready) |

---

## Security Headers

All responses include:

| Header | Value |
|--------|-------|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `X-XSS-Protection` | `1; mode=block` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
