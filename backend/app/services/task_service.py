"""Task tracking for LYRA tool execution.

A *task* is created whenever a conversational turn makes LYRA plan or execute actions
(open apps, browse, create files, ...). Progress is observed without modifying the
orchestrator: the orchestrator's planner and tool executor are wrapped by thin
observers that read the active turn from a ``ContextVar`` and report each real step.

Statuses: pending, planning, running, waiting_for_confirmation, verifying,
completed, failed, cancelled.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, Callable
import uuid

from lyra.models.tools import ToolRequest, ToolResult
from lyra.observability.logging import get_logger, sanitize_text

from app.core.errors import APIError
from app.services.events import EventBus, make_event, utc_iso
from app.services.serialization import to_jsonable
from app.services.store import APIStore

logger = get_logger("api.tasks")

TASK_STATUSES = (
    "pending",
    "planning",
    "running",
    "waiting_for_confirmation",
    "verifying",
    "completed",
    "failed",
    "cancelled",
)
ACTIVE_STATUSES = frozenset({"pending", "planning", "running", "verifying"})
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})

Emitter = Callable[[dict[str, Any]], None]  # must not block (e.g. queue.put_nowait)


@dataclass
class TurnContext:
    """State for one conversational turn, visible to observers via a ContextVar."""

    session_id: str
    command: str
    emit: Emitter | None = None
    task: dict[str, Any] | None = None
    source: str = "chat"


current_turn: ContextVar[TurnContext | None] = ContextVar("lyra_current_turn", default=None)


def _summarize_args(arguments: dict[str, Any]) -> str:
    parts = []
    for k, v in list(arguments.items())[:3]:
        text = str(v)
        parts.append(f"{k}={text[:40]}{'…' if len(text) > 40 else ''}")
    return ", ".join(parts)


def _step_label(tool: str, arguments: dict[str, Any]) -> str:
    action = arguments.get("action") or arguments.get("operation")
    target = arguments.get("query") or arguments.get("app_name") or arguments.get("app") or arguments.get(
        "path") or arguments.get("url") or arguments.get("name")
    label = f"{tool}"
    if action:
        label += f": {str(action).replace('_', ' ')}"
    if target:
        label += f" — {str(target)[:60]}"
    return label


def postcheck(output: Any) -> tuple[bool | None, str | None]:
    """Independent, read-only check that a filesystem action really took effect.

    Returns (verified, note). ``None`` means no independent check applies to this action.
    """
    if not isinstance(output, dict):
        return None, None
    action = output.get("action")
    if action in ("create_directory", "create_file"):
        path = output.get("path")
        if path:
            exists = Path(path).is_dir() if action == "create_directory" else Path(path).is_file()
            return exists, f"{'Confirmed' if exists else 'Could not find'} {path}"
    if action == "create_structure":
        base = output.get("base_path")
        created = output.get("created_paths") or []
        if base and created:
            missing = [c for c in created if not (Path(base) / c).exists() and not Path(c).exists()]
            return not missing, (f"All {len(created)} folders exist" if not missing
                                 else f"{len(missing)} expected folders are missing")
    if action == "delete":
        path = output.get("path")
        if path and output.get("deleted", True) and output.get("confirmed", True):
            gone = not Path(path).exists()
            return gone, f"{'Confirmed removal of' if gone else 'Still present:'} {path}"
    if action == "rename":
        dest = output.get("destination") or output.get("new_path")
        if dest:
            exists = Path(dest).exists()
            return exists, f"{'Confirmed' if exists else 'Could not find'} {dest}"
    if "verified" in output and isinstance(output["verified"], bool):
        return output["verified"], "Verified by the tool's own post-action check"
    return None, None


class TaskTracker:
    def __init__(self, store: APIStore, bus: EventBus) -> None:
        self.store = store
        self.bus = bus
        self._active: dict[str, dict[str, Any]] = {}
        self._handles: dict[str, asyncio.Task[Any]] = {}

    # Creation / updates ---------------------------------------------------------
    def new_task(self, session_id: str | None, command: str, status: str = "pending") -> dict[str, Any]:
        now = utc_iso()
        task = {
            "id": f"task_{uuid.uuid4().hex[:12]}",
            "session_id": session_id,
            "command": command,
            "status": status,
            "intent": None,
            "steps": [],
            "message": "Request received",
            "response": None,
            "error": None,
            "confirmation_prompt": None,
            "verification": None,
            "created_at": now,
            "updated_at": now,
            "created_ts": time.time(),
        }
        self._active[task["id"]] = task
        self.store.save_task(task)
        self.bus.publish(make_event("task_update", task_id=task["id"], status=task["status"], task=self.public(task)))
        return task

    def update(self, task: dict[str, Any], **changes: Any) -> None:
        if task["status"] in TERMINAL_STATUSES and changes.get("status") not in (None, task["status"]):
            return  # never resurrect a finished/cancelled task
        task.update(changes)
        task["updated_at"] = utc_iso()
        self.store.save_task(task)
        event = make_event(
            "task_update",
            task_id=task["id"],
            status=task["status"],
            message=task.get("message"),
            task=self.public(task),
        )
        self.bus.publish(event)
        turn = current_turn.get()
        if turn and turn.emit and turn.task is task:
            turn.emit(event)
        if task["status"] in TERMINAL_STATUSES:
            self._active.pop(task["id"], None)
            self._handles.pop(task["id"], None)

    @staticmethod
    def public(task: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in task.items() if k != "created_ts"}

    # Queries ----------------------------------------------------------------------
    def get(self, task_id: str) -> dict[str, Any]:
        task = self._active.get(task_id) or self.store.get_task(task_id)
        if not task:
            raise APIError("TASK_NOT_FOUND", "Task not found.", 404)
        return self.public(task)

    def list(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if status and status not in TASK_STATUSES:
            raise APIError("VALIDATION_ERROR", f"Unknown status '{status}'.", 422)
        return [self.public(t) for t in self.store.list_tasks(status=status, limit=limit)]

    @property
    def active_count(self) -> int:
        return len(self._active)

    # Cancellation ----------------------------------------------------------------
    def attach_handle(self, task_id: str, handle: asyncio.Task[Any]) -> None:
        self._handles[task_id] = handle

    def cancel(self, task_id: str) -> dict[str, Any]:
        task = self._active.get(task_id)
        if not task:
            stored = self.store.get_task(task_id)
            if not stored:
                raise APIError("TASK_NOT_FOUND", "Task not found.", 404)
            raise APIError("TASK_NOT_CANCELLABLE", f"Task is already {stored['status']}.", 409)
        handle = self._handles.get(task_id)
        if handle is None or handle.done():
            raise APIError("TASK_NOT_CANCELLABLE", "This task cannot be cancelled at its current stage.", 409)
        handle.cancel()
        self.update(task, status="cancelled", message="Cancelled by user")
        return self.public(task)

    # Observer hooks (called from the wrapped planner/executor) ---------------------
    def ensure_task(self, turn: TurnContext) -> dict[str, Any]:
        if turn.task is None:
            turn.task = self.new_task(turn.session_id, turn.command, status="planning")
            handle = asyncio.current_task()
            if handle is not None:
                self._handles[turn.task["id"]] = handle
            if turn.emit:
                turn.emit(make_event("task_started", task_id=turn.task["id"], task=self.public(turn.task)))
        return turn.task

    def on_plan(self, plan: Any) -> None:
        turn = current_turn.get()
        if turn is None:
            return
        task = self.ensure_task(turn)
        steps = [
            {
                "index": i,
                "tool": s.tool,
                "description": s.description or _step_label(s.tool, s.arguments),
                "status": "pending",
                "summary": None,
            }
            for i, s in enumerate(plan.steps)
        ]
        changes: dict[str, Any] = {"intent": plan.intent, "steps": steps, "message": "Plan ready"}
        if plan.user_confirmation_prompt:
            changes.update(
                status="waiting_for_confirmation",
                confirmation_prompt=plan.user_confirmation_prompt,
                message="Waiting for your confirmation",
            )
        self.update(task, **changes)

    def on_tool_start(self, request: ToolRequest) -> dict[str, Any] | None:
        turn = current_turn.get()
        if turn is None:
            return None
        task = self.ensure_task(turn)
        step = next((s for s in task["steps"] if s["status"] == "pending" and s["tool"] == request.tool_name), None)
        if step is None:
            step = {
                "index": len(task["steps"]),
                "tool": request.tool_name,
                "description": _step_label(request.tool_name, request.arguments),
                "status": "pending",
                "summary": None,
            }
            task["steps"].append(step)
        step["status"] = "running"
        step["arguments"] = _summarize_args(request.arguments)
        if turn.emit:
            turn.emit(make_event("tool_selected", task_id=task["id"], tool=request.tool_name,
                                       description=step["description"]))
        self.update(task, status="running", message=step["description"])
        if turn.emit:
            turn.emit(make_event("tool_executing", task_id=task["id"], tool=request.tool_name,
                                       step=step["index"]))
        return step

    def on_tool_result(self, step: dict[str, Any] | None, result: ToolResult, summary: str | None = None) -> None:
        turn = current_turn.get()
        if turn is None or step is None or turn.task is None:
            return
        task = turn.task
        needs_confirmation = bool(result.metadata.get("requires_confirmation"))
        step["status"] = "completed" if result.success else ("waiting" if needs_confirmation else "failed")
        step["summary"] = sanitize_text(result.error or summary or result.to_text())[:300]
        if result.success:
            verified, note = postcheck(result.output)
            step["verified"], step["verification_note"] = verified, note
            if verified is False:
                step["status"] = "failed"
                step["summary"] = f"Verification failed: {note}"
        if turn.emit:
            turn.emit(make_event("tool_result", task_id=task["id"], tool=result.tool_name,
                                 success=step["status"] == "completed", summary=step["summary"]))
        changes: dict[str, Any] = {"message": step["summary"]}
        if needs_confirmation:
            changes.update(status="waiting_for_confirmation",
                           confirmation_prompt=result.error or "Confirmation required.")
        self.update(task, **changes)

    def finish_turn(self, turn: TurnContext, response: str | None, error: str | None = None) -> None:
        """Verify step outcomes and close the task for a finished turn."""
        task = turn.task
        if task is None or task["status"] in TERMINAL_STATUSES:
            return
        if error:
            self.update(task, status="failed", error=error, message=error, response=response)
            return
        if task["status"] == "waiting_for_confirmation":
            for s in task["steps"]:
                if s["status"] == "pending":
                    s["status"] = "skipped"
            self.update(task, response=response, message=task.get("confirmation_prompt") or response)
            return
        executed = [s for s in task["steps"] if s["status"] in ("completed", "failed")]
        self.update(task, status="verifying", message="Verifying results")
        if turn.emit:
            turn.emit(make_event("verifying", task_id=task["id"]))
        for s in task["steps"]:
            if s["status"] == "pending":
                s["status"] = "skipped"
        failed = [s for s in executed if s["status"] == "failed"]
        verified_steps = [s for s in executed if s.get("verified") is True]
        verification = {
            "notes": [s["verification_note"] for s in executed if s.get("verification_note")],
            "checked_steps": len(executed),
            "succeeded": len(executed) - len(failed),
            "failed": len(failed),
            "tool_verified": len(verified_steps),
            "summary": (
                "No actions were executed." if not executed
                else f"{len(executed) - len(failed)}/{len(executed)} steps succeeded"
                + (f"; {len(verified_steps)} independently verified" if verified_steps else "")
            ),
        }
        if failed or not executed:
            self.update(task, status="failed", verification=verification, response=response,
                              error=failed[0]["summary"] if failed else "No actions were executed.",
                              message="Task failed")
        else:
            self.update(task, status="completed", verification=verification, response=response,
                              message="Completed")


class ObservedToolExecutor:
    """Delegates to LYRA's ToolExecutor (validation + permissions unchanged) and reports steps."""

    def __init__(self, inner: Any, tracker: TaskTracker) -> None:
        self._inner = inner
        self._tracker = tracker

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    @property
    def offline_mode(self) -> bool:
        return self._inner.offline_mode

    @offline_mode.setter
    def offline_mode(self, value: bool) -> None:
        self._inner.offline_mode = value

    async def execute(self, request: ToolRequest, execution_count: int = 0) -> ToolResult:
        step = self._tracker.on_tool_start(request)
        result = await self._inner.execute(request, execution_count=execution_count)
        summary = None
        try:
            tool = self._inner.registry.get(result.tool_name)
            if tool is not None and result.success and hasattr(tool, "format_result"):
                summary = tool.format_result(result)
        except Exception:
            summary = None
        self._tracker.on_tool_result(step, result, summary)
        return result


class ObservedPlanner:
    """Delegates to LYRA's ActionPlanner and reports generated plans."""

    def __init__(self, inner: Any, tracker: TaskTracker) -> None:
        self._inner = inner
        self._tracker = tracker

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def plan(self, *args: Any, **kwargs: Any) -> Any:
        plan = self._inner.plan(*args, **kwargs)
        if plan is not None:
            self._tracker.on_plan(plan)
        return plan

    async def plan_async(self, *args: Any, **kwargs: Any) -> Any:
        plan = await self._inner.plan_async(*args, **kwargs)
        if plan is not None:
            self._tracker.on_plan(plan)
        return plan
