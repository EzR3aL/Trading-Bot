"""Tests for the settings utility."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.utils.settings import get_setting, get_hl_config


class TestGetSetting:
    """Tests for get_setting."""

    @pytest.mark.asyncio
    async def test_returns_db_value(self):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "db_value"

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("src.utils.settings.get_session", return_value=mock_session):
            result = await get_setting("MY_KEY")
        assert result == "db_value"

    @pytest.mark.asyncio
    async def test_falls_back_to_env(self):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("src.utils.settings.get_session", return_value=mock_session):
            with patch.dict(os.environ, {"MY_KEY": "  env_value  "}):
                result = await get_setting("MY_KEY")
        assert result == "env_value"

    @pytest.mark.asyncio
    async def test_returns_default_when_missing(self):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        env = os.environ.copy()
        env.pop("MY_MISSING_KEY", None)

        with patch("src.utils.settings.get_session", return_value=mock_session):
            with patch.dict(os.environ, env, clear=True):
                result = await get_setting("MY_MISSING_KEY", "fallback")
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_empty_db_value_falls_back(self):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = ""

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("src.utils.settings.get_session", return_value=mock_session):
            with patch.dict(os.environ, {"MY_KEY": "env_val"}):
                result = await get_setting("MY_KEY")
        assert result == "env_val"


class TestGetHlConfig:
    """Tests for get_hl_config."""

    @pytest.mark.asyncio
    async def test_returns_hl_settings(self):
        values = {
            "HL_BUILDER_ADDRESS": "0xabc",
            "HL_BUILDER_FEE": "50",
            "HL_REFERRAL_CODE": "myref",
        }

        async def fake_get_setting(key, default=""):
            return values.get(key, default)

        with patch("src.utils.settings.get_setting", side_effect=fake_get_setting):
            result = await get_hl_config()
        assert result["builder_address"] == "0xabc"
        assert result["builder_fee"] == 50
        assert result["referral_code"] == "myref"
