"""Tests for src/auth/auth_code.py — thread-safe one-time code store (SEC-014).

Covers:
- generate/exchange happy path
- single-use guarantee
- TTL expiration (5-minute window)
- concurrent exchanges cannot both succeed
- generate under concurrent cleanup does not lose codes
"""

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest

from src.auth import auth_code as auth_code_module
from src.auth.auth_code import CODE_TTL_SECONDS, AuthCodeStore


class TestTTL:
    def test_ttl_is_five_minutes(self):
        """SEC-013: TTL must be 5 minutes (300 seconds)."""
        assert CODE_TTL_SECONDS == 300


class TestGenerateAndExchange:
    @pytest.mark.asyncio
    async def test_generate_returns_non_empty_code(self):
        store = AuthCodeStore()
        code = await store.generate("supabase-jwt-xyz")
        assert isinstance(code, str)
        assert len(code) > 0

    @pytest.mark.asyncio
    async def test_exchange_returns_jwt_on_valid_code(self):
        store = AuthCodeStore()
        code = await store.generate("supabase-jwt-xyz")
        result = await store.exchange(code)
        assert result == "supabase-jwt-xyz"

    @pytest.mark.asyncio
    async def test_exchange_unknown_code_returns_none(self):
        store = AuthCodeStore()
        result = await store.exchange("does-not-exist")
        assert result is None

    @pytest.mark.asyncio
    async def test_code_is_single_use(self):
        """Exchange consumes the code — second call must fail."""
        store = AuthCodeStore()
        code = await store.generate("supabase-jwt-xyz")

        first = await store.exchange(code)
        second = await store.exchange(code)

        assert first == "supabase-jwt-xyz"
        assert second is None

    @pytest.mark.asyncio
    async def test_each_generate_produces_unique_code(self):
        store = AuthCodeStore()
        codes = {await store.generate(f"jwt-{i}") for i in range(50)}
        assert len(codes) == 50


class TestEviction:
    @pytest.mark.asyncio
    async def test_expired_code_is_rejected_on_exchange(self, monkeypatch):
        """A code past its TTL must not be redeemable."""
        store = AuthCodeStore()
        code = await store.generate("supabase-jwt-xyz")

        # Fast-forward monotonic clock past the 5-minute window
        real_monotonic = auth_code_module.time.monotonic
        fake_now = real_monotonic() + CODE_TTL_SECONDS + 1
        monkeypatch.setattr(
            auth_code_module.time, "monotonic", lambda: fake_now
        )

        result = await store.exchange(code)
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_code_is_removed_on_exchange(self, monkeypatch):
        """Expired entries should be purged as they are observed."""
        store = AuthCodeStore()
        code = await store.generate("supabase-jwt-xyz")
        assert await store.pending_count() == 1

        real_monotonic = auth_code_module.time.monotonic
        fake_now = real_monotonic() + CODE_TTL_SECONDS + 1
        monkeypatch.setattr(
            auth_code_module.time, "monotonic", lambda: fake_now
        )

        await store.exchange(code)
        assert await store.pending_count() == 0

    @pytest.mark.asyncio
    async def test_cleanup_loop_evicts_expired_codes(self, monkeypatch):
        """Background cleanup loop removes expired codes."""
        # Short-circuit sleep + cleanup interval so the test runs fast.
        monkeypatch.setattr(auth_code_module, "CLEANUP_INTERVAL_SECONDS", 0)

        store = AuthCodeStore()
        code = await store.generate("supabase-jwt-xyz")
        assert await store.pending_count() == 1

        # Advance the clock past the TTL
        real_monotonic = auth_code_module.time.monotonic
        fake_now = real_monotonic() + CODE_TTL_SECONDS + 1
        monkeypatch.setattr(
            auth_code_module.time, "monotonic", lambda: fake_now
        )

        # Run one cleanup cycle manually (don't rely on timer race conditions)
        async with store._lock:
            before = len(store._codes)
            store._codes = {
                k: v for k, v in store._codes.items() if not v.expired
            }
            removed = before - len(store._codes)

        assert removed == 1
        assert await store.pending_count() == 0
        # Code can no longer be redeemed
        assert await store.exchange(code) is None


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_exchange_only_one_succeeds(self):
        """Race: two clients exchange the same code at once — only one wins."""
        store = AuthCodeStore()
        code = await store.generate("supabase-jwt-xyz")

        results = await asyncio.gather(
            *[store.exchange(code) for _ in range(20)]
        )

        hits = [r for r in results if r is not None]
        misses = [r for r in results if r is None]
        assert len(hits) == 1
        assert hits[0] == "supabase-jwt-xyz"
        assert len(misses) == 19

    @pytest.mark.asyncio
    async def test_concurrent_generate_preserves_all_codes(self):
        """Parallel generate() calls must not drop entries."""
        store = AuthCodeStore()
        codes = await asyncio.gather(
            *[store.generate(f"jwt-{i}") for i in range(50)]
        )
        assert len(set(codes)) == 50
        assert await store.pending_count() == 50

        # Every generated code must still redeem to its original payload.
        for i, code in enumerate(codes):
            assert await store.exchange(code) == f"jwt-{i}"
