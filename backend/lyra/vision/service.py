"""Screen awareness: SEE → UNDERSTAND → ACT → VERIFY, plus opt-in change monitoring.

Privacy model
* Capture happens only on request (or while the user has explicitly turned monitoring on).
* Screenshots live in memory only, never on disk, and are dropped with the visual context.
* Sending screen content to *cloud* AI requires the user's consent setting; without it LYRA
  uses local OCR/accessibility only (or a local Ollama vision model if one is installed).
* Actions go through the existing ComputerController policy; sensitive steps need confirmation.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import sys
import time
from typing import Any, Callable

from lyra.computer.models import ComputerAction, ComputerActionType, Point
from lyra.observability.logging import get_logger
from lyra.vision import apps
from lyra.vision.analyzer import VisionAnalyzer, VisionUnavailableError, vision_elements
from lyra.vision.capture import ScreenCaptureError, ScreenCaptureService, ScreenPermissionError
from lyra.vision.elements import accessibility_elements, center, locate, ocr_elements
from lyra.vision.models import ScreenContext, Screenshot, UIElement, utc_now
from lyra.vision.ocr import lines_to_text, ocr_available, recognize_text

logger = get_logger("vision.service")

CONTEXT_TTL_SECONDS = 600.0
FRESH_SCREENSHOT_SECONDS = 15.0
_ERROR_RE = re.compile(r"\b(error|exception|traceback|failed|failure|fatal|cannot|can't|unable to|denied|not found|invalid|undefined)\b", re.I)
_WARN_RE = re.compile(r"\b(warning|deprecated|caution)\b", re.I)
SENSITIVE_RE = re.compile(
    r"\b(delete|remove|erase|format|uninstall|pay|purchase|buy|checkout|order|transfer|send|submit|publish|post|"
    r"sign out|log ?out|unsubscribe|reset|discard|confirm payment|place order|empty trash|deactivate)\b", re.I)
_SECRET_FIELD_RE = re.compile(r"\b(password|passcode|pin|cvv|card number|ssn|secret|token|api key)\b", re.I)


class VisualActionError(Exception):
    pass


class ScreenAwareness:
    def __init__(self, router: Any, computer_controller: Any = None, settings: Any = None) -> None:
        self.capture_service = ScreenCaptureService()
        self.analyzer = VisionAnalyzer(router, settings)
        self.computer = computer_controller
        self.enabled = True
        self.server_mode = False            # running on a remote server: there is no user screen here
        self.cloud_consent = False          # user must opt in before screen content goes to cloud AI
        self.state = "idle"
        self.state_detail: str | None = None
        self._listeners: list[Callable[[dict[str, Any]], None]] = []
        self._contexts: dict[str, tuple[float, ScreenContext, Screenshot | None, list[UIElement]]] = {}
        self.monitor = ScreenMonitor(self)

    # ------------------------------------------------------------- state/events
    def add_listener(self, fn: Callable[[dict[str, Any]], None]) -> None:
        self._listeners.append(fn)

    def _emit(self, event: dict[str, Any]) -> None:
        for fn in list(self._listeners):
            try:
                fn(event)
            except Exception:
                pass

    def set_state(self, state: str, detail: str | None = None) -> None:
        self.state, self.state_detail = state, detail
        self._emit({"type": "vision_state", "state": state, "detail": detail})

    # ------------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        win = apps.active_window() if sys.platform == "darwin" else None
        latest = max(self._contexts.values(), key=lambda v: v[0], default=None)
        return {
            "enabled": self.enabled,
            "state": self.state if self.enabled else "disabled",
            "state_detail": self.state_detail,
            "platform_supported": self.capture_service.supported and not self.server_mode,
            "server_mode": self.server_mode,
            "screen_permission": self.capture_service.permission_status(),
            "accessibility_permission": apps.accessibility_trusted(),
            "ocr_available": ocr_available(),
            "cloud_consent": self.cloud_consent,
            "vision": self.analyzer.status(),
            "displays": self.capture_service.displays(),
            "active_app": (win or {}).get("app"),
            "active_window": (win or {}).get("title"),
            "monitoring": self.monitor.status(),
            "context_age_seconds": round(time.monotonic() - latest[0], 1) if latest else None,
        }

    # ----------------------------------------------------------------- context
    def context(self, session_id: str | None) -> ScreenContext | None:
        item = self._contexts.get(session_id or "_")
        if not item or time.monotonic() - item[0] > CONTEXT_TTL_SECONDS:
            return None
        return item[1]

    def clear_context(self, session_id: str | None = None) -> None:
        if session_id is None:
            self._contexts.clear()
        else:
            self._contexts.pop(session_id, None)
        self._emit({"type": "vision_context", "cleared": True})

    def _store(self, session_id: str | None, ctx: ScreenContext, shot: Screenshot | None, els: list[UIElement]) -> None:
        self._contexts[session_id or "_"] = (time.monotonic(), ctx, shot, els)
        self._emit({"type": "vision_context", "context": ctx.to_dict()})

    # ------------------------------------------------------------------ observe
    async def observe(
        self,
        session_id: str | None = None,
        question: str | None = None,
        use_ai: bool = True,
        target: str = "screen",          # screen | active_window
        display: int | None = None,
        fast_ocr: bool = False,
    ) -> ScreenContext:
        if not self.enabled:
            raise VisualActionError("Screen awareness is turned off in Settings.")
        self.set_state("capturing")
        try:
            win = apps.active_window()
            if target == "active_window" and win and win.get("window_id"):
                shot = await self.capture_service.capture(window_id=win["window_id"], window_info=win)
            else:
                shot = await self.capture_service.capture(display=display)
        except ScreenPermissionError:
            self.set_state("permission_denied")
            raise
        except ScreenCaptureError:
            self.set_state("failed", "Screen capture failed")
            raise

        self.set_state("analyzing")
        lines = await recognize_text(shot.png, fast=fast_ocr)
        ax_els = accessibility_elements(win["pid"], shot) if win else []
        els: list[UIElement] = ax_els + ocr_elements(lines)
        visible_text = lines_to_text(lines)
        errors = sorted({l.text.strip() for l in lines if _ERROR_RE.search(l.text)})[:8]
        warnings = sorted({l.text.strip() for l in lines if _WARN_RE.search(l.text)})[:8]

        summary = (f"{(win or {}).get('app') or 'An app'} is in front"
                   + (f" ('{win['title']}')" if win and win.get("title") else "")
                   + f"; {len(lines)} lines of text and {sum(e.actionable for e in els)} actionable elements detected.")
        page_state = answer = next_action = None
        confidence, source = 0.55, "local"
        if use_ai:
            local_only = not self.cloud_consent
            try:
                data = await self.analyzer.analyze(shot, lines, els, win, question=question, local_only=local_only)
                summary = str(data.get("summary") or summary)
                page_state = data.get("page_state")
                answer = data.get("answer")
                next_action = data.get("suggested_next_action")
                errors = list(dict.fromkeys([*map(str, data.get("errors") or []), *errors]))[:10]
                warnings = list(dict.fromkeys([*map(str, data.get("warnings") or []), *warnings]))[:10]
                v_els = vision_elements(data, shot, els)
                known_ids = {e.id for e in v_els}
                els = v_els + [e for e in els if e.id not in known_ids]
                confidence = float(data.get("confidence") or 0.7)
                source = f"vision:{data['_source']}"
            except VisionUnavailableError as err:
                source = "local"
                self.state_detail = str(err)
                if local_only:
                    self.state_detail = "Cloud vision not permitted; used local OCR."

        ctx = ScreenContext(
            captured_at=shot.captured_at, active_app=(win or {}).get("app"), window_title=(win or {}).get("title"),
            summary=summary, visible_text=visible_text, elements=els, errors=errors, warnings=warnings,
            page_state=page_state, suggested_next_action=next_action, confidence=round(confidence, 2),
            analysis_source=source, screenshot=shot.meta(), ocr_lines=len(lines), question=question, answer=answer,
        )
        self._store(session_id, ctx, shot, els)
        self.set_state("analyzed", source)
        return ctx

    def latest_screenshot_png(self, session_id: str | None) -> bytes | None:
        item = self._contexts.get(session_id or "_")
        return item[2].png if item and item[2] else None

    # ------------------------------------------------------------------- act
    async def _fresh(self, session_id: str | None) -> tuple[Screenshot, list[UIElement]]:
        item = self._contexts.get(session_id or "_")
        if item and item[2] and time.monotonic() - item[0] <= FRESH_SCREENSHOT_SECONDS:
            return item[2], item[3]
        await self.observe(session_id, use_ai=False, fast_ocr=True)  # never reuse stale coordinates
        item = self._contexts[session_id or "_"]
        return item[2], item[3]  # type: ignore[return-value]

    def is_sensitive(self, action: dict[str, Any], element: UIElement | None) -> bool:
        label = " ".join(str(x) for x in (action.get("target"), element.label if element else "") if x)
        return bool(action.get("sensitive")) or bool(SENSITIVE_RE.search(label))

    async def perform(self, action: dict[str, Any], session_id: str | None, confirmed: bool) -> dict[str, Any]:
        """Execute one UI step via the existing ComputerController (policy enforced)."""
        if self.computer is None:
            raise VisualActionError("Computer control is not available.")
        kind = str(action.get("action") or "").lower()
        self.set_state("executing", kind)
        element: UIElement | None = None
        result: dict[str, Any] = {"action": kind}
        if kind in ("click", "type"):
            shot, els = await self._fresh(session_id)
            target = str(action.get("target") or "")
            element = locate(target, els, action.get("element_id")) if (target or action.get("element_id")) else None
            if kind == "click" and element is None:
                raise VisualActionError(f"I couldn't find '{target}' on the current screen.")
            if self.is_sensitive(action, element) and not confirmed:
                return {**result, "requires_confirmation": True, "target": element.label if element else target}
            secret_field = (element is not None and element.type == "password_field") or bool(_SECRET_FIELD_RE.search(target))
            if kind == "type" and secret_field:
                raise VisualActionError("I don't type passwords or other secrets — please enter that yourself.")
            if element is not None:
                cx, cy = center(element)
                x, y = shot.to_screen_point(cx, cy)
                res = await self.computer.execute_action(
                    ComputerAction(action_type=ComputerActionType.CLICK, point=Point(x, y), confirmed=True))
                if not res.success:
                    raise VisualActionError(res.error or "Click failed.")
                result.update(target=element.label, element_type=element.type, source=element.source,
                              point=[x, y])
            if kind == "type":
                text = str(action.get("text") or "")
                if not text:
                    raise VisualActionError("Nothing to type.")
                res = await self.computer.execute_action(
                    ComputerAction(action_type=ComputerActionType.TYPE_TEXT, text=text, confirmed=True))
                if not res.success:
                    raise VisualActionError(res.error or "Typing failed.")
                result["typed_chars"] = len(text)
        elif kind == "press":
            key = str(action.get("key") or "return").lower()
            res = await self.computer.execute_action(
                ComputerAction(action_type=ComputerActionType.PRESS_KEY, key=key, confirmed=True))
            if not res.success:
                raise VisualActionError(res.error or "Key press failed.")
            result["key"] = key
        elif kind == "scroll":
            key = "pageup" if str(action.get("direction") or "down").lower() == "up" else "pagedown"
            res = await self.computer.execute_action(
                ComputerAction(action_type=ComputerActionType.PRESS_KEY, key=key, confirmed=True))
            if not res.success:
                raise VisualActionError(res.error or "Scroll failed.")
            result["direction"] = "up" if key == "pageup" else "down"
        else:
            raise VisualActionError(f"Unsupported visual action '{kind}'.")
        self._contexts.pop(session_id or "_", None)  # the screen changed; old coordinates are stale now
        return result

    # ----------------------------------------------------------------- verify
    async def verify(self, expectation: str, session_id: str | None, use_ai: bool = True) -> dict[str, Any]:
        """Re-capture and check that the expected state is visible."""
        self.set_state("verifying")
        await asyncio.sleep(0.8)  # let the UI settle
        ctx = await self.observe(session_id, use_ai=False, fast_ocr=False)
        words = [w for w in re.findall(r"[A-Za-z0-9][\w'-]{3,}", expectation or "") if w.lower() not in
                 {"should", "visible", "screen", "appear", "appears", "shown", "page", "with", "that", "this", "the", "have", "been"}]
        quoted = re.findall(r"['\"“”‘’]([^'\"“”‘’]{2,60})['\"“”‘’]", expectation or "")
        text = ctx.visible_text.lower()
        if quoted:
            hits = [q for q in quoted if q.lower() in text]
            local = {"verified": len(hits) == len(quoted), "evidence": f"Found {len(hits)}/{len(quoted)} expected texts on screen", "method": "ocr"}
        elif words:
            hits = [w for w in words if w.lower() in text]
            ratio = len(hits) / len(words)
            local = {"verified": ratio >= 0.6, "evidence": f"{len(hits)}/{len(words)} expected words visible", "method": "ocr"}
        else:
            local = {"verified": None, "evidence": "No checkable text in expectation", "method": "ocr"}
        if use_ai and local["verified"] is not True:
            item = self._contexts.get(session_id or "_")
            try:
                ai = await self.analyzer.verify(item[2], expectation, local_only=not self.cloud_consent)  # type: ignore[index]
                local = {"verified": bool(ai.get("verified")), "evidence": str(ai.get("evidence") or ""),
                         "method": f"vision:{ai.get('_source')}", "confidence": ai.get("confidence")}
            except Exception:
                pass
        self.set_state("analyzed")
        return {**local, "screen": ctx.summary}


class ScreenMonitor:
    """Opt-in, low-cost change detection: app/window switches every tick; content hash only with permission."""

    def __init__(self, awareness: ScreenAwareness) -> None:
        self.aw = awareness
        self.interval = 4.0
        self.detect_errors = True
        self._task: asyncio.Task | None = None
        self._last: dict[str, Any] = {}
        self.events: list[dict[str, Any]] = []
        self.started_at: str | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict[str, Any]:
        return {"running": self.running, "interval_seconds": self.interval, "started_at": self.started_at,
                "recent_events": self.events[-10:]}

    def start(self, interval: float | None = None) -> dict[str, Any]:
        if interval:
            self.interval = max(2.0, min(60.0, float(interval)))
        if not self.running:
            self._last = {}
            self.started_at = utc_now()
            self._task = asyncio.create_task(self._loop())
            self.aw.set_state("monitoring")
        return self.status()

    async def stop(self) -> dict[str, Any]:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        self.started_at = None
        self.aw.set_state("idle")
        return self.status()

    def _record(self, kind: str, detail: str) -> None:
        ev = {"type": "screen_change", "change": kind, "detail": detail, "at": utc_now()}
        self.events = (self.events + [ev])[-50:]
        self.aw._emit(ev)

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as err:
                logger.debug("monitor tick failed: %s", err)
            await asyncio.sleep(self.interval)

    async def tick(self) -> None:
        win = apps.active_window() or {}
        app, title = win.get("app"), win.get("title")
        if self._last.get("app") and app != self._last.get("app"):
            self._record("app_switch", f"{self._last.get('app')} → {app}")
        elif self._last.get("title") and title and title != self._last.get("title"):
            self._record("window_change", f"{title}")
        self._last.update(app=app, title=title)
        if self.aw.capture_service.permission_status() != "granted":
            return
        try:
            shot = await self.aw.capture_service.capture()
        except Exception:
            return
        # Cheap signature first; OCR only when pixels changed. Digits are ignored so clocks don't count.
        digest = hashlib.blake2b(shot.png[:: max(1, len(shot.png) // 4096)], digest_size=8).hexdigest()
        if digest == self._last.get("digest"):
            return
        self._last["digest"] = digest
        lines = await recognize_text(shot.png, fast=True)
        texts = {re.sub(r"\d+", "#", l.text.strip().lower()) for l in lines if len(l.text.strip()) > 2}
        prev_texts: set[str] = self._last.get("texts") or set()
        self._last["texts"] = texts
        errs = [l.text for l in lines if _ERROR_RE.search(l.text)]
        prev_errs = self._last.get("errors") or []
        self._last["errors"] = errs
        if not prev_texts:
            return  # first observation establishes the baseline
        if self.detect_errors and [e for e in errs if e not in prev_errs]:
            self._record("error_appeared", next(e for e in errs if e not in prev_errs)[:160])
        elif self.detect_errors and prev_errs and not errs:
            self._record("error_cleared", "Previously visible errors are gone")
        else:
            union = len(texts | prev_texts) or 1
            if len(texts ^ prev_texts) / union > 0.3:
                self._record("content_changed", "The screen content changed significantly")
