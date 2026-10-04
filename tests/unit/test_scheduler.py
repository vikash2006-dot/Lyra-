"""Unit tests for Scheduler coordinating automation lifecycle and execution."""

import asyncio
from datetime import datetime, timedelta, timezone
import pytest

from lyra.automation.executor import AutomationExecutor
from lyra.automation.scheduler import Scheduler
from lyra.automation.sqlite_store import SQLiteAutomationStore
from lyra.core.exceptions import AutomationNotFoundError
from lyra.models.automation import (
    Automation,
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


class DummyPingTool(Tool):
    """Simple ping tool for testing."""

    @property
    def name(self) -> str:
        return "dummy_ping"

    @property
    def description(self) -> str:
        return "Ping tool"

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, request: ToolRequest) -> ToolResult:
        return ToolResult(tool_name=self.name, success=True, output="pong")


@pytest.fixture
def scheduler_env(tmp_path):
    """Setup Scheduler test environment."""
    db_file = str(tmp_path / "test_scheduler.db")
    store = SQLiteAutomationStore(db_path=db_file)

    registry = ToolRegistry()
    registry.register(DummyPingTool())
    tool_executor = ToolExecutor(registry=registry, policy=PermissionPolicy())

    executor = AutomationExecutor(store=store, tool_executor=tool_executor)
    scheduler = Scheduler(store=store, executor=executor, poll_interval_seconds=0.1)

    return scheduler, store, db_file


def test_create_and_list_automations(scheduler_env):
    """Verify creating and listing automations with user scoping."""
    scheduler, _, _ = scheduler_env
    now = datetime.now(timezone.utc)

    auto_u1 = scheduler.create_automation(
        user_id="user_1",
        name="User 1 Task",
        trigger=IntervalTrigger(interval_seconds=60),
        action=ReminderAction(message="Hello 1"),
    )
    assert auto_u1.id is not None
    assert auto_u1.user_id == "user_1"
    assert auto_u1.next_run > now

    auto_u2 = scheduler.create_automation(
        user_id="user_2",
        name="User 2 Task",
        trigger=IntervalTrigger(interval_seconds=60),
        action=ReminderAction(message="Hello 2"),
    )

    # User 1 only sees their automations
    u1_list = scheduler.list_automations(user_id="user_1")
    assert len(u1_list) == 1
    assert u1_list[0].id == auto_u1.id

    # User 2 only sees their automations
    u2_list = scheduler.list_automations(user_id="user_2")
    assert len(u2_list) == 1
    assert u2_list[0].id == auto_u2.id


def test_run_pending_executes_due_tasks(scheduler_env):
    """Verify run_pending executes due automations and skips future ones."""
    scheduler, store, _ = scheduler_env
    now = datetime.now(timezone.utc)

    due_time = now - timedelta(seconds=10)
    future_time = now + timedelta(hours=1)

    auto_due = scheduler.create_automation(
        user_id="alice",
        name="Due Task",
        trigger=OneTimeTrigger(run_at=due_time),
        action=ToolAction(tool_name="dummy_ping", arguments={}),
    )
    # Manually backdate next_run in store to simulate elapsed time
    persisted = store.get(auto_due.id)
    store.save(Automation(
        id=persisted.id,
        user_id=persisted.user_id,
        name=persisted.name,
        description=persisted.description,
        trigger=persisted.trigger,
        action=persisted.action,
        enabled=persisted.enabled,
        created_at=persisted.created_at,
        updated_at=persisted.updated_at,
        next_run=due_time,
    ))

    auto_future = scheduler.create_automation(
        user_id="alice",
        name="Future Task",
        trigger=OneTimeTrigger(run_at=future_time),
        action=ToolAction(tool_name="dummy_ping", arguments={}),
    )

    # Run pending
    results = asyncio.run(scheduler.run_pending(now=now))
    assert len(results) == 1
    assert results[0].automation_id == auto_due.id
    assert results[0].success is True
    assert results[0].output == "pong"

    # Future task is still enabled and scheduled
    future_persisted = store.get(auto_future.id)
    assert future_persisted.enabled is True
    assert future_persisted.next_run == future_time


def test_enable_disable_and_delete_automation(scheduler_env):
    """Verify user control over enabling, disabling, and deleting automations."""
    scheduler, _, _ = scheduler_env

    auto = scheduler.create_automation(
        user_id="alice",
        name="Toggle Test",
        trigger=IntervalTrigger(interval_seconds=120),
        action=ReminderAction(message="Ping"),
    )
    assert auto.enabled is True

    # Disable
    disabled = scheduler.disable_automation(automation_id=auto.id, user_id="alice")
    assert disabled.enabled is False
    assert disabled.next_run is None

    # Enable
    enabled = scheduler.enable_automation(automation_id=auto.id, user_id="alice")
    assert enabled.enabled is True
    assert enabled.next_run is not None

    # Unauthorized access by Bob raises AutomationNotFoundError
    with pytest.raises(AutomationNotFoundError):
        scheduler.disable_automation(automation_id=auto.id, user_id="bob")

    # Delete
    deleted = scheduler.delete_automation(automation_id=auto.id, user_id="alice")
    assert deleted is True
    assert scheduler.get_automation(auto.id) is None


def test_scheduler_restart_recovery(scheduler_env):
    """Verify scheduler seamlessly recovers and runs pending tasks after a restart."""
    scheduler1, store1, db_file = scheduler_env
    now = datetime.now(timezone.utc)
    due_time = now - timedelta(seconds=5)

    auto = scheduler1.create_automation(
        user_id="charlie",
        name="Restart Task",
        trigger=IntervalTrigger(interval_seconds=60),
        action=ToolAction(tool_name="dummy_ping", arguments={}),
    )
    # Set to due
    store1.save(Automation(
        id=auto.id,
        user_id=auto.user_id,
        name=auto.name,
        description=auto.description,
        trigger=auto.trigger,
        action=auto.action,
        enabled=True,
        created_at=auto.created_at,
        updated_at=auto.updated_at,
        next_run=due_time,
    ))

    # Simulate restart by instantiating new store & scheduler
    store2 = SQLiteAutomationStore(db_path=db_file)
    registry = ToolRegistry()
    registry.register(DummyPingTool())
    tool_executor = ToolExecutor(registry=registry, policy=PermissionPolicy())
    executor2 = AutomationExecutor(store=store2, tool_executor=tool_executor)
    scheduler2 = Scheduler(store=store2, executor=executor2)

    # Run pending on recovered scheduler
    results = asyncio.run(scheduler2.run_pending(now=now))
    assert len(results) == 1
    assert results[0].automation_id == auto.id
    assert results[0].success is True
    assert results[0].output == "pong"


def test_scheduler_lifecycle(scheduler_env):
    """Verify scheduler start and stop lifecycle."""
    scheduler, _, _ = scheduler_env
    assert scheduler.is_running is False

    async def _test():
        await scheduler.start()
        assert scheduler.is_running is True
        await asyncio.sleep(0.05)
        await scheduler.stop()
        assert scheduler.is_running is False

    asyncio.run(_test())
