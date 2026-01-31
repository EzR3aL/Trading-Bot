"""
Test script to send a Discord notification via webhook.
"""
import asyncio
from src.notifications.discord_notifier import DiscordNotifier
from config import settings

async def test_discord():
    """Send a test notification to Discord."""

    # Create notifier
    notifier = DiscordNotifier()

    print(f"📡 Sending test notification to Discord...")
    print(f"   Webhook URL: {settings.discord.webhook_url[:50]}...")

    # Send bot status message
    success = await notifier.send_bot_status(
        status="STARTED",
        message="✅ Discord Webhook Test erfolgreich! Der Bot kann jetzt Benachrichtigungen senden.",
        stats={
            "Trading Mode": "Demo" if settings.trading.demo_mode else "Live",
            "Max Trades/Day": settings.trading.max_trades_per_day,
            "Position Size": f"{settings.trading.position_size_percent}%",
            "Leverage": f"{settings.trading.leverage}x",
            "Trading Pairs": ", ".join(settings.trading.trading_pairs),
        }
    )

    if success:
        print("✅ Test-Nachricht erfolgreich gesendet!")
        print("   Überprüfen Sie Ihren Discord-Kanal.")
    else:
        print("❌ Fehler beim Senden der Test-Nachricht.")
        print("   Bitte überprüfen Sie:")
        print("   1. Webhook-URL in .env korrekt?")
        print("   2. Webhook in Discord noch aktiv?")

    await notifier.close()
    return success

if __name__ == "__main__":
    asyncio.run(test_discord())
