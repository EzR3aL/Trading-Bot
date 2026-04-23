"""Secret-redaction helpers for log lines and error payloads (SEC-010).

Error middleware exposes tracebacks in dev-mode; rate-limit middleware logs
request headers; exception strings sometimes quote DB URLs verbatim. Anything
that flows into those paths must pass through :func:`redact_secrets` first
so an accidental log-read / stack-trace does not leak an API key or a
database password.

The redactor is intentionally greedy — it's cheaper to over-redact a benign
string than to leak one secret. It recognises:

* explicit env-var names for known-sensitive keys
* key/value patterns like ``password=…`` / ``api_key: …`` / ``authorization: Bearer …``
* URLs with embedded credentials (``postgres://user:pass@host``)
* long base64-ish tokens (>=40 contiguous base64 chars)
"""

from __future__ import annotations

import os
import re
from typing import Any, Iterable

_PLACEHOLDER = "***REDACTED***"

# Env var names whose *value* must never appear in output.
_SENSITIVE_ENV_VARS: tuple[str, ...] = (
    "DATABASE_URL",
    "DB_PASSWORD",
    "POSTGRES_PASSWORD",
    "JWT_SECRET",
    "JWT_PRIVATE_KEY",
    "JWT_PUBLIC_KEY",
    "ENCRYPTION_KEY",
    "SECRET_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "BITGET_API_KEY",
    "BITGET_API_SECRET",
    "BITGET_PASSPHRASE",
    "HYPERLIQUID_PRIVATE_KEY",
    "BINGX_API_KEY",
    "BINGX_API_SECRET",
    "WEEX_API_KEY",
    "WEEX_API_SECRET",
    "BITUNIX_API_KEY",
    "BITUNIX_API_SECRET",
    "ADMIN_DISCORD_WEBHOOK_URL",
    "ADMIN_TELEGRAM_BOT_TOKEN",
    "HL_BUILDER_ADDRESS",
    "SUPABASE_SERVICE_ROLE_KEY",
)

# Sensitive key names inside text payloads — redact the value that follows.
# Covers JSON-ish ("key": "value"), YAML-ish (key: value), ENV-ish (KEY=value),
# and header-ish (Authorization: Bearer …).
_SENSITIVE_KEY_TOKENS: tuple[str, ...] = (
    "password", "passwd", "secret", "api_key", "apikey", "api-secret",
    "access_token", "refresh_token", "bearer", "authorization",
    "private_key", "privatekey", "jwt", "token", "passphrase",
    "db_password", "postgres_password", "encryption_key",
    "x-api-key", "x-api-secret", "access-key", "signing-key",
)

# Matches: (sensitive_key) (separator) (value up to line-end / quote / comma)
# Separator: =, :, ':', '":', 'value="', whitespace
_KV_PATTERN = re.compile(
    r"(?P<key>\b(?:" + "|".join(_SENSITIVE_KEY_TOKENS) + r")\b)"
    r"(?P<sep>\s*[:=]\s*|\s+)"
    r"(?P<quote>['\"]?)"
    r"(?P<value>[^'\",\s]+)"
    r"(?P=quote)",
    re.IGNORECASE,
)

# Matches: scheme://user:password@host — credentials in DSN/URL form.
_URL_CREDS_PATTERN = re.compile(
    r"(?P<scheme>\w+://)(?P<user>[^:@\s/]+):(?P<pwd>[^@\s/]+)@",
)

# Matches long opaque token-like runs (JWT, API tokens, bcrypt hashes).
# Deliberately loose; we over-redact.
_LONG_TOKEN_PATTERN = re.compile(
    r"\b[A-Za-z0-9_\-]{40,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"   # JWT shape
    r"|\b(?:sk-|pk_|rk_|xoxb-|ghp_|ghs_|gho_|github_pat_)[A-Za-z0-9_\-]{20,}\b"
)

# Matches `Bearer <token>` / `Basic <token>` after an Authorization-style
# header has already had its "Authorization: " prefix redacted by the KV
# rule. Catches the residual token that follows the scheme word.
_BEARER_PATTERN = re.compile(
    r"(?P<scheme>\b(?:Bearer|Basic|Token)\b)\s+(?P<token>[A-Za-z0-9_\-\.=+/]{8,})",
    re.IGNORECASE,
)


def _collect_env_secret_values() -> list[str]:
    """Snapshot the actual runtime values of known-sensitive env vars."""
    values: list[str] = []
    for name in _SENSITIVE_ENV_VARS:
        v = os.environ.get(name, "").strip()
        # Don't redact trivially-short values — too many false positives.
        if v and len(v) >= 8:
            values.append(v)
    return values


def redact_secrets(text: str, *, extra_values: Iterable[str] | None = None) -> str:
    """Return ``text`` with any detected secret redacted.

    Safe to pass to JSON/log emitters. Applies four passes in order:
      1. Exact substitution for current env-var values (highest signal).
      2. Exact substitution for caller-provided ``extra_values``.
      3. Key/value regex (``password=…``, ``api_key: …``, header-style).
      4. URL-credential + long-token patterns.
    """
    if not isinstance(text, str):
        text = str(text)
    if not text:
        return text

    for value in _collect_env_secret_values():
        text = text.replace(value, _PLACEHOLDER)

    if extra_values:
        for value in extra_values:
            if value and isinstance(value, str) and len(value) >= 4:
                text = text.replace(value, _PLACEHOLDER)

    # Bearer/Basic/Token must run BEFORE KV, otherwise the KV pattern
    # captures "Bearer" as the value and leaves the real token untouched.
    def _bearer_sub(match: re.Match[str]) -> str:
        return f"{match.group('scheme')} {_PLACEHOLDER}"

    text = _BEARER_PATTERN.sub(_bearer_sub, text)

    def _kv_sub(match: re.Match[str]) -> str:
        return f"{match.group('key')}{match.group('sep')}{match.group('quote')}{_PLACEHOLDER}{match.group('quote')}"

    text = _KV_PATTERN.sub(_kv_sub, text)

    def _url_sub(match: re.Match[str]) -> str:
        return f"{match.group('scheme')}{match.group('user')}:{_PLACEHOLDER}@"

    text = _URL_CREDS_PATTERN.sub(_url_sub, text)
    text = _LONG_TOKEN_PATTERN.sub(_PLACEHOLDER, text)
    return text


def redact_lines(lines: Iterable[Any]) -> list[str]:
    """Apply :func:`redact_secrets` to each line of a traceback list."""
    return [redact_secrets(str(line)) for line in lines]
