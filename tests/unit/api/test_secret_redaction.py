"""Tests for secret-redaction utility (#258, SEC-010)."""

from __future__ import annotations

import pytest

from src.api.secret_redaction import (
    _PLACEHOLDER,
    redact_lines,
    redact_secrets,
)


class TestKeyValueRedaction:
    @pytest.mark.parametrize("raw", [
        "password=hunter2",
        "password: hunter2",
        'password="hunter2"',
        "api_key=abcdef123456",
        "api_key: abcdef123456",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9",
        "authorization = Bearer eyJhbGciOiJIUzI1NiJ9",
        "X-API-Key: abcdef123456",
    ])
    def test_kv_pairs_redacted(self, raw):
        out = redact_secrets(raw)
        assert "hunter2" not in out
        assert "abcdef123456" not in out
        assert "eyJhbGciOiJIUzI1NiJ9" not in out
        assert _PLACEHOLDER in out

    def test_preserves_key_name(self):
        out = redact_secrets("password=hunter2")
        assert out.lower().startswith("password")

    def test_multiple_on_same_line(self):
        out = redact_secrets("api_key=abcdef password=hunter2")
        assert "abcdef" not in out
        assert "hunter2" not in out


class TestUrlCredentials:
    def test_postgres_dsn_redacted(self):
        out = redact_secrets(
            "database_url=postgres://myuser:mypassword@db.example.com/mydb"
        )
        assert "mypassword" not in out
        assert _PLACEHOLDER in out

    def test_preserves_scheme_and_user(self):
        out = redact_secrets("postgres://myuser:mypassword@db.example.com/mydb")
        assert out.startswith("postgres://myuser:")
        assert "mypassword" not in out

    def test_redis_dsn(self):
        out = redact_secrets("redis://default:sekret123@redis:6379")
        assert "sekret123" not in out


class TestLongTokens:
    def test_jwt_redacted(self):
        # synthetic JWT shape
        jwt = (
            "eyJhbGciOiJIUzI1NiJ9ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef."
            "eyJzdWIiOiIxIn0."
            "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        )
        out = redact_secrets(jwt)
        assert jwt not in out
        assert _PLACEHOLDER in out

    def test_openai_key_redacted(self):
        key = "sk-abcdef1234567890abcdef1234567890"
        out = redact_secrets(f"calling OpenAI with key {key}")
        assert key not in out

    def test_github_pat_redacted(self):
        pat = "ghp_abcdefghijklmnop1234567890"
        out = redact_secrets(f"token {pat}")
        assert pat not in out


class TestEnvVarValues:
    def test_env_secret_value_redacted(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgres://admin:SuperSecret99@host/db")
        # bare value occurrence (not behind a key=…) still gets redacted
        # because the redactor snapshots current env values.
        out = redact_secrets("Error reaching postgres://admin:SuperSecret99@host/db during query")
        assert "SuperSecret99" not in out

    def test_short_env_values_ignored(self, monkeypatch):
        # 1-2 character env values would cause rampant false positives.
        monkeypatch.setenv("JWT_SECRET", "ab")
        out = redact_secrets("error ab happened")
        assert "ab" in out  # too short to treat as secret

    def test_extra_values_param(self):
        out = redact_secrets(
            "My hidden thing is super-secret-token-xyz",
            extra_values=["super-secret-token-xyz"],
        )
        assert "super-secret-token-xyz" not in out


class TestLinesHelper:
    def test_redacts_each_line(self):
        out = redact_lines([
            "line 1 password=abc12345",
            "line 2 api_key=def67890",
            "line 3 normal text",
        ])
        assert len(out) == 3
        assert "abc12345" not in out[0]
        assert "def67890" not in out[1]
        assert out[2] == "line 3 normal text"


class TestNonStringInputs:
    def test_handles_non_string(self):
        out = redact_secrets(12345)  # type: ignore[arg-type]
        assert out == "12345"

    def test_handles_empty(self):
        assert redact_secrets("") == ""
        assert redact_secrets(None) == "None"  # type: ignore[arg-type]


class TestIdempotence:
    def test_running_twice_is_stable(self):
        raw = "db=postgres://admin:pw12345678@host password=abc12345"
        once = redact_secrets(raw)
        twice = redact_secrets(once)
        assert once == twice
