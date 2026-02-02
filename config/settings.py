"""
Configuration settings for the Bitget Trading Bot.
Loads settings from environment variables with sensible defaults.
"""

import os
from dataclasses import dataclass, field
from typing import List, Tuple
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(f"Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors))


def get_env(key: str, default: str = "", cast_type: type = str):
    """Get environment variable with type casting."""
    value = os.getenv(key, default)
    if cast_type == bool:
        return value.lower() in ("true", "1", "yes")
    if cast_type == list:
        return [item.strip() for item in value.split(",") if item.strip()]
    try:
        return cast_type(value) if value else cast_type(default)
    except (ValueError, TypeError):
        return cast_type(default) if default else None


@dataclass
class BitgetConfig:
    """Bitget API configuration."""
    # Live Trading API Keys (for real money trading)
    api_key: str = field(default_factory=lambda: get_env("BITGET_API_KEY"))
    api_secret: str = field(default_factory=lambda: get_env("BITGET_API_SECRET"))
    passphrase: str = field(default_factory=lambda: get_env("BITGET_PASSPHRASE"))

    # Demo Trading API Keys (for paper money trading on Bitget Demo Account)
    demo_api_key: str = field(default_factory=lambda: get_env("BITGET_DEMO_API_KEY"))
    demo_api_secret: str = field(default_factory=lambda: get_env("BITGET_DEMO_API_SECRET"))
    demo_passphrase: str = field(default_factory=lambda: get_env("BITGET_DEMO_PASSPHRASE"))

    testnet: bool = field(default_factory=lambda: get_env("BITGET_TESTNET", "false", bool))

    def validate(self, demo_mode: bool = False) -> bool:
        """
        Validate that all required credentials are present.

        Args:
            demo_mode: If True, validate demo API keys; otherwise validate live API keys
        """
        if demo_mode:
            return all([self.demo_api_key, self.demo_api_secret, self.demo_passphrase])
        else:
            return all([self.api_key, self.api_secret, self.passphrase])

    def get_active_credentials(self, demo_mode: bool = False) -> dict:
        """
        Get the active API credentials based on trading mode.

        Args:
            demo_mode: If True, return demo credentials; otherwise return live credentials

        Returns:
            Dictionary with api_key, api_secret, and passphrase
        """
        if demo_mode:
            return {
                "api_key": self.demo_api_key,
                "api_secret": self.demo_api_secret,
                "passphrase": self.demo_passphrase,
            }
        else:
            return {
                "api_key": self.api_key,
                "api_secret": self.api_secret,
                "passphrase": self.passphrase,
            }


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
    max_trades_per_day: int = field(default_factory=lambda: get_env("MAX_TRADES_PER_DAY", "2", int))
    daily_loss_limit_percent: float = field(default_factory=lambda: get_env("DAILY_LOSS_LIMIT_PERCENT", "5.0", float))
    position_size_percent: float = field(default_factory=lambda: get_env("POSITION_SIZE_PERCENT", "7.5", float))
    leverage: int = field(default_factory=lambda: get_env("LEVERAGE", "4", int))
    take_profit_percent: float = field(default_factory=lambda: get_env("TAKE_PROFIT_PERCENT", "4.0", float))
    stop_loss_percent: float = field(default_factory=lambda: get_env("STOP_LOSS_PERCENT", "1.5", float))
    trading_pairs: List[str] = field(default_factory=lambda: get_env("TRADING_PAIRS", "BTCUSDT,ETHUSDT", list))

    # Portfolio weights (comma-separated, must match trading_pairs count)
    # e.g., "40,30,15,15" for 40% BTC, 30% ETH, 15% SOL, 15% DOGE
    portfolio_weights: str = field(default_factory=lambda: get_env("PORTFOLIO_WEIGHTS", ""))

    # Portfolio rebalance threshold (0.10 = rebalance when weight drifts >10%)
    rebalance_threshold: float = field(default_factory=lambda: get_env("REBALANCE_THRESHOLD", "0.10", float))

    # Funding rate arbitrage settings
    # Minimum funding rate to trigger entry (0.0005 = 0.05%)
    funding_arb_min_rate: float = field(default_factory=lambda: get_env("FUNDING_ARB_MIN_RATE", "0.0005", float))
    # Rate below which to close positions (0.0001 = 0.01%)
    funding_arb_exit_rate: float = field(default_factory=lambda: get_env("FUNDING_ARB_EXIT_RATE", "0.0001", float))
    # Maximum value per side per arbitrage position
    funding_arb_max_position: float = field(default_factory=lambda: get_env("FUNDING_ARB_MAX_POSITION", "10000", float))
    # Maximum delta drift before rebalancing (0.05 = 5%)
    funding_arb_delta_threshold: float = field(default_factory=lambda: get_env("FUNDING_ARB_DELTA_THRESHOLD", "0.05", float))
    # Maximum concurrent arbitrage positions
    funding_arb_max_positions: int = field(default_factory=lambda: get_env("FUNDING_ARB_MAX_POSITIONS", "3", int))

    # Trading mode (demo = no real trades, live = real trades)
    demo_mode: bool = field(default_factory=lambda: get_env("DEMO_MODE", "true", bool))

    def validate(self) -> Tuple[bool, List[str]]:
        """
        Validate trading configuration with range checks.

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []

        # Max trades per day: 1-10
        if not (1 <= self.max_trades_per_day <= 10):
            errors.append(f"MAX_TRADES_PER_DAY must be 1-10 (got {self.max_trades_per_day})")

        # Daily loss limit: 1-20%
        if not (1.0 <= self.daily_loss_limit_percent <= 20.0):
            errors.append(f"DAILY_LOSS_LIMIT_PERCENT must be 1-20% (got {self.daily_loss_limit_percent}%)")

        # Position size: 1-25%
        if not (1.0 <= self.position_size_percent <= 25.0):
            errors.append(f"POSITION_SIZE_PERCENT must be 1-25% (got {self.position_size_percent}%)")

        # Leverage: 1-20x (above 20x is extremely risky)
        if not (1 <= self.leverage <= 20):
            errors.append(f"LEVERAGE must be 1-20x (got {self.leverage}x)")

        # Take profit: 0.5-20%
        if not (0.5 <= self.take_profit_percent <= 20.0):
            errors.append(f"TAKE_PROFIT_PERCENT must be 0.5-20% (got {self.take_profit_percent}%)")

        # Stop loss: 0.5-10%
        if not (0.5 <= self.stop_loss_percent <= 10.0):
            errors.append(f"STOP_LOSS_PERCENT must be 0.5-10% (got {self.stop_loss_percent}%)")

        # Must have at least one trading pair
        if not self.trading_pairs:
            errors.append("TRADING_PAIRS must have at least one pair")

        # Validate trading pairs format
        for pair in self.trading_pairs:
            if not pair.endswith("USDT"):
                errors.append(f"Invalid trading pair '{pair}' - must end with USDT")

        return (len(errors) == 0, errors)


@dataclass
class StrategyConfig:
    """Strategy thresholds configuration."""
    # Fear & Greed Index thresholds (stricter for better signals)
    fear_greed_extreme_fear: int = field(default_factory=lambda: get_env("FEAR_GREED_EXTREME_FEAR", "20", int))
    fear_greed_extreme_greed: int = field(default_factory=lambda: get_env("FEAR_GREED_EXTREME_GREED", "80", int))

    # Long/Short Ratio thresholds (stricter for stronger signals)
    long_short_crowded_longs: float = field(default_factory=lambda: get_env("LONG_SHORT_CROWDED_LONGS", "2.5", float))
    long_short_crowded_shorts: float = field(default_factory=lambda: get_env("LONG_SHORT_CROWDED_SHORTS", "0.4", float))

    # Funding Rate thresholds (in decimal, e.g., 0.0005 = 0.05%)
    funding_rate_high: float = field(default_factory=lambda: get_env("FUNDING_RATE_HIGH", "0.0005", float))
    funding_rate_low: float = field(default_factory=lambda: get_env("FUNDING_RATE_LOW", "-0.0002", float))

    # Confidence thresholds (raised low min for better trade quality)
    high_confidence_min: int = field(default_factory=lambda: get_env("HIGH_CONFIDENCE_MIN", "85", int))
    low_confidence_min: int = field(default_factory=lambda: get_env("LOW_CONFIDENCE_MIN", "60", int))

    # Signal stack weights (comma-separated: fear_greed,funding,ls_ratio,oi,momentum,rsi,volume,liquidation)
    # Default: "20,15,20,10,10,10,8,7"
    signal_weights: str = field(default_factory=lambda: get_env("SIGNAL_WEIGHTS", "20,15,20,10,10,10,8,7"))

    def validate(self) -> Tuple[bool, List[str]]:
        """
        Validate strategy configuration.

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []

        # Fear & Greed thresholds: 0-100
        if not (0 <= self.fear_greed_extreme_fear <= 50):
            errors.append(f"FEAR_GREED_EXTREME_FEAR must be 0-50 (got {self.fear_greed_extreme_fear})")
        if not (50 <= self.fear_greed_extreme_greed <= 100):
            errors.append(f"FEAR_GREED_EXTREME_GREED must be 50-100 (got {self.fear_greed_extreme_greed})")
        if self.fear_greed_extreme_fear >= self.fear_greed_extreme_greed:
            errors.append("FEAR_GREED_EXTREME_FEAR must be less than FEAR_GREED_EXTREME_GREED")

        # Long/Short Ratio thresholds
        if not (1.5 <= self.long_short_crowded_longs <= 5.0):
            errors.append(f"LONG_SHORT_CROWDED_LONGS must be 1.5-5.0 (got {self.long_short_crowded_longs})")
        if not (0.2 <= self.long_short_crowded_shorts <= 0.7):
            errors.append(f"LONG_SHORT_CROWDED_SHORTS must be 0.2-0.7 (got {self.long_short_crowded_shorts})")

        # Confidence thresholds: 0-100
        if not (50 <= self.low_confidence_min <= 100):
            errors.append(f"LOW_CONFIDENCE_MIN must be 50-100 (got {self.low_confidence_min})")
        if not (50 <= self.high_confidence_min <= 100):
            errors.append(f"HIGH_CONFIDENCE_MIN must be 50-100 (got {self.high_confidence_min})")
        if self.low_confidence_min >= self.high_confidence_min:
            errors.append("LOW_CONFIDENCE_MIN must be less than HIGH_CONFIDENCE_MIN")

        return (len(errors) == 0, errors)


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
        trading_valid, _ = self.trading.validate()
        strategy_valid, _ = self.strategy.validate()

        return {
            "bitget": self.bitget.validate(),
            "discord": self.discord.validate(),
            "trading": trading_valid,
            "strategy": strategy_valid,
        }

    def validate_strict(self, raise_on_error: bool = True) -> Tuple[bool, List[str]]:
        """
        Validate all configurations with detailed error messages.

        Args:
            raise_on_error: If True, raises ConfigValidationError on failure

        Returns:
            Tuple of (is_valid, list of all error messages)

        Raises:
            ConfigValidationError: If raise_on_error=True and validation fails
        """
        all_errors = []

        # Validate Bitget credentials
        if not self.bitget.validate():
            all_errors.append("Bitget API credentials are incomplete")

        # Validate Discord (optional, just warn)
        if not self.discord.validate():
            all_errors.append("Discord notifications not configured (optional)")

        # Validate trading config
        trading_valid, trading_errors = self.trading.validate()
        all_errors.extend(trading_errors)

        # Validate strategy config
        strategy_valid, strategy_errors = self.strategy.validate()
        all_errors.extend(strategy_errors)

        is_valid = len([e for e in all_errors if "optional" not in e.lower()]) == 0

        if not is_valid and raise_on_error:
            raise ConfigValidationError(all_errors)

        return (is_valid, all_errors)

    @property
    def is_demo_mode(self) -> bool:
        """Check if bot is running in demo mode."""
        return self.trading.demo_mode


# Global settings instance
settings = Settings()
