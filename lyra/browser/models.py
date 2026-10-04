"""Domain models for LYRA browser automation."""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any


class BrowserActionType(str, Enum):
    """Supported browser action types."""

    NAVIGATE = "navigate"
    EXTRACT = "extract"
    CLICK = "click"
    FILL = "fill"
    DOWNLOAD = "download"
    CLOSE = "close"


# Sensitive field identifiers that must be masked in representations and logs
SENSITIVE_FIELD_PATTERN = re.compile(
    r"(?i)(password|pass|secret|token|api[_-]?key|auth|credit|card|cvv|pin|ssn)"
)


@dataclass(frozen=True)
class BrowserAction:
    """Represents an intent or request to perform an action in a browser session."""

    action_type: BrowserActionType
    target: str
    value: str | None = None
    confirmed: bool = False
    session_id: str | None = None
    is_sensitive: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def safe_repr(self) -> str:
        """Return a string representation guaranteed to mask passwords and sensitive values."""
        masked_val = self.value
        if self.value is not None:
            # Mask if action is marked sensitive or selector/target matches sensitive terms
            if self.is_sensitive or SENSITIVE_FIELD_PATTERN.search(self.target):
                masked_val = "***REDACTED***"

        return (
            f"BrowserAction(action_type={self.action_type.value}, "
            f"target='{self.target}', "
            f"value={repr(masked_val)}, "
            f"confirmed={self.confirmed}, "
            f"session_id={repr(self.session_id)})"
        )


@dataclass
class PageContent:
    """Extracted content and structural elements from a browser page."""

    url: str
    title: str
    text_content: str
    html_content: str | None = None
    links: list[dict[str, str]] = field(default_factory=list)
    forms: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BrowserActionResult:
    """Outcome of a browser action execution."""

    success: bool
    action_type: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    requires_confirmation: bool = False
    confirmation_reason: str | None = None
    page_content: PageContent | None = None
