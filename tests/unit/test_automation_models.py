"""Unit tests for Automation domain models, triggers, and actions."""

from datetime import datetime, timedelta, timezone
import pytest

from lyra.core.exceptions import AutomationValidationError
from lyra.models.automation import (
    Action,
    ActionType,
    Automation,
    ConditionTrigger,
    DailyTrigger,
    IntervalTrigger,
    OneTimeTrigger,
    ReminderAction,
    ToolAction,
    Trigger,
    TriggerType,
)


def test_one_time_trigger():
    """Verify OneTimeTrigger schedule computation and serialization."""
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=15)
    past = now - timedelta(minutes=15)

    trigger = OneTimeTrigger(run_at=future)
    assert trigger.type == TriggerType.ONE_TIME
    assert trigger.compute_next_run(after=now) == future
    assert trigger.compute_next_run(after=future) is None
    assert trigger.compute_next_run(after=future + timedelta(seconds=1)) is None

    # Serialization
    data = trigger.to_dict()
    reconstructed = Trigger.from_dict(data)
    assert isinstance(reconstructed, OneTimeTrigger)
    assert reconstructed.run_at == future

    # Invalid run_at
    with pytest.raises(AutomationValidationError, match="datetime object"):
        OneTimeTrigger(run_at="not_a_datetime")  # type: ignore


def test_interval_trigger():
    """Verify IntervalTrigger schedule computation and serialization."""
    now = datetime.now(timezone.utc)
    trigger = IntervalTrigger(interval_seconds=300.0)
    assert trigger.type == TriggerType.INTERVAL

    next_run = trigger.compute_next_run(after=now)
    assert next_run == now + timedelta(seconds=300.0)

    # With future start_at
    future_start = now + timedelta(hours=1)
    delayed_trigger = IntervalTrigger(interval_seconds=60.0, start_at=future_start)
    assert delayed_trigger.compute_next_run(after=now) == future_start

    # Invalid interval
    with pytest.raises(AutomationValidationError, match="positive number"):
        IntervalTrigger(interval_seconds=-10.0)

    # Serialization
    data = trigger.to_dict()
    reconstructed = Trigger.from_dict(data)
    assert isinstance(reconstructed, IntervalTrigger)
    assert reconstructed.interval_seconds == 300.0


def test_daily_trigger():
    """Verify DailyTrigger computes next daily occurrence."""
    # Test morning time
    trigger = DailyTrigger(time_of_day="08:30")
    assert trigger.type == TriggerType.DAILY

    ref_early = datetime(2026, 9, 12, 6, 0, 0, tzinfo=timezone.utc)
    next_early = trigger.compute_next_run(after=ref_early)
    assert next_early == datetime(2026, 9, 12, 8, 30, 0, tzinfo=timezone.utc)

    # Ref after scheduled time -> should advance to next day
    ref_late = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    next_late = trigger.compute_next_run(after=ref_late)
    assert next_late == datetime(2026, 9, 13, 8, 30, 0, tzinfo=timezone.utc)

    # Invalid format
    with pytest.raises(AutomationValidationError, match="Invalid time_of_day"):
        DailyTrigger(time_of_day="25:00")
    with pytest.raises(AutomationValidationError, match="Invalid time_of_day"):
        DailyTrigger(time_of_day="invalid")


def test_condition_trigger():
    """Verify ConditionTrigger configuration and serialization."""
    now = datetime.now(timezone.utc)
    trigger = ConditionTrigger(
        condition_tool="weather",
        condition_args={"city": "London"},
        expected_output="rain",
        check_interval_seconds=120.0,
    )
    assert trigger.type == TriggerType.CONDITION
    assert trigger.compute_next_run(after=now) == now + timedelta(seconds=120.0)

    # Serialization
    data = trigger.to_dict()
    reconstructed = Trigger.from_dict(data)
    assert isinstance(reconstructed, ConditionTrigger)
    assert reconstructed.condition_tool == "weather"
    assert reconstructed.expected_output == "rain"


def test_tool_action_and_reminder_action():
    """Verify ToolAction and ReminderAction validation and serialization."""
    tool_act = ToolAction(tool_name="weather", arguments={"city": "Tokyo"})
    assert tool_act.type == ActionType.TOOL
    assert tool_act.tool_name == "weather"

    data_tool = tool_act.to_dict()
    rec_tool = Action.from_dict(data_tool)
    assert isinstance(rec_tool, ToolAction)
    assert rec_tool.arguments["city"] == "Tokyo"

    reminder_act = ReminderAction(message="Hydrate yourself!", target="user")
    assert reminder_act.type == ActionType.REMINDER
    assert reminder_act.message == "Hydrate yourself!"

    data_rem = reminder_act.to_dict()
    rec_rem = Action.from_dict(data_rem)
    assert isinstance(rec_rem, ReminderAction)
    assert rec_rem.message == "Hydrate yourself!"

    # Invariants
    with pytest.raises(AutomationValidationError, match="non-empty tool_name"):
        ToolAction(tool_name="")
    with pytest.raises(AutomationValidationError, match="non-empty message"):
        ReminderAction(message="   ")


def test_automation_model_and_due_check():
    """Verify Automation invariants, is_due(), and dictionary serialization."""
    now = datetime.now(timezone.utc)
    past = now - timedelta(seconds=10)
    future = now + timedelta(seconds=100)

    trigger = OneTimeTrigger(run_at=past)
    action = ReminderAction(message="Meeting in 5 mins")

    auto = Automation(
        id="auto-001",
        user_id="user-123",
        name="Team Sync Reminder",
        description="Daily standup alert",
        trigger=trigger,
        action=action,
        enabled=True,
        next_run=past,
    )

    assert auto.is_due(as_of=now) is True
    assert auto.consecutive_failures == 0
    assert auto.max_retries == 3

    # Future run is not due
    auto_future = Automation(
        id="auto-002",
        user_id="user-123",
        name="Future Task",
        description="",
        trigger=trigger,
        action=action,
        enabled=True,
        next_run=future,
    )
    assert auto_future.is_due(as_of=now) is False

    # Disabled is never due
    auto_disabled = Automation(
        id="auto-003",
        user_id="user-123",
        name="Disabled Task",
        description="",
        trigger=trigger,
        action=action,
        enabled=False,
        next_run=past,
    )
    assert auto_disabled.is_due(as_of=now) is False

    # Serialization roundtrip
    data = auto.to_dict()
    reconstructed = Automation.from_dict(data)
    assert reconstructed.id == auto.id
    assert reconstructed.user_id == auto.user_id
    assert reconstructed.name == auto.name
    assert reconstructed.trigger.type == TriggerType.ONE_TIME
    assert reconstructed.action.type == ActionType.REMINDER
