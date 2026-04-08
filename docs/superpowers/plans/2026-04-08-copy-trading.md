# Copy Trading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `copy_trading` strategy that tracks a public Hyperliquid wallet and copies its entries/closes onto the user's chosen exchange, with budget+slot sizing and validation.

**Architecture:** New strategy plugin (`CopyTradingStrategy`) registered alongside `EdgeIndicatorStrategy` and `LiquidationHunterStrategy`. A new read-only `HyperliquidWalletTracker` calls public HL endpoints (no auth). The strategy is *self-managed*: instead of being driven by the per-symbol bot worker loop, it implements `run_tick(ctx)` and polls source-wallet fills itself, dispatching trades through the existing `trade_executor`. State (`last_processed_fill_ms`) is persisted in a new `strategy_state` Text/JSON column on `bot_configs`. Wallet validation and per-exchange leverage limits are exposed via two new API endpoints.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, Alembic, pytest (asyncio_mode=auto), React 18 + TypeScript + Vite, Vitest.

---

## Spec adjustments discovered during exploration

These differ from the original spec and are baked into this plan:

1. **`strategy_state` does not exist** on `BotConfig`. We add it as a `Text` column (matching the existing JSON-as-text convention) via Alembic migration `018`.
2. **No exchange client has `get_max_leverage(symbol)`**. Adding it on all 5 clients is too much for v1. Instead we ship a simple `LEVERAGE_LIMITS` constant table per exchange (per-symbol or default fallback) in `src/exchanges/leverage_limits.py`. Live verification still happens at trade execution by catching exchange errors. This is documented as an approximation in the bot builder UI.
3. **Strategy interface is per-symbol** (`generate_signal(symbol)`), which doesn't fit copy-trading. We add an opt-in flag `is_self_managed: bool = False` on `BaseStrategy` and a new `async def run_tick(self, ctx) -> None` method. The bot worker, on each scheduled tick, checks `is_self_managed`: if `True`, calls `run_tick(ctx)` and skips the per-symbol loop entirely. Existing strategies are untouched.
4. **`symbol_fetcher` already has `get_exchange_symbols(exchange) -> list[str]`** — we use this for `is_symbol_listed` checks, no new low-level helper needed.
5. **Source-wallet fills are fetched via `info.user_fills(address)`** (the existing HL client uses this; `user_fills_by_time` is not in use). We filter by timestamp client-side.

---

## File structure

**Create:**
- `migrations/versions/018_add_strategy_state_to_bot_configs.py` — adds `strategy_state` Text column
- `src/exchanges/leverage_limits.py` — static leverage limit lookup per exchange/symbol
- `src/exchanges/hyperliquid/wallet_tracker.py` — read-only HL public-API wrapper
- `src/strategy/copy_trading.py` — `CopyTradingStrategy` class
- `src/api/routers/copy_trading.py` — wallet validation + leverage limits endpoints
- `tests/unit/exchanges/test_hyperliquid_wallet_tracker.py`
- `tests/unit/exchanges/test_leverage_limits.py`
- `tests/unit/strategy/test_copy_trading.py`
- `tests/unit/api/test_copy_trading_router.py`
- `frontend/src/components/bots/CopyTradingValidator.tsx` — wallet preview UI block
- `frontend/src/api/copyTrading.ts` — frontend API client for the two new endpoints

**Modify:**
- `src/strategy/base.py` — add `is_self_managed` class attr + `run_tick()` default impl
- `src/strategy/__init__.py` — import copy_trading so `StrategyRegistry.register()` runs
- `src/models/database.py::BotConfig` — add `strategy_state = Column(Text, nullable=True)`
- `src/bot/bot_worker.py` — branch on `strategy.is_self_managed` in the schedule loop
- `src/api/routers/bots.py::_check_symbol_conflicts` — relax for `copy_trading` strategy
- `src/api/main.py` (or wherever routers are registered) — register the new router
- `frontend/src/components/bots/BotBuilderStepStrategy.tsx` — render `text` param input type and the `CopyTradingValidator` when `strategy_type === 'copy_trading'`
- `frontend/src/pages/Bots.tsx` — render copy-bot card variant (source wallet + slots)
- `frontend/src/i18n/de.json`, `en.json` — add new param labels and validation error strings
- `CHANGELOG.md` — release notes

---

## Phase 1 — Database & Strategy interface

### Task 1: Alembic migration for `strategy_state`

**Files:**
- Create: `migrations/versions/018_add_strategy_state_to_bot_configs.py`
- Modify: `src/models/database.py` (add column to BotConfig)

- [ ] **Step 1: Write the migration**

```python
"""Add strategy_state JSON column to bot_configs.

Revision ID: 018
Revises: 017
Create Date: 2026-04-08

Adds a free-form JSON column for strategies to persist runtime state
that should NOT be part of user-facing strategy_params (e.g. the copy
trading strategy's last_processed_fill_ms).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bot_configs",
        sa.Column("strategy_state", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bot_configs", "strategy_state")
```

- [ ] **Step 2: Add column to ORM model**

In `src/models/database.py::BotConfig` (alongside the existing `strategy_params = Column(Text, nullable=True)` line):

```python
    strategy_state = Column(Text, nullable=True)  # JSON, runtime state managed by the strategy
```

- [ ] **Step 3: Verify migration applies cleanly**

Run inside the dev container:
```bash
alembic upgrade head
alembic current
```
Expected: `018 (head)`

- [ ] **Step 4: Verify rollback works**

```bash
alembic downgrade -1
alembic current
```
Expected: `017`

Then re-upgrade: `alembic upgrade head`

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/018_add_strategy_state_to_bot_configs.py src/models/database.py
git commit -m "feat: add strategy_state column to bot_configs (#NNN)"
```

---

### Task 2: Self-managed strategy hook in BaseStrategy

**Files:**
- Modify: `src/strategy/base.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/strategy/test_base_strategy_self_managed.py`:

```python
"""Test the self-managed strategy interface added for copy trading."""
import pytest
from src.strategy.base import BaseStrategy


class _NormalStrategy(BaseStrategy):
    async def generate_signal(self, symbol):  # type: ignore[override]
        return None
    async def should_trade(self, signal):  # type: ignore[override]
        return False, ""
    @classmethod
    def get_param_schema(cls):
        return {}
    @classmethod
    def get_description(cls):
        return ""


def test_base_strategy_default_is_not_self_managed():
    s = _NormalStrategy()
    assert s.is_self_managed is False


@pytest.mark.asyncio
async def test_base_strategy_run_tick_default_is_noop():
    s = _NormalStrategy()
    # Default run_tick should be a safe no-op for non-self-managed strategies
    await s.run_tick(ctx=None)
```

- [ ] **Step 2: Run test, expect failure**

```bash
pytest tests/unit/strategy/test_base_strategy_self_managed.py -v
```
Expected: `AttributeError: 'BaseStrategy' has no attribute 'is_self_managed'` or similar.

- [ ] **Step 3: Add the interface to BaseStrategy**

In `src/strategy/base.py`, inside `class BaseStrategy(ABC):` (after `__init__`):

```python
    #: Self-managed strategies are NOT driven by the per-symbol BotWorker loop.
    #: They implement `run_tick()` and handle their own signal/trade dispatch.
    #: Used by CopyTradingStrategy to poll a source wallet's fills.
    is_self_managed: bool = False

    async def run_tick(self, ctx) -> None:
        """Self-managed tick entry point.

        Default no-op for non-self-managed strategies. Self-managed strategies
        override this and ignore `generate_signal()` / `should_trade()` /
        `should_exit()` (the BotWorker won't call them).

        Args:
            ctx: A `StrategyTickContext` providing DB session, exchange client,
                 bot config, trade executor, notifier dispatch, and user_id.
        """
        return None
```

- [ ] **Step 4: Run test, expect pass**

```bash
pytest tests/unit/strategy/test_base_strategy_self_managed.py -v
```
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/strategy/base.py tests/unit/strategy/test_base_strategy_self_managed.py
git commit -m "feat: add is_self_managed flag and run_tick() hook to BaseStrategy"
```

---

### Task 3: BotWorker self-managed branch

**Files:**
- Modify: `src/bot/bot_worker.py` around line 788 (the schedule loop)

- [ ] **Step 1: Find the exact loop**

Open `src/bot/bot_worker.py` and locate the section where the per-symbol loop calls `await self._strategy.generate_signal(symbol)`. It's around line 788 (verified during exploration).

- [ ] **Step 2: Add the self-managed branch ABOVE the per-symbol loop**

Replace the start of the schedule iteration with:

```python
        # Self-managed strategies (e.g. copy_trading) handle their own
        # signal generation and trade dispatch — bypass the per-symbol loop.
        if self._strategy.is_self_managed:
            from src.strategy.base import StrategyTickContext
            ctx = StrategyTickContext(
                bot_config=self._config,
                user_id=self._config.user_id,
                exchange_client=client,
                trade_executor=self,  # BotWorker is also the TradeExecutorMixin
                send_notification=self._send_notification,
                logger=logger,
                bot_config_id=self.bot_config_id,
            )
            try:
                await self._strategy.run_tick(ctx)
            except Exception as e:
                logger.error("[Bot:%s] Self-managed run_tick error: %s", self.bot_config_id, e)
            return  # Skip the per-symbol loop entirely
        # --- existing per-symbol loop continues below ---
```

- [ ] **Step 3: Add `StrategyTickContext` dataclass to `src/strategy/base.py`**

```python
@dataclass
class StrategyTickContext:
    """Injected context for self-managed strategies (run_tick)."""
    bot_config: Any  # BotConfig ORM object
    user_id: int
    exchange_client: Any  # ExchangeClient
    trade_executor: Any  # TradeExecutorMixin (typically the BotWorker itself)
    send_notification: Any  # async callable: (lambda n: n.send_*(...), event_type, summary)
    logger: Any
    bot_config_id: int
```

- [ ] **Step 4: Smoke-test that existing bots still work**

Run the bot worker test suite:
```bash
pytest tests/unit/bot/ -v
```
Expected: all green (the new branch is gated on `is_self_managed=False` for existing strategies, so this is a no-op for them).

- [ ] **Step 5: Commit**

```bash
git add src/bot/bot_worker.py src/strategy/base.py
git commit -m "feat: bot worker dispatches to strategy.run_tick() for self-managed strategies"
```

---

## Phase 2 — Hyperliquid wallet tracker

### Task 4: `HyperliquidWalletTracker` class

**Files:**
- Create: `src/exchanges/hyperliquid/wallet_tracker.py`
- Test: `tests/unit/exchanges/test_hyperliquid_wallet_tracker.py`

- [ ] **Step 1: Write the dataclasses + failing test**

`tests/unit/exchanges/test_hyperliquid_wallet_tracker.py`:

```python
"""Tests for the read-only Hyperliquid wallet tracker."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.exchanges.hyperliquid.wallet_tracker import (
    HyperliquidWalletTracker,
    SourceFill,
    SourcePosition,
)


@pytest.fixture
def mock_info():
    """Mock the HL Info SDK object."""
    info = MagicMock()
    info.user_state = MagicMock(return_value={
        "assetPositions": [
            {
                "position": {
                    "coin": "BTC",
                    "szi": "0.5",  # positive = long, negative = short
                    "entryPx": "67000",
                    "leverage": {"value": 5, "type": "cross"},
                }
            }
        ]
    })
    info.user_fills = MagicMock(return_value=[
        {
            "coin": "BTC",
            "side": "B",  # B=buy/long, A=ask/short
            "sz": "0.5",
            "px": "67000",
            "time": 1712568000000,
            "dir": "Open Long",
            "hash": "0xabc",
        },
        {
            "coin": "ETH",
            "side": "A",
            "sz": "5",
            "px": "3500",
            "time": 1712567000000,
            "dir": "Open Short",
            "hash": "0xdef",
        },
    ])
    return info


@pytest.mark.asyncio
async def test_get_open_positions_normalizes_long(mock_info):
    tracker = HyperliquidWalletTracker(info=mock_info)
    positions = await tracker.get_open_positions("0x1234")
    assert len(positions) == 1
    p = positions[0]
    assert p.coin == "BTC"
    assert p.side == "long"
    assert p.size == 0.5
    assert p.entry_price == 67000.0
    assert p.leverage == 5


@pytest.mark.asyncio
async def test_get_open_positions_normalizes_short(mock_info):
    mock_info.user_state.return_value = {
        "assetPositions": [
            {"position": {"coin": "ETH", "szi": "-2.0",
                          "entryPx": "3500", "leverage": {"value": 10}}}
        ]
    }
    tracker = HyperliquidWalletTracker(info=mock_info)
    positions = await tracker.get_open_positions("0x1234")
    assert positions[0].side == "short"
    assert positions[0].size == 2.0


@pytest.mark.asyncio
async def test_get_fills_since_filters_by_timestamp(mock_info):
    tracker = HyperliquidWalletTracker(info=mock_info)
    # since_ms is between the two fills (BTC at 1712568000000, ETH at 1712567000000)
    fills = await tracker.get_fills_since("0x1234", since_ms=1712567500000)
    assert len(fills) == 1
    assert fills[0].coin == "BTC"
    assert fills[0].side == "long"
    assert fills[0].is_entry is True


@pytest.mark.asyncio
async def test_get_fills_since_returns_empty_when_no_new(mock_info):
    tracker = HyperliquidWalletTracker(info=mock_info)
    fills = await tracker.get_fills_since("0x1234", since_ms=9999999999999)
    assert fills == []


@pytest.mark.asyncio
async def test_recent_coins_returns_unique_set(mock_info):
    tracker = HyperliquidWalletTracker(info=mock_info)
    coins = await tracker.recent_coins("0x1234", since_ms=0)
    assert sorted(coins) == ["BTC", "ETH"]


@pytest.mark.asyncio
async def test_get_open_positions_handles_no_positions(mock_info):
    mock_info.user_state.return_value = {"assetPositions": []}
    tracker = HyperliquidWalletTracker(info=mock_info)
    positions = await tracker.get_open_positions("0x1234")
    assert positions == []
```

- [ ] **Step 2: Run test, expect import failure**

```bash
pytest tests/unit/exchanges/test_hyperliquid_wallet_tracker.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.exchanges.hyperliquid.wallet_tracker'`

- [ ] **Step 3: Implement the tracker**

Create `src/exchanges/hyperliquid/wallet_tracker.py`:

```python
"""Read-only Hyperliquid wallet tracker for the copy-trading strategy.

Wraps the public Hyperliquid Info API. Does NOT require API keys — all
endpoints used here are read-only against on-chain perpetuals data.
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

from hyperliquid.info import Info as HLInfo
from hyperliquid.utils import constants as hl_constants

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SourcePosition:
    coin: str
    side: str           # "long" | "short"
    size: float         # absolute, in base coin
    entry_price: float
    leverage: int


@dataclass
class SourceFill:
    coin: str
    side: str           # "long" | "short"
    size: float         # absolute, base coin
    price: float
    time_ms: int
    is_entry: bool      # True if direction string starts with "Open"
    hash: str


class HyperliquidWalletTracker:
    """Thin read-only wrapper around the public HL Info API."""

    def __init__(self, info: Optional[HLInfo] = None, *, mainnet: bool = True):
        if info is None:
            base_url = hl_constants.MAINNET_API_URL if mainnet else hl_constants.TESTNET_API_URL
            info = HLInfo(base_url, skip_ws=True)
        self._info = info

    async def _call(self, fn, *args, **kwargs):
        """Run a sync SDK call in a thread so we don't block the event loop."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def get_open_positions(self, wallet: str) -> list[SourcePosition]:
        try:
            state = await self._call(self._info.user_state, wallet)
        except Exception as e:
            logger.warning("HL user_state failed for %s: %s", wallet, e)
            return []
        out: list[SourcePosition] = []
        for entry in state.get("assetPositions", []):
            pos = entry.get("position") or {}
            try:
                szi = float(pos.get("szi", "0"))
            except (TypeError, ValueError):
                continue
            if szi == 0:
                continue
            try:
                lev = int((pos.get("leverage") or {}).get("value", 1))
            except (TypeError, ValueError):
                lev = 1
            out.append(SourcePosition(
                coin=pos.get("coin", ""),
                side="long" if szi > 0 else "short",
                size=abs(szi),
                entry_price=float(pos.get("entryPx") or 0),
                leverage=lev,
            ))
        return out

    async def get_fills_since(self, wallet: str, since_ms: int) -> list[SourceFill]:
        try:
            raw = await self._call(self._info.user_fills, wallet)
        except Exception as e:
            logger.warning("HL user_fills failed for %s: %s", wallet, e)
            return []
        if not isinstance(raw, list):
            return []
        out: list[SourceFill] = []
        for fill in raw:
            ts = int(fill.get("time", 0))
            if ts <= since_ms:
                continue
            side_letter = (fill.get("side") or "").upper()
            side = "long" if side_letter == "B" else "short"
            direction = (fill.get("dir") or "").lower()
            is_entry = direction.startswith("open")
            try:
                sz = abs(float(fill.get("sz", 0)))
                px = float(fill.get("px", 0))
            except (TypeError, ValueError):
                continue
            out.append(SourceFill(
                coin=fill.get("coin", ""),
                side=side,
                size=sz,
                price=px,
                time_ms=ts,
                is_entry=is_entry,
                hash=fill.get("hash", ""),
            ))
        # Sort ascending by time so callers can advance their watermark cleanly
        out.sort(key=lambda f: f.time_ms)
        return out

    async def recent_coins(self, wallet: str, since_ms: int = 0) -> list[str]:
        fills = await self.get_fills_since(wallet, since_ms)
        return sorted({f.coin for f in fills})

    async def close(self) -> None:
        # Info has no resources to release; provided for symmetry with other clients.
        return None
```

- [ ] **Step 4: Run tests, expect pass**

```bash
pytest tests/unit/exchanges/test_hyperliquid_wallet_tracker.py -v
```
Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/exchanges/hyperliquid/wallet_tracker.py tests/unit/exchanges/test_hyperliquid_wallet_tracker.py
git commit -m "feat: add HyperliquidWalletTracker for read-only public API access"
```

---

## Phase 3 — Static leverage limits table

### Task 5: `leverage_limits.py`

**Files:**
- Create: `src/exchanges/leverage_limits.py`
- Test: `tests/unit/exchanges/test_leverage_limits.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the static leverage limits lookup."""
import pytest
from src.exchanges.leverage_limits import get_max_leverage, ExchangeNotSupported


def test_bitget_btc_default():
    assert get_max_leverage("bitget", "BTCUSDT") == 125


def test_bitget_unknown_symbol_falls_back_to_default():
    assert get_max_leverage("bitget", "UNKNOWN") == 50


def test_hyperliquid_btc():
    assert get_max_leverage("hyperliquid", "BTC") == 50


def test_unknown_exchange_raises():
    with pytest.raises(ExchangeNotSupported):
        get_max_leverage("kraken", "BTCUSDT")


def test_case_insensitive_exchange_name():
    assert get_max_leverage("BITGET", "BTCUSDT") == 125
```

- [ ] **Step 2: Run test, expect import failure**

```bash
pytest tests/unit/exchanges/test_leverage_limits.py -v
```

- [ ] **Step 3: Implement**

Create `src/exchanges/leverage_limits.py`:

```python
"""Static per-exchange max leverage lookup.

This is an APPROXIMATION used by the bot builder to give the user immediate
feedback when configuring a copy-trading bot. The exchange itself remains
the source of truth — at trade execution time, leverage that exceeds the
real exchange limit is caught and reported.

Numbers reflect public docs as of 2026-04. Update if the exchanges change them.
"""

from typing import Optional


class ExchangeNotSupported(ValueError):
    """Raised when an exchange has no leverage limits configured."""


# Per-exchange: per-symbol overrides + default fallback
_LIMITS: dict[str, dict[str, int]] = {
    "bitget": {
        "_default": 50,
        "BTCUSDT": 125,
        "ETHUSDT": 125,
        "SOLUSDT": 75,
    },
    "bingx": {
        "_default": 50,
        "BTC-USDT": 125,
        "ETH-USDT": 100,
    },
    "hyperliquid": {
        "_default": 25,
        "BTC": 50,
        "ETH": 50,
        "SOL": 20,
    },
    "bitunix": {
        "_default": 50,
        "BTCUSDT": 100,
    },
    "weex": {
        "_default": 50,
        "BTCUSDT": 100,
    },
}


def get_max_leverage(exchange: str, symbol: str) -> int:
    """Return the max leverage for a symbol on a given exchange.

    Falls back to the exchange's `_default` if the symbol is not in the
    override list. Raises `ExchangeNotSupported` for unknown exchanges.
    """
    table = _LIMITS.get(exchange.lower())
    if table is None:
        raise ExchangeNotSupported(f"No leverage limits configured for {exchange}")
    return table.get(symbol, table["_default"])


def get_supported_exchanges() -> list[str]:
    return sorted(_LIMITS.keys())
```

- [ ] **Step 4: Run test, expect pass**

```bash
pytest tests/unit/exchanges/test_leverage_limits.py -v
```
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/exchanges/leverage_limits.py tests/unit/exchanges/test_leverage_limits.py
git commit -m "feat: add static per-exchange leverage limits table"
```

---

## Phase 4 — Wallet validation + leverage limits API

### Task 6: API endpoints

**Files:**
- Create: `src/api/routers/copy_trading.py`
- Modify: `src/api/main.py` (or wherever routers are mounted) — register the new router
- Test: `tests/unit/api/test_copy_trading_router.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for /api/copy-trading and /api/exchanges/{exchange}/leverage-limits."""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.api.main import app


@pytest.fixture
def mock_user(monkeypatch):
    """Bypass auth for these tests."""
    from src.auth.dependencies import get_current_user
    from src.models.database import User
    fake = User(id=1, username="tester")
    app.dependency_overrides[get_current_user] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_validate_source_rejects_bad_address(mock_user):
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.post("/api/copy-trading/validate-source", json={
            "wallet": "not-an-address",
            "target_exchange": "bitget",
        })
    assert r.status_code == 400
    assert "Wallet-Adresse" in r.json()["detail"]


@pytest.mark.asyncio
async def test_validate_source_returns_preview(mock_user):
    fake_fills = [
        type("F", (), {"coin": "BTC", "time_ms": 1712568000000, "side": "long",
                       "size": 0.5, "price": 67000, "is_entry": True, "hash": "0xa"})(),
        type("F", (), {"coin": "HYPE", "time_ms": 1712568000000, "side": "long",
                       "size": 100, "price": 12, "is_entry": True, "hash": "0xb"})(),
    ]
    with patch(
        "src.api.routers.copy_trading.HyperliquidWalletTracker"
    ) as TrackerCls, patch(
        "src.api.routers.copy_trading.get_exchange_symbols",
        new=AsyncMock(return_value=["BTCUSDT", "ETHUSDT", "SOLUSDT"]),
    ):
        instance = TrackerCls.return_value
        instance.get_open_positions = AsyncMock(return_value=[])
        instance.get_fills_since = AsyncMock(return_value=fake_fills)
        instance.close = AsyncMock()

        async with AsyncClient(app=app, base_url="http://test") as ac:
            r = await ac.post("/api/copy-trading/validate-source", json={
                "wallet": "0x" + "ab" * 20,
                "target_exchange": "bitget",
            })
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["trades_30d"] == 2
    assert "BTC" in body["available"]
    assert "HYPE" in body["unavailable"]


@pytest.mark.asyncio
async def test_leverage_limits_endpoint(mock_user):
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.get("/api/exchanges/bitget/leverage-limits", params={"symbol": "BTCUSDT"})
    assert r.status_code == 200
    assert r.json()["max_leverage"] == 125


@pytest.mark.asyncio
async def test_leverage_limits_unknown_exchange(mock_user):
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.get("/api/exchanges/kraken/leverage-limits", params={"symbol": "BTCUSDT"})
    assert r.status_code == 404
```

- [ ] **Step 2: Run test, expect import failure**

```bash
pytest tests/unit/api/test_copy_trading_router.py -v
```

- [ ] **Step 3: Implement the router**

Create `src/api/routers/copy_trading.py`:

```python
"""Copy-trading specific endpoints: source-wallet validation + leverage limits."""

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.api.rate_limit import limiter
from src.auth.dependencies import get_current_user
from src.exchanges.hyperliquid.wallet_tracker import HyperliquidWalletTracker
from src.exchanges.leverage_limits import ExchangeNotSupported, get_max_leverage
from src.exchanges.symbol_fetcher import get_exchange_symbols
from src.exchanges.symbol_map import to_exchange_symbol
from src.models.database import User
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["copy-trading"])

WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
LOOKBACK_DAYS = 30


class ValidateSourceRequest(BaseModel):
    wallet: str
    target_exchange: str


class ValidateSourceResponse(BaseModel):
    valid: bool
    wallet_label: str
    trades_30d: int
    available: list[str]
    unavailable: list[str]
    warning: str | None = None


@router.post("/copy-trading/validate-source", response_model=ValidateSourceResponse)
async def validate_source(
    body: ValidateSourceRequest,
    user: User = Depends(get_current_user),
):
    """Validate a Hyperliquid source wallet for copy-trading."""

    # 1. Format check
    if not WALLET_RE.match(body.wallet):
        raise HTTPException(
            status_code=400,
            detail="Ungültige Wallet-Adresse — erwartet wird 0x gefolgt von 40 Hex-Zeichen.",
        )

    tracker = HyperliquidWalletTracker()
    try:
        # 2. Existence check (user_state always returns something for live wallets)
        positions = await tracker.get_open_positions(body.wallet)

        # 3. Activity check — fills in the last 30d
        since_ms = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)
        fills = await tracker.get_fills_since(body.wallet, since_ms)
        if not fills and not positions:
            raise HTTPException(
                status_code=404,
                detail="Wallet hat in den letzten 30 Tagen keine Trading-Aktivität. "
                       "Copy-Trading benötigt eine aktive Source-Wallet.",
            )

        # 4. Symbol availability preview
        try:
            target_symbols = await get_exchange_symbols(body.target_exchange)
        except Exception as e:
            logger.warning("Failed to fetch %s symbols: %s", body.target_exchange, e)
            target_symbols = []

        seen_coins = sorted({f.coin for f in fills} | {p.coin for p in positions})
        available: list[str] = []
        unavailable: list[str] = []
        for coin in seen_coins:
            try:
                target_sym = to_exchange_symbol(coin, body.target_exchange)
            except Exception:
                target_sym = None
            if target_sym and target_sym in target_symbols:
                available.append(coin)
            else:
                unavailable.append(coin)

        if not available:
            raise HTTPException(
                status_code=400,
                detail=f"Keines der zuletzt von dieser Wallet gehandelten Symbole "
                       f"ist auf {body.target_exchange} verfügbar — Bot würde nichts kopieren können.",
            )

        warning = None
        if unavailable:
            warning = (
                f"{len(unavailable)} von {len(seen_coins)} zuletzt gehandelten "
                f"Symbolen sind nicht auf {body.target_exchange} verfügbar und werden übersprungen."
            )

        return ValidateSourceResponse(
            valid=True,
            wallet_label=body.wallet[:6] + "…" + body.wallet[-4:],
            trades_30d=len(fills),
            available=available,
            unavailable=unavailable,
            warning=warning,
        )
    finally:
        await tracker.close()


class LeverageLimitsResponse(BaseModel):
    exchange: str
    symbol: str
    max_leverage: int


@router.get("/exchanges/{exchange}/leverage-limits", response_model=LeverageLimitsResponse)
async def leverage_limits(
    exchange: str,
    symbol: str = Query(...),
    user: User = Depends(get_current_user),
):
    try:
        max_lev = get_max_leverage(exchange, symbol)
    except ExchangeNotSupported as e:
        raise HTTPException(status_code=404, detail=str(e))
    return LeverageLimitsResponse(exchange=exchange, symbol=symbol, max_leverage=max_lev)
```

- [ ] **Step 4: Register the router**

In `src/api/main.py` (next to the other `app.include_router(...)` calls):

```python
from src.api.routers.copy_trading import router as copy_trading_router
app.include_router(copy_trading_router)
```

- [ ] **Step 5: Run tests, expect pass**

```bash
pytest tests/unit/api/test_copy_trading_router.py -v
```
Expected: 4 PASSED.

- [ ] **Step 6: Commit**

```bash
git add src/api/routers/copy_trading.py src/api/main.py tests/unit/api/test_copy_trading_router.py
git commit -m "feat: add copy-trading validation + leverage-limits API endpoints"
```

---

## Phase 5 — `CopyTradingStrategy` core

### Task 7: Strategy class with run_tick + tests

**Files:**
- Create: `src/strategy/copy_trading.py`
- Modify: `src/strategy/__init__.py` to import the new module
- Test: `tests/unit/strategy/test_copy_trading.py`

- [ ] **Step 1: Write the failing tests** *(this is the largest test file in the plan; one task with multiple test cases)*

```python
"""Tests for CopyTradingStrategy."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.strategy.copy_trading import CopyTradingStrategy
from src.exchanges.hyperliquid.wallet_tracker import SourceFill, SourcePosition


def _make_ctx(bot_config, exchange_client, executor=None, notifier=None):
    """Build a minimal StrategyTickContext for tests."""
    from src.strategy.base import StrategyTickContext
    return StrategyTickContext(
        bot_config=bot_config,
        user_id=1,
        exchange_client=exchange_client,
        trade_executor=executor or MagicMock(),
        send_notification=notifier or AsyncMock(),
        logger=MagicMock(),
        bot_config_id=99,
    )


def _params(**overrides):
    base = {
        "source_wallet": "0x" + "ab" * 20,
        "budget_usdt": 1000.0,
        "max_slots": 5,
        "leverage": None,
        "symbol_whitelist": "",
        "symbol_blacklist": "",
        "min_position_size_usdt": 10.0,
        "copy_tp_sl": False,
    }
    base.update(overrides)
    return base


def _bot_config(strategy_state=None, exchange="bitget"):
    cfg = MagicMock()
    cfg.id = 99
    cfg.exchange_type = exchange
    cfg.user_id = 1
    cfg.strategy_state = json.dumps(strategy_state) if strategy_state else None
    return cfg


def test_is_self_managed_flag():
    s = CopyTradingStrategy(_params())
    assert s.is_self_managed is True


def test_param_schema_keys():
    schema = CopyTradingStrategy.get_param_schema()
    for key in ("source_wallet", "budget_usdt", "max_slots", "leverage",
                "symbol_whitelist", "symbol_blacklist",
                "min_position_size_usdt", "copy_tp_sl"):
        assert key in schema


@pytest.mark.asyncio
async def test_run_tick_skips_when_no_new_fills(monkeypatch):
    s = CopyTradingStrategy(_params())
    tracker = MagicMock()
    tracker.get_fills_since = AsyncMock(return_value=[])
    tracker.get_open_positions = AsyncMock(return_value=[])
    tracker.close = AsyncMock()
    monkeypatch.setattr(
        "src.strategy.copy_trading.HyperliquidWalletTracker",
        lambda: tracker,
    )
    cfg = _bot_config(strategy_state={"last_processed_fill_ms": 1000})
    ctx = _make_ctx(cfg, exchange_client=MagicMock())
    await s.run_tick(ctx)
    ctx.trade_executor.execute_trade.assert_not_called()


@pytest.mark.asyncio
async def test_run_tick_dispatches_entry_signal(monkeypatch):
    fills = [SourceFill(coin="BTC", side="long", size=0.5, price=67000,
                        time_ms=2000, is_entry=True, hash="0xa")]
    tracker = MagicMock()
    tracker.get_fills_since = AsyncMock(return_value=fills)
    tracker.get_open_positions = AsyncMock(return_value=[])
    tracker.close = AsyncMock()
    monkeypatch.setattr("src.strategy.copy_trading.HyperliquidWalletTracker", lambda: tracker)

    # Stub symbol availability
    monkeypatch.setattr(
        "src.strategy.copy_trading.get_exchange_symbols",
        AsyncMock(return_value=["BTCUSDT"]),
    )
    monkeypatch.setattr(
        "src.strategy.copy_trading.to_exchange_symbol",
        lambda coin, ex: "BTCUSDT" if coin == "BTC" else None,
    )

    s = CopyTradingStrategy(_params(budget_usdt=1000, max_slots=5))
    cfg = _bot_config(strategy_state={"last_processed_fill_ms": 1000})
    executor = MagicMock()
    executor.execute_trade = AsyncMock()
    executor.get_open_trades_count = AsyncMock(return_value=0)
    ctx = _make_ctx(cfg, exchange_client=MagicMock(), executor=executor)
    await s.run_tick(ctx)

    executor.execute_trade.assert_called_once()
    call = executor.execute_trade.call_args
    assert call.kwargs["symbol"] == "BTCUSDT"
    assert call.kwargs["side"] == "long"
    # Notional ≈ budget / max_slots = 200
    assert abs(call.kwargs["notional_usdt"] - 200.0) < 0.01


@pytest.mark.asyncio
async def test_run_tick_skips_blacklisted_symbol(monkeypatch):
    fills = [SourceFill(coin="HYPE", side="long", size=10, price=12,
                        time_ms=2000, is_entry=True, hash="0xa")]
    tracker = MagicMock()
    tracker.get_fills_since = AsyncMock(return_value=fills)
    tracker.get_open_positions = AsyncMock(return_value=[])
    tracker.close = AsyncMock()
    monkeypatch.setattr("src.strategy.copy_trading.HyperliquidWalletTracker", lambda: tracker)

    s = CopyTradingStrategy(_params(symbol_blacklist="HYPE,PURR"))
    cfg = _bot_config(strategy_state={"last_processed_fill_ms": 1000})
    executor = MagicMock()
    executor.execute_trade = AsyncMock()
    executor.get_open_trades_count = AsyncMock(return_value=0)
    ctx = _make_ctx(cfg, exchange_client=MagicMock(), executor=executor)
    await s.run_tick(ctx)
    executor.execute_trade.assert_not_called()


@pytest.mark.asyncio
async def test_run_tick_skips_when_slots_exhausted(monkeypatch):
    fills = [SourceFill(coin="BTC", side="long", size=0.5, price=67000,
                        time_ms=2000, is_entry=True, hash="0xa")]
    tracker = MagicMock()
    tracker.get_fills_since = AsyncMock(return_value=fills)
    tracker.get_open_positions = AsyncMock(return_value=[])
    tracker.close = AsyncMock()
    monkeypatch.setattr("src.strategy.copy_trading.HyperliquidWalletTracker", lambda: tracker)
    monkeypatch.setattr("src.strategy.copy_trading.get_exchange_symbols", AsyncMock(return_value=["BTCUSDT"]))
    monkeypatch.setattr("src.strategy.copy_trading.to_exchange_symbol", lambda c, e: "BTCUSDT")

    s = CopyTradingStrategy(_params(max_slots=2))
    cfg = _bot_config(strategy_state={"last_processed_fill_ms": 1000})
    executor = MagicMock()
    executor.execute_trade = AsyncMock()
    executor.get_open_trades_count = AsyncMock(return_value=2)  # already at max
    ctx = _make_ctx(cfg, exchange_client=MagicMock(), executor=executor)
    await s.run_tick(ctx)
    executor.execute_trade.assert_not_called()


@pytest.mark.asyncio
async def test_run_tick_advances_watermark_after_processing(monkeypatch):
    fills = [SourceFill(coin="BTC", side="long", size=0.5, price=67000,
                        time_ms=5000, is_entry=True, hash="0xa")]
    tracker = MagicMock()
    tracker.get_fills_since = AsyncMock(return_value=fills)
    tracker.get_open_positions = AsyncMock(return_value=[])
    tracker.close = AsyncMock()
    monkeypatch.setattr("src.strategy.copy_trading.HyperliquidWalletTracker", lambda: tracker)
    monkeypatch.setattr("src.strategy.copy_trading.get_exchange_symbols", AsyncMock(return_value=["BTCUSDT"]))
    monkeypatch.setattr("src.strategy.copy_trading.to_exchange_symbol", lambda c, e: "BTCUSDT")
    save_state = MagicMock()
    monkeypatch.setattr("src.strategy.copy_trading._save_strategy_state", save_state)

    s = CopyTradingStrategy(_params())
    cfg = _bot_config(strategy_state={"last_processed_fill_ms": 1000})
    executor = MagicMock()
    executor.execute_trade = AsyncMock()
    executor.get_open_trades_count = AsyncMock(return_value=0)
    ctx = _make_ctx(cfg, exchange_client=MagicMock(), executor=executor)
    await s.run_tick(ctx)

    # Watermark should advance to the latest fill time (5000)
    save_state.assert_called_once()
    saved_state = save_state.call_args.args[1]
    assert saved_state["last_processed_fill_ms"] == 5000


@pytest.mark.asyncio
async def test_cold_start_initializes_watermark_to_now(monkeypatch):
    """First tick after start: strategy_state is None → set to now, skip all existing fills."""
    fills = [SourceFill(coin="BTC", side="long", size=0.5, price=67000,
                        time_ms=1000, is_entry=True, hash="0xa")]
    tracker = MagicMock()
    tracker.get_fills_since = AsyncMock(return_value=fills)
    tracker.get_open_positions = AsyncMock(return_value=[])
    tracker.close = AsyncMock()
    monkeypatch.setattr("src.strategy.copy_trading.HyperliquidWalletTracker", lambda: tracker)
    save_state = MagicMock()
    monkeypatch.setattr("src.strategy.copy_trading._save_strategy_state", save_state)

    s = CopyTradingStrategy(_params())
    cfg = _bot_config(strategy_state=None)  # cold start
    executor = MagicMock()
    executor.execute_trade = AsyncMock()
    executor.get_open_trades_count = AsyncMock(return_value=0)
    ctx = _make_ctx(cfg, exchange_client=MagicMock(), executor=executor)
    await s.run_tick(ctx)

    # No trade executed (cold start sets watermark to now, fills filtered out)
    executor.execute_trade.assert_not_called()
    # State persisted with the new watermark
    save_state.assert_called()


@pytest.mark.asyncio
async def test_run_tick_exits_when_source_closed_position(monkeypatch):
    """Source no longer holds a position → close any open copies of it."""
    tracker = MagicMock()
    tracker.get_fills_since = AsyncMock(return_value=[])
    tracker.get_open_positions = AsyncMock(return_value=[])  # source flat
    tracker.close = AsyncMock()
    monkeypatch.setattr("src.strategy.copy_trading.HyperliquidWalletTracker", lambda: tracker)

    s = CopyTradingStrategy(_params())
    cfg = _bot_config(strategy_state={"last_processed_fill_ms": 1000})
    open_trade = MagicMock()
    open_trade.symbol = "BTCUSDT"
    open_trade.side = "long"
    open_trade.id = 7
    executor = MagicMock()
    executor.execute_trade = AsyncMock()
    executor.get_open_trades_for_bot = AsyncMock(return_value=[open_trade])
    executor.close_trade_by_strategy = AsyncMock()
    executor.get_open_trades_count = AsyncMock(return_value=1)
    monkeypatch.setattr("src.strategy.copy_trading.to_exchange_symbol", lambda c, e: "BTCUSDT")

    ctx = _make_ctx(cfg, exchange_client=MagicMock(), executor=executor)
    await s.run_tick(ctx)
    executor.close_trade_by_strategy.assert_called_once_with(open_trade, reason="COPY_SOURCE_CLOSED")
```

- [ ] **Step 2: Run tests, expect import failure**

```bash
pytest tests/unit/strategy/test_copy_trading.py -v
```

- [ ] **Step 3: Implement the strategy**

Create `src/strategy/copy_trading.py`:

```python
"""Copy-trading strategy: mirror a public Hyperliquid wallet's trades."""

import json
import time
from typing import Any, Dict, Optional

from src.exchanges.hyperliquid.wallet_tracker import (
    HyperliquidWalletTracker,
    SourceFill,
    SourcePosition,
)
from src.exchanges.leverage_limits import ExchangeNotSupported, get_max_leverage
from src.exchanges.symbol_fetcher import get_exchange_symbols
from src.exchanges.symbol_map import to_exchange_symbol
from src.strategy.base import (
    BaseStrategy,
    SignalDirection,
    StrategyRegistry,
    StrategyTickContext,
    TradeSignal,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _save_strategy_state(bot_config, state: dict) -> None:
    """Persist strategy_state JSON on the BotConfig.

    Side-effect only — caller is responsible for the surrounding DB session
    commit. Tests monkey-patch this function to assert state transitions.
    """
    bot_config.strategy_state = json.dumps(state)


def _load_strategy_state(bot_config) -> dict:
    raw = getattr(bot_config, "strategy_state", None)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _parse_csv_list(value: Optional[str]) -> set[str]:
    if not value:
        return set()
    return {item.strip().upper() for item in value.split(",") if item.strip()}


class CopyTradingStrategy(BaseStrategy):
    """Mirrors a Hyperliquid wallet's trades onto the user's chosen exchange."""

    is_self_managed = True

    @classmethod
    def get_param_schema(cls) -> Dict[str, Any]:
        return {
            "source_wallet": {
                "type": "text",
                "label": "Hyperliquid Wallet (0x…)",
                "description": "Adresse der Wallet, deren Trades kopiert werden sollen",
                "required": True,
            },
            "budget_usdt": {
                "type": "float",
                "label": "Gesamtbudget (USDT)",
                "description": "Wird gleichmäßig auf die Slots verteilt",
                "default": 500.0,
                "min": 50.0,
            },
            "max_slots": {
                "type": "int",
                "label": "Parallele Positionen",
                "description": "Maximale Anzahl gleichzeitig offener Trades",
                "default": 5,
                "min": 1,
                "max": 20,
            },
            "leverage": {
                "type": "int",
                "label": "Hebel (leer = wie Source)",
                "description": "Wird gegen das Maximum der Ziel-Exchange validiert",
                "default": None,
                "min": 1,
                "max": 125,
            },
            "symbol_whitelist": {
                "type": "text",
                "label": "Whitelist (kommagetrennt, optional)",
                "description": "Wenn gesetzt: nur diese Symbole kopieren",
                "default": "",
            },
            "symbol_blacklist": {
                "type": "text",
                "label": "Blacklist (kommagetrennt, optional)",
                "description": "Diese Symbole werden nie kopiert",
                "default": "",
            },
            "min_position_size_usdt": {
                "type": "float",
                "label": "Mindestgröße pro Trade (USDT)",
                "default": 10.0,
                "min": 1.0,
            },
            "copy_tp_sl": {
                "type": "bool",
                "label": "TP/SL der Source übernehmen",
                "default": False,
            },
        }

    @classmethod
    def get_description(cls) -> str:
        return "Kopiert die Trades einer öffentlichen Hyperliquid-Wallet 1:1."

    # ---------- Interface stubs (unused for self-managed) ----------

    async def generate_signal(self, symbol):  # type: ignore[override]
        # Self-managed — bot worker calls run_tick instead.
        return None

    async def should_trade(self, signal):  # type: ignore[override]
        return False, "self-managed"

    # ---------- Self-managed entry point ----------

    async def run_tick(self, ctx: StrategyTickContext) -> None:
        wallet = (self.params.get("source_wallet") or "").strip()
        if not wallet:
            ctx.logger.warning("[Bot:%s] copy_trading: no source_wallet configured", ctx.bot_config_id)
            return

        target_exchange = ctx.bot_config.exchange_type
        state = _load_strategy_state(ctx.bot_config)

        # Cold start: initialise watermark to now-ish so existing fills are skipped.
        if "last_processed_fill_ms" not in state:
            state["last_processed_fill_ms"] = int(time.time() * 1000)
            _save_strategy_state(ctx.bot_config, state)
            return

        last_ms = int(state["last_processed_fill_ms"])

        tracker = HyperliquidWalletTracker()
        try:
            new_fills = await tracker.get_fills_since(wallet, last_ms)
            source_positions = await tracker.get_open_positions(wallet)

            # 1. Process exits first (close trades whose source position is gone)
            await self._process_exits(ctx, source_positions, target_exchange)

            # 2. Process new entries
            for fill in new_fills:
                if not fill.is_entry:
                    continue
                await self._process_entry_fill(ctx, fill, target_exchange)

            # 3. Advance watermark
            if new_fills:
                state["last_processed_fill_ms"] = max(f.time_ms for f in new_fills)
                _save_strategy_state(ctx.bot_config, state)
        finally:
            await tracker.close()

    # ---------- Helpers ----------

    async def _process_entry_fill(
        self,
        ctx: StrategyTickContext,
        fill: SourceFill,
        target_exchange: str,
    ) -> None:
        coin = fill.coin

        # Whitelist / blacklist
        whitelist = _parse_csv_list(self.params.get("symbol_whitelist"))
        blacklist = _parse_csv_list(self.params.get("symbol_blacklist"))
        if whitelist and coin.upper() not in whitelist:
            ctx.logger.info("[Bot:%s] copy_trading: %s not in whitelist, skipped",
                            ctx.bot_config_id, coin)
            return
        if coin.upper() in blacklist:
            ctx.logger.info("[Bot:%s] copy_trading: %s in blacklist, skipped",
                            ctx.bot_config_id, coin)
            return

        # Symbol mapping + availability
        try:
            target_sym = to_exchange_symbol(coin, target_exchange)
        except Exception:
            target_sym = None
        if not target_sym:
            await self._notify_skip(ctx, f"Symbol-Mapping für {coin} → {target_exchange} fehlgeschlagen")
            return

        try:
            available = await get_exchange_symbols(target_exchange)
        except Exception:
            available = []
        if target_sym not in available:
            await self._notify_skip(
                ctx,
                f"Source eröffnete {coin} {fill.side.upper()} — nicht auf {target_exchange} verfügbar, übersprungen.",
            )
            return

        # Slot exhaustion
        budget = float(self.params.get("budget_usdt", 0))
        max_slots = int(self.params.get("max_slots", 5))
        open_count = await ctx.trade_executor.get_open_trades_count(ctx.bot_config_id)
        if open_count >= max_slots:
            ctx.logger.info("[Bot:%s] copy_trading: slot exhausted (%d/%d), skip %s",
                            ctx.bot_config_id, open_count, max_slots, coin)
            return

        # Sizing
        notional = budget / max_slots
        if notional < float(self.params.get("min_position_size_usdt", 10)):
            ctx.logger.info("[Bot:%s] copy_trading: notional %.2f below min, skip", ctx.bot_config_id, notional)
            return

        # Leverage
        user_leverage = self.params.get("leverage")
        effective_leverage = int(user_leverage) if user_leverage else 1
        try:
            max_lev = get_max_leverage(target_exchange, target_sym)
            if effective_leverage > max_lev:
                await self._notify_skip(
                    ctx,
                    f"Source nutzte {effective_leverage}x auf {target_sym}, "
                    f"{target_exchange} erlaubt nur {max_lev}x — kopiert mit {max_lev}x.",
                )
                effective_leverage = max_lev
        except ExchangeNotSupported:
            pass

        await ctx.trade_executor.execute_trade(
            symbol=target_sym,
            side=fill.side,
            notional_usdt=notional,
            leverage=effective_leverage,
            reason=f"COPY_TRADING source={fill.hash[:8]} coin={coin}",
            bot_config_id=ctx.bot_config_id,
        )

    async def _process_exits(
        self,
        ctx: StrategyTickContext,
        source_positions: list[SourcePosition],
        target_exchange: str,
    ) -> None:
        # Build a normalized set of (target_symbol, side) the source still holds
        active: set[tuple[str, str]] = set()
        for pos in source_positions:
            try:
                sym = to_exchange_symbol(pos.coin, target_exchange)
            except Exception:
                sym = None
            if sym:
                active.add((sym, pos.side))

        open_trades = await ctx.trade_executor.get_open_trades_for_bot(ctx.bot_config_id)
        for trade in open_trades:
            if (trade.symbol, trade.side) not in active:
                ctx.logger.info("[Bot:%s] copy_trading: source closed %s %s — closing trade #%s",
                                ctx.bot_config_id, trade.symbol, trade.side, trade.id)
                await ctx.trade_executor.close_trade_by_strategy(trade, reason="COPY_SOURCE_CLOSED")

    async def _notify_skip(self, ctx: StrategyTickContext, message: str) -> None:
        ctx.logger.info("[Bot:%s] %s", ctx.bot_config_id, message)
        try:
            await ctx.send_notification(
                lambda n: n.send_message(message),
                event_type="copy_skip",
                summary=message,
            )
        except Exception:
            pass


StrategyRegistry.register("copy_trading", CopyTradingStrategy)
```

- [ ] **Step 4: Wire it into the registry**

In `src/strategy/__init__.py` add:

```python
from . import copy_trading  # noqa: F401  — registers strategy at import time
```

(Match the existing import-for-side-effect pattern that the other strategies use.)

- [ ] **Step 5: Run tests, expect pass**

```bash
pytest tests/unit/strategy/test_copy_trading.py -v
```
Expected: 8 PASSED.

- [ ] **Step 6: Add `execute_trade` / `close_trade_by_strategy` / `get_open_trades_count` / `get_open_trades_for_bot` to TradeExecutorMixin if missing**

Read `src/bot/trade_executor.py`. If any of the four methods used by the strategy don't exist with the expected signatures, add thin wrappers around the existing logic. Each missing method gets:

- a unit test in `tests/unit/bot/test_trade_executor.py`
- a minimal implementation
- a green test run

(This step is intentionally exploratory — exact method names may already exist with slightly different names. Adapt the strategy to call them if so, rather than adding new methods.)

- [ ] **Step 7: Commit**

```bash
git add src/strategy/copy_trading.py src/strategy/__init__.py tests/unit/strategy/test_copy_trading.py src/bot/trade_executor.py tests/unit/bot/test_trade_executor.py
git commit -m "feat: CopyTradingStrategy with self-managed run_tick + tests"
```

---

## Phase 6 — Symbol conflict relaxation

### Task 8: Relax `_check_symbol_conflicts` for copy bots

**Files:**
- Modify: `src/api/routers/bots.py` around `_check_symbol_conflicts`
- Test: `tests/unit/api/test_bots_router_extra.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/api/test_bots_router_extra.py`:

```python
@pytest.mark.asyncio
async def test_copy_trading_bot_does_not_conflict_with_existing(db_session, test_user):
    """Copy bots may overlap with existing bots on the same symbols."""
    from src.api.routers.bots import _check_symbol_conflicts
    from src.models.database import BotConfig

    existing = BotConfig(
        user_id=test_user.id, exchange_type="bitget", mode="demo",
        strategy_type="edge_indicator", trading_pairs='["BTCUSDT"]', name="edge",
    )
    db_session.add(existing)
    await db_session.commit()

    conflicts = await _check_symbol_conflicts(
        db_session, test_user.id, "bitget", "demo",
        ["BTCUSDT"], strategy_type="copy_trading",
    )
    assert conflicts == []
```

- [ ] **Step 2: Run test, expect failure** (signature mismatch)

- [ ] **Step 3: Add the `strategy_type` kwarg + early-return**

In `src/api/routers/bots.py::_check_symbol_conflicts`, change the signature:

```python
async def _check_symbol_conflicts(
    db: AsyncSession,
    user_id: int,
    exchange_type: str,
    mode: str,
    trading_pairs: list[str],
    exclude_bot_id: int | None = None,
    strategy_type: str | None = None,
) -> list[SymbolConflict]:
    # Copy-trading bots are budget-isolated and may overlap with normal bots.
    if strategy_type == "copy_trading":
        return []
    # ... existing implementation unchanged ...
```

Update all callers in the same file to pass `strategy_type=body.strategy_type` (or equivalent). Search for `_check_symbol_conflicts(` and add the kwarg.

- [ ] **Step 4: Run test, expect pass**

- [ ] **Step 5: Commit**

```bash
git add src/api/routers/bots.py tests/unit/api/test_bots_router_extra.py
git commit -m "feat: relax symbol conflict check for copy_trading bots"
```

---

## Phase 7 — Frontend

### Task 9: Frontend API client

**Files:**
- Create: `frontend/src/api/copyTrading.ts`

- [ ] **Step 1: Implement**

```typescript
import { apiClient } from './client'

export interface ValidateSourceResponse {
  valid: boolean
  wallet_label: string
  trades_30d: number
  available: string[]
  unavailable: string[]
  warning: string | null
}

export interface LeverageLimitsResponse {
  exchange: string
  symbol: string
  max_leverage: number
}

export async function validateSourceWallet(
  wallet: string,
  target_exchange: string,
): Promise<ValidateSourceResponse> {
  const r = await apiClient.post('/api/copy-trading/validate-source', {
    wallet,
    target_exchange,
  })
  return r.data
}

export async function getLeverageLimits(
  exchange: string,
  symbol: string,
): Promise<LeverageLimitsResponse> {
  const r = await apiClient.get(`/api/exchanges/${exchange}/leverage-limits`, {
    params: { symbol },
  })
  return r.data
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/copyTrading.ts
git commit -m "feat(frontend): copy-trading API client"
```

---

### Task 10: `CopyTradingValidator` component

**Files:**
- Create: `frontend/src/components/bots/CopyTradingValidator.tsx`

- [ ] **Step 1: Implement**

```tsx
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, AlertTriangle, XCircle, Loader2 } from 'lucide-react'
import { validateSourceWallet, type ValidateSourceResponse } from '../../api/copyTrading'

interface Props {
  wallet: string
  targetExchange: string
  onValidated: (result: ValidateSourceResponse | null) => void
}

export default function CopyTradingValidator({ wallet, targetExchange, onValidated }: Props) {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ValidateSourceResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    setLoading(true); setError(null); setResult(null)
    try {
      const r = await validateSourceWallet(wallet, targetExchange)
      setResult(r); onValidated(r)
    } catch (e: any) {
      const msg = e?.response?.data?.detail ?? String(e)
      setError(msg); onValidated(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={run}
        disabled={!wallet || !targetExchange || loading}
        className="px-3 py-1.5 rounded-md text-xs bg-primary-500/15 text-primary-400 hover:bg-primary-500/25 disabled:opacity-40"
      >
        {loading ? <Loader2 size={14} className="animate-spin inline mr-1" /> : null}
        {t('copyTrading.validateButton', 'Wallet prüfen')}
      </button>

      {error && (
        <div className="flex items-start gap-2 p-2.5 rounded-md bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
          <XCircle size={14} className="shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {result && (
        <div className="p-2.5 rounded-md bg-emerald-500/10 border border-emerald-500/20 text-xs space-y-1">
          <div className="flex items-center gap-1.5 text-emerald-400 font-medium">
            <CheckCircle2 size={14} />
            {result.wallet_label} · {result.trades_30d} {t('copyTrading.tradesIn30d', 'Trades in 30 Tagen')}
          </div>
          <div className="text-emerald-300">
            {t('copyTrading.available', 'Verfügbar')}: {result.available.join(', ') || '—'}
          </div>
          {result.unavailable.length > 0 && (
            <div className="flex items-start gap-1.5 text-amber-400">
              <AlertTriangle size={12} className="shrink-0 mt-0.5" />
              <span>{result.warning}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/bots/CopyTradingValidator.tsx
git commit -m "feat(frontend): CopyTradingValidator component"
```

---

### Task 11: Bot builder integration

**Files:**
- Modify: `frontend/src/components/bots/BotBuilderStepStrategy.tsx`

- [ ] **Step 1: Add `text` input handling for params**

Add to the always-visible param block (next to `selectEntries` / `textareaEntries`), a third filter:

```tsx
const textEntries = Object.entries(selectedStrategy.param_schema).filter(
  ([, def]) => (def as ParamDef).type === 'text'
)
```

And render them with a single-line `<input type="text">` element next to the others.

- [ ] **Step 2: Render `CopyTradingValidator` when strategy_type === 'copy_trading'**

Below the param block, add:

```tsx
{strategyType === 'copy_trading' && strategyParams.source_wallet && (
  <CopyTradingValidator
    wallet={strategyParams.source_wallet}
    targetExchange={/* pulled from parent step's exchange selection */}
    onValidated={(r) => onStrategyParamsChange({ ...strategyParams, _validation: r })}
  />
)}
```

The `_validation` key is consumed by the bot creation submit handler — if `_validation === null` or `available.length === 0`, block submission with a clear error toast.

- [ ] **Step 3: Add i18n keys**

`frontend/src/i18n/de.json` (under `bots.builder`):
```json
"copyTrading": {
  "validateButton": "Wallet prüfen",
  "tradesIn30d": "Trades in 30 Tagen",
  "available": "Verfügbar",
  "blockedNoSymbols": "Keines der zuletzt von dieser Wallet gehandelten Symbole ist auf der Ziel-Exchange verfügbar."
}
```

`en.json`: same shape with English values.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/bots/BotBuilderStepStrategy.tsx frontend/src/i18n/de.json frontend/src/i18n/en.json
git commit -m "feat(frontend): bot builder text-input params + CopyTradingValidator"
```

---

### Task 12: Bot card variant

**Files:**
- Modify: `frontend/src/pages/Bots.tsx`

- [ ] **Step 1: Conditional render the source-wallet line for copy bots**

Where the bot card currently shows the strategy + risk profile, branch when `bot.strategy_type === 'copy_trading'`:

```tsx
{bot.strategy_type === 'copy_trading' ? (
  <div className="text-xs text-gray-400">
    Source: <span className="font-mono">{shortenWallet(bot.strategy_params?.source_wallet)}</span>
    {' · '}Slots: {openTradesForBot(bot.id)} / {bot.strategy_params?.max_slots}
    {' · '}Budget: ${bot.strategy_params?.budget_usdt}
  </div>
) : (
  /* existing strategy + risk profile display */
)}
```

Add `shortenWallet` helper at the top of the file:
```tsx
const shortenWallet = (w?: string) => w ? `${w.slice(0, 6)}…${w.slice(-4)}` : '—'
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Bots.tsx
git commit -m "feat(frontend): copy-trading variant of bot card"
```

---

## Phase 8 — Anleitung & verification

### Task 13: Bilingual user guide

**Files:**
- Create: `Anleitungen/copy-trading.md`

- [ ] **Step 1: Write the bilingual guide**

Following the project rule "Anleitungen sind zweisprachig (DE zuerst, dann EN)", create `Anleitungen/copy-trading.md`:

```markdown
# Copy Trading

## Deutsch

### Was macht Copy Trading?
Der Copy-Trading-Bot trackt eine öffentliche Hyperliquid-Wallet und kopiert
deren Trades auf die Exchange deiner Wahl …

### Bot anlegen
1. Gehe zu *Bots* → *Neuer Bot*
2. Wähle eine Exchange (die Ziel-Börse für die Kopien)
3. Wähle die Strategie *Copy Trading*
4. Trage die Hyperliquid-Wallet-Adresse (0x…) ein
5. Setze Budget und Anzahl paralleler Positionen
6. Klicke auf *Wallet prüfen* — der Bot zeigt dir, welche Symbole verfügbar sind
7. Optional: Hebel, Whitelist/Blacklist, Mindestgröße
8. *Bot erstellen*

### Wichtige Hinweise
- **Cold Start:** Bestehende Positionen der Source-Wallet werden NICHT kopiert.
  Der Bot folgt nur Trades, die nach dem Start eröffnet werden.
- **Slots:** Dein Budget wird gleichmäßig auf die Slots verteilt …

---

## English

### What does Copy Trading do?
The copy-trading bot tracks a public Hyperliquid wallet and mirrors its trades
onto the exchange of your choice …

### Creating the bot
1. Go to *Bots* → *New Bot*
2. Pick an exchange (the target exchange for the copies)
3. Pick the *Copy Trading* strategy
4. Enter the Hyperliquid wallet address (0x…)
5. Set the budget and the number of concurrent slots
6. Click *Validate wallet* — the bot shows you which symbols are available
7. Optional: leverage, whitelist/blacklist, min size
8. *Create bot*

### Important notes
- **Cold start:** Positions the source wallet already has open are NOT copied.
  The bot only follows trades opened after the start.
- **Slots:** Your budget is split evenly across the slots …
```

(Fill in the `…` sections with the exact behaviour described in the spec.)

- [ ] **Step 2: Commit**

```bash
git add Anleitungen/copy-trading.md
git commit -m "docs: bilingual guide for copy trading"
```

---

### Task 14: End-to-end manual test on testnet + CHANGELOG

- [ ] **Step 1: Manual test**

1. On the dev server, create an exchange connection in demo mode for Bitget.
2. In the bot builder, choose strategy `Copy Trading`, paste a known active
   Hyperliquid testnet wallet (use a wallet you control on testnet).
3. Click *Wallet prüfen* — verify the preview shows expected coins.
4. Create the bot with budget=200 / max_slots=2.
5. From a separate terminal, open a position on the source wallet via the
   HL testnet UI.
6. Wait one tick (≈1 minute). Verify a trade appears on the bot user's
   Bitget demo account, with notional ≈100 USDT (200 / 2).
7. Close the source position. Wait one tick. Verify the bot's trade closes
   automatically with `exit_reason=COPY_SOURCE_CLOSED`.
8. Try a coin that doesn't exist on Bitget (e.g. `HYPE` if not listed) →
   verify the skip notification arrives.
9. Stop the bot and start it again — verify cold-start logic skips any
   currently-open source positions.

- [ ] **Step 2: Update CHANGELOG**

Add a new entry to `CHANGELOG.md` under a new version bump:

```markdown
## [4.16.0] - 2026-04-XX

### Hinzugefügt
- **Copy-Trading-Strategie** — Neue Bot-Strategie `copy_trading` die eine
  öffentliche Hyperliquid-Wallet trackt und ihre Trades auf der gewünschten
  Exchange (Bitget, BingX, Bitunix, Weex, HL) kopiert. Fixe Slot-Aufteilung
  des Budgets, Cold-Start ohne bestehende Positionen, Symbol-Whitelist/
  -Blacklist, optionaler Hebel-Override (validiert gegen Exchange-Limit),
  präzise Skip-Notifications für nicht-listbare Symbole. Wallet-Validierung
  vor dem Anlegen mit Symbol-Verfügbarkeits-Preview.
- Neue Endpoints `POST /api/copy-trading/validate-source` und
  `GET /api/exchanges/{exchange}/leverage-limits`.
- Neue Anleitung `Anleitungen/copy-trading.md` (DE + EN).

### Geändert
- `BaseStrategy` hat einen neuen `is_self_managed`-Flag und einen
  `run_tick(ctx)`-Hook. Der Bot-Worker dispatched zu `run_tick` wenn
  ein Bot self-managed ist und überspringt dann den Per-Symbol-Loop.
- `_check_symbol_conflicts` ignoriert Copy-Trading-Bots (sind Budget-isoliert).

### Datenbank
- Neue Spalte `bot_configs.strategy_state` (Text/JSON) — Migration `018`.
```

- [ ] **Step 3: Final commit + branch ready for PR**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog entry for copy trading v1"
```

---

## Self-review checklist (run before declaring done)

- [ ] All 8 spec sections implemented (architecture, params, validation,
  state, symbol mapping, failure modes, frontend, testing)
- [ ] No `TODO` / `TBD` / `placeholder` strings in any committed file
- [ ] All new tests pass: `pytest tests/unit/exchanges/test_hyperliquid_wallet_tracker.py
  tests/unit/exchanges/test_leverage_limits.py
  tests/unit/strategy/test_copy_trading.py
  tests/unit/strategy/test_base_strategy_self_managed.py
  tests/unit/api/test_copy_trading_router.py -v`
- [ ] All existing tests still pass: `pytest -x`
- [ ] Migration up + down works
- [ ] Manual end-to-end test on testnet passed all 9 steps
- [ ] CHANGELOG entry added
- [ ] DE + EN i18n strings added for all new UI text
- [ ] Bilingual Anleitung committed
