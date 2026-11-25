"""Mock and local HTML browser driver for deterministic, zero-dependency browser automation."""

import asyncio
from html.parser import HTMLParser
from pathlib import Path
import re
from typing import Any
from urllib.parse import urljoin

from lyra.browser.driver import BrowserDriver, BrowserPageDriver, BrowserSessionDriver
from lyra.browser.models import PageContent
from lyra.core.exceptions import (
    BrowserDownloadLimitError,
    BrowserNavigationError,
    BrowserTimeoutError,
)


class SimpleHTMLDOMParser(HTMLParser):
    """Lightweight standard-library HTML parser for extracting text, title, links, and forms."""

    def __init__(self) -> None:
        super().__init__()
        self.title: str = ""
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self.forms: list[dict[str, Any]] = []

        self._in_title = False
        self._in_script_or_style = False
        self._current_form: dict[str, Any] | None = None
        self._current_link: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k.lower(): (v or "") for k, v in attrs}
        tag_lower = tag.lower()

        if tag_lower in ("script", "style", "noscript"):
            self._in_script_or_style = True
            return

        if tag_lower == "title":
            self._in_title = True
            return

        if tag_lower == "a":
            href = attr_dict.get("href", "")
            self._current_link = {"href": href, "text": ""}
            return

        if tag_lower == "form":
            self._current_form = {
                "action": attr_dict.get("action", ""),
                "method": attr_dict.get("method", "GET").upper(),
                "inputs": [],
            }
            return

        if tag_lower in ("input", "textarea", "select", "button") and self._current_form is not None:
            input_entry = {
                "tag": tag_lower,
                "name": attr_dict.get("name", ""),
                "type": attr_dict.get("type", "text" if tag_lower == "input" else tag_lower),
                "value": attr_dict.get("value", ""),
                "id": attr_dict.get("id", ""),
            }
            self._current_form["inputs"].append(input_entry)

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in ("script", "style", "noscript"):
            self._in_script_or_style = False
        elif tag_lower == "title":
            self._in_title = False
        elif tag_lower == "a" and self._current_link is not None:
            self._current_link["text"] = self._current_link["text"].strip()
            self.links.append(self._current_link)
            self._current_link = None
        elif tag_lower == "form" and self._current_form is not None:
            self.forms.append(self._current_form)
            self._current_form = None

    def handle_data(self, data: str) -> None:
        if self._in_script_or_style:
            return
        if self._in_title:
            self.title += data
        else:
            text = data.strip()
            if text:
                self.text_parts.append(text)
            if self._current_link is not None:
                self._current_link["text"] += data


class MockBrowserPageDriver(BrowserPageDriver):
    """Mock implementation of a browser page."""

    def __init__(
        self,
        url: str,
        title: str,
        html: str,
        session_driver: "MockBrowserSessionDriver",
    ) -> None:
        self._url = url
        self._title = title
        self._html = html
        self._session_driver = session_driver
        self.clicked_selectors: list[str] = []
        self.filled_inputs: dict[str, str] = {}
        self._parse_dom()

    def _parse_dom(self) -> None:
        parser = SimpleHTMLDOMParser()
        parser.feed(self._html)
        if parser.title:
            self._title = parser.title.strip()
        self._text_content = " ".join(parser.text_parts)
        self._links = parser.links
        self._forms = parser.forms

    @property
    def url(self) -> str:
        return self._url

    @property
    def title(self) -> str:
        return self._title

    async def extract_content(self) -> PageContent:
        return PageContent(
            url=self._url,
            title=self._title,
            text_content=self._text_content,
            html_content=self._html,
            links=self._links,
            forms=self._forms,
            metadata={"session_id": self._session_driver.session_id},
        )

    async def click(self, selector: str, timeout: float = 10.0) -> None:
        if self._session_driver.simulate_timeout:
            raise BrowserTimeoutError(f"Click on selector '{selector}' timed out after {timeout}s.")
        self.clicked_selectors.append(selector)

    async def fill(self, selector: str, value: str, timeout: float = 10.0) -> None:
        if self._session_driver.simulate_timeout:
            raise BrowserTimeoutError(f"Fill on selector '{selector}' timed out after {timeout}s.")
        self.filled_inputs[selector] = value

    async def download(
        self,
        target: str,
        destination_dir: Path,
        max_bytes: int,
        timeout: float = 30.0,
    ) -> Path:
        if self._session_driver.simulate_timeout:
            raise BrowserTimeoutError(f"Download of '{target}' timed out after {timeout}s.")

        destination_dir.mkdir(parents=True, exist_ok=True)
        # Determine filename
        filename = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", target.split("/")[-1] or "download.txt")
        file_path = destination_dir / filename

        # Content to download
        content = self._session_driver.mock_download_data.get(
            target, f"Mock download content for {target}".encode("utf-8")
        )
        if len(content) > max_bytes:
            raise BrowserDownloadLimitError(
                f"File size {len(content)} bytes exceeds maximum limit of {max_bytes} bytes."
            )

        file_path.write_bytes(content)
        return file_path


class MockBrowserSessionDriver(BrowserSessionDriver):
    """Mock implementation of an isolated browser session."""

    def __init__(self, session_id: str, driver: "MockBrowserDriver") -> None:
        self._session_id = session_id
        self._driver = driver
        self._current_page: MockBrowserPageDriver | None = None
        self.cookies: dict[str, str] = {}
        self.simulate_timeout: bool = False
        self.simulate_navigation_error: bool = False
        self.mock_download_data: dict[str, bytes] = {}

    @property
    def session_id(self) -> str:
        return self._session_id

    async def navigate(self, url: str, timeout: float = 30.0) -> MockBrowserPageDriver:
        if self.simulate_timeout:
            raise BrowserTimeoutError(f"Navigation to '{url}' timed out after {timeout}s.")
        if self.simulate_navigation_error:
            raise BrowserNavigationError(f"Failed to navigate to '{url}': network failure.")

        # Check registered pages in mock driver
        if url in self._driver.registered_pages:
            title, html = self._driver.registered_pages[url]
        elif url.startswith("file://"):
            local_path = Path(url[7:])
            if local_path.exists():
                html = local_path.read_text(encoding="utf-8")
                title = f"Local: {local_path.name}"
            else:
                raise BrowserNavigationError(f"File not found: {local_path}")
        else:
            title = f"Mock Page: {url}"
            html = (
                f"<html><head><title>{title}</title></head>"
                f"<body><h1>Heading for {url}</h1><p>Mock text content from {url}</p></body></html>"
            )

        page = MockBrowserPageDriver(url=url, title=title, html=html, session_driver=self)
        self._current_page = page
        return page

    async def get_current_page(self) -> MockBrowserPageDriver | None:
        return self._current_page

    async def clear_session(self) -> None:
        self.cookies.clear()
        self._current_page = None

    async def close(self) -> None:
        await self.clear_session()


class MockBrowserDriver(BrowserDriver):
    """Top-level mock browser driver for testing and offline environments."""

    def __init__(self) -> None:
        self.registered_pages: dict[str, tuple[str, str]] = {}
        self.active_sessions: dict[str, MockBrowserSessionDriver] = {}
        self.is_started: bool = False

    @property
    def current_url(self) -> str:
        for session in reversed(list(self.active_sessions.values())):
            if session._current_page and session._current_page.url:
                return session._current_page.url
        return ""

    def register_page(self, url: str, title: str, html: str) -> None:
        """Register a canned HTML response for a URL."""
        self.registered_pages[url] = (title, html)

    async def start(self) -> None:
        self.is_started = True

    async def create_session(
        self,
        session_id: str,
        isolated: bool = True,
    ) -> MockBrowserSessionDriver:
        session = MockBrowserSessionDriver(session_id=session_id, driver=self)
        self.active_sessions[session_id] = session
        return session

    async def close(self) -> None:
        for session in list(self.active_sessions.values()):
            await session.close()
        self.active_sessions.clear()
        self.is_started = False
