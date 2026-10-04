"""BrowserManager lifecycle and session coordinator."""

import logging
from pathlib import Path
from typing import Any

from lyra.browser.driver import BrowserDriver
from lyra.browser.mock_driver import MockBrowserDriver
from lyra.browser.models import BrowserAction
from lyra.browser.playwright_driver import PlaywrightDriver
from lyra.browser.policy import BrowserPolicy
from lyra.browser.session import BrowserSession
from lyra.config.settings import Settings

logger = logging.getLogger(__name__)


class BrowserManager:
    """Coordinates browser driver lifecycle and user/session isolation."""

    def __init__(
        self,
        settings: Settings | None = None,
        driver: BrowserDriver | None = None,
        policy: BrowserPolicy | None = None,
    ) -> None:
        self.settings = settings
        self.policy = policy or self._create_default_policy(settings)
        self._driver = driver
        self._active_sessions: dict[str, BrowserSession] = {}
        self._started = False

    @staticmethod
    def _create_default_policy(settings: Settings | None) -> BrowserPolicy:
        if settings is None:
            return BrowserPolicy()
        return BrowserPolicy(
            allowed_domains=settings.browser_allowed_domains,
            blocked_domains=settings.browser_blocked_domains,
            max_download_size_bytes=settings.browser_max_download_size_bytes,
            download_dir=Path(settings.browser_download_dir),
        )

    def _resolve_driver(self) -> BrowserDriver:
        if self._driver is not None:
            return self._driver

        driver_type = "auto"
        headless = True
        if self.settings is not None:
            driver_type = self.settings.browser_driver_type
            headless = self.settings.browser_headless

        if driver_type == "mock":
            logger.info("Initializing MockBrowserDriver as configured.")
            return MockBrowserDriver()

        if driver_type == "playwright":
            logger.info("Initializing PlaywrightDriver as configured.")
            return PlaywrightDriver(headless=headless)

        # "auto" mode: check if playwright is installed; fallback to mock driver
        try:
            import playwright  # noqa: F401
            logger.info("Playwright detected; using PlaywrightDriver.")
            return PlaywrightDriver(headless=headless)
        except ImportError:
            logger.info("Playwright not installed; defaulting to MockBrowserDriver.")
            return MockBrowserDriver()

    async def start(self) -> None:
        """Start underlying browser driver if not already running."""
        if not self._started:
            if self._driver is None:
                self._driver = self._resolve_driver()
            await self._driver.start()
            self._started = True
            logger.info("BrowserManager started successfully.")

    async def get_or_create_session(
        self,
        session_id: str,
        user_id: str | None = None,
        policy_override: BrowserPolicy | None = None,
    ) -> BrowserSession:
        """Retrieve existing session or create a new isolated session."""
        if session_id in self._active_sessions:
            return self._active_sessions[session_id]

        if not self._started:
            await self.start()

        assert self._driver is not None
        session_policy = policy_override or self.policy
        session_driver = await self._driver.create_session(session_id=session_id, isolated=True)
        session = BrowserSession(
            session_id=session_id,
            driver=session_driver,
            policy=session_policy,
            user_id=user_id,
        )
        self._active_sessions[session_id] = session
        logger.info("Created isolated browser session '%s' for user '%s'.", session_id, user_id)
        return session

    def get_session(self, session_id: str) -> BrowserSession | None:
        """Get existing session by ID or return None."""
        return self._active_sessions.get(session_id)

    async def close_session(self, session_id: str) -> None:
        """Close an active session and purge its memory."""
        session = self._active_sessions.pop(session_id, None)
        if session is not None:
            await session.close()
            logger.info("Closed browser session '%s'.", session_id)

    async def close(self) -> None:
        """Close all active sessions and shut down browser engine."""
        for session_id in list(self._active_sessions.keys()):
            await self.close_session(session_id)

        if self._driver is not None and self._started:
            await self._driver.close()
            self._started = False
            logger.info("BrowserManager shut down.")

    async def __aenter__(self) -> "BrowserManager":
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
