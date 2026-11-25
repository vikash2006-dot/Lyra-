"""Tool intent decider for LYRA."""

from typing import Any

from lyra.models.tools import ToolRequest
from lyra.tools.registry import ToolRegistry


class ToolDecider:
    """Decides which registered tool (if any) should handle a given user input."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def decide(self, user_input: str, session_id: str | None = None) -> ToolRequest | None:
        """Inspect registered tools to determine if any tool matches the user's intent.

        Each tool may implement `can_handle(user_input: str) -> dict[str, Any] | None`
        to signal whether it can process the request and extract parameters.
        """
        for tool in self.registry.list_tools():
            can_handle_fn = getattr(tool, "can_handle", None)
            if callable(can_handle_fn):
                args = can_handle_fn(user_input)
                if args is not None:
                    return ToolRequest(
                        tool_name=tool.name,
                        arguments=args if isinstance(args, dict) else {},
                        session_id=session_id,
                    )
        return None
