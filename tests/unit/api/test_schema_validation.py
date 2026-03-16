"""
Pydantic schema boundary validation tests.

Verifies field constraints (min/max, regex patterns, required fields, defaults)
for all API input schemas.
"""

import pytest
from pydantic import ValidationError

from src.api.schemas.bots import BotConfigCreate, BotConfigUpdate
from src.api.schemas.user import UserCreate, UserUpdate
from src.api.schemas.config import (
    TradingConfigUpdate,
    StrategyConfigUpdate,
    ApiKeysUpdate,
    ExchangeConfigUpdate,
    LLMConnectionUpdate,
)
from src.api.schemas.auth import LoginRequest, RefreshRequest
from src.api.schemas.affiliate import AffiliateLinkUpdate


# ---------------------------------------------------------------------------
# BotConfigCreate
# ---------------------------------------------------------------------------


class TestBotConfigCreate:

    def test_valid_minimal(self):
        bot = BotConfigCreate(name="Test", strategy_type="degen", exchange_type="bitget")
        assert bot.name == "Test"
        assert bot.mode == "demo"
        assert bot.trading_pairs == ["BTCUSDT"]
        assert bot.leverage is None

    def test_name_too_short(self):
        with pytest.raises(ValidationError, match="name"):
            BotConfigCreate(name="", strategy_type="degen", exchange_type="bitget")

    def test_name_too_long(self):
        with pytest.raises(ValidationError, match="name"):
            BotConfigCreate(name="A" * 101, strategy_type="degen", exchange_type="bitget")

    def test_strategy_type_required(self):
        with pytest.raises(ValidationError, match="strategy_type"):
            BotConfigCreate(name="Bot", exchange_type="bitget")

    def test_strategy_type_empty(self):
        with pytest.raises(ValidationError, match="strategy_type"):
            BotConfigCreate(name="Bot", strategy_type="", exchange_type="bitget")

    def test_exchange_type_invalid(self):
        with pytest.raises(ValidationError, match="exchange_type"):
            BotConfigCreate(name="Bot", strategy_type="degen", exchange_type="binance")

    def test_exchange_type_valid_values(self):
        for exch in ("bitget", "weex", "hyperliquid"):
            bot = BotConfigCreate(name="Bot", strategy_type="degen", exchange_type=exch)
            assert bot.exchange_type == exch

    def test_mode_invalid(self):
        with pytest.raises(ValidationError, match="mode"):
            BotConfigCreate(name="Bot", strategy_type="degen", exchange_type="bitget", mode="paper")

    def test_mode_valid_values(self):
        for m in ("demo", "live", "both"):
            bot = BotConfigCreate(name="Bot", strategy_type="degen", exchange_type="bitget", mode=m)
            assert bot.mode == m

    def test_leverage_too_low(self):
        with pytest.raises(ValidationError, match="leverage"):
            BotConfigCreate(name="Bot", strategy_type="d", exchange_type="bitget", leverage=0)

    def test_leverage_too_high(self):
        with pytest.raises(ValidationError, match="leverage"):
            BotConfigCreate(name="Bot", strategy_type="d", exchange_type="bitget", leverage=21)

    def test_leverage_boundary_valid(self):
        for lev in (1, 20):
            bot = BotConfigCreate(name="Bot", strategy_type="d", exchange_type="bitget", leverage=lev)
            assert bot.leverage == lev

    def test_position_size_too_low(self):
        with pytest.raises(ValidationError, match="position_size"):
            BotConfigCreate(name="B", strategy_type="d", exchange_type="bitget", position_size_percent=0.5)

    def test_position_size_too_high(self):
        with pytest.raises(ValidationError, match="position_size"):
            BotConfigCreate(name="B", strategy_type="d", exchange_type="bitget", position_size_percent=101)

    def test_max_trades_too_low(self):
        with pytest.raises(ValidationError, match="max_trades"):
            BotConfigCreate(name="B", strategy_type="d", exchange_type="bitget", max_trades_per_day=0)

    def test_max_trades_too_high(self):
        with pytest.raises(ValidationError, match="max_trades"):
            BotConfigCreate(name="B", strategy_type="d", exchange_type="bitget", max_trades_per_day=51)

    def test_take_profit_boundaries(self):
        with pytest.raises(ValidationError):
            BotConfigCreate(name="B", strategy_type="d", exchange_type="bitget", take_profit_percent=0.4)
        with pytest.raises(ValidationError):
            BotConfigCreate(name="B", strategy_type="d", exchange_type="bitget", take_profit_percent=20.1)

    def test_stop_loss_boundaries(self):
        with pytest.raises(ValidationError):
            BotConfigCreate(name="B", strategy_type="d", exchange_type="bitget", stop_loss_percent=0.4)
        with pytest.raises(ValidationError):
            BotConfigCreate(name="B", strategy_type="d", exchange_type="bitget", stop_loss_percent=10.1)

    def test_daily_loss_limit_boundaries(self):
        with pytest.raises(ValidationError):
            BotConfigCreate(name="B", strategy_type="d", exchange_type="bitget", daily_loss_limit_percent=0.5)
        with pytest.raises(ValidationError):
            BotConfigCreate(name="B", strategy_type="d", exchange_type="bitget", daily_loss_limit_percent=51)

    def test_schedule_type_invalid(self):
        with pytest.raises(ValidationError, match="schedule_type"):
            BotConfigCreate(name="B", strategy_type="d", exchange_type="bitget", schedule_type="every_5_min")

    def test_schedule_type_valid_values(self):
        for st in ("market_sessions", "interval", "custom_cron", "rotation_only"):
            bot = BotConfigCreate(name="B", strategy_type="d", exchange_type="bitget", schedule_type=st)
            assert bot.schedule_type == st

    def test_rotation_interval_boundaries(self):
        with pytest.raises(ValidationError):
            BotConfigCreate(name="B", strategy_type="d", exchange_type="bitget", rotation_interval_minutes=4)
        with pytest.raises(ValidationError):
            BotConfigCreate(name="B", strategy_type="d", exchange_type="bitget", rotation_interval_minutes=10081)
        bot = BotConfigCreate(name="B", strategy_type="d", exchange_type="bitget", rotation_interval_minutes=5)
        assert bot.rotation_interval_minutes == 5
        bot = BotConfigCreate(name="B", strategy_type="d", exchange_type="bitget", rotation_interval_minutes=10080)
        assert bot.rotation_interval_minutes == 10080

    def test_rotation_start_time_pattern(self):
        bot = BotConfigCreate(name="B", strategy_type="d", exchange_type="bitget", rotation_start_time="08:00")
        assert bot.rotation_start_time == "08:00"
        # Pattern only validates HH:MM format (2 digits colon 2 digits)
        with pytest.raises(ValidationError):
            BotConfigCreate(name="B", strategy_type="d", exchange_type="bitget", rotation_start_time="8:00")
        with pytest.raises(ValidationError):
            BotConfigCreate(name="B", strategy_type="d", exchange_type="bitget", rotation_start_time="noon")


# ---------------------------------------------------------------------------
# BotConfigUpdate
# ---------------------------------------------------------------------------


class TestBotConfigUpdate:

    def test_all_none_is_valid(self):
        u = BotConfigUpdate()
        assert u.name is None
        assert u.leverage is None

    def test_name_too_short(self):
        with pytest.raises(ValidationError, match="name"):
            BotConfigUpdate(name="")

    def test_name_too_long(self):
        with pytest.raises(ValidationError, match="name"):
            BotConfigUpdate(name="X" * 101)

    def test_leverage_boundaries(self):
        with pytest.raises(ValidationError):
            BotConfigUpdate(leverage=0)
        with pytest.raises(ValidationError):
            BotConfigUpdate(leverage=21)
        u = BotConfigUpdate(leverage=1)
        assert u.leverage == 1

    def test_position_size_boundaries(self):
        with pytest.raises(ValidationError):
            BotConfigUpdate(position_size_percent=0.9)
        with pytest.raises(ValidationError):
            BotConfigUpdate(position_size_percent=25.1)

    def test_exchange_type_pattern(self):
        with pytest.raises(ValidationError):
            BotConfigUpdate(exchange_type="binance")
        u = BotConfigUpdate(exchange_type="weex")
        assert u.exchange_type == "weex"

    def test_mode_pattern(self):
        with pytest.raises(ValidationError):
            BotConfigUpdate(mode="test")
        u = BotConfigUpdate(mode="live")
        assert u.mode == "live"


# ---------------------------------------------------------------------------
# UserCreate / UserUpdate
# ---------------------------------------------------------------------------


class TestUserSchemas:

    def test_username_too_short(self):
        with pytest.raises(ValidationError, match="username"):
            UserCreate(username="ab", password="Test@1234")

    def test_username_too_long(self):
        with pytest.raises(ValidationError, match="username"):
            UserCreate(username="A" * 51, password="Test@1234")

    def test_password_too_short(self):
        with pytest.raises(ValidationError, match="password"):
            UserCreate(username="user1", password="1234567")

    def test_password_too_long(self):
        with pytest.raises(ValidationError, match="password"):
            UserCreate(username="user1", password="A" * 129)

    def test_role_invalid(self):
        with pytest.raises(ValidationError, match="role"):
            UserCreate(username="user1", password="Test@1234", role="superadmin")

    def test_role_valid(self):
        for r in ("admin", "user"):
            u = UserCreate(username="user1", password="Test@1234", role=r)
            assert u.role == r

    def test_language_invalid(self):
        with pytest.raises(ValidationError, match="language"):
            UserCreate(username="user1", password="Test@1234", language="fr")

    def test_language_valid(self):
        for lang in ("de", "en"):
            u = UserCreate(username="user1", password="Test@1234", language=lang)
            assert u.language == lang

    def test_defaults(self):
        u = UserCreate(username="user1", password="Test@1234")
        assert u.role == "user"
        assert u.language == "de"
        assert u.email is None

    def test_password_no_uppercase_rejected(self):
        with pytest.raises(ValidationError, match="uppercase"):
            UserCreate(username="user1", password="test@1234")

    def test_password_no_lowercase_rejected(self):
        with pytest.raises(ValidationError, match="lowercase"):
            UserCreate(username="user1", password="TEST@1234")

    def test_password_no_digit_rejected(self):
        with pytest.raises(ValidationError, match="digit"):
            UserCreate(username="user1", password="Test@abcd")

    def test_password_no_special_char_rejected(self):
        with pytest.raises(ValidationError, match="special"):
            UserCreate(username="user1", password="Test12345")

    def test_update_password_complexity_enforced(self):
        with pytest.raises(ValidationError, match="uppercase"):
            UserUpdate(password="weakpass1!")

    def test_update_password_too_short(self):
        with pytest.raises(ValidationError, match="password"):
            UserUpdate(password="short")

    def test_update_role_invalid(self):
        with pytest.raises(ValidationError, match="role"):
            UserUpdate(role="root")


# ---------------------------------------------------------------------------
# TradingConfigUpdate / StrategyConfigUpdate
# ---------------------------------------------------------------------------


class TestConfigSchemas:

    def test_trading_leverage_boundaries(self):
        with pytest.raises(ValidationError):
            TradingConfigUpdate(leverage=0)
        with pytest.raises(ValidationError):
            TradingConfigUpdate(leverage=21)

    def test_trading_max_trades_boundaries(self):
        with pytest.raises(ValidationError):
            TradingConfigUpdate(max_trades_per_day=0)
        with pytest.raises(ValidationError):
            TradingConfigUpdate(max_trades_per_day=11)

    def test_trading_defaults(self):
        t = TradingConfigUpdate()
        assert t.max_trades_per_day == 3
        assert t.leverage == 4
        assert t.demo_mode is True

    def test_strategy_fear_greed_boundaries(self):
        with pytest.raises(ValidationError):
            StrategyConfigUpdate(fear_greed_extreme_fear=-1)
        with pytest.raises(ValidationError):
            StrategyConfigUpdate(fear_greed_extreme_fear=51)
        with pytest.raises(ValidationError):
            StrategyConfigUpdate(fear_greed_extreme_greed=49)
        with pytest.raises(ValidationError):
            StrategyConfigUpdate(fear_greed_extreme_greed=101)

    def test_strategy_confidence_boundaries(self):
        with pytest.raises(ValidationError):
            StrategyConfigUpdate(high_confidence_min=49)
        with pytest.raises(ValidationError):
            StrategyConfigUpdate(high_confidence_min=101)

    def test_api_keys_exchange_pattern(self):
        with pytest.raises(ValidationError, match="exchange_type"):
            ApiKeysUpdate(exchange_type="kraken")
        a = ApiKeysUpdate(exchange_type="bitget")
        assert a.exchange_type == "bitget"

    def test_exchange_config_pattern(self):
        with pytest.raises(ValidationError, match="exchange_type"):
            ExchangeConfigUpdate(exchange_type="coinbase")

    def test_llm_connection_key_required(self):
        with pytest.raises(ValidationError, match="api_key"):
            LLMConnectionUpdate(api_key="")


# ---------------------------------------------------------------------------
# Auth schemas
# ---------------------------------------------------------------------------


class TestAuthSchemas:

    def test_login_username_empty(self):
        with pytest.raises(ValidationError, match="username"):
            LoginRequest(username="", password="x")

    def test_login_password_empty(self):
        with pytest.raises(ValidationError, match="password"):
            LoginRequest(password="", username="x")

    def test_login_username_too_long(self):
        with pytest.raises(ValidationError, match="username"):
            LoginRequest(username="A" * 51, password="test")

    def test_refresh_token_required(self):
        with pytest.raises(ValidationError, match="refresh_token"):
            RefreshRequest()

    def test_valid_login(self):
        r = LoginRequest(username="user", password="pass")
        assert r.username == "user"


# ---------------------------------------------------------------------------
# Affiliate schemas
# ---------------------------------------------------------------------------


class TestAffiliateSchemas:

    def test_valid_url(self):
        a = AffiliateLinkUpdate(affiliate_url="https://bitget.com/ref/test")
        assert str(a.affiliate_url) == "https://bitget.com/ref/test"

    def test_invalid_url(self):
        with pytest.raises(ValidationError, match="affiliate_url"):
            AffiliateLinkUpdate(affiliate_url="not-a-url")

    def test_defaults(self):
        a = AffiliateLinkUpdate(affiliate_url="https://bitget.com/ref/test")
        assert a.is_active is True
        assert a.uid_required is False
