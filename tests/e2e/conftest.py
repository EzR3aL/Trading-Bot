"""
E2E test fixtures using Playwright.

Requires: pip install playwright && playwright install chromium

These tests run against a live instance of the application.
Set TEST_BASE_URL environment variable to point to the running app.
"""

import os

import pytest

# Skip all E2E tests if playwright is not installed
pytest.importorskip("playwright")

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8080")


@pytest.fixture(scope="session")
def base_url():
    """Base URL for the running application."""
    return BASE_URL
