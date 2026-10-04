"""Domain models for controlled local computer interaction."""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any

# Sensitive patterns that must be redacted in representations and diagnostic logs
SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?i)(password|pass|secret|token|api[_-]?key|credential|auth|pin|ssn)"
)


class ComputerActionType(str, Enum):
    """Supported computer interaction actions."""

    SCREENSHOT = "screenshot"
    INSPECT_SCREEN = "inspect_screen"
    MOVE_CURSOR = "move_cursor"
    CLICK = "click"
    TYPE_TEXT = "type_text"
    PRESS_KEY = "press_key"
    HOTKEY = "hotkey"
    LAUNCH_APP = "launch_app"
    TERMINATE_APP = "terminate_app"
    EMERGENCY_STOP = "emergency_stop"


class MouseButton(str, Enum):
    """Mouse button choices."""

    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"
    DOUBLE = "double"


@dataclass(frozen=True)
class Point:
    """Screen coordinate."""

    x: int
    y: int


@dataclass(frozen=True)
class ScreenSize:
    """Screen dimensions."""

    width: int
    height: int


@dataclass(frozen=True)
class ComputerAction:
    """Represents an intent or request to perform a computer interaction."""

    action_type: ComputerActionType
    point: Point | None = None
    text: str | None = None
    key: str | None = None
    keys: tuple[str, ...] | None = None
    app_name: str | None = None
    button: MouseButton = MouseButton.LEFT
    confirmed: bool = False
    is_sensitive: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def safe_repr(self) -> str:
        """Return representation guaranteed to mask passwords and sensitive strings."""
        masked_text = self.text
        if self.text is not None:
            if self.is_sensitive or SENSITIVE_TEXT_PATTERN.search(self.text):
                masked_text = "***REDACTED***"

        return (
            f"ComputerAction(action_type={self.action_type.value}, "
            f"point={self.point}, "
            f"text={repr(masked_text)}, "
            f"key={repr(self.key)}, "
            f"keys={self.keys}, "
            f"app_name={repr(self.app_name)}, "
            f"button={self.button.value}, "
            f"confirmed={self.confirmed})"
        )


@dataclass
class ComputerActionResult:
    """Outcome of a computer action execution."""

    success: bool
    action_type: str
    output: Any = None
    error: str | None = None
    requires_confirmation: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
