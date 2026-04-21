"""Credentials provider for :class:`WebSocketManager` (#240).

Resolves an ``(user_id, exchange)`` tuple into the per-exchange dict
expected by the WS clients. Keeps encrypted-key decryption out of the
manager so the manager stays transport-focused.

Shapes returned
---------------
* ``bitget`` — ``{"api_key", "api_secret", "passphrase", "demo_mode"}``.
  ``demo_mode`` is derived from the user's most recent enabled
  :class:`BotConfig` row for that exchange (``mode == "demo"``). If no
  enabled bot config exists we default to ``False`` — this matches the
  conservative production default and keeps the WS subscribed to the
  live endpoint until a real bot is running.
* ``hyperliquid`` — ``{"wallet_address", "mainnet"}``. HL stores the
  wallet address in the ``api_key_encrypted`` column (see
  ``src/exchanges/hyperliquid/client.py`` where
  ``self.wallet_address = api_key``) — there is no dedicated column.
  ``mainnet`` defaults to ``True``; HL referrals and account state live
  on mainnet regardless of the user's trading mode.

Returns ``None`` when the ``ExchangeConnection`` row is absent or the
credentials needed for the transport are missing — the manager logs it
as ``ws_manager.no_credentials`` and skips the start.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from src.models.database import BotConfig, ExchangeConnection
from src.models.session import get_session
from src.utils.encryption import decrypt_value
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def _resolve_demo_mode(user_id: int, exchange: str) -> bool:
    """Return True if the user's latest enabled bot for ``exchange`` is demo.

    Falls back to ``False`` when no enabled bot exists — the WS client
    defaults to the live endpoint in that case, which is the safer
    production default. ``BotConfig.mode`` is one of ``demo | live | both``.
    ``both`` → live transport (demo is a strict subset).
    """
    async with get_session() as session:
        result = await session.execute(
            select(BotConfig.mode)
            .where(
                BotConfig.user_id == user_id,
                BotConfig.exchange_type == exchange,
                BotConfig.is_enabled.is_(True),
            )
            .order_by(BotConfig.updated_at.desc().nullslast(), BotConfig.id.desc())
            .limit(1)
        )
        mode = result.scalar_one_or_none()
    return mode == "demo"


async def ws_credentials_provider(
    user_id: int, exchange: str,
) -> Optional[dict]:
    """Return transport credentials for ``(user_id, exchange)`` or ``None``.

    See module docstring for the shape each exchange expects.
    """
    async with get_session() as session:
        result = await session.execute(
            select(ExchangeConnection).where(
                ExchangeConnection.user_id == user_id,
                ExchangeConnection.exchange_type == exchange,
            )
        )
        conn = result.scalar_one_or_none()

    if conn is None:
        return None

    if exchange == "bitget":
        demo_mode = await _resolve_demo_mode(user_id, exchange)
        if demo_mode:
            key_enc = conn.demo_api_key_encrypted
            secret_enc = conn.demo_api_secret_encrypted
            passphrase_enc = conn.demo_passphrase_encrypted
        else:
            key_enc = conn.api_key_encrypted
            secret_enc = conn.api_secret_encrypted
            passphrase_enc = conn.passphrase_encrypted
        if not key_enc or not secret_enc:
            return None
        return {
            "api_key": decrypt_value(key_enc),
            "api_secret": decrypt_value(secret_enc),
            "passphrase": decrypt_value(passphrase_enc) if passphrase_enc else "",
            "demo_mode": demo_mode,
        }

    if exchange == "hyperliquid":
        # HL stores the wallet address in api_key_encrypted — see
        # src/exchanges/hyperliquid/client.py (self.wallet_address = api_key).
        # Prefer live creds; fall back to demo since the EVM address is
        # the same on mainnet and testnet.
        wallet_enc = conn.api_key_encrypted or conn.demo_api_key_encrypted
        if not wallet_enc:
            return None
        return {
            "wallet_address": decrypt_value(wallet_enc),
            "mainnet": True,
        }

    return None


__all__ = ["ws_credentials_provider"]
