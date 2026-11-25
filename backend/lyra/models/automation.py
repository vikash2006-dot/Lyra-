"""Canonical domain models for LYRA automation and scheduling."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from enum import Enum
import re
from typing import Any
import uuid

from lyra.core.exceptions import AutomationValidationError, ModelValidationError


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class TriggerType(str, Enum):
    """Supported trigger types for automations."""

    ONE_TIME = "one_time"
    INTERVAL = "interval"
    DAILY = "daily"
    CONDITION = "condition"


class Trigger(ABC):
    """Abstract base class for automation triggers."""

    @property
    @abstractmethod
    def type(self) -> TriggerType:
        """Trigger classification type."""

    @abstractmethod
    def compute_next_run(self, after: datetime) -> datetime | None:
        """Calculate the next execution timestamp strictly after the provided reference time.

        Returns:
            datetime in UTC, or None if the trigger will not fire again.
        """

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Serialize trigger configuration to dictionary."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Trigger":
        """Reconstruct trigger instance from dictionary."""
        ttype = data.get("type")
        if ttype == TriggerType.ONE_TIME.value:
            return OneTimeTrigger.from_dict(data)
        elif ttype == TriggerType.INTERVAL.value:
            return IntervalTrigger.from_dict(data)
        elif ttype == TriggerType.DAILY.value:
            return DailyTrigger.from_dict(data)
        elif ttype == TriggerType.CONDITION.value:
            return ConditionTrigger.from_dict(data)
        raise AutomationValidationError(f"Unknown trigger type: {ttype}")


@dataclass(frozen=True)
class OneTimeTrigger(Trigger):
    """Fires once at an exact future timestamp."""

    run_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.run_at, datetime):
            raise AutomationValidationError("run_at must be a datetime object.")

    @property
    def type(self) -> TriggerType:
        return TriggerType.ONE_TIME

    def compute_next_run(self, after: datetime) -> datetime | None:
        target = _ensure_utc(self.run_at)
        ref = _ensure_utc(after)
        if target > ref:
            return target
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "run_at": _ensure_utc(self.run_at).isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OneTimeTrigger":
        return cls(run_at=datetime.fromisoformat(data["run_at"]))


@dataclass(frozen=True)
class IntervalTrigger(Trigger):
    """Fires periodically at a fixed interval."""

    interval_seconds: float
    start_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise AutomationValidationError("interval_seconds must be a positive number.")

    @property
    def type(self) -> TriggerType:
        return TriggerType.INTERVAL

    def compute_next_run(self, after: datetime) -> datetime | None:
        ref = _ensure_utc(after)
        if self.start_at is not None:
            start = _ensure_utc(self.start_at)
            if start > ref:
                return start
        return ref + timedelta(seconds=self.interval_seconds)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "interval_seconds": self.interval_seconds,
            "start_at": _ensure_utc(self.start_at).isoformat() if self.start_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IntervalTrigger":
        start_str = data.get("start_at")
        start_at = datetime.fromisoformat(start_str) if start_str else None
        return cls(
            interval_seconds=float(data["interval_seconds"]),
            start_at=start_at,
        )


TIME_OF_DAY_REGEX = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


@dataclass(frozen=True)
class DailyTrigger(Trigger):
    """Fires daily at a specific hour and minute (HH:MM UTC)."""

    time_of_day: str  # "HH:MM"

    def __post_init__(self) -> None:
        if not TIME_OF_DAY_REGEX.match(self.time_of_day.strip()):
            raise AutomationValidationError(
                f"Invalid time_of_day '{self.time_of_day}'. Expected 'HH:MM' (24-hour format)."
            )

    @property
    def type(self) -> TriggerType:
        return TriggerType.DAILY

    def compute_next_run(self, after: datetime) -> datetime | None:
        ref = _ensure_utc(after)
        hh, mm = map(int, self.time_of_day.split(":"))
        target_today = ref.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target_today > ref:
            return target_today
        return target_today + timedelta(days=1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "time_of_day": self.time_of_day,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DailyTrigger":
        return cls(time_of_day=data["time_of_day"])


@dataclass(frozen=True)
class ConditionTrigger(Trigger):
    """Fires periodically to check a tool condition and trigger action if matched."""

    condition_tool: str
    condition_args: dict[str, Any] = field(default_factory=dict)
    expected_output: Any = None
    check_interval_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not self.condition_tool or not isinstance(self.condition_tool, str):
            raise AutomationValidationError("condition_tool must be a non-empty string.")
        if self.check_interval_seconds <= 0:
            raise AutomationValidationError("check_interval_seconds must be a positive number.")

    @property
    def type(self) -> TriggerType:
        return TriggerType.CONDITION

    def compute_next_run(self, after: datetime) -> datetime | None:
        ref = _ensure_utc(after)
        return ref + timedelta(seconds=self.check_interval_seconds)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "condition_tool": self.condition_tool,
            "condition_args": dict(self.condition_args),
            "expected_output": self.expected_output,
            "check_interval_seconds": self.check_interval_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConditionTrigger":
        return cls(
            condition_tool=data["condition_tool"],
            condition_args=data.get("condition_args", {}),
            expected_output=data.get("expected_output"),
            check_interval_seconds=float(data.get("check_interval_seconds", 60.0)),
        )


class ActionType(str, Enum):
    """Supported action types."""

    TOOL = "tool"
    REMINDER = "reminder"


class Action(ABC):
    """Abstract base class for automated actions."""

    @property
    @abstractmethod
    def type(self) -> ActionType:
        """Action classification type."""

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Serialize action configuration to dictionary."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Action":
        """Reconstruct action instance from dictionary."""
        atype = data.get("type")
        if atype == ActionType.TOOL.value:
            return ToolAction.from_dict(data)
        elif atype == ActionType.REMINDER.value:
            return ReminderAction.from_dict(data)
        raise AutomationValidationError(f"Unknown action type: {atype}")


@dataclass(frozen=True)
class ToolAction(Action):
    """Executes a registered tool using the existing ToolExecutor."""

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tool_name or not isinstance(self.tool_name, str):
            raise AutomationValidationError("ToolAction requires a non-empty tool_name.")
        if not isinstance(self.arguments, dict):
            raise AutomationValidationError("ToolAction arguments must be a dictionary.")

    @property
    def type(self) -> ActionType:
        return ActionType.TOOL

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolAction":
        return cls(
            tool_name=data["tool_name"],
            arguments=data.get("arguments", {}),
        )


@dataclass(frozen=True)
class ReminderAction(Action):
    """Emits a reminder or notification message."""

    message: str
    target: str = "user"

    def __post_init__(self) -> None:
        if not self.message or not isinstance(self.message, str) or not self.message.strip():
            raise AutomationValidationError("ReminderAction requires a non-empty message.")

    @property
    def type(self) -> ActionType:
        return ActionType.REMINDER

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "message": self.message,
            "target": self.target,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReminderAction":
        return cls(
            message=data["message"],
            target=data.get("target", "user"),
        )


@dataclass(frozen=True)
class Automation:
    """Canonical model for a persistent automation task."""

    id: str
    user_id: str
    name: str
    description: str
    trigger: Trigger
    action: Action
    enabled: bool = True
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    next_run: datetime | None = None
    last_run: datetime | None = None
    consecutive_failures: int = 0
    last_error: str | None = None
    max_retries: int = 3

    def __post_init__(self) -> None:
        if not self.id or not isinstance(self.id, str) or not self.id.strip():
            raise AutomationValidationError("Automation id must be a non-empty string.")
        if not self.user_id or not isinstance(self.user_id, str) or not self.user_id.strip():
            raise AutomationValidationError("Automation user_id must be a non-empty string.")
        if not self.name or not isinstance(self.name, str) or not self.name.strip():
            raise AutomationValidationError("Automation name must be a non-empty string.")
        if not isinstance(self.trigger, Trigger):
            raise AutomationValidationError(f"Invalid trigger: {self.trigger}")
        if not isinstance(self.action, Action):
            raise AutomationValidationError(f"Invalid action: {self.action}")
        if self.max_retries < 0:
            raise AutomationValidationError("max_retries must be non-negative.")

    def is_due(self, as_of: datetime | None = None) -> bool:
        """Check if this automation is active and currently scheduled to run."""
        if not self.enabled or self.next_run is None:
            return False
        ref = _ensure_utc(as_of or _utc_now())
        nr = _ensure_utc(self.next_run)
        return nr <= ref

    def to_dict(self) -> dict[str, Any]:
        """Serialize automation to dictionary representation."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "description": self.description,
            "trigger": self.trigger.to_dict(),
            "action": self.action.to_dict(),
            "enabled": self.enabled,
            "created_at": _ensure_utc(self.created_at).isoformat(),
            "updated_at": _ensure_utc(self.updated_at).isoformat(),
            "next_run": _ensure_utc(self.next_run).isoformat() if self.next_run else None,
            "last_run": _ensure_utc(self.last_run).isoformat() if self.last_run else None,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "max_retries": self.max_retries,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Automation":
        """Reconstruct automation instance from dictionary."""
        created_at = datetime.fromisoformat(data["created_at"])
        updated_at = datetime.fromisoformat(data["updated_at"])
        next_run = datetime.fromisoformat(data["next_run"]) if data.get("next_run") else None
        last_run = datetime.fromisoformat(data["last_run"]) if data.get("last_run") else None

        trigger = Trigger.from_dict(data["trigger"])
        action = Action.from_dict(data["action"])

        return cls(
            id=data["id"],
            user_id=data["user_id"],
            name=data["name"],
            description=data.get("description", ""),
            trigger=trigger,
            action=action,
            enabled=bool(data.get("enabled", True)),
            created_at=_ensure_utc(created_at),
            updated_at=_ensure_utc(updated_at),
            next_run=_ensure_utc(next_run) if next_run else None,
            last_run=_ensure_utc(last_run) if last_run else None,
            consecutive_failures=int(data.get("consecutive_failures", 0)),
            last_error=data.get("last_error"),
            max_retries=int(data.get("max_retries", 3)),
        )
