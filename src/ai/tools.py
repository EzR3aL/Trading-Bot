"""
Tool executor for the AI Trading Assistant.

Maps Claude tool calls to database queries and service calls.
All outputs are sanitized — no order IDs, API keys, or credentials.
"""

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import BotConfig, TradeRecord
from src.strategy.base import StrategyRegistry
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ToolExecutor:
    """Executes tool calls from Claude and returns sanitized results."""

    def __init__(self, user_id: int, db: AsyncSession):
        self.user_id = user_id
        self.db = db

    async def execute(self, tool_name: str, tool_input: dict) -> dict:
        """Route a tool call to the appropriate handler."""
        handler = getattr(self, f"_tool_{tool_name}", None)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            return await handler(tool_input)
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            return {"error": f"Tool execution failed: {str(e)}"}

    async def _tool_get_trading_stats(self, params: dict) -> dict:
        """Get aggregated trading statistics."""
        days = params.get("days", 30)
        since = datetime.utcnow() - timedelta(days=days)

        result = await self.db.execute(
            select(
                func.count().label("total_trades"),
                func.sum(case((TradeRecord.pnl > 0, 1), else_=0)).label("winning_trades"),
                func.sum(case((TradeRecord.pnl <= 0, 1), else_=0)).label("losing_trades"),
                func.sum(TradeRecord.pnl).label("total_pnl"),
                func.sum(TradeRecord.fees).label("total_fees"),
                func.sum(TradeRecord.funding_paid).label("total_funding"),
                func.avg(TradeRecord.pnl_percent).label("avg_pnl_percent"),
                func.max(TradeRecord.pnl).label("best_trade"),
                func.min(TradeRecord.pnl).label("worst_trade"),
            ).where(
                TradeRecord.user_id == self.user_id,
                TradeRecord.status == "closed",
                TradeRecord.entry_time >= since,
            )
        )
        row = result.one()
        total = row.total_trades or 0
        winning = row.winning_trades or 0
        total_pnl = row.total_pnl or 0
        total_fees = row.total_fees or 0
        total_funding = row.total_funding or 0

        return {
            "period_days": days,
            "total_trades": total,
            "winning_trades": winning,
            "losing_trades": row.losing_trades or 0,
            "win_rate": round((winning / total * 100) if total > 0 else 0, 1),
            "total_pnl": round(total_pnl, 2),
            "total_fees": round(total_fees, 2),
            "total_funding": round(total_funding, 2),
            "net_pnl": round(total_pnl - total_fees - abs(total_funding), 2),
            "avg_pnl_percent": round(row.avg_pnl_percent or 0, 2),
            "best_trade": round(row.best_trade or 0, 2),
            "worst_trade": round(row.worst_trade or 0, 2),
        }

    async def _tool_get_recent_trades(self, params: dict) -> dict:
        """Get recent trades, sanitized (no order IDs)."""
        limit = min(params.get("limit", 10), 50)
        status_filter = params.get("status", "all")

        query = select(TradeRecord).where(
            TradeRecord.user_id == self.user_id
        ).order_by(TradeRecord.entry_time.desc()).limit(limit)

        if status_filter in ("open", "closed"):
            query = query.where(TradeRecord.status == status_filter)

        result = await self.db.execute(query)
        trades = result.scalars().all()

        return {
            "trades": [
                {
                    "id": t.id,
                    "symbol": t.symbol,
                    "side": t.side,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "take_profit": t.take_profit,
                    "stop_loss": t.stop_loss,
                    "leverage": t.leverage,
                    "confidence": t.confidence,
                    "reason": t.reason,
                    "status": t.status,
                    "pnl": round(t.pnl, 2) if t.pnl else None,
                    "pnl_percent": round(t.pnl_percent, 2) if t.pnl_percent else None,
                    "fees": round(t.fees or 0, 2),
                    "entry_time": t.entry_time.isoformat() if t.entry_time else None,
                    "exit_time": t.exit_time.isoformat() if t.exit_time else None,
                    "exit_reason": t.exit_reason,
                    "exchange": t.exchange,
                    "demo_mode": t.demo_mode,
                }
                for t in trades
            ],
            "count": len(trades),
        }

    async def _tool_get_market_data(self, _params: dict) -> dict:
        """Get current market metrics."""
        try:
            from src.data.market_data import MarketDataFetcher
            fetcher = MarketDataFetcher()
            metrics = await fetcher.fetch_all_metrics()
            return {
                "fear_greed_index": metrics.fear_greed_index,
                "fear_greed_classification": metrics.fear_greed_classification,
                "long_short_ratio": metrics.long_short_ratio,
                "funding_rate_btc": metrics.funding_rate_btc,
                "funding_rate_eth": metrics.funding_rate_eth,
                "btc_price": metrics.btc_price,
                "eth_price": metrics.eth_price,
                "btc_24h_change_percent": metrics.btc_24h_change_percent,
                "eth_24h_change_percent": metrics.eth_24h_change_percent,
                "timestamp": metrics.timestamp.isoformat() if metrics.timestamp else None,
            }
        except Exception as e:
            logger.warning(f"Market data fetch failed: {e}")
            return {"error": "Market data temporarily unavailable", "details": str(e)}

    async def _tool_get_bot_configs(self, _params: dict) -> dict:
        """Get user's bot configurations."""
        result = await self.db.execute(
            select(BotConfig).where(BotConfig.user_id == self.user_id)
        )
        bots = result.scalars().all()

        return {
            "bots": [
                {
                    "id": b.id,
                    "name": b.name,
                    "strategy_type": b.strategy_type,
                    "exchange_type": b.exchange_type,
                    "mode": b.mode,
                    "trading_pairs": json.loads(b.trading_pairs) if b.trading_pairs else [],
                    "leverage": b.leverage,
                    "position_size_percent": b.position_size_percent,
                    "take_profit_percent": b.take_profit_percent,
                    "stop_loss_percent": b.stop_loss_percent,
                    "is_enabled": b.is_enabled,
                }
                for b in bots
            ],
            "count": len(bots),
        }

    async def _tool_get_available_strategies(self, _params: dict) -> dict:
        """Get available strategies with param schemas."""
        strategies = StrategyRegistry.list_available()
        return {"strategies": strategies}

    async def _tool_create_bot(self, params: dict) -> dict:
        """Return a bot config preview for user confirmation. Does NOT create in DB."""
        strategy_type = params.get("strategy_type", "")
        if not StrategyRegistry.get(strategy_type):
            return {"error": f"Unknown strategy: {strategy_type}"}

        config_preview = {
            "name": params.get("name", "New Bot"),
            "strategy_type": strategy_type,
            "exchange_type": params.get("exchange_type", "bitget"),
            "mode": params.get("mode", "demo"),
            "trading_pairs": params.get("trading_pairs", ["BTCUSDT"]),
            "leverage": params.get("leverage", 4),
            "position_size_percent": params.get("position_size_percent", 7.5),
            "max_trades_per_day": params.get("max_trades_per_day", 2),
            "take_profit_percent": params.get("take_profit_percent", 4.0),
            "stop_loss_percent": params.get("stop_loss_percent", 1.5),
            "daily_loss_limit_percent": params.get("daily_loss_limit_percent", 5.0),
            "strategy_params": params.get("strategy_params", {}),
            "schedule_type": "market_sessions",
        }

        return {
            "action": "bot_config_preview",
            "config": config_preview,
            "message": "Here is the proposed bot configuration. The user can confirm to create it.",
        }

    async def _tool_analyze_trade(self, params: dict) -> dict:
        """Get detailed trade data for analysis."""
        trade_id = params.get("trade_id")
        if not trade_id:
            return {"error": "trade_id is required"}

        result = await self.db.execute(
            select(TradeRecord).where(
                TradeRecord.id == trade_id,
                TradeRecord.user_id == self.user_id,
            )
        )
        trade = result.scalars().first()
        if not trade:
            return {"error": f"Trade {trade_id} not found"}

        metrics = {}
        if trade.metrics_snapshot:
            try:
                metrics = json.loads(trade.metrics_snapshot)
            except json.JSONDecodeError:
                pass

        bot_info = None
        if trade.bot_config_id:
            bot_result = await self.db.execute(
                select(BotConfig).where(BotConfig.id == trade.bot_config_id)
            )
            bot = bot_result.scalars().first()
            if bot:
                bot_info = {
                    "name": bot.name,
                    "strategy_type": bot.strategy_type,
                    "leverage": bot.leverage,
                    "take_profit_percent": bot.take_profit_percent,
                    "stop_loss_percent": bot.stop_loss_percent,
                }

        return {
            "trade": {
                "id": trade.id,
                "symbol": trade.symbol,
                "side": trade.side,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "take_profit": trade.take_profit,
                "stop_loss": trade.stop_loss,
                "leverage": trade.leverage,
                "confidence": trade.confidence,
                "reason": trade.reason,
                "status": trade.status,
                "pnl": round(trade.pnl, 2) if trade.pnl else None,
                "pnl_percent": round(trade.pnl_percent, 2) if trade.pnl_percent else None,
                "fees": round(trade.fees or 0, 2),
                "entry_time": trade.entry_time.isoformat() if trade.entry_time else None,
                "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
                "exit_reason": trade.exit_reason,
                "demo_mode": trade.demo_mode,
            },
            "metrics_at_entry": metrics,
            "bot_config": bot_info,
        }
