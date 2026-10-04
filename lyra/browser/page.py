"""Browser page abstraction with prompt injection defense and safe interactions."""

from pathlib import Path
import re
from typing import Any

from lyra.browser.driver import BrowserPageDriver
from lyra.browser.models import BrowserAction, BrowserActionType, PageContent
from lyra.browser.policy import BrowserPolicy
from lyra.tools.sanitizer import sanitize_external_text, wrap_untrusted_context


class BrowserPage:
    """High-level page abstraction enforcing security policies and untrusted data wrapping."""

    def __init__(
        self,
        driver: BrowserPageDriver,
        policy: BrowserPolicy,
    ) -> None:
        self._driver = driver
        self._policy = policy

    @property
    def url(self) -> str:
        return self._driver.url

    @property
    def title(self) -> str:
        return self._driver.title

    async def extract_content(self) -> PageContent:
        """Extract structured content from the page, sanitizing text and wrapping with untrusted boundary."""
        raw_content = await self._driver.extract_content()

        # 1. Sanitize raw text to neutralize prompt injection attacks and control characters
        sanitized_text = sanitize_external_text(raw_content.text_content, max_chars=5000)

        # 2. Format links and forms cleanly for AI context
        links_summary = "\n".join(
            f"- [{link.get('text', '').strip() or 'Link'}]({link.get('href', '')})"
            for link in raw_content.links[:25]
        )

        forms_summary = ""
        if raw_content.forms:
            form_lines = []
            for idx, form in enumerate(raw_content.forms[:10], start=1):
                inputs_desc = ", ".join(
                    f"{inp.get('name') or inp.get('id') or 'field'} ({inp.get('type', 'text')})"
                    for inp in form.get("inputs", [])
                )
                form_lines.append(
                    f"Form #{idx}: method={form.get('method', 'GET')} action={form.get('action', '')} fields=[{inputs_desc}]"
                )
            forms_summary = "\n".join(form_lines)

        structured_body = f"PAGE TITLE: {raw_content.title}\nURL: {raw_content.url}\n\nTEXT CONTENT:\n{sanitized_text}"
        if links_summary:
            structured_body += f"\n\nPAGE LINKS:\n{links_summary}"
        if forms_summary:
            structured_body += f"\n\nPAGE FORMS:\n{forms_summary}"

        # 3. Encapsulate inside untrusted external content container
        isolated_content = wrap_untrusted_context(source="browser", content=structured_body)

        return PageContent(
            url=raw_content.url,
            title=raw_content.title,
            text_content=isolated_content,
            html_content=None,  # Do not return raw uncontrolled HTML
            links=raw_content.links,
            forms=raw_content.forms,
            metadata=raw_content.metadata,
        )

    async def click(self, selector: str, confirmed: bool = False, timeout: float = 10.0) -> None:
        """Click an element, validating against policy and requiring confirmation if destructive."""
        action = BrowserAction(
            action_type=BrowserActionType.CLICK,
            target=selector,
            confirmed=confirmed,
        )
        self._policy.enforce_confirmation(action)
        await self._driver.click(selector=selector, timeout=timeout)

    async def fill(
        self,
        selector: str,
        value: str,
        confirmed: bool = False,
        is_sensitive: bool = False,
        timeout: float = 10.0,
    ) -> None:
        """Fill an input element, enforcing confirmation for credentials or payment fields."""
        action = BrowserAction(
            action_type=BrowserActionType.FILL,
            target=selector,
            value=value,
            confirmed=confirmed,
            is_sensitive=is_sensitive,
        )
        self._policy.enforce_confirmation(action)
        await self._driver.fill(selector=selector, value=value, timeout=timeout)

    async def download(
        self,
        target: str,
        confirmed: bool = False,
        timeout: float = 30.0,
    ) -> Path:
        """Download file to controlled directory, enforcing size limits and confirmation."""
        action = BrowserAction(
            action_type=BrowserActionType.DOWNLOAD,
            target=target,
            confirmed=confirmed,
        )
        self._policy.enforce_confirmation(action)

        destination_dir = self._policy.download_dir
        return await self._driver.download(
            target=target,
            destination_dir=destination_dir,
            max_bytes=self._policy.max_download_size_bytes,
            timeout=timeout,
        )
