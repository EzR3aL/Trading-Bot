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
