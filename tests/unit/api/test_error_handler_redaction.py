"""Tests for error-handler traceback redaction (#258, SEC-010)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

from src.api.middleware.error_handler import global_exception_handler


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_request() -> MagicMock:
    req = MagicMock()
    req.method = "GET"
    req.url.path = "/api/x"
    return req


def _decode(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


class TestDevModeRedaction:
    def test_redacts_dsn_in_traceback(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")

        def _boom() -> None:
            url = "postgres://admin:SuperSecretPW@host/db"
            raise RuntimeError(f"failed reaching {url}")

        try:
            _boom()
        except RuntimeError as exc:
            body = _decode(asyncio.run(global_exception_handler(_make_request(), exc)))

        # Neither the detail string nor any traceback line may contain the pw.
        assert "SuperSecretPW" not in body["detail"]
        for line in body["traceback"]:
            assert "SuperSecretPW" not in line

    def test_redacts_env_secret_value(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("JWT_SECRET", "must-be-kept-hidden-value")

        try:
            raise RuntimeError("JWT decode failed with secret must-be-kept-hidden-value")
        except RuntimeError as exc:
            body = _decode(asyncio.run(global_exception_handler(_make_request(), exc)))

        assert "must-be-kept-hidden-value" not in body["detail"]
        for line in body["traceback"]:
            assert "must-be-kept-hidden-value" not in line

    def test_redacts_bearer_token(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        token = "eyJhbGciOiJIUzI1NiJ9abcdefghijklmnopqrstuvwxyz.eyJzdWIiOiIxIn0.sig123456xyz"
        try:
            raise RuntimeError(f"auth failed: Authorization: Bearer {token}")
        except RuntimeError as exc:
            body = _decode(asyncio.run(global_exception_handler(_make_request(), exc)))

        assert token not in body["detail"]


class TestProductionMode:
    def test_production_returns_generic_without_traceback(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")

        try:
            raise RuntimeError("postgres://admin:pw12345678@host/db connection refused")
        except RuntimeError as exc:
            body = _decode(asyncio.run(global_exception_handler(_make_request(), exc)))

        assert "traceback" not in body
        assert "pw12345678" not in body.get("detail", "")
        assert body["detail"] == "Internal server error"
