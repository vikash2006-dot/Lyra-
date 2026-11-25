"""Memory tool enabling LYRA to store, search, list, and forget long-term memories."""

import re
from typing import Any

from lyra.core.exceptions import (
    MemoryError,
    MemoryNotFoundError,
    MemoryPolicyViolationError,
)
from lyra.memory.manager import MemoryManager
from lyra.models.memory import MemoryType
from lyra.models.tools import ToolRequest, ToolResult
from lyra.observability.logging import get_logger
from lyra.tools.base import Tool
from lyra.tools.permissions import ToolPermissionLevel

logger = get_logger("tools.memory")


class MemoryTool(Tool):
    """Tool allowing LYRA to explicitly manage permitted personal memories."""

    def __init__(self, memory_manager: MemoryManager, default_user_id: str = "default_user") -> None:
        self.memory_manager = memory_manager
        self.default_user_id = default_user_id

    @property
    def name(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return (
            "Store, search, list, or forget long-term memories and preferences for the user. "
            "Supported categories: preference, fact, goal, habit, important_event, task, conversation_summary."
        )

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.LOW_RISK

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["remember", "list", "search", "forget"],
                    "description": "Action to perform: 'remember', 'list', 'search', or 'forget'.",
                },
                "content": {
                    "type": "string",
                    "description": "Information to remember (required for 'remember').",
                },
                "memory_type": {
                    "type": "string",
                    "enum": [t.value for t in MemoryType],
                    "description": "Category of memory. Defaults to 'fact' or 'preference'.",
                },
                "query": {
                    "type": "string",
                    "description": "Search keyword query (for 'search').",
                },
                "memory_id": {
                    "type": "string",
                    "description": "ID of memory record to forget (for 'forget').",
                },
                "user_id": {
                    "type": "string",
                    "description": "User identifier. Defaults to active user.",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    async def execute(self, request: ToolRequest) -> ToolResult:
        """Execute memory operations."""
        action = str(request.arguments.get("action", "")).strip().lower()
        user_id = str(request.arguments.get("user_id", self.default_user_id)).strip() or self.default_user_id

        try:
            if action == "remember":
                content = str(request.arguments.get("content", "")).strip()
                if not content:
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error="Content cannot be empty for 'remember' action.",
                    )

                raw_type = request.arguments.get("memory_type", "fact")
                try:
                    mem_type = MemoryType.from_str(str(raw_type))
                except Exception:
                    mem_type = MemoryType.FACT

                record = self.memory_manager.remember(
                    user_id=user_id,
                    content=content,
                    memory_type=mem_type,
                    source="user_request",
                )
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={
                        "action": "remember",
                        "memory": record.to_dict(),
                        "message": f"Successfully remembered: {record.content}",
                    },
                )

            elif action == "list":
                raw_type = request.arguments.get("memory_type")
                mem_type = MemoryType.from_str(str(raw_type)) if raw_type else None
                records = self.memory_manager.list_memories(
                    user_id=user_id,
                    memory_type=mem_type,
                )
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={
                        "action": "list",
                        "memories": [r.to_dict() for r in records],
                        "count": len(records),
                    },
                )

            elif action == "search":
                query = str(request.arguments.get("query", "")).strip()
                if not query:
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error="Search query cannot be empty.",
                    )
                raw_type = request.arguments.get("memory_type")
                mem_type = MemoryType.from_str(str(raw_type)) if raw_type else None
                records = self.memory_manager.search(
                    user_id=user_id,
                    query=query,
                    memory_type=mem_type,
                )
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={
                        "action": "search",
                        "query": query,
                        "memories": [r.to_dict() for r in records],
                        "count": len(records),
                    },
                )

            elif action == "forget":
                memory_id = str(request.arguments.get("memory_id", "")).strip()
                if not memory_id:
                    # Also check if query or content was provided to find the memory
                    query = str(request.arguments.get("query", "")).strip()
                    if query:
                        matches = self.memory_manager.search(user_id=user_id, query=query, limit=1)
                        if matches:
                            memory_id = matches[0].id
                    if not memory_id:
                        return ToolResult(
                            tool_name=self.name,
                            success=False,
                            error="Memory ID or matching query is required to forget a memory.",
                        )

                deleted = self.memory_manager.forget(memory_id=memory_id, user_id=user_id)
                if deleted:
                    return ToolResult(
                        tool_name=self.name,
                        success=True,
                        output={
                            "action": "forget",
                            "memory_id": memory_id,
                            "message": f"Successfully forgotten memory {memory_id}.",
                        },
                    )
                else:
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error=f"No memory found with ID '{memory_id}' for user '{user_id}'.",
                    )

            else:
                return ToolResult(
                    tool_name=self.name,
                    success=False,
                    error=f"Unsupported memory action '{action}'. Valid actions: remember, list, search, forget.",
                )

        except MemoryPolicyViolationError as pol_err:
            logger.warning("Memory policy violation: %s", pol_err)
            return ToolResult(tool_name=self.name, success=False, error=str(pol_err))
        except MemoryNotFoundError as nf_err:
            return ToolResult(tool_name=self.name, success=False, error=str(nf_err))
        except MemoryError as mem_err:
            logger.error("Memory operation error: %s", mem_err)
            return ToolResult(tool_name=self.name, success=False, error=str(mem_err))
        except Exception as err:
            logger.error("Unexpected memory tool error: %s", err)
            return ToolResult(tool_name=self.name, success=False, error=f"Memory error: {err}")

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        """Parse natural language commands to recognize memory intent."""
        lowered = user_input.lower().strip()

        # 1. Forget triggers
        match_forget = re.search(r"\b(?:forget|delete memory|remove memory)\s+(?:that\s+)?(.+)", lowered)
        if match_forget:
            target = match_forget.group(1).strip(".!?, ")
            # Check if target is UUID / memory_id format
            if re.match(r"^[a-f0-9\-]{8,36}$", target):
                return {"action": "forget", "memory_id": target}
            return {"action": "forget", "query": target}

        # 2. List triggers
        list_triggers = (
            "what do you remember",
            "what do you know about me",
            "show my memories",
            "list memories",
            "show what you remember",
            "view memories",
        )
        if any(trigger in lowered for trigger in list_triggers):
            return {"action": "list"}

        # 3. Search triggers
        match_search = re.search(
            r"\b(?:search memories? for|do you remember anything about|what do you remember about)\s+(.+)",
            lowered,
        )
        if match_search:
            query = match_search.group(1).strip("?.,! ")
            if query not in ("me", "myself"):
                return {"action": "search", "query": query}

        # 4. Remember triggers
        match_remember = re.search(r"\b(?:remember that|please remember that|remember to|remember)\s+(.+)", lowered)
        if match_remember:
            content = match_remember.group(1).strip(".!?, ")
            # Determine likely type
            mem_type = "fact"
            if any(p in content for p in ("i prefer", "my preference", "i like", "i dislike", "i love", "i hate")):
                mem_type = "preference"
            elif any(t in lowered for t in ("remember to", "todo", "task")):
                mem_type = "task"
            elif "my goal is" in content or "i want to achieve" in content:
                mem_type = "goal"
            elif "i usually" in content or "habit" in content:
                mem_type = "habit"

            return {
                "action": "remember",
                "content": content,
                "memory_type": mem_type,
            }

        return None

    def format_result(self, result: ToolResult) -> str:
        """Format memory result into natural companion text."""
        if not result.is_success():
            return f"I couldn't complete the memory operation: {result.error}"

        out = result.output
        if not isinstance(out, dict):
            return result.to_text()

        action = out.get("action")
        if action == "remember":
            mem = out.get("memory", {})
            return f"I've noted that: \"{mem.get('content')}\" (saved as {mem.get('type')})."

        elif action == "list":
            memories = out.get("memories", [])
            if not memories:
                return "I don't have any saved memories for you yet."
            lines = ["Here is what I remember about you:"]
            for m in memories:
                lines.append(f"• [{m.get('type')}] {m.get('content')}")
            return "\n".join(lines)

        elif action == "search":
            memories = out.get("memories", [])
            query = out.get("query", "")
            if not memories:
                return f"I couldn't find any memories matching '{query}'."
            lines = [f"Found {len(memories)} matching memories for '{query}':"]
            for m in memories:
                lines.append(f"• [{m.get('type')}] {m.get('content')}")
            return "\n".join(lines)

        elif action == "forget":
            return "I have removed that memory as requested."

        return result.to_text()
