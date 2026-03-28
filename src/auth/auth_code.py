"""One-time authorization code store for the auth bridge.

Codes are short-lived (60 s), single-use tokens that carry a Supabase
JWT from the main site to the bot backend.  They live in memory — a
container restart simply invalidates any pending codes, which is fine
because they expire in under a minute anyway.
"""

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

CODE_TTL_SECONDS = 60
CLEANUP_INTERVAL_SECONDS = 300  # 5 minutes


@dataclass
class _PendingCode:
    supabase_jwt: str
    created_at: float = field(default_factory=time.monotonic)
    used: bool = False

    @property
    def expired(self) -> bool:
        return (time.monotonic() - self.created_at) > CODE_TTL_SECONDS


class AuthCodeStore:
    """Thread-safe, in-memory store for one-time auth codes."""

    def __init__(self) -> None:
        self._codes: dict[str, _PendingCode] = {}
        self._cleanup_task: asyncio.Task | None = None

    # ── Public API ────────────────────────────────────────────

    def generate(self, supabase_jwt: str) -> str:
        """Create a new one-time code and return it."""
        code = secrets.token_urlsafe(24)
        self._codes[code] = _PendingCode(supabase_jwt=supabase_jwt)
        logger.info("AUTH_BRIDGE: Generated one-time code (total pending: %d)", len(self._codes))
        return code

    def exchange(self, code: str) -> str | None:
        """Consume a code and return the stored Supabase JWT.

        Returns None if the code does not exist, is expired, or was
        already used.
        """
        entry = self._codes.get(code)
        if entry is None:
            logger.warning("AUTH_BRIDGE: Code exchange failed — code not found")
            return None
        if entry.expired:
            del self._codes[code]
            logger.warning("AUTH_BRIDGE: Code exchange failed — code expired")
            return None
        if entry.used:
            logger.warning("AUTH_BRIDGE: Code exchange failed — code already used")
            return None

        entry.used = True
        jwt_value = entry.supabase_jwt
        del self._codes[code]
        logger.info("AUTH_BRIDGE: Code exchanged successfully")
        return jwt_value

    # ── Background cleanup ────────────────────────────────────

    def start_cleanup(self) -> None:
        """Start the background task that purges expired codes."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    def stop_cleanup(self) -> None:
        """Cancel the background cleanup task."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            self._cleanup_task = None

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
                before = len(self._codes)
                self._codes = {
                    k: v for k, v in self._codes.items() if not v.expired
                }
                removed = before - len(self._codes)
                if removed:
                    logger.debug("AUTH_BRIDGE: Cleaned up %d expired codes", removed)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("AUTH_BRIDGE: Cleanup task error")


# Singleton — shared across the application
auth_code_store = AuthCodeStore()
