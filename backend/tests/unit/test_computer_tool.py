"""Unit tests for ComputerTool integration with LYRA tool system, executor, and permissions."""

import asyncio
from pathlib import Path
import pytest

from lyra.computer.controller import ComputerController
from lyra.computer.policy import ComputerPolicy
from lyra.models.tools import ToolRequest, ToolResult
from lyra.tools.computer_tool import ComputerTool
from lyra.tools.executor import ToolExecutor
from lyra.tools.permissions import PermissionPolicy, ToolPermissionLevel
from lyra.tools.registry import ToolRegistry


def test_computer_tool_metadata():
    tool = ComputerTool()
    assert tool.name == "computer"
    assert "screen" in tool.description.lower() or "display" in tool.description.lower()
    assert tool.permission_level == ToolPermissionLevel.READ_ONLY

    schema = tool.input_schema
    assert schema["type"] == "object"
    assert "action" in schema["required"]
    actions = schema["properties"]["action"]["enum"]
    assert "screenshot" in actions
    assert "click" in actions
    assert "type_text" in actions
    assert "emergency_stop" in actions


def test_computer_tool_can_handle():
    tool = ComputerTool()

    # Emergency stop
    res_estop = tool.can_handle("Emergency stop computer control")
    assert res_estop is not None
    assert res_estop["action"] == "emergency_stop"

    res_kill = tool.can_handle("trigger kill switch")
    assert res_kill is not None
    assert res_kill["action"] == "emergency_stop"

    # Screenshot
    res_shot = tool.can_handle("Take a screenshot please")
    assert res_shot is not None
    assert res_shot["action"] == "screenshot"

    # Inspect
    res_insp = tool.can_handle("Inspect screen display resolution")
    assert res_insp is not None
    assert res_insp["action"] == "inspect_screen"

    # App launch
    res_app = tool.can_handle("Open application Calculator")
    assert res_app is not None
    assert res_app["action"] == "launch_app"
    assert "Calculator" in res_app["app_name"]

    # Unrelated queries
    assert tool.can_handle("What is 2 + 2?") is None
    assert tool.can_handle("Tell me a story.") is None


def test_computer_tool_execution_flow(tmp_path: Path):
    async def _test():
        controller = ComputerController(
            enabled=True,
            screenshot_dir=tmp_path / "screenshots",
        )
        permission_policy = PermissionPolicy(allowed_levels=[
            ToolPermissionLevel.READ_ONLY,
            ToolPermissionLevel.LOW_RISK,
            ToolPermissionLevel.CONFIRMATION_REQUIRED,
        ])
        tool = ComputerTool(controller=controller, permission_policy=permission_policy)

        # 1. Screenshot (READ_ONLY permission)
        req_shot = ToolRequest(
            tool_name="computer",
            arguments={"action": "screenshot"},
        )
        res_shot = await tool.execute(req_shot)
        assert res_shot.success
        assert "screenshot_" in res_shot.output["path"]

        # 2. Move cursor (LOW_RISK permission)
        req_move = ToolRequest(
            tool_name="computer",
            arguments={"action": "move_cursor", "x": 100, "y": 200},
        )
        res_move = await tool.execute(req_move)
        assert res_move.success
        assert res_move.output["x"] == 100 and res_move.output["y"] == 200

        # 3. Click without confirmation (CONFIRMATION_REQUIRED)
        req_click_unconf = ToolRequest(
            tool_name="computer",
            arguments={"action": "click", "x": 100, "y": 200, "confirmed": False},
        )
        res_click_unconf = await tool.execute(req_click_unconf)
        assert not res_click_unconf.success
        assert res_click_unconf.metadata.get("requires_confirmation") is True

        # 4. Click with confirmed=True succeeds
        req_click_conf = ToolRequest(
            tool_name="computer",
            arguments={"action": "click", "x": 100, "y": 200, "confirmed": True},
        )
        res_click_conf = await tool.execute(req_click_conf)
        assert res_click_conf.success
        assert res_click_conf.output["clicked_point"] == {"x": 100, "y": 200}

        # 5. Emergency stop action locks controller
        req_estop = ToolRequest(
            tool_name="computer",
            arguments={"action": "emergency_stop", "text": "Panic button"},
        )
        res_estop = await tool.execute(req_estop)
        assert res_estop.success
        assert controller.emergency_stop.is_stopped

        # Subsequent actions blocked
        res_blocked = await tool.execute(req_shot)
        assert not res_blocked.success
        assert "Emergency stop is active" in res_blocked.error

    asyncio.run(_test())


def test_computer_tool_executor_permission_enforcement():
    async def _test():
        controller = ComputerController(enabled=True)
        # Policy permits only READ_ONLY
        strict_policy = PermissionPolicy(allowed_levels=[ToolPermissionLevel.READ_ONLY])

        tool = ComputerTool(controller=controller, permission_policy=strict_policy)
        registry = ToolRegistry(tools=[tool])
        executor = ToolExecutor(registry=registry, policy=strict_policy)

        # READ_ONLY action (inspect_screen) succeeds
        req_inspect = ToolRequest(
            tool_name="computer",
            arguments={"action": "inspect_screen"},
        )
        res_inspect = await executor.execute(req_inspect)
        assert res_inspect.success

        # CONFIRMATION_REQUIRED action (click) fails permission check
        req_click = ToolRequest(
            tool_name="computer",
            arguments={"action": "click", "x": 50, "y": 50, "confirmed": True},
        )
        res_click = await executor.execute(req_click)
        assert not res_click.success
        assert "Permission denied" in res_click.error

    asyncio.run(_test())


def test_computer_tool_format_result():
    tool = ComputerTool()

    # Success screenshot
    res_shot = ToolResult(
        tool_name="computer",
        success=True,
        output={"action": "screenshot", "path": "/path/to/shot.png", "size_bytes": 1024},
    )
    formatted = tool.format_result(res_shot)
    assert "/path/to/shot.png" in formatted
    assert "1024" in formatted

    # Emergency stop
    res_estop = ToolResult(
        tool_name="computer",
        success=True,
        output={"action": "emergency_stop"},
    )
    assert "EMERGENCY STOP engaged" in tool.format_result(res_estop)

    # Failure
    res_fail = ToolResult(
        tool_name="computer",
        success=False,
        error="Permission denied",
    )
    assert "Computer action failed: Permission denied" in tool.format_result(res_fail)
