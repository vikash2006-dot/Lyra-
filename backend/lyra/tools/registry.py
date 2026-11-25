"""Central tool registry for LYRA."""

from typing import Any, Sequence

from lyra.core.exceptions import ToolError
from lyra.tools.base import Tool


class ToolRegistry:
    """Registry maintaining available tools and preventing duplicate collisions."""

    def __init__(self, tools: Sequence[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        if tools:
            for tool in tools:
                self.register(tool)

    def register(self, tool: Tool) -> None:
        """Register a new Tool instance in the registry.

        Raises:
            ToolError: If a tool with the same normalized name is already registered,
                       or if tool is not a valid Tool instance.
        """
        if not isinstance(tool, Tool):
            raise ToolError(f"Cannot register non-Tool object: {type(tool)}")

        norm_name = tool.name.lower().strip()
        if not norm_name:
            raise ToolError("Tool name cannot be empty.")

        if norm_name in self._tools:
            raise ToolError(f"Tool with name '{tool.name}' is already registered.")

        self._tools[norm_name] = tool

    def register_alias(self, alias: str, target_name: str) -> None:
        """Register an alias name that maps to an existing tool."""
        norm_alias = alias.lower().strip()
        norm_target = target_name.lower().strip()
        if norm_target in self._tools:
            self._tools[norm_alias] = self._tools[norm_target]

    def get(self, name: str) -> Tool | None:
        """Retrieve a tool by name (case-insensitive, supporting dotted action notation)."""
        norm_name = name.lower().strip()
        if norm_name in self._tools:
            return self._tools[norm_name]
        if "." in norm_name:
            prefix = norm_name.split(".", 1)[0].strip()
            if prefix in self._tools:
                return self._tools[prefix]
            if prefix in ("youtube", "google") and "browser" in self._tools:
                return self._tools["browser"]
        return None

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return self.get(name) is not None

    def list_tools(self) -> list[Tool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def get_schemas(self) -> list[dict[str, Any]]:
        """Export tool specifications and JSON schemas for discovery."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
                "permission_level": tool.permission_level.value,
            }
            for tool in self.list_tools()
        ]
