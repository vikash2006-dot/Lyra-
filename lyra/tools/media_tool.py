"""Media control tool for LYRA.

Controls media playback across running media players and active web browsers.
"""

import logging
from typing import Any, Optional

from lyra.computer.media import MediaController
from lyra.models.tools import ToolRequest, ToolResult
from lyra.tools.base import Tool
from lyra.tools.permissions import ToolPermissionLevel

logger = logging.getLogger("tools.media")


class MediaTool(Tool):
    """Media tool controlling playback on running players and browsers."""

    def __init__(self, controller: Optional[MediaController] = None) -> None:
        self.controller = controller or MediaController()

    @property
    def name(self) -> str:
        return "media"

    @property
    def description(self) -> str:
        return "Control media playback (play, pause, resume, next, previous, stop)."

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
                "action": {
                    "type": "string",
                    "enum": ["play", "pause", "resume", "next", "previous", "stop"],
                },
            },
            "required": ["action"],
        }

    def format_result(self, result: ToolResult) -> str:
        if not result.success:
            return f"Media action failed: {result.error}"
        data = result.output if isinstance(result.output, dict) else {}
        action = data.get("action", "")
        if action == "pause":
            return "Paused playback."
        elif action in ("play", "resume"):
            return "Resumed playback."
        elif action == "next":
            return "Skipped to next track."
        elif action == "previous":
            return "Returned to previous track."
        elif action == "stop":
            return "Stopped playback."
        return "Playback updated."

    async def execute(self, request: ToolRequest) -> ToolResult:
        args = request.arguments
        action_name = args.get("action", "")
        if not action_name and "." in request.tool_name:
            action_name = request.tool_name.split(".", 1)[1]

        if action_name == "play":
            res = self.controller.play()
            return ToolResult(tool_name=self.name, success=True, output={"action": "play", **res})
        elif action_name == "pause":
            res = self.controller.pause()
            return ToolResult(tool_name=self.name, success=True, output={"action": "pause", **res})
        elif action_name == "resume":
            res = self.controller.resume()
            return ToolResult(tool_name=self.name, success=True, output={"action": "resume", **res})
        elif action_name == "next":
            res = self.controller.next_track()
            return ToolResult(tool_name=self.name, success=True, output={"action": "next", **res})
        elif action_name == "previous":
            res = self.controller.previous_track()
            return ToolResult(tool_name=self.name, success=True, output={"action": "previous", **res})
        elif action_name == "stop":
            res = self.controller.stop()
            return ToolResult(tool_name=self.name, success=True, output={"action": "stop", **res})

        return ToolResult(tool_name=self.name, success=False, error=f"Unknown media action: '{action_name}'.")
