"""Dedicated macOS Notes Tool for LYRA.

Provides reliable natural-language control and real-world execution
for Apple Notes: opening Notes, creating notes, writing text, and verifying content.
"""

import logging
import re
import sys
from typing import Any, Optional

from lyra.computer.notes import NotesController
from lyra.models.tools import ToolRequest, ToolResult
from lyra.tools.base import Tool
from lyra.tools.permissions import ToolPermissionLevel

logger = logging.getLogger("tools.notes")


class NotesTool(Tool):
    """Tool for controlling real macOS Apple Notes application."""

    def __init__(self, controller: Optional[NotesController] = None) -> None:
        if controller is None:
            use_mock = "pytest" in sys.modules or sys.platform != "darwin"
            controller = NotesController(use_mock=use_mock)
        self.controller = controller

    @property
    def name(self) -> str:
        return "notes"

    @property
    def description(self) -> str:
        return (
            "Control the real macOS Notes application: open Notes, create notes, "
            "write text into notes, and verify that note content was successfully recorded."
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
                    "enum": [
                        "open_notes",
                        "write_note",
                        "create_note",
                        "read_notes",
                        "verify_note",
                    ],
                    "description": "Notes operation to perform.",
                },
                "text": {
                    "type": "string",
                    "description": "Content or message to write into the note.",
                },
                "title": {
                    "type": "string",
                    "description": "Optional title for the note.",
                },
                "folder": {
                    "type": "string",
                    "description": "Optional target folder inside Notes.",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        """Parse natural language commands targeting Apple Notes."""
        text = user_input.strip()
        cleaned = re.sub(r"(?i)^(?:hey|hi|hello|ok|okay)?\s*lyra[,:\s]*", "", text).strip()
        cleaned = re.sub(r"(?i)^(?:can|could|would)\s+you(?:\s+please)?\s+", "", cleaned)
        cleaned = re.sub(r"(?i)^please\s+", "", cleaned)
        lowered = cleaned.lower()

        # 1. "Open Notes and write <text>" or "Open Notes, write <text>"
        m_open_write = re.search(
            r"(?i)^open\s+(?:the\s+)?notes(?:\s+app(?:lication)?)?(?:,\s*|\s+and\s+)(?:write|type)\s+['\"]?(.+?)['\"]?$",
            cleaned,
        )
        if m_open_write:
            content = m_open_write.group(1).strip()
            return {"action": "write_note", "text": content}

        # 2. "Create a note called <title> and write <text>"
        m_create_named_write = re.search(
            r"(?i)^create\s+(?:a\s+)?note\s+(?:called|named)\s+['\"]?([a-zA-Z0-9_\- ]+?)['\"]?\s+and\s+write\s+['\"]?(.+?)['\"]?$",
            cleaned,
        )
        if m_create_named_write:
            title = m_create_named_write.group(1).strip()
            content = m_create_named_write.group(2).strip()
            return {"action": "write_note", "title": title, "text": content}

        # 3. "Create a new note and write <text>"
        m_create_new_write = re.search(
            r"(?i)^(?:create|make)\s+(?:a\s+)?(?:new\s+)?note\s+(?:and\s+)?(?:write|type)\s+['\"]?(.+?)['\"]?$",
            cleaned,
        )
        if m_create_new_write:
            content = m_create_new_write.group(1).strip()
            return {"action": "write_note", "text": content}

        # 4. "Write this in Notes: <text>" or "Write <text> in Notes"
        m_write_in_notes1 = re.search(
            r"(?i)^write\s+(?:this\s+)?in\s+(?:my\s+)?notes\s*[:,-]?\s*['\"]?(.+?)['\"]?$",
            cleaned,
        )
        if m_write_in_notes1:
            content = m_write_in_notes1.group(1).strip()
            return {"action": "write_note", "text": content}

        m_write_in_notes2 = re.search(
            r"(?i)^write\s+['\"]?(.+?)['\"]?\s+in\s+(?:my\s+)?notes(?:\s+app)?$",
            cleaned,
        )
        if m_write_in_notes2:
            content = m_write_in_notes2.group(1).strip()
            return {"action": "write_note", "text": content}

        # 5. "Create a note called <title>"
        m_create_named = re.search(
            r"(?i)^(?:create|make)\s+(?:a\s+)?note\s+(?:called|named)\s+['\"]?([a-zA-Z0-9_\- ]+?)['\"]?$",
            cleaned,
        )
        if m_create_named:
            title = m_create_named.group(1).strip()
            return {"action": "create_note", "title": title, "text": ""}

        # 6. "Open Notes" / "Open my Notes"
        if re.search(r"(?i)^open\s+(?:my\s+)?notes(?:\s+app)?(?:\\.|$)", cleaned):
            return {"action": "open_notes"}

        return None

    def format_result(self, result: ToolResult) -> str:
        """Format the result of a Notes action into concise natural language."""
        if not result.success:
            if "couldn't type" in str(result.error) or "couldn't write" in str(result.error):
                return str(result.error)
            return f"Notes action failed: {result.error}"

        out = result.output if isinstance(result.output, dict) else {}
        action = out.get("action", "")

        if action in ("write_note", "create_note"):
            text = out.get("text", "")
            title = out.get("title", "")
            if text:
                return f"Done, I wrote '{text}' in Notes."
            elif title:
                return f"Done, I created a note called '{title}'."
            return "Done, I updated Notes."

        elif action == "open_notes":
            return "Done, Notes is open."

        return result.to_text()

    async def execute(self, request: ToolRequest) -> ToolResult:
        """Execute the requested Notes operation."""
        args = request.arguments
        action = args.get("action", "open_notes")

        if action == "open_notes":
            res = self.controller.open_notes()
            return ToolResult(
                tool_name=self.name,
                success=res.get("success", True),
                output=res,
                error=res.get("error"),
            )

        elif action in ("write_note", "create_note"):
            text = args.get("text", "")
            title = args.get("title")
            folder = args.get("folder")
            res = self.controller.create_note(body_text=text, title=title, folder=folder)

            success = res.get("success", False)
            error_msg = res.get("error") if not success else None

            return ToolResult(
                tool_name=self.name,
                success=success,
                output=res,
                error=error_msg,
            )

        elif action == "read_notes":
            res = self.controller.get_front_note_content()
            return ToolResult(
                tool_name=self.name,
                success=res.get("success", False),
                output=res,
                error=res.get("error"),
            )

        elif action == "verify_note":
            expected = args.get("text", "")
            verified = self.controller.verify_note_content(expected)
            return ToolResult(
                tool_name=self.name,
                success=verified,
                output={"verified": verified, "expected": expected},
                error=None if verified else f"Expected text '{expected}' not found in front note",
            )

        return ToolResult(
            tool_name=self.name,
            success=False,
            error=f"Unrecognized notes action '{action}'",
        )
