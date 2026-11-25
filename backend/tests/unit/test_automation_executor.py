"""Unit tests for AutomationExecutor (tool execution, permissions, and bounded retries)."""

import asyncio
from datetime import datetime, timedelta, timezone
import pytest

from lyra.automation.executor import AutomationExecutor
from lyra.automation.sqlite_store import SQLiteAutomationStore
from lyra.models.automation import (
    Automation,
    ConditionTrigger,
    IntervalTrigger,
    OneTimeTrigger,
    ReminderAction,
    ToolAction,
)
from lyra.models.tools import ToolRequest, ToolResult
from lyra.tools.base import Tool
from lyra.tools.executor import ToolExecutor
from lyra.tools.permissions import PermissionPolicy, ToolPermissionLevel
from lyra.tools.registry import ToolRegistry


class MockSafeTool(Tool):
    """Safe read-only tool."""

    @property
    def name(self) -> str:
        return "mock_safe"

    @property
    def description(self) -> str:
        return "Safe tool"

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"msg": {"type": "string"}}}

    async def execute(self, request: ToolRequest) -> ToolResult:
        return ToolResult(tool_name=self.name, success=True, output=f"Executed safe: {request.arguments.get('msg')}")


class MockHighRiskTool(Tool):
    """High-risk tool requiring elevated permission."""

    @property
    def name(self) -> str:
        return "mock_danger"

    @property
    def description(self) -> str:
        return "Dangerous tool"

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.HIGH_RISK

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, request: ToolRequest) -> ToolResult:
        return ToolResult(tool_name=self.name, success=True, output="Danger executed")


class MockFailingTool(Tool):
    """Tool that always fails."""

    @property
    def name(self) -> str:
        return "mock_fail"

    @property
    def description(self) -> str:
        return "Failing tool"

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.LOW_RISK

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, request: ToolRequest) -> ToolResult:
        return ToolResult(tool_name=self.name, success=False, error="Upstream service unavailable")


@pytest.fixture
def executor_env(tmp_path):
    """Setup SQLiteAutomationStore and ToolExecutor."""
    db_file = str(tmp_path / "test_exec.db")
    store = SQLiteAutomationStore(db_path=db_file)

    registry = ToolRegistry()
    registry.register(MockSafeTool())
    registry.register(MockHighRiskTool())
    registry.register(MockFailingTool())

    policy = PermissionPolicy()  # Defaults to READ_ONLY and LOW_RISK
    tool_executor = ToolExecutor(registry=registry, policy=policy)

    notifications = []
    def callback(uid, msg):
        notifications.append((uid, msg))

    auto_executor = AutomationExecutor(
        store=store,
        tool_executor=tool_executor,
        notification_callback=callback,
    )
    return auto_executor, store, notifications


def test_execute_safe_tool_action(executor_env):
    """Verify successful execution of a safe tool action."""
    auto_executor, store, _ = executor_env
    now = datetime.now(timezone.utc)

    auto = Automation(
        id="safe-run-1",
        user_id="alice",
        name="Run Safe Tool",
        description="",
        trigger=IntervalTrigger(interval_seconds=60.0),
        action=ToolAction(tool_name="mock_safe", arguments={"msg": "ping"}),
        enabled=True,
        next_run=now,
    )
    store.save(auto)

    result = asyncio.run(auto_executor.execute(auto, now=now))

    assert result.success is True
    assert "Executed safe: ping" in result.output
    assert result.consecutive_failures == 0
    assert result.next_run == now + timedelta(seconds=60.0)

    # Verify persisted record
    persisted = store.get("safe-run-1")
    assert persisted.last_run == now
    assert persisted.consecutive_failures == 0


def test_one_time_automation_disables_on_success(executor_env):
    """Verify one-time automation is disabled after running."""
    auto_executor, store, _ = executor_env
    now = datetime.now(timezone.utc)

    auto = Automation(
        id="once-run-1",
        user_id="alice",
        name="One-time Task",
        description="",
        trigger=OneTimeTrigger(run_at=now),
        action=ToolAction(tool_name="mock_safe", arguments={"msg": "once"}),
        enabled=True,
        next_run=now,
    )
    store.save(auto)

    result = asyncio.run(auto_executor.execute(auto, now=now))

    assert result.success is True
    assert result.next_run is None

    # Persisted record should now be disabled
    persisted = store.get("once-run-1")
    assert persisted.enabled is False
    assert persisted.next_run is None


def test_permission_enforcement_blocks_dangerous_tool(executor_env):
    """Verify that scheduling a high-risk tool does NOT bypass permission policy."""
    auto_executor, store, _ = executor_env
    now = datetime.now(timezone.utc)

    # User schedules a high-risk tool under default policy
    auto = Automation(
        id="danger-run-1",
        user_id="unprivileged_user",
        name="Dangerous Scheduled Task",
        description="",
        trigger=OneTimeTrigger(run_at=now),
        action=ToolAction(tool_name="mock_danger", arguments={}),
        enabled=True,
        next_run=now,
    )
    store.save(auto)

    result = asyncio.run(auto_executor.execute(auto, now=now))

    # Must fail permission check!
    assert result.success is False
    assert "Permission denied" in result.error
    assert result.consecutive_failures == 1


def test_bounded_retries_auto_disables_automation(executor_env):
    """Verify that repeated failures trigger auto-disable after max_retries."""
    auto_executor, store, _ = executor_env
    now = datetime.now(timezone.utc)

    auto = Automation(
        id="failing-auto",
        user_id="bob",
        name="Failing Task",
        description="",
        trigger=IntervalTrigger(interval_seconds=10.0),
        action=ToolAction(tool_name="mock_fail", arguments={}),
        enabled=True,
        max_retries=3,
        consecutive_failures=0,
        next_run=now,
    )
    store.save(auto)

    # 1st failure
    r1 = asyncio.run(auto_executor.execute(auto, now=now))
    assert r1.success is False
    assert r1.consecutive_failures == 1
    assert store.get("failing-auto").enabled is True

    # 2nd failure
    auto_updated = store.get("failing-auto")
    r2 = asyncio.run(auto_executor.execute(auto_updated, now=now))
    assert r2.success is False
    assert r2.consecutive_failures == 2
    assert store.get("failing-auto").enabled is True

    # 3rd failure -> hits max_retries (3)
    auto_updated = store.get("failing-auto")
    r3 = asyncio.run(auto_executor.execute(auto_updated, now=now))
    assert r3.success is False
    assert r3.consecutive_failures == 3

    # Must be auto-disabled!
    persisted = store.get("failing-auto")
    assert persisted.enabled is False
    assert persisted.next_run is None


def test_reminder_action_execution(executor_env):
    """Verify ReminderAction triggers notification callback."""
    auto_executor, store, notifications = executor_env
    now = datetime.now(timezone.utc)

    auto = Automation(
        id="remind-1",
        user_id="alice",
        name="Reminder Alert",
        description="",
        trigger=OneTimeTrigger(run_at=now),
        action=ReminderAction(message="Take a break!"),
        enabled=True,
        next_run=now,
    )
    store.save(auto)

    result = asyncio.run(auto_executor.execute(auto, now=now))
    assert result.success is True
    assert len(notifications) == 1
    assert notifications[0] == ("alice", "Take a break!")
