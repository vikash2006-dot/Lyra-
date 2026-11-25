"""Unit tests for LYRA TimeTool."""

import asyncio
from datetime import datetime, timezone

from lyra.models.tools import ToolRequest, ToolResult
from lyra.tools.permissions import ToolPermissionLevel
from lyra.tools.time_tool import TimeTool


def test_time_tool_metadata():
    """Verify TimeTool properties, description, permissions, and schema."""
    tool = TimeTool()
    assert tool.name == "time"
    assert "date" in tool.description.lower() or "time" in tool.description.lower()
    assert tool.permission_level == ToolPermissionLevel.READ_ONLY
    assert tool.input_schema["type"] == "object"
    assert "format" in tool.input_schema["properties"]
    assert tool.input_schema["properties"]["format"]["enum"] == ["12h", "24h", "iso"]


def test_time_tool_execution_deterministic():
    """Verify TimeTool execution output with an injected deterministic clock."""
    fixed_time = datetime(2026, 9, 12, 14, 30, 45, tzinfo=timezone.utc)
    tool = TimeTool(clock_fn=lambda: fixed_time)

    # 1. Default 12h format
    req_12h = ToolRequest(tool_name="time", arguments={})
    res_12h = asyncio.run(tool.execute(req_12h))

    assert res_12h.success is True
    assert res_12h.tool_name == "time"
    assert isinstance(res_12h.output, dict)
    assert res_12h.output["time_12h"] == "2:30 PM"
    assert "2:30 PM" in res_12h.output["readable_time"]
    assert res_12h.output["date"] == "Saturday, September 12, 2026"
    assert res_12h.output["timezone"] == "UTC"
    assert res_12h.output["iso"] == "2026-09-12T14:30:45+00:00"

    # 2. 24h format
    req_24h = ToolRequest(tool_name="time", arguments={"format": "24h"})
    res_24h = asyncio.run(tool.execute(req_24h))
    assert res_24h.success is True
    assert "14:30:45" in res_24h.output["readable_time"]

    # 3. ISO format
    req_iso = ToolRequest(tool_name="time", arguments={"format": "iso"})
    res_iso = asyncio.run(tool.execute(req_iso))
    assert res_iso.success is True
    assert res_iso.output["readable_time"] == "2026-09-12T14:30:45+00:00"

    # 4. Synchronous execution helper
    res_sync = tool.execute_sync(req_12h)
    assert res_sync.success is True
    assert res_sync.output["time_12h"] == "2:30 PM"


def test_time_tool_can_handle():
    """Verify TimeTool intent detection for various query phrasings."""
    tool = TimeTool()

    assert tool.can_handle("what time is it?") == {"format": "12h"}
    assert tool.can_handle("What is the current time?") == {"format": "12h"}
    assert tool.can_handle("Tell me today's date please") == {"format": "12h"}
    assert tool.can_handle("What time is it in 24 hour format?") == {"format": "24h"}
    assert tool.can_handle("Give me time in iso format") == {"format": "iso"}

    # Irrelevant queries
    assert tool.can_handle("Who wrote Hamlet?") is None
    assert tool.can_handle("Hello LYRA, how are you?") is None


def test_time_tool_format_result():
    """Verify format_result provides friendly conversational output."""
    fixed_time = datetime(2026, 9, 12, 14, 30, 45, tzinfo=timezone.utc)
    tool = TimeTool(clock_fn=lambda: fixed_time)

    req = ToolRequest(tool_name="time", arguments={})
    res = tool.execute_sync(req)
    formatted = tool.format_result(res)

    assert "The current time is" in formatted
    assert "2:30 PM" in formatted
    assert "Saturday, September 12, 2026" in formatted

    # Failure format
    err_res = ToolResult(tool_name="time", success=False, error="Clock fault")
    assert "couldn't retrieve the time" in tool.format_result(err_res)
