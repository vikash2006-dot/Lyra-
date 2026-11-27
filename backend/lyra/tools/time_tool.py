"""Local TimeTool implementation for LYRA."""

import re
from datetime import datetime, timezone
import time
from typing import Any, Callable

from lyra.models.tools import ToolRequest, ToolResult
from lyra.tools.base import Tool
from lyra.tools.permissions import ToolPermissionLevel


class TimeTool(Tool):
    """Tool that inspects local system time and returns formatted date and time."""

    def __init__(
        self,
        clock_fn: Callable[[], datetime] | None = None,
    ) -> None:
        # clock_fn allows deterministic injection during unit testing
        self._clock_fn = clock_fn or (lambda: datetime.now().astimezone())

    @property
    def name(self) -> str:
        return "time"

    @property
    def description(self) -> str:
        return "Get the current local system date, time, and timezone."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["12h", "24h", "iso"],
                    "description": "Formatting style for time string ('12h', '24h', or 'iso').",
                }
            },
            "additionalProperties": False,
        }

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        """Check if user query is asking for date, time, or timezone."""
        lowered = user_input.lower().strip()
        # Whole-word matching only: "timer", "update", "sometimes" or "validate" are not time questions.
        if re.search(r"\btimer?s?\b.*\b(?:code|example|script|function|python|app|program|countdown)\b"
                     r"|\b(?:pomodoro|stopwatch|countdown)\b", lowered):
            return None
        time_patterns = (
            r"\bwhat(?:'s| is)? (?:the )?(?:current )?time\b",
            r"\bwhat time\b",
            r"\bcurrent time\b",
            r"\btime (?:is it|now|right now)\b",
            r"\btell me the time\b",
            r"\b(?:give|show) me (?:the )?time\b",
            r"\btime in (?:iso|24|12)",
            r"\b(?:today'?s|the|current) date\b",
            r"\bwhat(?:'s| is)? (?:the )?date\b",
            r"\bdate today\b",
            r"\bwhat day (?:is it|is today|of the week)\b",
            r"\bwhat(?:'s| is) the day\b",
            r"\b(?:my |the )?timezone\b",
            r"\bclock\b",
            r"^time\??$",
        )
        time_triggers = [p for p in time_patterns if re.search(p, lowered)]
        if time_triggers:
            fmt = "24h" if ("24" in lowered or "military" in lowered) else "12h"
            if "iso" in lowered:
                fmt = "iso"
            return {"format": fmt}
        return None

    def format_result(self, result: ToolResult) -> str:
        """Format a ToolResult for friendly companion display."""
        if not result.is_success():
            return f"I couldn't retrieve the time: {result.error}"
        output = result.output
        if isinstance(output, dict):
            readable = output.get("readable_time", "")
            date_str = output.get("date", "")
            if readable and date_str:
                return f"The current time is {readable} on {date_str}."
            if readable:
                return f"The current time is {readable}."
        return result.to_text()

    async def execute(self, request: ToolRequest) -> ToolResult:
        """Return the current local system time in structured format."""
        now = self._clock_fn()
        fmt = request.arguments.get("format", "12h")

        # 12-hour format without leading zero on hour where possible
        time_12h = now.strftime("%I:%M %p").lstrip("0")
        time_24h = now.strftime("%H:%M:%S")
        date_str = now.strftime("%A, %B %d, %Y")
        tz_name = now.tzname() or time.tzname[0]

        if fmt == "24h":
            readable_time = f"{time_24h} {tz_name}"
        elif fmt == "iso":
            readable_time = now.isoformat()
        else:
            readable_time = f"{time_12h} {tz_name}"

        structured_output = {
            "readable_time": readable_time,
            "iso": now.isoformat(),
            "date": date_str,
            "time_12h": time_12h,
            "time_24h": time_24h,
            "timezone": tz_name,
            "timestamp": now.timestamp(),
        }

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=structured_output,
            metadata={"source": "system_clock"},
        )
