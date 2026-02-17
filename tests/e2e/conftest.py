"""
E2E test fixtures using Playwright.

Requires: pip install playwright && playwright install chromium

These tests run against a live instance of the application.
Set TEST_BASE_URL environment variable to point to the running app.
"""

import os
import socket

import pytest

# Skip all E2E tests if playwright is not installed
pytest.importorskip("playwright")

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8080")


def _is_server_running(host: str = "localhost", port: int = 8080) -> bool:
    """Check if the application server is reachable."""
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except (ConnectionRefusedError, OSError, socket.timeout):
        return False


# Parse port from BASE_URL
_port = int(BASE_URL.rsplit(":", 1)[-1].split("/")[0]) if ":" in BASE_URL.rsplit("//", 1)[-1] else 8080
_server_available = _is_server_running(port=_port)

# Skip all E2E tests if server is not running
pytestmark = pytest.mark.skipif(
    not _server_available,
    reason=f"E2E server not running at {BASE_URL}",
)


@pytest.fixture(scope="session")
def base_url():
    """Base URL for the running application."""
    if not _server_available:
        pytest.skip(f"E2E server not running at {BASE_URL}")
    return BASE_URL
