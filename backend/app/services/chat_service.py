"""Runs conversational turns through LYRA's CompanionOrchestrator for the API."""

from __future__ import annotations

import asyncio
from typing import Any, Sequence

from lyra.companion.orchestrator import CompanionOrchestrator
from lyra.models.messages import Role
from lyra.models.stream import CancellationToken, StreamCompleted, StreamError, StreamStarted, TextDelta
from lyra.observability.logging import get_logger, sanitize_text

from app.core.errors import APIError
from app.services.events import make_event
from app.services.session_service import SessionService
from app.services.task_service import Emitter, TaskTracker, TurnContext, current_turn

logger = get_logger("api.chat")

MAX_MESSAGE_CHARS = 8000


class ChatService:
    def __init__(self, orchestrator: CompanionOrchestrator, sessions: SessionService, tracker: TaskTracker) -> None:
        self.orchestrator = orchestrator
        self.sessions = sessions
        self.tracker = tracker
        self._waiting_by_session: dict[str, list[dict[str, Any]]] = {}

    @staticmethod
    def validate_message(message: str) -> str:
        text = (message or "").strip()
        if not text:
            raise APIError("VALIDATION_ERROR", "Message cannot be empty.", 422)
        if len(text) > MAX_MESSAGE_CHARS:
            raise APIError("VALIDATION_ERROR", f"Message is too long (max {MAX_MESSAGE_CHARS} characters).", 422)
        return text

    async def run_turn(
        self,
        message: str,
        session_id: str | None = None,
        *,
        parts: Sequence[Any] | None = None,
        emit: Emitter | None = None,
        stream: bool = False,
        task: dict[str, Any] | None = None,
        source: str = "chat",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one turn. Raises APIError(SESSION_BUSY) if the session is mid-turn."""
        text = self.validate_message(message)
        session = self.sessions.resolve(session_id)
        lock = self.sessions.lock_for(session.session_id)
        if lock.locked():
            raise APIError("SESSION_BUSY", "LYRA is still working on the previous message in this chat.", 409)

        async with lock:
            if task is not None:
                task["session_id"] = session.session_id
            turn = TurnContext(session_id=session.session_id, command=text, emit=emit, task=task, source=source)
            runner = asyncio.create_task(self._execute(turn, session, text, parts, stream, metadata))
            if task is not None:
                self.tracker.attach_handle(task["id"], runner)
            try:
                return await runner
            except asyncio.CancelledError:
                if not runner.done():
                    runner.cancel()
                return {
                    "response": "Stopped.",
                    "session_id": session.session_id,
                    "task_id": turn.task["id"] if turn.task else None,
                    "task": self.tracker.public(turn.task) if turn.task else None,
                    "cancelled": True,
                }

    async def _execute(
        self,
        turn: TurnContext,
        session: Any,
        text: str,
        parts: Sequence[Any] | None,
        stream: bool,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current_turn.set(turn)
        if turn.task is not None:
            self.tracker.update(turn.task, status="planning", message="Understanding request")
        emit = turn.emit or (lambda _e: None)
        emit(make_event("thinking", session_id=session.session_id, message="Thinking…"))

        provider: str | None = None
        model: str | None = None
        cancelled = False
        try:
            if stream:
                token = CancellationToken()
                chunks: list[str] = []
                stream_error: str | None = None
                try:
                    async for event in self.orchestrator.stream_turn(session, text, parts=parts, metadata=metadata,
                                                                     cancellation_token=token):
                        if isinstance(event, StreamStarted):
                            provider, model = event.provider, event.model
                            emit(make_event("response_start", session_id=session.session_id,
                                            provider=provider, model=model))
                        elif isinstance(event, TextDelta):
                            chunks.append(event.delta)
                            emit(make_event("response_delta", session_id=session.session_id, delta=event.delta))
                        elif isinstance(event, StreamError):
                            stream_error = event.error_message
                        elif isinstance(event, StreamCompleted) and not chunks:
                            chunks.append(event.full_text)
                except asyncio.CancelledError:
                    token.cancel()
                    raise
                reply = "".join(chunks) or (stream_error or "")
                if stream_error and not chunks:
                    emit(make_event("error", session_id=session.session_id,
                                    error={"code": "PROVIDER_UNAVAILABLE", "message": stream_error}))
            else:
                reply = await self.orchestrator.process_turn(session, text, parts=parts, metadata=metadata)
                last = session.messages[-1] if session.messages else None
                if last is not None and last.role == Role.ASSISTANT:
                    model = (last.metadata or {}).get("model")

            self._finish(turn, reply)
            return {
                "response": reply,
                "session_id": session.session_id,
                "task_id": turn.task["id"] if turn.task else None,
                "task": self.tracker.public(turn.task) if turn.task else None,
                "provider": provider,
                "model": model,
            }
        except asyncio.CancelledError:
            cancelled = True
            if turn.task is not None:
                self.tracker.update(turn.task, status="cancelled", message="Cancelled by user")
            raise
        except APIError:
            raise
        except Exception as err:
            clean = sanitize_text(str(err))
            logger.error("Turn failed for session %s: %s", session.session_id, clean)
            if turn.task is not None:
                self.tracker.finish_turn(turn, None, error="The task failed unexpectedly.")
            raise APIError("CHAT_FAILED", "LYRA could not complete this request.", 500) from err
        finally:
            self.sessions.persist_new_messages(session)
            if cancelled:
                logger.info("Turn cancelled for session %s", session.session_id)

    def _finish(self, turn: TurnContext, reply: str) -> None:
        task = turn.task
        sid = turn.session_id
        # Resolve earlier tasks in this chat that were waiting for a yes/no answer.
        previous = self._waiting_by_session.pop(sid, [])
        if task is not None:
            if task.get("intent") == "cancel_action":
                self.tracker.update(task, status="cancelled", response=reply, message=reply)
            elif turn.source == "task" and not task["steps"]:
                self.tracker.update(task, status="completed", response=reply, message="Answered without actions",
                                    verification={"summary": "No tool actions were required."})
            else:
                self.tracker.finish_turn(turn, reply)
        for old in previous:
            if old is task or old["status"] != "waiting_for_confirmation":
                continue
            if task is not None and task["status"] in ("completed", "failed") and task["steps"]:
                self.tracker.update(old, status=task["status"], followed_by=task["id"],
                                    message=f"Resolved by follow-up task {task['id']}")
            else:
                self.tracker.update(old, status="cancelled", message="Not confirmed")
        if task is not None and task["status"] == "waiting_for_confirmation":
            self._waiting_by_session.setdefault(sid, []).append(task)
