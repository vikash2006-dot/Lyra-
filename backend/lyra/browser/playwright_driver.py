"""Playwright driver implementation isolated behind the LYRA browser driver interface."""

import asyncio
from pathlib import Path
import re
from typing import Any

from lyra.browser.driver import BrowserDriver, BrowserPageDriver, BrowserSessionDriver
from lyra.browser.models import PageContent
from lyra.core.exceptions import (
    BrowserDownloadLimitError,
    BrowserDriverError,
    BrowserNavigationError,
    BrowserTimeoutError,
)


class PlaywrightPageDriver(BrowserPageDriver):
    """Wraps a Playwright Page instance."""

    def __init__(self, pw_page: Any, session_id: str) -> None:
        self._page = pw_page
        self._session_id = session_id

    @property
    def url(self) -> str:
        try:
            return self._page.url or ""
        except Exception:
            return ""

    @property
    def title(self) -> str:
        # Title will be extracted asynchronously when content is inspected
        return ""

    async def extract_content(self) -> PageContent:
        try:
            url = self._page.url
            title = await self._page.title()
            text_content = await self._page.evaluate("() => document.body ? document.body.innerText : ''")

            # Extract basic links and forms
            links = await self._page.evaluate("""() => {
                const results = [];
                document.querySelectorAll('a[href]').forEach(el => {
                    const text = (el.innerText || el.textContent || '').trim();
                    const href = el.getAttribute('href') || '';
                    if (href && !href.startsWith('javascript:')) {
                        results.push({ text: text.slice(0, 100), href });
                    }
                });
                return results.slice(0, 50);
            }""")

            forms = await self._page.evaluate("""() => {
                const results = [];
                document.querySelectorAll('form').forEach(f => {
                    const inputs = [];
                    f.querySelectorAll('input, select, textarea, button').forEach(inp => {
                        inputs.push({
                            tag: inp.tagName.toLowerCase(),
                            name: inp.getAttribute('name') || '',
                            type: inp.getAttribute('type') || 'text',
                            id: inp.getAttribute('id') || '',
                        });
                    });
                    results.push({
                        action: f.getAttribute('action') || '',
                        method: (f.getAttribute('method') || 'GET').toUpperCase(),
                        inputs,
                    });
                });
                return results.slice(0, 20);
            }""")

            return PageContent(
                url=url,
                title=title,
                text_content=text_content or "",
                html_content=None,  # Do not blow up context with massive raw HTML unless requested
                links=links or [],
                forms=forms or [],
                metadata={"session_id": self._session_id},
            )
        except Exception as err:
            raise BrowserDriverError(f"Failed to extract page content: {err}") from err

    async def click(self, selector: str, timeout: float = 10.0) -> None:
        try:
            await self._page.click(selector, timeout=int(timeout * 1000))
        except TimeoutError as err:
            raise BrowserTimeoutError(f"Click on '{selector}' timed out after {timeout}s.") from err
        except Exception as err:
            raise BrowserDriverError(f"Failed to click selector '{selector}': {err}") from err

    async def fill(self, selector: str, value: str, timeout: float = 10.0) -> None:
        try:
            await self._page.fill(selector, value, timeout=int(timeout * 1000))
        except TimeoutError as err:
            raise BrowserTimeoutError(f"Fill on '{selector}' timed out after {timeout}s.") from err
        except Exception as err:
            raise BrowserDriverError(f"Failed to fill input '{selector}': {err}") from err

    async def download(
        self,
        target: str,
        destination_dir: Path,
        max_bytes: int,
        timeout: float = 30.0,
    ) -> Path:
        try:
            destination_dir.mkdir(parents=True, exist_ok=True)
            # Listen for download event while triggering download
            async with self._page.expect_download(timeout=int(timeout * 1000)) as download_info:
                # If target looks like a selector, click it; otherwise navigate to it
                if target.startswith("http://") or target.startswith("https://"):
                    await self._page.goto(target)
                else:
                    await self._page.click(target)

            download = await download_info.value
            suggested_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", download.suggested_filename)
            dest_file = destination_dir / (suggested_name or "download.bin")

            # Save and verify file size
            await download.save_as(str(dest_file))
            file_size = dest_file.stat().st_size
            if file_size > max_bytes:
                dest_file.unlink(missing_ok=True)
                raise BrowserDownloadLimitError(
                    f"Downloaded file size {file_size} bytes exceeds limit of {max_bytes} bytes."
                )
            return dest_file
        except (BrowserDownloadLimitError, BrowserTimeoutError):
            raise
        except TimeoutError as err:
            raise BrowserTimeoutError(f"Download of '{target}' timed out after {timeout}s.") from err
        except Exception as err:
            raise BrowserDriverError(f"Download failed for '{target}': {err}") from err


class PlaywrightSessionDriver(BrowserSessionDriver):
    """Manages an isolated Playwright browser context."""

    def __init__(self, session_id: str, context: Any) -> None:
        self._session_id = session_id
        self._context = context
        self._current_page: PlaywrightPageDriver | None = None

    @property
    def session_id(self) -> str:
        return self._session_id

    async def navigate(self, url: str, timeout: float = 30.0) -> PlaywrightPageDriver:
        try:
            pw_page = await self._context.new_page()
            await pw_page.goto(url, timeout=int(timeout * 1000), wait_until="domcontentloaded")
            self._current_page = PlaywrightPageDriver(pw_page=pw_page, session_id=self._session_id)
            return self._current_page
        except TimeoutError as err:
            raise BrowserTimeoutError(f"Navigation to '{url}' timed out after {timeout}s.") from err
        except Exception as err:
            raise BrowserNavigationError(f"Failed to navigate to '{url}': {err}") from err

    async def get_current_page(self) -> PlaywrightPageDriver | None:
        return self._current_page

    async def clear_session(self) -> None:
        try:
            await self._context.clear_cookies()
        except Exception:
            pass

    async def close(self) -> None:
        try:
            await self._context.close()
        except Exception:
            pass
        self._current_page = None


class PlaywrightDriver(BrowserDriver):
    """Playwright browser automation driver with isolated processes."""

    def __init__(self, headless: bool = True) -> None:
        self._headless = headless
        self._playwright: Any = None
        self._browser: Any = None
        self._active_sessions: dict[str, PlaywrightSessionDriver] = {}

    async def start(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as err:
            raise BrowserDriverError(
                "Playwright is not installed. To use real browser automation, run "
                "'pip install playwright' followed by 'playwright install chromium'."
            ) from err

        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self._headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
        except Exception as err:
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
            raise BrowserDriverError(f"Failed to launch Playwright browser: {err}") from err

    async def create_session(
        self,
        session_id: str,
        isolated: bool = True,
    ) -> PlaywrightSessionDriver:
        if self._browser is None:
            await self.start()

        try:
            # Create isolated incognito context (does not persist cookies to disk)
            context = await self._browser.new_context(
                ignore_https_errors=False,
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            session = PlaywrightSessionDriver(session_id=session_id, context=context)
            self._active_sessions[session_id] = session
            return session
        except Exception as err:
            raise BrowserDriverError(f"Failed to create browser session '{session_id}': {err}") from err

    async def close(self) -> None:
        for session in list(self._active_sessions.values()):
            await session.close()
        self._active_sessions.clear()

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
