"""Abstract base interface for LYRA tools."""

from abc import ABC, abstractmethod
import asyncio
from typing import Any

from lyra.models.tools import ToolRequest, ToolResult
from lyra.tools.permissions import ToolPermissionLevel


class Tool(ABC):
    """Abstract base class for all LYRA capabilities and tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier of the tool (e.g., 'time')."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Clear description of what the tool accomplishes."""

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema defining expected arguments, types, and constraints."""

    @property
    def permission_level(self) -> ToolPermissionLevel:
        """Risk and authorization level required to invoke this tool."""
        return ToolPermissionLevel.READ_ONLY

    @property
    def requires_network(self) -> bool:
        """Whether this tool requires external network access."""
        return False

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        """Inspect user input to determine if this tool should be invoked.

        Returns:
            dict of arguments if this tool can handle the input, None otherwise.
        """
        return None

    def format_result(self, result: ToolResult) -> str:
        """Format tool result into a friendly conversational string."""
        return result.to_text()

    @abstractmethod
    async def execute(self, request: ToolRequest) -> ToolResult:
        """Asynchronously execute the tool with the validated ToolRequest.

        Args:
            request: The validated, authorized ToolRequest.

        Returns:
            ToolResult containing structured output or error details.
        """

    def execute_sync(self, request: ToolRequest) -> ToolResult:
        """Synchronously execute the tool by running the event loop."""
        return asyncio.run(self.execute(request))
