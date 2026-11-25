"""Unit tests for LYRA ToolExecutor."""

import asyncio

from lyra.core.exceptions import ToolError
from lyra.models.tools import ToolRequest, ToolResult
from lyra.tools.base import Tool
from lyra.tools.executor import ToolExecutor
from lyra.tools.permissions import PermissionPolicy, ToolPermissionLevel
from lyra.tools.registry import ToolRegistry


class EchoTool(Tool):
    """Simple echo tool for executor testing."""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echoes back input message."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
            "additionalProperties": False,
        }

    async def execute(self, request: ToolRequest) -> ToolResult:
        return ToolResult(tool_name=self.name, success=True, output=request.arguments["msg"])


class SlowTool(Tool):
    """Tool that sleeps longer than executor timeout."""

    @property
    def name(self) -> str:
        return "slow"

    @property
    def description(self) -> str:
        return "Takes a long time."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict:
        return {"type": "object"}

    async def execute(self, request: ToolRequest) -> ToolResult:
        await asyncio.sleep(0.5)
        return ToolResult(tool_name=self.name, success=True, output="done")


class RiskyTool(Tool):
    """High risk tool requiring special permissions."""

    @property
    def name(self) -> str:
        return "risky"

    @property
    def description(self) -> str:
        return "High risk tool."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.HIGH_RISK

    @property
    def input_schema(self) -> dict:
        return {"type": "object"}

    async def execute(self, request: ToolRequest) -> ToolResult:
        return ToolResult(tool_name=self.name, success=True, output="risky executed")


class FaultyTool(Tool):
    """Tool that raises an exception during execution."""

    @property
    def name(self) -> str:
        return "faulty"

    @property
    def description(self) -> str:
        return "Fails during run."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict:
        return {"type": "object"}

    async def execute(self, request: ToolRequest) -> ToolResult:
        raise RuntimeError("Disk corrupted")


def test_executor_successful_execution():
    """Verify ToolExecutor runs registered tool and returns structured result."""
    registry = ToolRegistry(tools=[EchoTool()])
    executor = ToolExecutor(registry=registry)

    req = ToolRequest(tool_name="echo", arguments={"msg": "Hello LYRA"})
    res = asyncio.run(executor.execute(req))

    assert res.success is True
    assert res.output == "Hello LYRA"
    assert res.error is None

    # Test sync helper
    res_sync = executor.execute_sync(req)
    assert res_sync.success is True
    assert res_sync.output == "Hello LYRA"


def test_executor_unknown_tool():
    """Verify ToolExecutor handles unregistered tool gracefully."""
    registry = ToolRegistry()
    executor = ToolExecutor(registry=registry)

    req = ToolRequest(tool_name="missing_tool")
    res = asyncio.run(executor.execute(req))

    assert res.success is False
    assert "not registered" in res.error


def test_executor_permission_denial():
    """Verify ToolExecutor rejects tool exceeding allowed permission policy."""
    registry = ToolRegistry(tools=[RiskyTool()])
    # Default policy only permits READ_ONLY and LOW_RISK
    executor = ToolExecutor(registry=registry)

    req = ToolRequest(tool_name="risky")
    res = asyncio.run(executor.execute(req))

    assert res.success is False
    assert "Permission denied" in res.error


def test_executor_validation_failure():
    """Verify ToolExecutor rejects invalid arguments before running tool."""
    registry = ToolRegistry(tools=[EchoTool()])
    executor = ToolExecutor(registry=registry)

    # Missing required argument 'msg'
    req = ToolRequest(tool_name="echo", arguments={})
    res = asyncio.run(executor.execute(req))

    assert res.success is False
    assert "Missing required argument" in res.error

    # Unexpected argument
    req_bad_arg = ToolRequest(tool_name="echo", arguments={"msg": "hi", "extra": 1})
    res_bad_arg = asyncio.run(executor.execute(req_bad_arg))

    assert res_bad_arg.success is False
    assert "Unexpected argument" in res_bad_arg.error


def test_executor_timeout_enforcement():
    """Verify ToolExecutor enforces execution timeout limit."""
    registry = ToolRegistry(tools=[SlowTool()])
    executor = ToolExecutor(registry=registry, timeout_seconds=0.05)

    req = ToolRequest(tool_name="slow")
    res = asyncio.run(executor.execute(req))

    assert res.success is False
    assert "timed out" in res.error


def test_executor_recursion_limit():
    """Verify ToolExecutor enforces loop prevention limit."""
    registry = ToolRegistry(tools=[EchoTool()])
    executor = ToolExecutor(registry=registry, max_executions_per_turn=3)

    req = ToolRequest(tool_name="echo", arguments={"msg": "test"})

    # Under limit
    res_ok = asyncio.run(executor.execute(req, execution_count=2))
    assert res_ok.success is True

    # At or above limit
    res_blocked = asyncio.run(executor.execute(req, execution_count=3))
    assert res_blocked.success is False
    assert "Tool execution limit (3) exceeded" in res_blocked.error


def test_executor_tool_exception():
    """Verify ToolExecutor safely catches tool execution errors."""
    registry = ToolRegistry(tools=[FaultyTool()])
    executor = ToolExecutor(registry=registry)

    req = ToolRequest(tool_name="faulty")
    res = asyncio.run(executor.execute(req))

    assert res.success is False
    assert "Disk corrupted" in res.error
