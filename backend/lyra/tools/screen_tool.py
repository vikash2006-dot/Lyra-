"""Screen tool: LYRA's visual capabilities exposed through the standard tool executor.

Each visual step (observe, click, type, press, scroll, verify) runs through ToolExecutor so it is
validated, permission-checked, timed out and shown live in task tracking like every other tool.
"""

from __future__ import annotations

from typing import Any

from lyra.models.tools import ToolRequest, ToolResult
from lyra.tools.base import Tool
from lyra.tools.permissions import ToolPermissionLevel


class ScreenTool(Tool):
    timeout_seconds = 120.0

    def __init__(self, awareness: Any) -> None:
        self.awareness = awareness

    @property
    def name(self) -> str:
        return "screen"

    @property
    def description(self) -> str:
        return "See and understand the user's screen (capture, OCR, UI elements, vision) and act on it visually."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.LOW_RISK

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["observe", "click", "type", "press", "scroll", "verify"]},
                "question": {"type": "string"},
                "target": {"type": "string"},
                "element_id": {"type": "string"},
                "text": {"type": "string"},
                "key": {"type": "string"},
                "direction": {"type": "string"},
                "expected": {"type": "string"},
                "confirmed": {"type": "boolean"},
                "sensitive": {"type": "boolean"},
                "use_ai": {"type": "boolean"},
                "target_window": {"type": "string"},
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        return None  # routed by the visual agent, which understands context

    def format_result(self, result: ToolResult) -> str:
        if not result.success:
            return result.error or "The screen action failed."
        out = result.output or {}
        if out.get("action") == "observe":
            return out.get("answer") or out.get("summary") or "I've looked at your screen."
        if out.get("action") == "verify":
            return "Verified." if out.get("verified") else "I couldn't confirm the expected result on screen."
        return f"Done: {out.get('action')} {out.get('target') or ''}".strip()

    async def execute(self, request: ToolRequest) -> ToolResult:
        from lyra.vision.capture import ScreenCaptureError, ScreenPermissionError
        from lyra.vision.service import VisualActionError

        args = request.arguments
        action = args.get("action")
        sid = request.session_id
        try:
            if action == "observe":
                ctx = await self.awareness.observe(
                    sid, question=args.get("question"), use_ai=args.get("use_ai", True),
                    target=args.get("target_window") or "screen",
                )
                data = ctx.to_dict()
                return ToolResult(tool_name=self.name, success=True,
                                  output={"action": "observe", **data, "elements": data["elements"][:40],
                                          "visible_text": data["visible_text"][:4000]})
            if action == "verify":
                out = await self.awareness.verify(str(args.get("expected") or ""), sid, use_ai=args.get("use_ai", True))
                return ToolResult(tool_name=self.name, success=out.get("verified") is not False,
                                  output={"action": "verify", **out},
                                  error=None if out.get("verified") is not False else f"Not verified: {out.get('evidence')}")
            out = await self.awareness.perform(dict(args), sid, confirmed=bool(args.get("confirmed")))
            if out.get("requires_confirmation"):
                return ToolResult(tool_name=self.name, success=False, output=out,
                                  error=f"Confirmation required before '{action}' on '{out.get('target')}'.",
                                  metadata={"requires_confirmation": True})
            return ToolResult(tool_name=self.name, success=True, output=out)
        except ScreenPermissionError as err:
            return ToolResult(tool_name=self.name, success=False, error=str(err), metadata={"permission": "screen"})
        except (ScreenCaptureError, VisualActionError) as err:
            return ToolResult(tool_name=self.name, success=False, error=str(err))
