"""Copy-trading strategy: mirror a public Hyperliquid wallet's trades."""

import json
import time
from datetime import datetime, time as dt_time, timezone
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
    StrategyRegistry,
    StrategyTickContext,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _save_strategy_state(bot_config, state: dict) -> None:
    """Persist strategy_state JSON on the BotConfig (in-memory only).

    Writes to the in-memory object. Actual DB persistence happens via the
    async helper `_save_strategy_state_db` from inside `run_tick` (an async
    context). This function is kept synchronous so existing tests that
    monkey-patch it don't need to deal with awaitables.
    """
    bot_config.strategy_state = json.dumps(state)


async def _save_strategy_state_db(bot_config_id: int, state_json: str) -> None:
    """Async DB persist of strategy_state. Best-effort, swallows errors."""
    try:
        from sqlalchemy import update
        from src.models.session import get_session
        from src.models.database import BotConfig as DBBotConfig

        async with get_session() as session:
            await session.execute(
                update(DBBotConfig)
                .where(DBBotConfig.id == bot_config_id)
                .values(strategy_state=state_json)
            )
            await session.commit()
    except Exception:
        pass


def _load_strategy_state(bot_config) -> dict:
    raw = getattr(bot_config, "strategy_state", None)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _parse_csv_list(value: Optional[str]) -> set:
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
            "take_profit_pct": {
                "type": "float",
                "label": "Take Profit % (leer = wie Source)",
                "description": "Wenn gesetzt, überschreibt dies das TP der Source. Leer = Source-TP übernehmen.",
                "default": None,
                "min": 0.1,
                "max": 100,
            },
            "stop_loss_pct": {
                "type": "float",
                "label": "Stop Loss % (leer = wie Source)",
                "description": "Wenn gesetzt, überschreibt dies das SL der Source und wirkt zusätzlich als Hard-Cap wenn die Source kein SL hat.",
                "default": None,
                "min": 0.1,
                "max": 50,
            },
            "daily_loss_limit_pct": {
                "type": "float",
                "label": "Tägliches Verlustlimit %",
                "description": "Wenn der Bot heute diesen Drawdown erreicht, werden weitere Kopien bis Mitternacht UTC pausiert.",
                "default": None,
                "min": 0.5,
                "max": 50,
            },
            "max_trades_per_day": {
                "type": "int",
                "label": "Max Trades pro Tag",
                "description": "Bot ignoriert weitere Source-Entries wenn das Tageskontingent erreicht ist.",
                "default": None,
                "min": 1,
                "max": 200,
            },
        }

    @classmethod
    def get_description(cls) -> str:
        return "Kopiert die Trades einer öffentlichen Hyperliquid-Wallet 1:1."

    # ---------- Interface stubs (unused for self-managed) ----------

    async def generate_signal(self, symbol):  # type: ignore[override]
        return None

    async def should_trade(self, signal):  # type: ignore[override]
        return False, "self-managed"

    # ---------- Self-managed entry point ----------

    async def run_tick(self, ctx: StrategyTickContext) -> None:
        wallet = (self.params.get("source_wallet") or "").strip()
        if not wallet:
            ctx.logger.warning(
                "[Bot:%s] copy_trading: no source_wallet configured",
                ctx.bot_config_id,
            )
            return

        target_exchange = ctx.bot_config.exchange_type
        state = _load_strategy_state(ctx.bot_config)

        # Cold start: initialise watermark to now so existing fills are skipped.
        if "last_processed_fill_ms" not in state:
            state["last_processed_fill_ms"] = int(time.time() * 1000)
            _save_strategy_state(ctx.bot_config, state)
            await _save_strategy_state_db(ctx.bot_config_id, ctx.bot_config.strategy_state)
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
                await _save_strategy_state_db(ctx.bot_config_id, ctx.bot_config.strategy_state)
        finally:
            await tracker.close()

    # ---------- Helpers ----------

    async def _process_entry_fill(
        self,
        ctx: StrategyTickContext,
        fill: SourceFill,
        target_exchange: str,
    ) -> None:
        """Dispatch a copy of a source entry fill onto the target exchange.

        v1.1 TP/SL semantics:
        - If the user sets ``take_profit_pct`` or ``stop_loss_pct`` in the
          strategy params, the bot computes absolute TP/SL prices from the
          entry price (entry * (1 ± pct/100)) and places them on the exchange.
        - If both are left empty, no TP/SL is placed. Hyperliquid fills do
          not carry TP/SL metadata (on HL these are separate orders), so
          "follow the source" is effectively a no-op — matching v1 behaviour
          where ``copy_tp_sl=False`` was the default.

        v1.1 also enforces two global safety limits BEFORE slot/whitelist
        checks, so they short-circuit the dispatch early:
        - ``daily_loss_limit_pct``: pauses copies until UTC midnight once
          the realized day-PnL drawdown hits the configured percentage.
        - ``max_trades_per_day``: caps the number of entries dispatched
          per UTC day.
        """
        # --- v1.1 safety limits (enforced before slot/whitelist checks) ---

        # A) Daily loss limit
        daily_loss_pct = self.params.get("daily_loss_limit_pct")
        if daily_loss_pct is not None and float(daily_loss_pct) > 0:
            today_pnl = await self._get_today_realized_pnl(ctx)
            budget = float(self.params.get("budget_usdt", 0))
            if (
                budget > 0
                and today_pnl < 0
                and (abs(today_pnl) / budget) * 100 >= float(daily_loss_pct)
            ):
                await self._notify_skip(
                    ctx,
                    f"Tägliches Verlustlimit von {daily_loss_pct}% erreicht "
                    f"(today PnL: {today_pnl:.2f} USDT). Pausiere bis Mitternacht UTC.",
                )
                return

        # B) Max trades per day
        max_trades = self.params.get("max_trades_per_day")
        if max_trades is not None and int(max_trades) > 0:
            today_count = await self._get_today_entry_count(ctx)
            if today_count >= int(max_trades):
                await self._notify_skip(
                    ctx,
                    f"Max-Trades-pro-Tag-Limit erreicht ({today_count}/{max_trades}). "
                    f"Pausiere bis Mitternacht UTC.",
                )
                return

        coin = fill.coin

        # Whitelist / blacklist
        whitelist = _parse_csv_list(self.params.get("symbol_whitelist"))
        blacklist = _parse_csv_list(self.params.get("symbol_blacklist"))
        if whitelist and coin.upper() not in whitelist:
            ctx.logger.info(
                "[Bot:%s] copy_trading: %s not in whitelist, skipped",
                ctx.bot_config_id, coin,
            )
            return
        if coin.upper() in blacklist:
            ctx.logger.info(
                "[Bot:%s] copy_trading: %s in blacklist, skipped",
                ctx.bot_config_id, coin,
            )
            return

        # Symbol mapping + availability
        try:
            target_sym = to_exchange_symbol(coin, target_exchange)
        except Exception:
            target_sym = None
        if not target_sym:
            await self._notify_skip(
                ctx,
                f"Symbol-Mapping für {coin} → {target_exchange} fehlgeschlagen",
            )
            return

        try:
            available = await get_exchange_symbols(target_exchange)
        except Exception:
            available = []
        if target_sym not in available:
            await self._notify_skip(
                ctx,
                f"Source eröffnete {coin} {fill.side.upper()} — nicht auf "
                f"{target_exchange} verfügbar, übersprungen.",
            )
            return

        # Slot exhaustion
        budget = float(self.params.get("budget_usdt", 0))
        max_slots = int(self.params.get("max_slots", 5))
        open_count = await ctx.trade_executor.get_open_trades_count(ctx.bot_config_id)
        if open_count >= max_slots:
            ctx.logger.info(
                "[Bot:%s] copy_trading: slot exhausted (%d/%d), skip %s",
                ctx.bot_config_id, open_count, max_slots, coin,
            )
            return

        # Sizing
        notional = budget / max_slots
        if notional < float(self.params.get("min_position_size_usdt", 10)):
            ctx.logger.info(
                "[Bot:%s] copy_trading: notional %.2f below min, skip",
                ctx.bot_config_id, notional,
            )
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

        # v1.1 TP/SL override: user-configured percentages override source
        # TP/SL. If None, no TP/SL is placed (source fills don't carry them).
        user_tp_pct = self.params.get("take_profit_pct")
        user_sl_pct = self.params.get("stop_loss_pct")

        await ctx.trade_executor.execute_trade(
            symbol=target_sym,
            side=fill.side,
            notional_usdt=notional,
            leverage=effective_leverage,
            reason=f"COPY_TRADING source={fill.hash[:8]} coin={coin}",
            bot_config_id=ctx.bot_config_id,
            take_profit_pct=user_tp_pct,
            stop_loss_pct=user_sl_pct,
        )

    async def _process_exits(
        self,
        ctx: StrategyTickContext,
        source_positions: list,
        target_exchange: str,
    ) -> None:
        active: set = set()
        for pos in source_positions:
            try:
                sym = to_exchange_symbol(pos.coin, target_exchange)
            except Exception:
                sym = None
            if sym:
                active.add((sym, pos.side))

        get_open = getattr(ctx.trade_executor, "get_open_trades_for_bot", None)
        if get_open is None:
            return
        try:
            result = get_open(ctx.bot_config_id)
            import inspect
            if inspect.isawaitable(result):
                open_trades = await result
            else:
                open_trades = result
        except Exception:
            return
        if not isinstance(open_trades, (list, tuple)):
            return
        for trade in open_trades:
            if (trade.symbol, trade.side) not in active:
                ctx.logger.info(
                    "[Bot:%s] copy_trading: source closed %s %s — closing trade #%s",
                    ctx.bot_config_id, trade.symbol, trade.side, trade.id,
                )
                await ctx.trade_executor.close_trade_by_strategy(
                    trade, reason="COPY_SOURCE_CLOSED",
                )

    def _today_start_utc(self) -> datetime:
        return datetime.combine(
            datetime.now(timezone.utc).date(), dt_time.min, tzinfo=timezone.utc
        )

    async def _get_today_realized_pnl(self, ctx: StrategyTickContext) -> float:
        """Sum realized PnL of trades closed by this bot since UTC midnight."""
        try:
            from sqlalchemy import select, func
            from src.models.session import get_session
            from src.models.database import TradeRecord
        except Exception:
            return 0.0
        start = self._today_start_utc()
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(func.coalesce(func.sum(TradeRecord.pnl), 0)).where(
                        TradeRecord.bot_config_id == ctx.bot_config_id,
                        TradeRecord.status == "closed",
                        TradeRecord.exit_time >= start,
                    )
                )
                return float(result.scalar_one() or 0)
        except Exception:
            return 0.0

    async def _get_today_entry_count(self, ctx: StrategyTickContext) -> int:
        """Count trades this bot has dispatched (entered) since UTC midnight."""
        try:
            from sqlalchemy import select, func
            from src.models.session import get_session
            from src.models.database import TradeRecord
        except Exception:
            return 0
        start = self._today_start_utc()
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(func.count(TradeRecord.id)).where(
                        TradeRecord.bot_config_id == ctx.bot_config_id,
                        TradeRecord.entry_time >= start,
                    )
                )
                return int(result.scalar_one() or 0)
        except Exception:
            return 0

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
