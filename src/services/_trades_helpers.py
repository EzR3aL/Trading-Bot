"""Module-level helpers for :mod:`src.services.trades_service`.

Pure functions and small async helpers extracted from the original
``trades_service.py`` so the per-concern mixins (and a handful of
external callers) can share them without dragging the whole file
around.

Public API note
---------------
``trades_service.py`` re-exports the helpers consumed by other modules
(``_compute_trailing_stop``, ``_compute_atr_for_trailing``,
``_derive_overall_status``, ``TRAILING_STOP_STRATEGIES``) so existing
``from src.services.trades_service import ...`` imports keep working
unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.risk_state_manager import RiskOpResult, RiskOpStatus
from src.data.market_data import MarketDataFetcher
from src.models.database import TradeRecord, UserConfig
from src.services.exceptions import InvalidTpSlIntent
from src.strategy.base import resolve_strategy_params
from src.utils.logger import get_logger

logger = get_logger(__name__)


#: Strategies that compute an ATR-based trailing stop for the dashboard display.
#: Owned by the service after #325 PR-3 — external callers (router, portfolio
#: service, bots_statistics router) import this via ``trades_service``.
TRAILING_STOP_STRATEGIES = ("edge_indicator", "liquidation_hunter")


# ---------------------------------------------------------------------------
# Status code sets used by the manager-path ``overall_status`` aggregate.
# ---------------------------------------------------------------------------


_RISK_OK_STATUSES = {RiskOpStatus.CONFIRMED.value, RiskOpStatus.CLEARED.value}
_RISK_FAIL_STATUSES = {
    RiskOpStatus.REJECTED.value,
    RiskOpStatus.CANCEL_FAILED.value,
}


def _derive_overall_status(legs: list) -> str:
    """Aggregate per-leg statuses into a single overall outcome label.

    ``legs`` is typed as ``list`` rather than ``list[RiskLegOutcome]`` to
    avoid a circular import — every element only needs a ``.status``
    attribute.
    """
    if not legs:
        return "no_change"
    statuses = [leg.status for leg in legs]
    has_ok = any(s in _RISK_OK_STATUSES for s in statuses)
    has_fail = any(s in _RISK_FAIL_STATUSES for s in statuses)
    if has_ok and not has_fail:
        return "all_confirmed"
    if has_fail and not has_ok:
        return "all_rejected"
    if has_ok and has_fail:
        return "partial_success"
    return "no_change"


def _risk_result_to_outcome(result: RiskOpResult):
    """Convert a :class:`RiskOpResult` into the service-layer outcome type.

    Imported lazily to avoid a circular dependency with
    ``trades_service`` (which defines ``RiskLegOutcome``).
    """
    from src.services.trades_service import RiskLegOutcome
    return RiskLegOutcome(
        value=result.value,
        status=result.status.value,
        order_id=result.order_id,
        error=result.error,
        latency_ms=result.latency_ms,
    )


def _leg_dict_to_snapshot(leg: Optional[dict]):
    """Convert a reconcile-leg dict into a :class:`RiskLegSnapshot`.

    Returns ``None`` when the manager reports no state for the leg so the
    router can project ``None`` onto the response's ``tp`` / ``sl`` /
    ``trailing`` fields directly.
    """
    if leg is None:
        return None
    from src.services.trades_service import RiskLegSnapshot
    return RiskLegSnapshot(
        value=leg.get("value"),
        status=leg.get("status", RiskOpStatus.CLEARED.value),
        order_id=leg.get("order_id"),
        error=leg.get("error"),
        latency_ms=int(leg.get("latency_ms", 0)),
    )


# ---------------------------------------------------------------------------
# Trailing-stop helpers (lifted from the router, FastAPI-free)
# ---------------------------------------------------------------------------


async def _compute_trailing_stop(
    trade: TradeRecord,
    strategy_type: Optional[str],
    strategy_params_json: Optional[str],
    klines_cache: Optional[dict] = None,
) -> dict:
    """Compute live trailing-stop fields for an open trade.

    Returns a dict with keys matching the ``TradeResponse`` trailing-stop
    fields. Uses ``resolve_strategy_params`` so the dashboard's view matches
    the live strategy exactly (same DEFAULTS -> RISK_PROFILE -> user_params
    merge, same ``kline_interval``).

    Behavior preserved verbatim from the pre-extract router handler.
    """
    if trade.status != "open":
        return {}

    has_manual_override = trade.trailing_atr_override is not None
    has_strategy = strategy_type in TRAILING_STOP_STRATEGIES

    if not has_manual_override and not has_strategy:
        return {}

    params = resolve_strategy_params(strategy_type, strategy_params_json)

    if not has_manual_override and not params.get("trailing_stop_enabled", True):
        return {}

    highest_price = trade.highest_price
    if highest_price is None:
        return {"trailing_stop_active": False, "can_close_at_loss": True}

    atr_period = params.get("atr_period", 14)
    interval = params.get("kline_interval", "1h")
    cache_key = (trade.symbol, interval)
    if klines_cache is not None and cache_key in klines_cache:
        klines = klines_cache[cache_key]
    else:
        try:
            fetcher = MarketDataFetcher()
            klines = await fetcher.get_binance_klines(
                trade.symbol, interval, atr_period + 15,
            )
            await fetcher.close()
        except Exception as exc:
            logger.debug("Trailing stop kline fetch failed for %s: %s", trade.symbol, exc)
            return {"trailing_stop_active": False}

    if not klines:
        return {"trailing_stop_active": False}

    atr_series = MarketDataFetcher.calculate_atr(klines, atr_period)
    atr_val = atr_series[-1] if atr_series else trade.entry_price * 0.015

    breakeven_atr = params.get("trailing_breakeven_atr", 1.5)
    trail_atr = (
        trade.trailing_atr_override
        if trade.trailing_atr_override is not None
        else params.get("trailing_trail_atr", 2.5)
    )
    breakeven_threshold = atr_val * breakeven_atr
    trail_distance = atr_val * trail_atr

    side = trade.side
    entry = trade.entry_price

    if side == "long":
        was_profitable = (highest_price - entry) >= breakeven_threshold
        if was_profitable:
            trailing_stop = max(highest_price - trail_distance, entry)
            distance = highest_price - trailing_stop
            distance_pct = (distance / highest_price) * 100 if highest_price else 0
            return {
                "trailing_stop_active": True,
                "trailing_stop_price": round(trailing_stop, 2),
                "trailing_stop_distance": round(distance, 2),
                "trailing_stop_distance_pct": round(distance_pct, 2),
                "can_close_at_loss": False,
            }
        return {
            "trailing_stop_active": False,
            "trailing_stop_distance_pct": round(trail_atr, 1),
            "can_close_at_loss": True,
        }
    # SHORT: highest_price tracks the lowest price since entry
    was_profitable = (entry - highest_price) >= breakeven_threshold
    if was_profitable:
        trailing_stop = min(highest_price + trail_distance, entry)
        distance = trailing_stop - highest_price
        distance_pct = (distance / highest_price) * 100 if highest_price else 0
        return {
            "trailing_stop_active": True,
            "trailing_stop_price": round(trailing_stop, 2),
            "trailing_stop_distance": round(distance, 2),
            "trailing_stop_distance_pct": round(distance_pct, 2),
            "can_close_at_loss": False,
        }
    return {
        "trailing_stop_active": False,
        "trailing_stop_distance_pct": round(trail_atr, 1),
        "can_close_at_loss": True,
    }


async def _compute_atr_for_trailing(
    symbol: str,
    entry_price: float,
    market_data_fetcher_cls: type,
) -> float:
    """Fetch ATR for the trailing-stop endpoint.

    Returns the live 1h/14-period ATR if available, otherwise a 1.5%
    fallback based on the trade's entry price. Accepts the fetcher class
    as a parameter so the router's patched class (from the
    characterization tests) is used rather than a fresh import.
    """
    fetcher = market_data_fetcher_cls()
    try:
        klines = await fetcher.get_binance_klines(symbol, "1h", 30)
        atr_series = market_data_fetcher_cls.calculate_atr(klines, 14)
        if atr_series:
            return atr_series[-1]
    except Exception as atr_err:  # noqa: BLE001 — fallback to estimate
        logger.warning(
            "ATR fetch failed for %s, using 1.5%% estimate: %s",
            symbol, atr_err,
        )
    finally:
        await fetcher.close()
    return entry_price * 0.015


async def _build_trailing_intent(
    *,
    trade: TradeRecord,
    callback_pct: float,
    market_data_fetcher_cls: type,
) -> dict:
    """Translate a UI trailing callback_pct into the manager's payload.

    Mirrors the router helper verbatim. The manager expects a dict with
    ``callback_rate``, ``activation_price``, ``trigger_price`` and
    ``atr_override`` keys so the user's chosen multiplier can be persisted
    on the trade row through Phase D.
    """
    atr_val = await _compute_atr_for_trailing(
        trade.symbol, trade.entry_price, market_data_fetcher_cls,
    )
    atr_mult = callback_pct
    trail_distance = atr_val * atr_mult
    callback_rate = (trail_distance / trade.entry_price) * 100
    breakeven_atr = 1.5
    if trade.side == "long":
        trigger = trade.entry_price + atr_val * breakeven_atr
    else:
        trigger = trade.entry_price - atr_val * breakeven_atr
    return {
        "callback_rate": round(callback_rate, 2),
        "activation_price": None,
        "trigger_price": round(trigger, 2),
        "atr_override": atr_mult,
    }


# ---------------------------------------------------------------------------
# TP/SL validation (FastAPI-free)
# ---------------------------------------------------------------------------


def _validate_tp_sl_against_trade(intent, trade: TradeRecord) -> None:
    """Run the shared side/entry-price validation.

    Mirrors the pre-extract router helper ``_validate_tp_sl_values``
    verbatim. Raises :class:`InvalidTpSlIntent` with a canonical reason
    string; the router maps the reason to the right error detail +
    status code for its path (400 on legacy, 400 on manager).
    """
    if intent.remove_tp and intent.take_profit is not None:
        raise InvalidTpSlIntent("tp_conflict")
    if intent.remove_sl and intent.stop_loss is not None:
        raise InvalidTpSlIntent("sl_conflict")
    if trade.entry_price <= 0:
        raise InvalidTpSlIntent("invalid_entry_price")

    is_long = trade.side == "long"
    if intent.take_profit is not None:
        if intent.take_profit <= 0:
            raise InvalidTpSlIntent("tp_non_positive")
        if is_long and intent.take_profit <= trade.entry_price:
            raise InvalidTpSlIntent("tp_below_entry_long")
        if not is_long and intent.take_profit >= trade.entry_price:
            raise InvalidTpSlIntent("tp_above_entry_short")
    if intent.stop_loss is not None:
        if intent.stop_loss <= 0:
            raise InvalidTpSlIntent("sl_non_positive")
        if is_long and intent.stop_loss >= trade.entry_price:
            raise InvalidTpSlIntent("sl_above_entry_long")
        if not is_long and intent.stop_loss <= trade.entry_price:
            raise InvalidTpSlIntent("sl_below_entry_short")


# ---------------------------------------------------------------------------
# Sync helpers
# ---------------------------------------------------------------------------


async def _resolve_exit_reason(
    *,
    trade: TradeRecord,
    exit_price: float,
    exit_time_now: datetime,
    rsm_enabled: bool,
    get_risk_state_manager: Callable[[], Any],
) -> str:
    """Resolve a trade's exit reason using classify_close or the heuristic.

    When ``rsm_enabled`` is True we defer to
    :meth:`RiskStateManager.classify_close` — it probes the exchange's
    order history and attributes the close precisely. On failure we fall
    back to the legacy heuristic. When the flag is off, only the
    heuristic runs. Behavior matches the pre-extract handler.
    """
    if rsm_enabled:
        try:
            manager = get_risk_state_manager()
            return await manager.classify_close(
                trade.id, exit_price, exit_time_now,
            )
        except Exception as classify_err:  # noqa: BLE001
            logger.warning(
                "Sync: classify_close failed for trade %s, falling back to "
                "heuristic: %s",
                trade.id, classify_err,
            )
    # Heuristic path (flag off or classify_close failed)
    if trade.take_profit and abs(exit_price - trade.take_profit) < trade.entry_price * 0.005:
        return "TAKE_PROFIT"
    if trade.stop_loss and abs(exit_price - trade.stop_loss) < trade.entry_price * 0.005:
        return "STOP_LOSS"
    return "MANUAL_CLOSE"


async def _send_sync_discord_notifications(
    *,
    db: AsyncSession,
    user_id: int,
    open_trades: list[TradeRecord],
    closed_trades: list,
    decrypt_value: Callable[[str], str],
    discord_notifier_cls: Callable[..., Any],
) -> None:
    """Fire-and-forget Discord webhook sends for closed trades.

    The router used to inline this block; we keep the try/except
    semantics unchanged so the sync response is never affected by a
    notifier failure.
    """
    cfg_result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == user_id)
    )
    config = cfg_result.scalar_one_or_none()
    if not config or not config.discord_webhook_url:
        return

    try:
        webhook_url = decrypt_value(config.discord_webhook_url)
    except (ValueError, Exception):
        webhook_url = None

    if not webhook_url:
        return

    notifier = discord_notifier_cls(webhook_url=webhook_url)
    try:
        for ct in closed_trades:
            matching = [t for t in open_trades if t.id == ct.id]
            if not matching:  # pragma: no cover — notify loop skip
                continue
            trade = matching[0]

            duration_minutes = None
            if trade.entry_time:
                entry = trade.entry_time
                if entry.tzinfo is None:
                    entry = entry.replace(tzinfo=timezone.utc)
                duration = datetime.now(timezone.utc) - entry
                duration_minutes = int(duration.total_seconds() / 60)

            await notifier.send_trade_exit(
                symbol=trade.symbol,
                side=trade.side,
                size=trade.size,
                entry_price=trade.entry_price,
                exit_price=trade.exit_price,
                pnl=trade.pnl,
                pnl_percent=trade.pnl_percent,
                fees=trade.fees or 0,
                funding_paid=trade.funding_paid or 0,
                reason=trade.exit_reason,
                order_id=trade.order_id,
                duration_minutes=duration_minutes,
                demo_mode=trade.demo_mode,
                strategy_reason=trade.reason,
            )
    except Exception as e:
        logger.warning("Discord sync notification failed: %s", e)
    finally:
        await notifier.close()
