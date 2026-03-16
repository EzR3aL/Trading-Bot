"""
E2E tests for settings flow.

Requires a running application instance with an admin user.
"""

import pytest

playwright = pytest.importorskip("playwright")

from tests.e2e.conftest import _server_available  # noqa: E402

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.slow,
    pytest.mark.skipif(not _server_available, reason="E2E server not running"),
]


@pytest.fixture
async def authenticated_page(base_url):
    """Create an authenticated browser page."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Login first
        await page.goto(f"{base_url}/login")
        await page.fill("input[type='text']", "admin")
        await page.fill("input[type='password']", "admin123456")
        await page.click("button[type='submit']")
        await page.wait_for_timeout(2000)

        yield page
        await context.close()
        await browser.close()


@pytest.mark.asyncio
async def test_settings_page_loads(authenticated_page, base_url):
    """Settings page should load with tabs."""
    await authenticated_page.goto(f"{base_url}/settings")
    await authenticated_page.wait_for_timeout(1000)
    # Should show settings heading
    content = await authenticated_page.content()
    assert "Settings" in content or "Einstellungen" in content


