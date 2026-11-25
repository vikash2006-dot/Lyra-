"""Abstract browser driver interface for LYRA browser automation."""

from abc import ABC, abstractmethod
from pathlib import Path

from lyra.browser.models import PageContent


class BrowserPageDriver(ABC):
    """Abstract interface for interacting with a single browser page."""

    @property
    @abstractmethod
    def url(self) -> str:
        """Current page URL."""

    @property
    @abstractmethod
    def title(self) -> str:
        """Current page title."""

    @abstractmethod
    async def extract_content(self) -> PageContent:
        """Extract structured text, links, forms, and metadata from the page."""

    @abstractmethod
    async def click(self, selector: str, timeout: float = 10.0) -> None:
        """Click an element matching the given CSS selector or target text."""

    @abstractmethod
    async def fill(self, selector: str, value: str, timeout: float = 10.0) -> None:
        """Fill an input element matching the selector with the specified value."""

    @abstractmethod
    async def download(
        self,
        target: str,
        destination_dir: Path,
        max_bytes: int,
        timeout: float = 30.0,
    ) -> Path:
        """Download a file from target URL or click a download selector into destination_dir."""


class BrowserSessionDriver(ABC):
    """Abstract interface for managing an isolated browsing session/context."""

    @property
    @abstractmethod
    def session_id(self) -> str:
        """Unique identifier for this browser session."""

    @abstractmethod
    async def navigate(self, url: str, timeout: float = 30.0) -> BrowserPageDriver:
        """Navigate to a target URL and return the resulting page driver."""

    @abstractmethod
    async def get_current_page(self) -> BrowserPageDriver | None:
        """Get the active page driver in this session, or None if no page is open."""

    @abstractmethod
    async def clear_session(self) -> None:
        """Clear all ephemeral cookies, local storage, and cached secrets."""

    @abstractmethod
    async def close(self) -> None:
        """Close the session and release all associated resources."""


class BrowserDriver(ABC):
    """Abstract top-level browser automation engine driver."""

    @abstractmethod
    async def start(self) -> None:
        """Initialize the browser engine."""

    @abstractmethod
    async def create_session(
        self,
        session_id: str,
        isolated: bool = True,
    ) -> BrowserSessionDriver:
        """Create a new isolated browsing session."""

    @abstractmethod
    async def close(self) -> None:
        """Shut down the browser engine and all active sessions."""
