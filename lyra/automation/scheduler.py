"""Scheduler coordinating automation lifecycle, timers, and execution."""

import asyncio
from datetime import datetime, timezone
from typing import Any
import uuid

from lyra.automation.executor import AutomationExecutionResult, AutomationExecutor
from lyra.automation.store import AutomationStore
from lyra.core.exceptions import AutomationNotFoundError, AutomationScheduleError
from lyra.models.automation import Action, Automation, Trigger
from lyra.observability.logging import get_logger

logger = get_logger("automation.scheduler")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Scheduler:
    """Coordinates persistent automation scheduling, periodic ticks, and user management."""

    def __init__(
        self,
        store: AutomationStore,
        executor: AutomationExecutor,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self.store = store
        self.executor = executor
        self.poll_interval_seconds = float(poll_interval_seconds)
        self._running = False
        self._loop_task: asyncio.Task | None = None

    @property
    def is_running(self) -> bool:
        """Check if background scheduler loop is currently active."""
        return self._running

    async def start(self) -> None:
        """Start the background scheduler evaluation loop."""
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._run_loop())
        logger.info(
            "Scheduler started (poll interval: %s seconds)",
            self.poll_interval_seconds,
        )

    async def stop(self) -> None:
        """Stop the background scheduler evaluation loop."""
        if not self._running:
            return
        self._running = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        self._loop_task = None
        logger.info("Scheduler stopped.")

    async def _run_loop(self) -> None:
        """Periodic background evaluation loop."""
        while self._running:
            try:
                await self.run_pending()
            except Exception as err:
                logger.error("Unexpected error in scheduler loop: %s", err)
            try:
                await asyncio.sleep(self.poll_interval_seconds)
            except asyncio.CancelledError:
                break

    async def run_pending(
        self,
        now: datetime | None = None,
    ) -> list[AutomationExecutionResult]:
        """Evaluate and execute all currently due automations."""
        as_of = now or _utc_now()
        due = self.store.get_due_automations(as_of=as_of)
        results: list[AutomationExecutionResult] = []

        for auto in due:
            res = await self.executor.execute(auto, now=as_of)
            results.append(res)

        return results

    def create_automation(
        self,
        user_id: str,
        name: str,
        trigger: Trigger,
        action: Action,
        description: str = "",
        max_retries: int = 3,
        enabled: bool = True,
    ) -> Automation:
        """Create and register a new persistent automation."""
        now = _utc_now()
        next_run = trigger.compute_next_run(after=now) if enabled else None

        automation = Automation(
            id=str(uuid.uuid4()),
            user_id=user_id,
            name=name,
            description=description,
            trigger=trigger,
            action=action,
            enabled=enabled,
            created_at=now,
            updated_at=now,
            next_run=next_run,
            last_run=None,
            consecutive_failures=0,
            last_error=None,
            max_retries=max_retries,
        )

        self.store.save(automation)
        logger.info(
            "Created automation '%s' (%s) for user '%s' [next run: %s]",
            automation.name,
            automation.id,
            user_id,
            next_run.isoformat() if next_run else "None",
        )
        return automation

    def get_automation(self, automation_id: str, user_id: str | None = None) -> Automation | None:
        """Retrieve an automation by ID, optionally validating user ownership."""
        return self.store.get(automation_id=automation_id, user_id=user_id)

    def list_automations(
        self,
        user_id: str | None = None,
        enabled_only: bool = False,
    ) -> list[Automation]:
        """List automations filtered by user and enabled status."""
        return self.store.list_automations(user_id=user_id, enabled_only=enabled_only)

    def enable_automation(self, automation_id: str, user_id: str) -> Automation:
        """Enable an existing automation and compute its next run time."""
        existing = self.store.get(automation_id=automation_id, user_id=user_id)
        if not existing:
            raise AutomationNotFoundError(
                f"Automation '{automation_id}' not found for user '{user_id}'."
            )

        now = _utc_now()
        next_run = existing.trigger.compute_next_run(after=now)

        updated = Automation(
            id=existing.id,
            user_id=existing.user_id,
            name=existing.name,
            description=existing.description,
            trigger=existing.trigger,
            action=existing.action,
            enabled=True,
            created_at=existing.created_at,
            updated_at=now,
            next_run=next_run,
            last_run=existing.last_run,
            consecutive_failures=0,
            last_error=None,
            max_retries=existing.max_retries,
        )

        self.store.save(updated)
        logger.info("Enabled automation '%s' for user '%s'", automation_id, user_id)
        return updated

    def disable_automation(self, automation_id: str, user_id: str) -> Automation:
        """Disable an existing automation."""
        existing = self.store.get(automation_id=automation_id, user_id=user_id)
        if not existing:
            raise AutomationNotFoundError(
                f"Automation '{automation_id}' not found for user '{user_id}'."
            )

        now = _utc_now()
        updated = Automation(
            id=existing.id,
            user_id=existing.user_id,
            name=existing.name,
            description=existing.description,
            trigger=existing.trigger,
            action=existing.action,
            enabled=False,
            created_at=existing.created_at,
            updated_at=now,
            next_run=None,
            last_run=existing.last_run,
            consecutive_failures=existing.consecutive_failures,
            last_error=existing.last_error,
            max_retries=existing.max_retries,
        )

        self.store.save(updated)
        logger.info("Disabled automation '%s' for user '%s'", automation_id, user_id)
        return updated

    def delete_automation(self, automation_id: str, user_id: str) -> bool:
        """Permanently delete an automation for a user."""
        existing = self.store.get(automation_id=automation_id, user_id=user_id)
        if not existing:
            raise AutomationNotFoundError(
                f"Automation '{automation_id}' not found for user '{user_id}'."
            )

        deleted = self.store.delete(automation_id=automation_id, user_id=user_id)
        if deleted:
            logger.info("Deleted automation '%s' for user '%s'", automation_id, user_id)
        return deleted

    def purge_user(self, user_id: str) -> int:
        """Purge all automations belonging to a user."""
        return self.store.purge_user(user_id)
