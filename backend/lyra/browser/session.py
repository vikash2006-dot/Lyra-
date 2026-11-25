"""Isolated browser session management with credential and history protection."""

from datetime import datetime, timezone
import logging
from typing import Any

from lyra.browser.driver import BrowserSessionDriver
from lyra.browser.models import BrowserAction
from lyra.browser.page import BrowserPage
from lyra.browser.policy import BrowserPolicy

logger = logging.getLogger(__name__)


class BrowserSession:
    """Manages an isolated browser session context with no persistent credentials."""

    def __init__(
        self,
        session_id: str,
        driver: BrowserSessionDriver,
        policy: BrowserPolicy,
        user_id: str | None = None,
    ) -> None:
        self.session_id = session_id
        self._driver = driver
        self.policy = policy
        self.user_id = user_id
        self.created_at = datetime.now(timezone.utc)
        self.history: list[str] = []
        self.action_log: list[str] = []
        self._current_page: BrowserPage | None = None

    @property
    def current_page(self) -> BrowserPage | None:
        return self._current_page

    async def navigate(self, url: str, timeout: float = 30.0) -> BrowserPage:
        """Navigate to target URL after validating URL against security policy."""
        # Enforce domain allowlist/denylist, blocked schemes, and SSRF restrictions
        self.policy.verify_url(url)

        page_driver = await self._driver.navigate(url=url, timeout=timeout)
        self._current_page = BrowserPage(driver=page_driver, policy=self.policy)
        self.history.append(url)
        logger.info("Browser session '%s' navigated to '%s'", self.session_id, url)
        return self._current_page

    async def get_current_page(self) -> BrowserPage | None:
        """Get currently active page, wrapping with BrowserPage if present."""
        if self._current_page is not None:
            return self._current_page

        page_driver = await self._driver.get_current_page()
        if page_driver is not None:
            self._current_page = BrowserPage(driver=page_driver, policy=self.policy)
        return self._current_page

    def log_action(self, action: BrowserAction) -> None:
        """Record action in session history with sensitive fields strictly masked."""
        safe_representation = action.safe_repr()
        self.action_log.append(safe_representation)
        logger.debug("Browser action in session '%s': %s", self.session_id, safe_representation)

    async def clear_session(self) -> None:
        """Clear cookies, local storage, and page context."""
        await self._driver.clear_session()
        self._current_page = None
        logger.info("Browser session '%s' cleared state and cookies.", self.session_id)

    async def close(self) -> None:
        """Close this session and release context resources."""
        await self._driver.close()
        self._current_page = None
        logger.info("Browser session '%s' closed.", self.session_id)
