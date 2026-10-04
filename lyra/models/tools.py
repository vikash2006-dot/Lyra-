"""Canonical models for tool requests and results."""

from dataclasses import dataclass, field
import json
from typing import Any

from lyra.core.exceptions import ModelValidationError


@dataclass(frozen=True)
class ToolRequest:
    """Represents a request to execute a specific tool with arguments."""

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tool_name or not isinstance(self.tool_name, str):
            raise ModelValidationError("ToolRequest requires a non-empty tool_name.")
        if not isinstance(self.arguments, dict):
            raise ModelValidationError("ToolRequest arguments must be a dictionary.")


@dataclass(frozen=True)
class ToolResult:
    """Represents the outcome of a tool execution."""

    tool_name: str
    success: bool
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tool_name or not isinstance(self.tool_name, str):
            raise ModelValidationError("ToolResult requires a non-empty tool_name.")

    def is_success(self) -> bool:
        """Check if execution succeeded."""
        return self.success

    def is_failure(self) -> bool:
        """Check if execution failed."""
        return not self.success

    def to_text(self) -> str:
        """Return a clean string representation for AI context or user display."""
        if self.is_success():
            if isinstance(self.output, str):
                return self.output
            if isinstance(self.output, (dict, list)):
                return json.dumps(self.output, indent=2)
            return str(self.output)
        return f"Tool Error ({self.tool_name}): {self.error or 'Unknown failure'}"
