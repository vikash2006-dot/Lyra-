"""Execution engine for automated tasks using existing tool infrastructure."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from lyra.automation.store import AutomationStore
from lyra.core.exceptions import AutomationExecutionError, ToolError
from lyra.models.automation import (
    ActionType,
    Automation,
    ConditionTrigger,
    ReminderAction,
    ToolAction,
)
from lyra.models.tools import ToolRequest, ToolResult
from lyra.observability.logging import get_logger
from lyra.tools.executor import ToolExecutor

logger = get_logger("automation.executor")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AutomationExecutionResult:
    """Outcome of an automation execution run."""

    automation_id: str
    success: bool
    output: Any = None
    error: str | None = None
    consecutive_failures: int = 0
    next_run: datetime | None = None


class AutomationExecutor:
    """Safely executes automated actions using existing tool and permission infrastructure."""

    def __init__(
        self,
        store: AutomationStore,
        tool_executor: ToolExecutor,
        notification_callback: Callable[[str, str], Any] | None = None,
    ) -> None:
        self.store = store
        self.tool_executor = tool_executor
        self.notification_callback = notification_callback

    async def execute(
        self,
        automation: Automation,
        now: datetime | None = None,
    ) -> AutomationExecutionResult:
        """Execute the automation action, enforce permissions, update run state, and persist changes."""
        exec_time = now or _utc_now()

        if not automation.enabled:
            logger.warning("Skipping execution of disabled automation '%s'", automation.id)
            return AutomationExecutionResult(
                automation_id=automation.id,
                success=False,
                error="Automation is disabled.",
                consecutive_failures=automation.consecutive_failures,
                next_run=automation.next_run,
            )

        logger.info(
            "Executing automation '%s' (User: '%s', Action: %s)",
            automation.name,
            automation.user_id,
            automation.action.type.value,
        )

        success = False
        output = None
        error_msg = None

        try:
            # 1. Check ConditionTrigger predicate if applicable
            if isinstance(automation.trigger, ConditionTrigger):
                cond_req = ToolRequest(
                    tool_name=automation.trigger.condition_tool,
                    arguments=automation.trigger.condition_args,
                    user_id=automation.user_id,
                )
                cond_res = await self.tool_executor.execute(cond_req)
                if not cond_res.is_success():
                    raise AutomationExecutionError(f"Condition check failed: {cond_res.error}")

                # Compare output
                if automation.trigger.expected_output is not None:
                    if cond_res.output != automation.trigger.expected_output:
                        logger.debug("Condition not met for '%s'; deferring action.", automation.id)
                        # Defer without marking failure
                        next_run = automation.trigger.compute_next_run(after=exec_time)
                        updated = Automation(
                            id=automation.id,
                            user_id=automation.user_id,
                            name=automation.name,
                            description=automation.description,
                            trigger=automation.trigger,
                            action=automation.action,
                            enabled=automation.enabled,
                            created_at=automation.created_at,
                            updated_at=exec_time,
                            next_run=next_run,
                            last_run=automation.last_run,
                            consecutive_failures=automation.consecutive_failures,
                            last_error=automation.last_error,
                            max_retries=automation.max_retries,
                        )
                        self.store.save(updated)
                        return AutomationExecutionResult(
                            automation_id=automation.id,
                            success=True,
                            output="Condition evaluated: deferred",
                            next_run=next_run,
                        )

            # 2. Execute Action
            if isinstance(automation.action, ToolAction):
                request = ToolRequest(
                    tool_name=automation.action.tool_name,
                    arguments=automation.action.arguments,
                    user_id=automation.user_id,
                )
                tool_res: ToolResult = await self.tool_executor.execute(request)
                if tool_res.is_success():
                    success = True
                    output = tool_res.output
                else:
                    success = False
                    error_msg = tool_res.error or "Tool execution failed."

            elif isinstance(automation.action, ReminderAction):
                if self.notification_callback:
                    try:
                        self.notification_callback(automation.user_id, automation.action.message)
                    except Exception as cb_err:
                        logger.warning("Notification callback error: %s", cb_err)
                success = True
                output = f"Reminder sent: {automation.action.message}"

            else:
                raise AutomationExecutionError(f"Unsupported action type: {automation.action.type}")

        except Exception as err:
            success = False
            error_msg = str(err)
            logger.error("Error executing automation '%s': %s", automation.id, err)

        # 3. Handle state updates, bounded retries, and persistence
        if success:
            consecutive_failures = 0
            last_error = None
            last_run = exec_time
            next_run = automation.trigger.compute_next_run(after=exec_time)
            # One-time tasks with next_run None get disabled
            enabled = automation.enabled if next_run is not None else False
        else:
            consecutive_failures = automation.consecutive_failures + 1
            last_error = error_msg
            last_run = automation.last_run

            # Bounded retry policy: auto-disable if max_retries exceeded
            if consecutive_failures >= automation.max_retries:
                logger.warning(
                    "Automation '%s' reached max retries (%d). Auto-disabling.",
                    automation.id,
                    automation.max_retries,
                )
                enabled = False
                next_run = None
            else:
                enabled = automation.enabled
                next_run = automation.trigger.compute_next_run(after=exec_time)

        updated_automation = Automation(
            id=automation.id,
            user_id=automation.user_id,
            name=automation.name,
            description=automation.description,
            trigger=automation.trigger,
            action=automation.action,
            enabled=enabled,
            created_at=automation.created_at,
            updated_at=exec_time,
            next_run=next_run,
            last_run=last_run,
            consecutive_failures=consecutive_failures,
            last_error=last_error,
            max_retries=automation.max_retries,
        )

        self.store.save(updated_automation)

        return AutomationExecutionResult(
            automation_id=automation.id,
            success=success,
            output=output,
            error=error_msg,
            consecutive_failures=consecutive_failures,
            next_run=next_run,
        )
