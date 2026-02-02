# Sprint Plan: Multi-Tenant Trading Platform

## Objective
Transform the single-tenant Bitget Trading Bot into a multi-tenant, multi-account SaaS platform where users can register, add their own exchange credentials via a web interface, and manage multiple trading bot instances independently.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MULTI-TENANT TRADING PLATFORM                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    WEB INTERFACE (React/Vue)                        │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │    │
│  │  │  Login   │  │ Register │  │ Dashboard│  │ Account Settings │   │    │
│  │  │  /Logout │  │          │  │ (per-user)│  │ (API Keys, Risk) │   │    │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                              │ JWT Auth                                      │
│                              ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      FASTAPI BACKEND                                │    │
│  │  ┌────────────┐  ┌────────────┐  ┌─────────────┐  ┌────────────┐  │    │
│  │  │ Auth API   │  │ User API   │  │ Trading API │  │ Admin API  │  │    │
│  │  │ /api/auth  │  │ /api/users │  │ /api/trades │  │ /api/admin │  │    │
│  │  └────────────┘  └────────────┘  └─────────────┘  └────────────┘  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                              │                                               │
│                              ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                   MULTI-TENANT ORCHESTRATOR                         │    │
│  │  ┌──────────────────────────────────────────────────────────────┐  │    │
│  │  │  User 1 Bot Instance  │  User 2 Bot Instance  │  User N...   │  │    │
│  │  │  ├── BitgetClient     │  ├── BitgetClient     │              │  │    │
│  │  │  ├── RiskManager      │  ├── RiskManager      │              │  │    │
│  │  │  ├── Strategy         │  ├── Strategy         │              │  │    │
│  │  │  └── Notifier         │  └── Notifier         │              │  │    │
│  │  └──────────────────────────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                              │                                               │
│                              ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      DATA LAYER                                     │    │
│  │  ┌────────────┐  ┌─────────────────┐  ┌─────────────────────────┐ │    │
│  │  │ PostgreSQL │  │ Redis (Cache/   │  │ Credential Vault        │ │    │
│  │  │ (Multi-    │  │  Sessions)      │  │ (Encrypted API Keys)    │ │    │
│  │  │  tenant)   │  │                 │  │                         │ │    │
│  │  └────────────┘  └─────────────────┘  └─────────────────────────┘ │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Tasks (Prioritized by RICE Score)

| # | Task | Priority | Effort | Dependencies | RICE | Status |
|---|------|----------|--------|--------------|------|--------|
| 1 | Create database schema with multi-tenant tables | Must | M | None | 9.0 | Pending |
| 2 | Implement credential encryption module | Must | M | None | 8.5 | Pending |
| 3 | Add user authentication (JWT + sessions) | Must | L | #1 | 8.0 | Pending |
| 4 | Create user registration/login API endpoints | Must | M | #1, #3 | 7.5 | Pending |
| 5 | Add user_id to all existing database queries | Must | L | #1 | 7.0 | Pending |
| 6 | Create credential management API (add/rotate API keys) | Must | M | #2, #3 | 6.5 | Pending |
| 7 | Build MultiTenantOrchestrator for bot instances | Must | XL | #5, #6 | 6.0 | Pending |
| 8 | Implement per-user RiskManager isolation | Must | M | #5, #7 | 5.5 | Pending |
| 9 | Create web frontend for authentication | Should | L | #4 | 5.0 | Pending |
| 10 | Build account settings UI (API keys, risk config) | Should | L | #6, #9 | 4.5 | Pending |
| 11 | Add per-user WebSocket channels | Should | M | #7, #9 | 4.0 | Pending |
| 12 | Implement audit logging | Should | S | #3 | 3.5 | Pending |
| 13 | Add role-based access control (Admin/Trader/Viewer) | Could | M | #3 | 3.0 | Pending |
| 14 | Create admin dashboard for system monitoring | Could | L | #13 | 2.5 | Pending |
| 15 | Add multi-strategy support per user | Could | L | #7 | 2.0 | Pending |
| 16 | Implement usage billing/quotas | Won't | XL | #7 | 1.0 | Deferred |

---

## Critical Path

```
[#1 Database Schema] ─┬─→ [#3 JWT Auth] ───→ [#4 Auth API] ──┐
                      │                                       │
                      └─→ [#5 Add user_id] ──────────────────┤
                                                              │
[#2 Encryption] ──────────────────→ [#6 Credential API] ─────┤
                                                              │
                                                              ▼
                                    [#7 MultiTenantOrchestrator] ──→ [#8 RiskManager]
                                              │
                                              ▼
                                    [#9 Frontend] ──→ [#10 Settings UI] ──→ [#11 WebSocket]
```

---

## Phase 1: Foundation (Week 1-2)

### Task #1: Database Schema with Multi-Tenant Tables

**Description**: Create new database schema supporting multiple users, accounts, and credentials with proper isolation.

**Files to Create/Modify**:
- `src/models/migrations/001_multi_tenant_schema.py`
- `src/models/user.py`
- `src/models/credential.py`
- `src/models/bot_instance.py`

**Schema**:
```sql
-- Users table
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    is_admin BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- API Credentials (encrypted)
CREATE TABLE user_credentials (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    exchange VARCHAR(50) NOT NULL DEFAULT 'bitget',
    credential_type VARCHAR(20) CHECK(credential_type IN ('live', 'demo')),
    api_key_encrypted TEXT NOT NULL,
    api_secret_encrypted TEXT NOT NULL,
    passphrase_encrypted TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used TIMESTAMP,
    UNIQUE(user_id, name)
);

-- Bot instances per user
CREATE TABLE bot_instances (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    credential_id INTEGER NOT NULL REFERENCES user_credentials(id),
    name VARCHAR(100) NOT NULL,
    config JSONB NOT NULL DEFAULT '{}',
    is_running BOOLEAN DEFAULT FALSE,
    last_heartbeat TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, name)
);

-- Add user_id to existing tables
ALTER TABLE trades ADD COLUMN user_id INTEGER REFERENCES users(id);
ALTER TABLE trades ADD COLUMN bot_instance_id INTEGER REFERENCES bot_instances(id);
CREATE INDEX idx_trades_user ON trades(user_id);
CREATE INDEX idx_trades_user_status ON trades(user_id, status);

-- Sessions
CREATE TABLE user_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Audit log
CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id INTEGER,
    details JSONB,
    ip_address INET,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_audit_user_time ON audit_logs(user_id, created_at DESC);
```

**Acceptance Criteria**:
- [ ] All tables created with proper foreign keys
- [ ] Indexes for common query patterns
- [ ] Migration script runs successfully
- [ ] Backward compatible (old data preserved)

---

### Task #2: Credential Encryption Module

**Description**: Implement secure encryption for storing API keys using AES-256-GCM.

**Files to Create**:
- `src/security/__init__.py`
- `src/security/encryption.py`
- `src/security/credential_manager.py`

**Implementation**:
```python
# src/security/encryption.py
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os
import base64

class CredentialEncryption:
    def __init__(self, master_key: bytes = None):
        """Initialize with master key from env or generate"""
        if master_key is None:
            master_key = os.environ.get('ENCRYPTION_MASTER_KEY')
            if master_key:
                master_key = base64.b64decode(master_key)
            else:
                raise ValueError("ENCRYPTION_MASTER_KEY not set")
        self.aesgcm = AESGCM(master_key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt and return base64-encoded ciphertext"""
        nonce = os.urandom(12)
        ciphertext = self.aesgcm.encrypt(nonce, plaintext.encode(), None)
        return base64.b64encode(nonce + ciphertext).decode()

    def decrypt(self, encrypted: str) -> str:
        """Decrypt base64-encoded ciphertext"""
        data = base64.b64decode(encrypted)
        nonce, ciphertext = data[:12], data[12:]
        return self.aesgcm.decrypt(nonce, ciphertext, None).decode()
```

**Acceptance Criteria**:
- [ ] AES-256-GCM encryption implemented
- [ ] Master key loaded from environment variable
- [ ] Unit tests for encrypt/decrypt round-trip
- [ ] Credentials never logged in plaintext

---

### Task #3: User Authentication (JWT + Sessions)

**Description**: Implement JWT-based authentication with refresh tokens.

**Files to Create**:
- `src/auth/__init__.py`
- `src/auth/jwt_handler.py`
- `src/auth/password.py`
- `src/auth/dependencies.py`

**Implementation**:
```python
# src/auth/dependencies.py
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer
from jose import JWTError, jwt

security = HTTPBearer()

async def get_current_user(
    credentials = Depends(security),
    db = Depends(get_db)
) -> int:
    """Extract and validate user from JWT token"""
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=["HS256"]
        )
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return int(user_id)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
```

**Acceptance Criteria**:
- [ ] JWT tokens with 15-minute expiry
- [ ] Refresh tokens with 7-day expiry
- [ ] Password hashing with bcrypt
- [ ] Token blacklisting on logout
- [ ] Rate limiting on auth endpoints

---

### Task #4: User Registration/Login API Endpoints

**Description**: Create REST API endpoints for user management.

**Files to Modify**:
- `src/dashboard/app.py` (add auth routes)

**New Endpoints**:
```
POST /api/auth/register     - Create new user account
POST /api/auth/login        - Authenticate and get tokens
POST /api/auth/refresh      - Refresh access token
POST /api/auth/logout       - Invalidate tokens
GET  /api/auth/me           - Get current user profile
PUT  /api/auth/me           - Update user profile
POST /api/auth/change-password - Change password
```

**Acceptance Criteria**:
- [ ] Registration with email validation
- [ ] Login returns access + refresh tokens
- [ ] Refresh endpoint issues new access token
- [ ] Logout invalidates session
- [ ] All endpoints have rate limiting

---

## Phase 2: Data Isolation (Week 2-3)

### Task #5: Add user_id to All Database Queries

**Description**: Update all database operations to filter by user_id for proper tenant isolation.

**Files to Modify**:
- `src/models/trade_database.py`
- `src/data/funding_tracker.py`
- All dashboard API endpoints

**Example Changes**:
```python
# Before
async def get_open_trades(self, symbol: str = None) -> List[Trade]:
    cursor = await db.execute("SELECT * FROM trades WHERE status = 'open'")

# After
async def get_open_trades(self, user_id: int, symbol: str = None) -> List[Trade]:
    cursor = await db.execute(
        "SELECT * FROM trades WHERE user_id = ? AND status = 'open'",
        (user_id,)
    )
```

**Acceptance Criteria**:
- [ ] All SELECT queries filter by user_id
- [ ] All INSERT queries include user_id
- [ ] No cross-tenant data leaks possible
- [ ] Unit tests verify isolation

---

### Task #6: Credential Management API

**Description**: API endpoints for users to add, rotate, and remove exchange API keys.

**New Endpoints**:
```
GET    /api/credentials              - List user's credentials (masked)
POST   /api/credentials              - Add new credential
PUT    /api/credentials/{id}         - Update credential
DELETE /api/credentials/{id}         - Revoke credential
POST   /api/credentials/{id}/test    - Test credential validity
```

**Security Requirements**:
- API keys shown only on creation (masked afterwards)
- Test endpoint verifies with exchange
- Revocation is immediate
- Audit log for all operations

**Acceptance Criteria**:
- [ ] CRUD operations for credentials
- [ ] Credentials encrypted at rest
- [ ] Keys masked in responses (show only last 4 chars)
- [ ] Test endpoint validates with Bitget API
- [ ] Audit log entries created

---

## Phase 3: Multi-Instance Trading (Week 3-4)

### Task #7: MultiTenantOrchestrator

**Description**: Create orchestration layer to manage multiple trading bot instances.

**Files to Create**:
- `src/bot/orchestrator.py`
- `src/bot/bot_instance.py`

**Implementation**:
```python
class MultiTenantOrchestrator:
    """Manages multiple trading bot instances across users"""

    def __init__(self):
        self.instances: Dict[int, BotInstance] = {}  # bot_instance_id -> instance
        self.credential_manager = CredentialManager()

    async def start_instance(self, bot_instance_id: int):
        """Start a specific bot instance"""
        config = await self.load_instance_config(bot_instance_id)
        credentials = await self.credential_manager.get_decrypted(config.credential_id)

        instance = BotInstance(
            instance_id=bot_instance_id,
            user_id=config.user_id,
            credentials=credentials,
            trading_config=config.config
        )

        await instance.start()
        self.instances[bot_instance_id] = instance

    async def stop_instance(self, bot_instance_id: int):
        """Gracefully stop a bot instance"""
        if instance := self.instances.get(bot_instance_id):
            await instance.stop()
            del self.instances[bot_instance_id]

    async def get_instance_status(self, bot_instance_id: int) -> dict:
        """Get status of a specific instance"""
        instance = self.instances.get(bot_instance_id)
        if not instance:
            return {"status": "stopped"}
        return await instance.get_status()
```

**New Endpoints**:
```
GET    /api/bots                     - List user's bot instances
POST   /api/bots                     - Create new bot instance
GET    /api/bots/{id}                - Get bot instance details
PUT    /api/bots/{id}                - Update bot configuration
DELETE /api/bots/{id}                - Delete bot instance
POST   /api/bots/{id}/start          - Start trading
POST   /api/bots/{id}/stop           - Stop trading
GET    /api/bots/{id}/status         - Get real-time status
```

**Acceptance Criteria**:
- [ ] Start/stop individual bot instances
- [ ] Each instance has isolated state
- [ ] Instance config persisted to database
- [ ] Graceful shutdown closes positions
- [ ] Health monitoring per instance

---

### Task #8: Per-User RiskManager Isolation

**Description**: Each bot instance gets its own risk manager with user-defined limits.

**Files to Modify**:
- `src/risk/risk_manager.py`

**Changes**:
```python
class RiskManager:
    def __init__(self, user_id: int, bot_instance_id: int, config: RiskConfig):
        self.user_id = user_id
        self.bot_instance_id = bot_instance_id
        self.config = config
        self.daily_stats = None

    async def load_daily_stats(self):
        """Load stats for this specific bot instance"""
        self.daily_stats = await db.fetchone(
            "SELECT * FROM daily_stats WHERE bot_instance_id = ? AND date = ?",
            (self.bot_instance_id, date.today())
        )
```

**Configurable Per-User**:
- `max_trades_per_day`
- `daily_loss_limit_percent`
- `position_size_percent`
- `leverage`
- `take_profit_percent`
- `stop_loss_percent`

**Acceptance Criteria**:
- [ ] Risk limits configurable per bot instance
- [ ] Daily stats tracked per instance
- [ ] No cross-instance limit interference
- [ ] User can view risk stats in UI

---

## Phase 4: Web Interface (Week 4-5)

### Task #9: Web Frontend for Authentication

**Description**: Build React/Vue frontend for login, registration, and session management.

**Files to Create**:
- `frontend/` directory structure
- `frontend/src/pages/Login.tsx`
- `frontend/src/pages/Register.tsx`
- `frontend/src/context/AuthContext.tsx`

**Features**:
- Login form with email/password
- Registration form with validation
- Password reset flow
- Remember me functionality
- Auto-logout on token expiry

**Acceptance Criteria**:
- [ ] Login/register forms functional
- [ ] JWT stored securely (httpOnly cookies preferred)
- [ ] Auto-refresh of access tokens
- [ ] Logout clears all tokens
- [ ] Loading states and error handling

---

### Task #10: Account Settings UI

**Description**: Web interface for managing API keys and trading configuration.

**Features**:
- Add/remove exchange credentials
- Configure trading parameters per bot
- View credential status (valid/invalid)
- Risk configuration UI

**Acceptance Criteria**:
- [ ] Add credential form with validation
- [ ] Credential list with masked keys
- [ ] Delete confirmation modal
- [ ] Trading config editor
- [ ] Real-time validation feedback

---

### Task #11: Per-User WebSocket Channels

**Description**: WebSocket connections scoped to individual users.

**Implementation**:
```python
class ConnectionManager:
    def __init__(self):
        self.connections: Dict[int, List[WebSocket]] = {}  # user_id -> connections

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.connections:
            self.connections[user_id] = []
        self.connections[user_id].append(websocket)

    async def broadcast_to_user(self, user_id: int, message: dict):
        """Send message to all connections for a specific user"""
        for connection in self.connections.get(user_id, []):
            await connection.send_json(message)
```

**Acceptance Criteria**:
- [ ] WebSocket requires authentication
- [ ] Messages scoped to user's data only
- [ ] Real-time trade notifications
- [ ] Bot status updates
- [ ] Reconnection handling

---

## Phase 5: Production Hardening (Week 5-6)

### Task #12: Audit Logging

**Description**: Log all sensitive operations for compliance and debugging.

**Events to Log**:
- User login/logout
- Credential add/remove/access
- Bot start/stop
- Trade execution
- Configuration changes
- Admin actions

**Acceptance Criteria**:
- [ ] All sensitive actions logged
- [ ] Logs include user_id, timestamp, IP
- [ ] Log viewer in admin UI
- [ ] Log retention policy (90 days default)

---

### Task #13: Role-Based Access Control

**Description**: Implement RBAC with Admin, Trader, and Viewer roles.

**Roles**:
| Role | Permissions |
|------|-------------|
| Admin | Full access, manage all users |
| Trader | Trade, manage own credentials |
| Viewer | Read-only access to own data |

**Acceptance Criteria**:
- [ ] Role stored in user table
- [ ] Permission checks on all endpoints
- [ ] Admin can impersonate users
- [ ] Viewer cannot start/stop bots

---

### Task #14: Admin Dashboard

**Description**: System monitoring dashboard for administrators.

**Features**:
- User management (list, disable, delete)
- System health metrics
- Active bot instances overview
- Error log viewer
- Usage statistics

**Acceptance Criteria**:
- [ ] Admin-only access
- [ ] User CRUD operations
- [ ] System metrics display
- [ ] Bot instance monitoring
- [ ] Audit log viewer

---

## Risk Register

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Credential leak | Low | Critical | AES-256 encryption, audit logging, no plaintext logging |
| Cross-tenant data leak | Medium | Critical | User_id on all queries, integration tests, query interceptors |
| Bot instance memory leak | Medium | High | Resource limits, health checks, auto-restart |
| Database corruption | Low | High | PostgreSQL transactions, daily backups, WAL mode |
| Authentication bypass | Low | Critical | JWT validation, session management, rate limiting |
| Performance degradation | Medium | Medium | Connection pooling, caching, query optimization |

---

## Success Criteria

- [ ] Multiple users can register and login independently
- [ ] Each user can add their own Bitget API credentials securely
- [ ] Each user can create and manage multiple bot instances
- [ ] Trading data is fully isolated between users
- [ ] Real-time updates via WebSocket are user-scoped
- [ ] Admin can monitor all users and system health
- [ ] All sensitive operations are audit logged
- [ ] System handles 100+ concurrent users without degradation

---

## Out of Scope (This Sprint)

- Billing/subscription system
- Multi-exchange support (Binance, Bybit) - **Bitget only (lowest fees)**
- Mobile app
- Two-factor authentication (future enhancement)
- Social/copy trading features
- Multi-region deployment
- Technical Analysis indicators (MACD, RSI, etc.) - **Deliberate choice: contrarian/sentiment strategy only**
- Altcoin support - **BTC + ETH only (highest liquidity, less manipulation)**

---

## Estimated Completion

**Total Tasks**: 14 (core) + 2 (optional)
**Effort**: ~6 weeks for core features
**Buffer**: 20% for unknowns

**Team Breakdown** (if applicable):
- Backend: Tasks #1-8, #12-13
- Frontend: Tasks #9-11, #14
- DevOps: Database migration, deployment

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| Database | PostgreSQL (migrate from SQLite) |
| Cache/Sessions | Redis |
| Backend | FastAPI (existing) |
| Frontend | React + TypeScript + TailwindCSS |
| Auth | JWT + bcrypt |
| Encryption | cryptography (AES-256-GCM) |
| WebSocket | FastAPI WebSockets |
| Task Queue | Celery (optional, for background jobs) |

---

## Configuration Changes

**New Environment Variables**:
```bash
# Database (migrate from SQLite)
DATABASE_URL=postgresql://user:pass@localhost:5432/trading_bot

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
JWT_SECRET=<generate-secure-key>
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# Encryption
ENCRYPTION_MASTER_KEY=<base64-encoded-32-byte-key>

# Admin
ADMIN_EMAIL=admin@example.com
ADMIN_INITIAL_PASSWORD=<change-me>
```

---

## Next Steps

1. **Review this plan** - Any adjustments needed?
2. **Create GitHub issues** - Run `/plan --issues` to create epic + child issues
3. **Start implementation** - Begin with Task #1 (database schema)
4. **Use /autonomous** - Run `/autonomous --epic <NUMBER>` for automated development

---

*Plan created: 2026-02-01*
*Branch: feature/multi-tenant-platform*
*Ready for /autonomous processing*
