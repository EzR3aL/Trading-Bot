"""Tests for client-IP resolution under spoofing scenarios (#258, SEC-006).

The rate-limit key function ``_get_real_client_ip`` MUST only trust the
``X-Forwarded-For`` header when ``BEHIND_PROXY`` is explicitly enabled.
Otherwise an unauthenticated attacker can set the header and rotate IPs
to bypass the rate limiter.
"""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock


def _reload_rate_limit_with_env(monkeypatch, value: str):
    """Re-import src.api.rate_limit with a specific BEHIND_PROXY value.

    The module evaluates the flag at import-time (by design — avoids re-
    reading env per request), so tests must reload to exercise both paths.
    """
    monkeypatch.setenv("BEHIND_PROXY", value)
    import src.api.rate_limit as rl
    return importlib.reload(rl)


def _make_request(*, peer: str, forwarded: str | None = None) -> MagicMock:
    req = MagicMock()
    req.client.host = peer
    headers = {}
    if forwarded is not None:
        headers["X-Forwarded-For"] = forwarded
    req.headers.get = headers.get
    return req


class TestBehindProxyFalse:
    def test_ignores_forwarded_header(self, monkeypatch):
        rl = _reload_rate_limit_with_env(monkeypatch, "false")
        req = _make_request(peer="10.0.0.1", forwarded="1.2.3.4")
        assert rl._get_real_client_ip(req) == "10.0.0.1"

    def test_ignores_forwarded_even_for_valid_ipv6(self, monkeypatch):
        rl = _reload_rate_limit_with_env(monkeypatch, "0")
        req = _make_request(peer="10.0.0.1", forwarded="2001:db8::1")
        assert rl._get_real_client_ip(req) == "10.0.0.1"

    def test_uses_peer_when_no_client(self, monkeypatch):
        rl = _reload_rate_limit_with_env(monkeypatch, "")
        req = MagicMock()
        req.client = None
        req.headers.get = {}.get
        assert rl._get_real_client_ip(req) == "unknown"

    def test_attacker_cannot_spoof_ip(self, monkeypatch):
        # Regression guard for SEC-006: without the flag, a malicious
        # X-Forwarded-For must not rotate the rate-limit bucket.
        rl = _reload_rate_limit_with_env(monkeypatch, "false")
        attacker_peer = "198.51.100.7"
        buckets = set()
        for spoof in ["1.1.1.1", "2.2.2.2", "3.3.3.3"]:
            req = _make_request(peer=attacker_peer, forwarded=spoof)
            buckets.add(rl._get_real_client_ip(req))
        assert buckets == {attacker_peer}


class TestBehindProxyTrue:
    def test_trusts_forwarded_header(self, monkeypatch):
        rl = _reload_rate_limit_with_env(monkeypatch, "true")
        req = _make_request(peer="10.0.0.1", forwarded="1.2.3.4")
        assert rl._get_real_client_ip(req) == "1.2.3.4"

    def test_first_hop_wins(self, monkeypatch):
        rl = _reload_rate_limit_with_env(monkeypatch, "true")
        req = _make_request(peer="10.0.0.1", forwarded="1.2.3.4, 10.0.0.2, 10.0.0.3")
        assert rl._get_real_client_ip(req) == "1.2.3.4"

    def test_rejects_malformed_forwarded_value(self, monkeypatch):
        rl = _reload_rate_limit_with_env(monkeypatch, "true")
        req = _make_request(peer="10.0.0.1", forwarded="not-an-ip; DROP TABLE")
        # Falls through to peer when the first hop is not a valid IP
        assert rl._get_real_client_ip(req) == "10.0.0.1"

    def test_empty_forwarded_falls_through(self, monkeypatch):
        rl = _reload_rate_limit_with_env(monkeypatch, "yes")
        req = _make_request(peer="10.0.0.1", forwarded="")
        assert rl._get_real_client_ip(req) == "10.0.0.1"
