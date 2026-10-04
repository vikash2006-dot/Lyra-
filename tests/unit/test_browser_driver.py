"""Unit tests for BrowserDriver implementations (MockBrowserDriver and PlaywrightDriver)."""

import asyncio
from pathlib import Path
import pytest

from lyra.browser.mock_driver import MockBrowserDriver
from lyra.browser.playwright_driver import PlaywrightDriver
from lyra.core.exceptions import (
    BrowserDownloadLimitError,
    BrowserDriverError,
    BrowserNavigationError,
    BrowserTimeoutError,
)


def test_mock_driver_navigation_and_dom_extraction():
    async def _test():
        driver = MockBrowserDriver()
        await driver.start()

        html_content = """
        <!DOCTYPE html>
        <html>
        <head><title>Test Store</title></head>
        <body>
            <h1>Welcome to Store</h1>
            <p>Featured products and services.</p>
            <a href="/products">View Products</a>
            <a href="https://example.com/about">About Us</a>
            <form action="/search" method="GET">
                <input type="text" name="q" value="" placeholder="Search...">
                <button type="submit">Search</button>
            </form>
        </body>
        </html>
        """
        driver.register_page("https://test.local/store", "Test Store", html_content)

        session = await driver.create_session("session_1")
        page = await session.navigate("https://test.local/store")

        assert page.url == "https://test.local/store"
        assert page.title == "Test Store"

        content = await page.extract_content()
        assert content.title == "Test Store"
        assert "Welcome to Store" in content.text_content
        assert "Featured products and services." in content.text_content
        assert len(content.links) == 2
        assert content.links[0]["href"] == "/products"
        assert len(content.forms) == 1
        assert content.forms[0]["action"] == "/search"
        assert len(content.forms[0]["inputs"]) == 2

        await driver.close()

    asyncio.run(_test())


def test_mock_driver_click_and_fill():
    async def _test():
        driver = MockBrowserDriver()
        await driver.start()

        session = await driver.create_session("session_click_fill")
        page = await session.navigate("https://test.local/form")

        await page.fill("input#username", "testuser")
        await page.fill("input#email", "test@example.com")
        await page.click("button#submit-btn")

        assert page.filled_inputs["input#username"] == "testuser"
        assert page.filled_inputs["input#email"] == "test@example.com"
        assert "button#submit-btn" in page.clicked_selectors

        await driver.close()

    asyncio.run(_test())


def test_mock_driver_download_success_and_limit(tmp_path: Path):
    async def _test():
        driver = MockBrowserDriver()
        await driver.start()

        session = await driver.create_session("session_download")
        page = await session.navigate("https://test.local/files")

        # Set mock download data
        session.mock_download_data["https://test.local/files/doc.pdf"] = b"PDF-DATA-12345"

        download_dir = tmp_path / "downloads"
        # Successful download
        saved_file = await page.download(
            target="https://test.local/files/doc.pdf",
            destination_dir=download_dir,
            max_bytes=1000,
        )
        assert saved_file.exists()
        assert saved_file.read_bytes() == b"PDF-DATA-12345"

        # Download exceeding max_bytes limit
        with pytest.raises(BrowserDownloadLimitError, match="exceeds maximum limit"):
            await page.download(
                target="https://test.local/files/doc.pdf",
                destination_dir=download_dir,
                max_bytes=5,
            )

        await driver.close()

    asyncio.run(_test())


def test_mock_driver_timeout_simulation():
    async def _test():
        driver = MockBrowserDriver()
        await driver.start()

        session = await driver.create_session("session_timeout")
        session.simulate_timeout = True

        with pytest.raises(BrowserTimeoutError, match="timed out"):
            await session.navigate("https://test.local/timeout")

        session.simulate_timeout = False
        page = await session.navigate("https://test.local/ok")

        session.simulate_timeout = True
        with pytest.raises(BrowserTimeoutError, match="timed out"):
            await page.click("#button")

        with pytest.raises(BrowserTimeoutError, match="timed out"):
            await page.fill("#input", "value")

        await driver.close()

    asyncio.run(_test())


def test_mock_driver_navigation_error_simulation():
    async def _test():
        driver = MockBrowserDriver()
        await driver.start()

        session = await driver.create_session("session_error")
        session.simulate_navigation_error = True

        with pytest.raises(BrowserNavigationError, match="network failure"):
            await session.navigate("https://test.local/error")

        await driver.close()

    asyncio.run(_test())


def test_playwright_driver_graceful_missing_handling(monkeypatch):
    async def _test():
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name.startswith("playwright"):
                raise ImportError("No module named 'playwright'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        pw_driver = PlaywrightDriver()
        with pytest.raises(BrowserDriverError, match="Playwright is not installed"):
            await pw_driver.start()

    asyncio.run(_test())
