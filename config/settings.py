"""
Configuration settings for the Bitget Trading Bot.
Loads settings from environment variables with sensible defaults.
"""

import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def get_env(key: str, default: str = "", cast_type: type = str):
    """Get environment variable with type casting."""
    value = os.getenv(key, default)
    if cast_type == bool:
        return value.lower() in ("true", "1", "yes")
    if cast_type == list:
        return [item.strip() for item in value.split(",") if item.strip()]
    return cast_type(value) if value else cast_type(default)


@dataclass
class BitgetConfig:
    """Bitget API configuration."""
    api_key: str = field(default_factory=lambda: get_env("BITGET_API_KEY"))
    api_secret: str = field(default_factory=lambda: get_env("BITGET_API_SECRET"))
    passphrase: str = field(default_factory=lambda: get_env("BITGET_PASSPHRASE"))
    testnet: bool = field(default_factory=lambda: get_env("BITGET_TESTNET", "false", bool))

    def validate(self) -> bool:
        """Validate that all required credentials are present."""
        return all([self.api_key, self.api_secret, self.passphrase])


@dataclass
class DiscordConfig:
    """Discord notification configuration."""
    bot_token: str = field(default_factory=lambda: get_env("DISCORD_BOT_TOKEN"))
    channel_id: int = field(default_factory=lambda: get_env("DISCORD_CHANNEL_ID", "0", int))
    webhook_url: str = field(default_factory=lambda: get_env("DISCORD_WEBHOOK_URL"))

    def validate(self) -> bool:
        """Validate Discord configuration."""
        return bool(self.webhook_url or (self.bot_token and self.channel_id))


@dataclass
class TradingConfig:
    """Trading parameters configuration."""
    max_trades_per_day: int = field(default_factory=lambda: get_env("MAX_TRADES_PER_DAY", "3", int))
    daily_loss_limit_percent: float = field(default_factory=lambda: get_env("DAILY_LOSS_LIMIT_PERCENT", "5.0", float))
    position_size_percent: float = field(default_factory=lambda: get_env("POSITION_SIZE_PERCENT", "10.0", float))
    leverage: int = field(default_factory=lambda: get_env("LEVERAGE", "5", int))
    take_profit_percent: float = field(default_factory=lambda: get_env("TAKE_PROFIT_PERCENT", "3.5", float))
    stop_loss_percent: float = field(default_factory=lambda: get_env("STOP_LOSS_PERCENT", "2.0", float))
    trading_pairs: List[str] = field(default_factory=lambda: get_env("TRADING_PAIRS", "BTCUSDT,ETHUSDT", list))


@dataclass
class StrategyConfig:
    """Strategy thresholds configuration."""
    # Fear & Greed Index thresholds
    fear_greed_extreme_fear: int = field(default_factory=lambda: get_env("FEAR_GREED_EXTREME_FEAR", "25", int))
    fear_greed_extreme_greed: int = field(default_factory=lambda: get_env("FEAR_GREED_EXTREME_GREED", "75", int))

    # Long/Short Ratio thresholds
    long_short_crowded_longs: float = field(default_factory=lambda: get_env("LONG_SHORT_CROWDED_LONGS", "2.0", float))
    long_short_crowded_shorts: float = field(default_factory=lambda: get_env("LONG_SHORT_CROWDED_SHORTS", "0.5", float))

    # Funding Rate thresholds (in decimal, e.g., 0.0005 = 0.05%)
    funding_rate_high: float = field(default_factory=lambda: get_env("FUNDING_RATE_HIGH", "0.0005", float))
    funding_rate_low: float = field(default_factory=lambda: get_env("FUNDING_RATE_LOW", "-0.0002", float))

    # Confidence thresholds
    high_confidence_min: int = field(default_factory=lambda: get_env("HIGH_CONFIDENCE_MIN", "85", int))
    low_confidence_min: int = field(default_factory=lambda: get_env("LOW_CONFIDENCE_MIN", "55", int))


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = field(default_factory=lambda: get_env("LOG_LEVEL", "INFO"))
    file: str = field(default_factory=lambda: get_env("LOG_FILE", "logs/trading_bot.log"))


@dataclass
class Settings:
    """Main settings container."""
    bitget: BitgetConfig = field(default_factory=BitgetConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    def validate(self) -> dict:
        """Validate all configurations and return status."""
        return {
            "bitget": self.bitget.validate(),
            "discord": self.discord.validate(),
            "trading": True,  # Has sensible defaults
            "strategy": True,  # Has sensible defaults
        }


# Global settings instance
settings = Settings()
