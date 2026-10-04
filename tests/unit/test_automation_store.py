"""Unit tests for SQLiteAutomationStore."""

from datetime import datetime, timedelta, timezone
import pytest

from lyra.automation.sqlite_store import SQLiteAutomationStore
from lyra.models.automation import (
    Automation,
    IntervalTrigger,
    OneTimeTrigger,
    ReminderAction,
    ToolAction,
)


@pytest.fixture
def store(tmp_path):
    """Provide fresh SQLiteAutomationStore."""
    db_file = str(tmp_path / "test_automations.db")
    return SQLiteAutomationStore(db_path=db_file)


def test_save_get_and_update_automation(store):
    """Verify storing, retrieving, and updating an automation."""
    now = datetime.now(timezone.utc)
    auto = Automation(
        id="auto-1",
        user_id="alice",
        name="Check Weather",
        description="Daily weather forecast",
        trigger=IntervalTrigger(interval_seconds=3600.0),
        action=ToolAction(tool_name="weather", arguments={"city": "Paris"}),
        enabled=True,
        next_run=now + timedelta(hours=1),
    )

    store.save(auto)

    # Retrieve
    fetched = store.get(automation_id="auto-1", user_id="alice")
    assert fetched is not None
    assert fetched.name == "Check Weather"
    assert fetched.user_id == "alice"
    assert fetched.action.type.value == "tool"

    # User isolation: Bob cannot access Alice's automation by user_id
    assert store.get(automation_id="auto-1", user_id="bob") is None

    # Update
    updated = Automation(
        id="auto-1",
        user_id="alice",
        name="Check Weather Updated",
        description="Updated description",
        trigger=auto.trigger,
        action=auto.action,
        enabled=False,
        consecutive_failures=1,
        last_error="Network timeout",
    )
    store.save(updated)

    refetched = store.get(automation_id="auto-1", user_id="alice")
    assert refetched.name == "Check Weather Updated"
    assert refetched.enabled is False
    assert refetched.consecutive_failures == 1
    assert refetched.last_error == "Network timeout"


def test_get_due_automations(store):
    """Verify get_due_automations filters by enabled and next_run."""
    now = datetime.now(timezone.utc)
    due_time = now - timedelta(seconds=10)
    future_time = now + timedelta(minutes=10)

    # Due and enabled
    auto_due = Automation(
        id="due-1",
        user_id="alice",
        name="Due Task",
        description="",
        trigger=OneTimeTrigger(run_at=due_time),
        action=ReminderAction(message="Alert"),
        enabled=True,
        next_run=due_time,
    )
    # Future and enabled
    auto_future = Automation(
        id="future-1",
        user_id="alice",
        name="Future Task",
        description="",
        trigger=OneTimeTrigger(run_at=future_time),
        action=ReminderAction(message="Later"),
        enabled=True,
        next_run=future_time,
    )
    # Due but disabled
    auto_disabled = Automation(
        id="disabled-1",
        user_id="alice",
        name="Disabled Task",
        description="",
        trigger=OneTimeTrigger(run_at=due_time),
        action=ReminderAction(message="Ignored"),
        enabled=False,
        next_run=due_time,
    )

    store.save(auto_due)
    store.save(auto_future)
    store.save(auto_disabled)

    due_list = store.get_due_automations(as_of=now)
    assert len(due_list) == 1
    assert due_list[0].id == "due-1"


def test_list_and_delete_automations(store):
    """Verify listing and deleting automations."""
    auto1 = Automation(
        id="a1",
        user_id="user_x",
        name="Task X",
        description="",
        trigger=IntervalTrigger(interval_seconds=60),
        action=ReminderAction(message="X"),
        enabled=True,
    )
    auto2 = Automation(
        id="a2",
        user_id="user_y",
        name="Task Y",
        description="",
        trigger=IntervalTrigger(interval_seconds=60),
        action=ReminderAction(message="Y"),
        enabled=False,
    )

    store.save(auto1)
    store.save(auto2)

    # List all
    assert len(store.list_automations()) == 2

    # List by user
    assert len(store.list_automations(user_id="user_x")) == 1
    assert len(store.list_automations(user_id="user_y")) == 1

    # List enabled only
    assert len(store.list_automations(enabled_only=True)) == 1

    # Delete
    deleted = store.delete(automation_id="a1", user_id="user_x")
    assert deleted is True
    assert store.get("a1") is None
    assert len(store.list_automations()) == 1


def test_restart_recovery(tmp_path):
    """Verify automations survive store re-instantiation (simulating application restart)."""
    db_file = str(tmp_path / "restart_test.db")
    store1 = SQLiteAutomationStore(db_path=db_file)

    now = datetime.now(timezone.utc)
    target_time = now + timedelta(days=1)

    auto = Automation(
        id="persistent-001",
        user_id="charlie",
        name="Persistent Reminder",
        description="Must survive restart",
        trigger=OneTimeTrigger(run_at=target_time),
        action=ReminderAction(message="Welcome back!"),
        enabled=True,
        next_run=target_time,
    )
    store1.save(auto)

    # Simulate restart by instantiating new store on same file
    store2 = SQLiteAutomationStore(db_path=db_file)
    recovered = store2.get("persistent-001")

    assert recovered is not None
    assert recovered.name == "Persistent Reminder"
    assert recovered.user_id == "charlie"
    assert recovered.enabled is True
    assert recovered.next_run == target_time
    assert recovered.trigger.type.value == "one_time"


def test_purge_user(store):
    """Verify purging all automations for a specific user."""
    store.save(Automation(
        id="u1-a",
        user_id="user1",
        name="Task 1",
        description="",
        trigger=IntervalTrigger(interval_seconds=10),
        action=ReminderAction(message="1"),
    ))
    store.save(Automation(
        id="u1-b",
        user_id="user1",
        name="Task 2",
        description="",
        trigger=IntervalTrigger(interval_seconds=10),
        action=ReminderAction(message="2"),
    ))
    store.save(Automation(
        id="u2-a",
        user_id="user2",
        name="Task 3",
        description="",
        trigger=IntervalTrigger(interval_seconds=10),
        action=ReminderAction(message="3"),
    ))

    purged = store.purge_user("user1")
    assert purged == 2

    # User 1 automations should be gone
    assert len(store.list_automations(user_id="user1")) == 0

    # User 2 automations should remain
    assert len(store.list_automations(user_id="user2")) == 1
