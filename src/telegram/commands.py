"""Telegram bot command handlers for interactive trade queries."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select

from src.models.database import BotConfig, TradeRecord
from src.models.session import get_session
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Commands registered with Telegram's setMyCommands API
COMMANDS = [
    {"command": "status", "description": "Bot-Übersicht & offene Trades"},
    {"command": "trades", "description": "Offene Positionen mit aktuellem PnL"},
    {"command": "pnl", "description": "PnL-Zusammenfassung (heute/7d/30d)"},
    {"command": "help", "description": "Verfügbare Befehle anzeigen"},
]


async def handle_command(command: str, user_id: int, args: str = "") -> str:
    """Route a command to the appropriate handler and return the response text."""
    handlers = {
        "/start": _handle_help,
        "/help": _handle_help,
        "/status": _handle_status,
        "/trades": _handle_trades,
        "/pnl": _handle_pnl,
    }
    handler = handlers.get(command)
    if not handler:
        return (
            "Unbekannter Befehl. Tippe /help für eine Liste der verfügbaren Befehle."
        )
    return await handler(user_id, args)


async def _handle_help(user_id: int, args: str = "") -> str:
    return (
        "<b>Trading Bot — Befehle</b>\n\n"
        "/status — Bot-Übersicht & offene Trades\n"
        "/trades — Offene Positionen mit aktuellem PnL\n"
        "/pnl — PnL-Zusammenfassung (heute/7d/30d)\n"
        "/pnl 7 — PnL der letzten 7 Tage\n"
        "/pnl 90 — PnL der letzten 90 Tage\n"
        "/help — Diese Hilfe anzeigen"
    )


async def _handle_status(user_id: int, args: str = "") -> str:
    async with get_session() as db:
        # Count bots
        bots_result = await db.execute(
            select(
                func.count().label("total"),
                func.sum(case((BotConfig.is_enabled == True, 1), else_=0)).label("active"),  # noqa: E712
            ).where(BotConfig.user_id == user_id)
        )
        row = bots_result.one()
        total_bots = row.total or 0
        active_bots = row.active or 0

        # Count open trades
        open_result = await db.execute(
            select(func.count()).where(
                TradeRecord.user_id == user_id,
                TradeRecord.status == "open",
            )
        )
        open_trades = open_result.scalar() or 0

        # Today's closed trades
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_result = await db.execute(
            select(
                func.count().label("cnt"),
                func.coalesce(func.sum(TradeRecord.pnl), 0).label("pnl"),
            ).where(
                TradeRecord.user_id == user_id,
                TradeRecord.status == "closed",
                TradeRecord.exit_time >= today_start,
            )
        )
        today = today_result.one()

    lines = [
        "<b>Status</b>\n",
        f"Bots: {active_bots} aktiv / {total_bots} gesamt",
        f"Offene Trades: {open_trades}",
        f"Trades heute: {today.cnt or 0}",
        f"PnL heute: <b>{_fmt_pnl(today.pnl)}</b>",
    ]
    return "\n".join(lines)


async def _handle_trades(user_id: int, args: str = "") -> str:
    async with get_session() as db:
        result = await db.execute(
            select(TradeRecord).where(
                TradeRecord.user_id == user_id,
                TradeRecord.status == "open",
            ).order_by(TradeRecord.entry_time.desc())
        )
        trades = result.scalars().all()

    if not trades:
        return "Keine offenen Trades."

    lines = ["<b>Offene Trades</b>\n"]
    for t in trades:
        side_emoji = "🟢" if t.side == "long" else "🔴"
        pnl_text = ""
        if t.pnl is not None:
            pnl_text = f" | PnL: <b>{_fmt_pnl(t.pnl)}</b>"
        elif t.entry_price and t.size:
            pnl_text = f" | Entry: ${t.entry_price:,.2f}"

        mode = "demo" if t.demo_mode else "live"
        lines.append(
            f"{side_emoji} <b>{t.symbol}</b> {t.side} ({mode}){pnl_text}"
        )

    lines.append(f"\nGesamt: {len(trades)} Position{'en' if len(trades) != 1 else ''}")
    return "\n".join(lines)


async def _handle_pnl(user_id: int, args: str = "") -> str:
    # Parse optional days argument
    days = 30
    if args.strip().isdigit():
        days = min(int(args.strip()), 365)

    async with get_session() as db:
        periods = [
            ("Heute", 1),
            ("7 Tage", 7),
            ("30 Tage", 30),
        ]
        if days not in [1, 7, 30]:
            periods.append((f"{days} Tage", days))

        lines = ["<b>PnL-Übersicht</b>\n"]

        for label, d in periods:
            since = datetime.now(timezone.utc) - timedelta(days=d)
            result = await db.execute(
                select(
                    func.count().label("cnt"),
                    func.coalesce(func.sum(TradeRecord.pnl), 0).label("pnl"),
                    func.coalesce(func.sum(TradeRecord.fees), 0).label("fees"),
                    func.sum(case((TradeRecord.pnl > 0, 1), else_=0)).label("wins"),
                ).where(
                    TradeRecord.user_id == user_id,
                    TradeRecord.status == "closed",
                    TradeRecord.exit_time >= since,
                )
            )
            row = result.one()
            cnt = row.cnt or 0
            pnl = row.pnl or 0
            fees = row.fees or 0
            wins = row.wins or 0
            net = pnl - fees
            wr = f"{wins / cnt * 100:.0f}%" if cnt > 0 else "-"

            lines.append(
                f"<b>{label}:</b> {_fmt_pnl(net)} "
                f"({cnt} Trades, WR: {wr})"
            )

    return "\n".join(lines)


def _fmt_pnl(value: float) -> str:
    """Format PnL with sign and color-neutral display."""
    if value >= 0:
        return f"+${value:,.2f}"
    return f"-${abs(value):,.2f}"
