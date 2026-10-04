"""Abstract controller interfaces for screen, mouse, keyboard, and application operations."""

from abc import ABC, abstractmethod

from lyra.computer.models import MouseButton, Point, ScreenSize


class ScreenCapture(ABC):
    """Abstract interface for screen inspection and capturing."""

    @abstractmethod
    async def capture_screen(self) -> bytes:
        """Capture screen as raw image bytes (e.g. PNG)."""

    @abstractmethod
    async def get_screen_size(self) -> ScreenSize:
        """Get the resolution/dimensions of the primary display."""


class MouseController(ABC):
    """Abstract interface for mouse pointer control."""

    @abstractmethod
    async def get_position(self) -> Point:
        """Get the current cursor position."""

    @abstractmethod
    async def move(self, point: Point) -> None:
        """Move cursor to the specified point."""

    @abstractmethod
    async def click(
        self,
        point: Point | None = None,
        button: MouseButton = MouseButton.LEFT,
        clicks: int = 1,
    ) -> None:
        """Click at the current position or specified point."""


class KeyboardController(ABC):
    """Abstract interface for keyboard typing and key presses."""

    @abstractmethod
    async def type_text(self, text: str) -> None:
        """Type a sequence of characters."""

    @abstractmethod
    async def press_key(self, key: str) -> None:
        """Press and release a single key."""

    @abstractmethod
    async def hotkey(self, *keys: str) -> None:
        """Press and release a key combination."""


class ApplicationController(ABC):
    """Abstract interface for application management."""

    @abstractmethod
    async def list_running_apps(self) -> list[str]:
        """List names of currently running graphical applications."""

    @abstractmethod
    async def launch_app(self, app_name: str) -> bool:
        """Launch a specified application."""

    @abstractmethod
    async def terminate_app(self, app_name: str) -> bool:
        """Terminate a specified application."""
