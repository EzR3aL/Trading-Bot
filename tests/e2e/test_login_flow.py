"""
E2E tests for login flow.

Requires a running application instance and Playwright installed.
Run with: pytest tests/e2e -v -m e2e
"""

import pytest

playwright = pytest.importorskip("playwright")

from tests.e2e.conftest import _server_available

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.slow,
    pytest.mark.skipif(not _server_available, reason="E2E server not running"),
]


@pytest.fixture
async def page(base_url):
    """Create a browser page for testing."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        yield page
        await context.close()
        await browser.close()


@pytest.mark.asyncio
async def test_login_page_loads(page, base_url):
    """Login page should render with username and password fields."""
    await page.goto(f"{base_url}/login")
    assert await page.locator("input[type='text']").count() >= 1
    assert await page.locator("input[type='password']").count() >= 1
    assert await page.locator("button[type='submit']").count() >= 1


@pytest.mark.asyncio
async def test_login_with_invalid_credentials(page, base_url):
    """Login with wrong credentials should show error."""
    await page.goto(f"{base_url}/login")
    await page.fill("input[type='text']", "wronguser")
    await page.fill("input[type='password']", "wrongpass")
    await page.click("button[type='submit']")
    # Should stay on login page
    await page.wait_for_timeout(1000)
    assert "/login" in page.url


@pytest.mark.asyncio
async def test_login_with_valid_credentials(page, base_url):
    """Login with correct credentials should redirect to dashboard."""
    await page.goto(f"{base_url}/login")
    await page.fill("input[type='text']", "admin")
    await page.fill("input[type='password']", "admin123456")
    await page.click("button[type='submit']")
    await page.wait_for_timeout(2000)
    # Should redirect away from login
    assert "/login" not in page.url or await page.locator("text=Dashboard").count() > 0
