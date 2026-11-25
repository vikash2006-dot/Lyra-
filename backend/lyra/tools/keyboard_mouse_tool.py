"""Keyboard and Mouse action tools for LYRA.

Safely handles keyboard typing/shortcuts and mouse movements/clicks via System Controllers.
"""

import logging
from typing import Any, Optional

from lyra.computer.controllers import KeyboardController, MouseController
from lyra.computer.models import MouseButton, Point
from lyra.computer.system import SystemKeyboardController, SystemMouseController
from lyra.models.tools import ToolRequest, ToolResult
from lyra.tools.base import Tool
from lyra.tools.permissions import ToolPermissionLevel

logger = logging.getLogger("tools.keyboard_mouse")


class KeyboardTool(Tool):
    """Safely executes keyboard actions (type, press, hotkey)."""

    def __init__(self, controller: Optional[KeyboardController] = None) -> None:
        self.controller = controller or SystemKeyboardController()

    @property
    def name(self) -> str:
        return "keyboard"

    @property
    def description(self) -> str:
        return "Safely execute keyboard actions (type text, press key, keyboard shortcuts)."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.LOW_RISK

    @property
    def requires_network(self) -> bool:
        return False

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["type", "press", "hotkey"]},
                "text": {"type": "string", "description": "Text to type"},
                "key": {"type": "string", "description": "Single key name (e.g. 'enter', 'escape')"},
                "keys": {"type": "array", "items": {"type": "string"}, "description": "Key combinations for hotkey"},
            },
            "required": ["action"],
        }

    def format_result(self, result: ToolResult) -> str:
        if not result.success:
            return f"Keyboard action failed: {result.error}"
        data = result.output if isinstance(result.output, dict) else {}
        action = data.get("action", "")
        if action == "type":
            return f"Typed text: {data.get('text', '')}"
        elif action == "press":
            return f"Pressed {data.get('key', '')}."
        elif action == "hotkey":
            return f"Pressed shortcut: {' + '.join(data.get('keys', []))}."
        return "Keyboard action executed."

    async def execute(self, request: ToolRequest) -> ToolResult:
        args = request.arguments
        action_name = args.get("action", "")
        if not action_name and "." in request.tool_name:
            action_name = request.tool_name.split(".", 1)[1]

        if action_name == "type":
            text = args.get("text", "")
            await self.controller.type_text(text)
            return ToolResult(tool_name=self.name, success=True, output={"action": "type", "text": text})
        elif action_name == "press":
            key = args.get("key", "")
            await self.controller.press_key(key)
            return ToolResult(tool_name=self.name, success=True, output={"action": "press", "key": key})
        elif action_name == "hotkey":
            keys = args.get("keys", [])
            if isinstance(keys, str):
                keys = [keys]
            await self.controller.hotkey(*keys)
            return ToolResult(tool_name=self.name, success=True, output={"action": "hotkey", "keys": keys})

        return ToolResult(tool_name=self.name, success=False, error=f"Unknown keyboard action: '{action_name}'.")


class MouseTool(Tool):
    """Safely executes mouse actions (move, click, double_click, scroll)."""

    def __init__(self, controller: Optional[MouseController] = None) -> None:
        self.controller = controller or SystemMouseController()

    @property
    def name(self) -> str:
        return "mouse"

    @property
    def description(self) -> str:
        return "Safely execute mouse movements, clicks, and scrolling."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.LOW_RISK

    @property
    def requires_network(self) -> bool:
        return False

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["move", "click", "double_click", "scroll"]},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
            },
            "required": ["action"],
        }

    def format_result(self, result: ToolResult) -> str:
        if not result.success:
            return f"Mouse action failed: {result.error}"
        data = result.output if isinstance(result.output, dict) else {}
        action = data.get("action", "")
        if action == "click":
            return f"Clicked mouse at ({data.get('x')}, {data.get('y')})."
        elif action == "move":
            return f"Moved cursor to ({data.get('x')}, {data.get('y')})."
        return "Mouse action executed."

    async def execute(self, request: ToolRequest) -> ToolResult:
        args = request.arguments
        action_name = args.get("action", "")
        if not action_name and "." in request.tool_name:
            action_name = request.tool_name.split(".", 1)[1]

        btn_str = args.get("button", "left").lower()
        btn = MouseButton.RIGHT if btn_str == "right" else MouseButton.LEFT

        if action_name == "move":
            pt = Point(int(args.get("x", 0)), int(args.get("y", 0)))
            await self.controller.move(pt)
            return ToolResult(tool_name=self.name, success=True, output={"action": "move", "x": pt.x, "y": pt.y})

        elif action_name == "click":
            pt = Point(int(args.get("x", 0)), int(args.get("y", 0))) if "x" in args and "y" in args else None
            await self.controller.click(point=pt, button=btn, clicks=1)
            pos = await self.controller.get_position()
            return ToolResult(tool_name=self.name, success=True, output={"action": "click", "x": pos.x, "y": pos.y})

        elif action_name == "double_click":
            pt = Point(int(args.get("x", 0)), int(args.get("y", 0))) if "x" in args and "y" in args else None
            await self.controller.click(point=pt, button=btn, clicks=2)
            pos = await self.controller.get_position()
            return ToolResult(tool_name=self.name, success=True, output={"action": "double_click", "x": pos.x, "y": pos.y})

        return ToolResult(tool_name=self.name, success=False, error=f"Unknown mouse action: '{action_name}'.")
