"""LYRA Computer Tool exposing controlled OS and desktop interaction."""

from typing import Any, TYPE_CHECKING
import re

if TYPE_CHECKING:
    from lyra.computer.controller import ComputerController
    from lyra.computer.policy import ComputerPolicy

from lyra.core.exceptions import (
    ComputerConfirmationRequiredError,
    ComputerDisabledError,
    ComputerEmergencyStopError,
    ComputerError,
    ComputerPolicyViolationError,
    ToolPermissionError,
)
from lyra.models.tools import ToolRequest, ToolResult
from lyra.tools.base import Tool
from lyra.tools.permissions import PermissionPolicy, ToolPermissionLevel


class ComputerTool(Tool):
    """Controlled computer interaction tool for LYRA."""

    def __init__(
        self,
        controller: Any | None = None,
        policy: Any | None = None,
        permission_policy: PermissionPolicy | None = None,
    ) -> None:
        if controller is None:
            from lyra.computer.controller import ComputerController
            controller = ComputerController(policy=policy)
        self.controller: ComputerController = controller
        self.policy: Any = policy or self.controller.policy
        self.permission_policy: PermissionPolicy = permission_policy or PermissionPolicy()

    @property
    def name(self) -> str:
        return "computer"

    @property
    def description(self) -> str:
        return (
            "Safely inspect display, take screenshots, move cursor, click, type text, "
            "press keys, and launch approved desktop applications with explicit user permission."
        )

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "screenshot",
                        "inspect_screen",
                        "move_cursor",
                        "click",
                        "type_text",
                        "press_key",
                        "hotkey",
                        "launch_app",
                        "terminate_app",
                        "emergency_stop",
                    ],
                    "description": "Computer interaction action to execute.",
                },
                "x": {
                    "type": "integer",
                    "description": "X-coordinate on screen (for move_cursor and click).",
                },
                "y": {
                    "type": "integer",
                    "description": "Y-coordinate on screen (for move_cursor and click).",
                },
                "text": {
                    "type": "string",
                    "description": "Text to type or emergency stop reason.",
                },
                "key": {
                    "type": "string",
                    "description": "Single key name to press (e.g. Return, Tab, Escape).",
                },
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of key names for a hotkey combination (e.g. ['ctrl', 's']).",
                },
                "app_name": {
                    "type": "string",
                    "description": "Application name to launch or terminate.",
                },
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle", "double"],
                    "description": "Mouse button to click.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Must be set to true for consequential actions requiring explicit confirmation.",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        """Inspect user query for intent to control computer or capture screen."""
        text = user_input.strip()

        # Emergency stop
        if re.search(r"(?i)\b(emergency stop|kill switch|stop computer|abort control)\b", text):
            return {"action": "emergency_stop", "text": "Emergency stop invoked by user"}

        # Screenshot requests
        if re.search(r"(?i)\b(take|capture|grab|show)\s+(a\s+)?(screenshot|screen\s+capture|screen)\b", text):
            return {"action": "screenshot"}

        # Inspect screen
        if re.search(r"(?i)\b(inspect\s+screen|display\s+resolution|running\s+apps|list\s+apps)\b", text):
            return {"action": "inspect_screen"}

        # Application launch
        app_match = re.search(r"(?i)\b(open|launch|start)\s+(app|application)?\s*([A-Za-z0-9_\-\s]+)\b", text)
        if app_match:
            candidate = app_match.group(3).strip()
            if candidate and not candidate.lower().startswith("website") and not candidate.lower().startswith("http"):
                return {"action": "launch_app", "app_name": candidate}

        return None

    def format_result(self, result: ToolResult) -> str:
        """Format computer action result for conversational display."""
        if not result.success:
            return f"Computer action failed: {result.error}"

        output = result.output if isinstance(result.output, dict) else {}
        action = output.get("action", "")

        if action == "screenshot":
            return f"Captured screenshot to '{output.get('path')}' ({output.get('size_bytes')} bytes)."
        elif action == "inspect_screen":
            dims = output.get("screen_size", {})
            cursor = output.get("cursor_position", {})
            apps = output.get("running_applications", [])
            return (
                f"Screen display: {dims.get('width')}x{dims.get('height')}. "
                f"Cursor: ({cursor.get('x')}, {cursor.get('y')}). "
                f"Running apps: {', '.join(apps) if apps else 'None'}."
            )
        elif action == "move_cursor":
            return f"Moved cursor to ({output.get('x')}, {output.get('y')})."
        elif action == "click":
            pt = output.get("clicked_point", {})
            return f"Clicked {output.get('button', 'left')} button at ({pt.get('x')}, {pt.get('y')})."
        elif action == "type_text":
            return f"Typed {output.get('typed_length')} characters."
        elif action == "press_key":
            return f"Pressed key '{output.get('key')}'."
        elif action == "hotkey":
            return f"Pressed hotkey: {'+'.join(output.get('keys', []))}."
        elif action == "launch_app":
            return f"Application '{output.get('app_name')}' launched successfully."
        elif action == "terminate_app":
            return f"Application '{output.get('app_name')}' terminated successfully."
        elif action == "emergency_stop":
            return "EMERGENCY STOP engaged! Computer control has been locked out."

        return result.to_text()

    async def execute(self, request: ToolRequest) -> ToolResult:
        """Execute computer action within security boundaries and permissions."""
        args = request.arguments
        action_name = args.get("action")
        confirmed = bool(args.get("confirmed", False))
        from lyra.computer.models import (
            ComputerAction,
            ComputerActionType,
            MouseButton,
            Point,
        )

        try:
            action_type = ComputerActionType(action_name)
        except ValueError:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Unrecognized computer action '{action_name}'.",
            )

        # 1. Permission level check using existing permission architecture
        required_level = self.policy.get_permission_level(action_type)
        try:
            self.permission_policy.verify_permission(
                tool_name=self.name,
                level=required_level,
                user_id=request.user_id,
            )
        except ToolPermissionError as perm_err:
            return ToolResult(tool_name=self.name, success=False, error=str(perm_err))

        # 2. Build ComputerAction domain model
        point = None
        if "x" in args and "y" in args:
            point = Point(x=int(args["x"]), y=int(args["y"]))

        button_str = args.get("button", "left")
        try:
            button = MouseButton(button_str)
        except ValueError:
            button = MouseButton.LEFT

        keys = tuple(args.get("keys", ())) if args.get("keys") is not None else None

        action = ComputerAction(
            action_type=action_type,
            point=point,
            text=args.get("text"),
            key=args.get("key"),
            keys=keys,
            app_name=args.get("app_name"),
            button=button,
            confirmed=confirmed,
        )

        # 3. Dispatch to controller
        try:
            result = await self.controller.execute_action(action)
        except ComputerError as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
            )

        if not result.success:
            metadata = dict(result.metadata) if result.metadata else {}
            if result.requires_confirmation:
                metadata["requires_confirmation"] = True
            return ToolResult(
                tool_name=self.name,
                success=False,
                output=result.output,
                error=result.error,
                metadata=metadata,
            )

        # Append action type to output dictionary if dict
        output_payload = result.output
        if isinstance(output_payload, dict):
            output_payload["action"] = action_name

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=output_payload,
            metadata=result.metadata,
        )
