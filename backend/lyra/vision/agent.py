"""Visual agent: understands screen-related requests and runs SEE → PLAN → ACT → VERIFY → ADAPT.

Routing is contextual: explicit screen language ("look at my screen", "click the Login button")
always routes here; short references ("what's wrong here?", "fix it", "check again") route here
only while a recent screen context exists for the conversation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import time
from typing import Any

from lyra.models.messages import AIRequest, Message, Role
from lyra.models.tools import ToolRequest
from lyra.observability.logging import get_logger, sanitize_text

logger = get_logger("vision.agent")

MAX_STEPS = 6
MAX_RETRIES_PER_STEP = 1
REUSE_CONTEXT_SECONDS = 60.0

_UI_NOUN = r"(?:button|link|field|box|tab|menu|checkbox|check box|dropdown|drop-down|icon|option|toggle|switch|input)"
_OBSERVE = re.compile(
    r"\b(?:look at|check|see|scan|read|analy[sz]e|describe|explain|summari[sz]e)\s+(?:my|the|this|current)\s+(?:screen|display|window|page|tab)\b"
    r"|\bwhat(?:'s| is)\s+(?:on|in)\s+(?:my|the)\s+screen\b"
    r"|\bwhat am i (?:doing|looking at|working on)\b"
    r"|\bwhat(?:'s| is)? (?:currently )?open\b|\bwhich (?:app|application|window)\b|\bwhat (?:app|application) (?:is|am i)\b"
    r"|\bexplain (?:this|what's happening|what is happening)\b|\bwhat(?:'s| is) happening (?:here|on (?:my|the) screen)\b"
    r"|\b(?:read|summari[sz]e) (?:this|the current|the) (?:page|screen|article|document|tab)\b|\bread this(?: for me)?\b"
    r"|\b(?:what(?:'s| is)|explain|why (?:is|am i getting)) (?:this|that|the) error\b|\bfind the error\b|\berror (?:in|on) (?:this|my) (?:code|screen)\b"
    r"|\bwhy (?:isn't|is not|doesn't|does not|won't) (?:this|it) work"
    r"|\bis (?:my|this) code (?:correct|right|ok|okay|fine|working)\b"
    r"|\bwhere (?:is|are) the\b.*\b" + _UI_NOUN + r"\b|\bwhere (?:should|do) i click\b|\bfind the\b.*\b" + _UI_NOUN + r"\b"
    r"|\bwhat should i do next\b|\bwhat(?:'s| is) next\b"
    r"|\b(?:on|in) (?:my|the) screen\b",
    re.I,
)
_ACT = re.compile(
    r"\b(?:click|press|tap|hit|select|choose|check|uncheck|toggle)\b.*\b" + _UI_NOUN + r"\b"
    r"|\bclick (?:on )?(?:that|this|it|the)\b"
    r"|\bfill (?:out|in) (?:this|the)\b|\b(?:type|enter|write)\b.+\b(?:in|into)\b.*\b(?:field|box|input|form)\b"
    r"|\bscroll (?:up|down)\b|\b(?:do|perform) the next step\b|\bhelp me (?:complete|finish) (?:this|the) (?:task|form)\b"
    r"|\b(?:complete|finish) (?:this|the) (?:task|form) (?:for me|on (?:my|the) screen)\b",
    re.I,
)
_FOLLOW_ACT = re.compile(r"^(?:ok(?:ay)?,? )?(?:please )?(?:fix (?:it|this|that|the error)|do it|go ahead(?: and do it)?|click it|try again)\b", re.I)
_VERIFY = re.compile(r"\b(?:check (?:again|whether|if)|now check|is (?:it|the task|this) (?:done|completed|finished|working now)|did (?:it|that) work|verify (?:it|that|the))\b", re.I)
_FOLLOW_ASK = re.compile(r"\b(?:here|this|that|it|the error|the button|the page|the screen|the code)\b", re.I)
_CLEAR = re.compile(r"\b(?:clear|forget|reset)\b.*\b(?:screen|visual)\b.*\bcontext\b|\bforget what you saw\b", re.I)
_YES = re.compile(r"^(?:yes|yeah|yep|sure|ok(?:ay)?|go ahead|do it|confirm(?:ed)?|proceed)\b", re.I)
_NO = re.compile(r"^(?:no|nope|cancel|stop|don't|do not|abort)\b", re.I)

_DIRECT_CLICK = re.compile(
    r"^(?:please )?(?:click|press|tap|hit|select|choose)(?: on)? (?:the )?['\"“]?(.+?)['\"”]?(?: " + _UI_NOUN + r")?(?: for me)?[.!]?$",
    re.I,
)
_DIRECT_TYPE = re.compile(
    r"^(?:please )?(?:type|enter|write) ['\"“](.+?)['\"”] (?:in|into) (?:the )?(.+?)(?: field| box| input)?[.!]?$", re.I)
_DIRECT_SCROLL = re.compile(r"^(?:please )?scroll (up|down)\b", re.I)


@dataclass
class _Pending:
    goal: str
    action: dict[str, Any]
    created: float = field(default_factory=time.monotonic)


class VisualAgent:
    def __init__(self, awareness: Any, router: Any, tool_executor: Any = None, styler: Any = None) -> None:
        self.aw = awareness
        self.router = router
        self.tool_executor = tool_executor
        self.boss = getattr(styler, "boss", "Boss")
        self._pending: dict[str, _Pending] = {}
        self._last_goal: dict[str, dict[str, Any]] = {}

    # --------------------------------------------------------------- routing
    def classify(self, text: str, session_id: str | None) -> str | None:
        if getattr(self.aw, "server_mode", False):
            # Deployed on a server: be honest instead of letting the AI pretend it can see the screen.
            return "unavailable" if (_OBSERVE.search(text or "") or _ACT.search(text or "")) else None
        if not self.aw.enabled:
            return None
        t = (text or "").strip()
        sid = session_id or "_"
        if sid in self._pending and (_YES.match(t) or _NO.match(t)):
            return "confirm"
        if _CLEAR.search(t):
            return "clear"
        if re.search(r"\b\d{2,4}\s*,\s*\d{2,4}\b", t):
            return None  # explicit coordinates: existing mouse tool handles these
        has_ctx = self.aw.context(session_id) is not None
        if _ACT.search(t) or (has_ctx and _FOLLOW_ACT.search(t)):
            return "act"
        if has_ctx and _VERIFY.search(t):
            return "verify"
        if _OBSERVE.search(t):
            return "observe"
        if has_ctx and len(t.split()) <= 12 and _FOLLOW_ASK.search(t) and t.endswith("?"):
            return "followup"
        return None

    # --------------------------------------------------------------- helpers
    async def _screen(self, session_id: str | None, **args: Any):
        req = ToolRequest(tool_name="screen", arguments=args, session_id=session_id)
        if self.tool_executor is not None:
            return await self.tool_executor.execute(req)
        from lyra.tools.screen_tool import ScreenTool

        return await ScreenTool(self.aw).execute(req)

    def _permission_reply(self, error: str | None) -> str:
        return (f"I'm sorry, {self.boss} — I can't see your screen yet. macOS hasn't given me Screen Recording "
                "permission. You can enable it in System Settings → Privacy & Security → Screen & System Audio "
                "Recording for the app running my backend, then restart me.")

    def _local_reply(self, ctx: dict[str, Any], question: str) -> str:
        app = ctx.get("active_app") or "an app"
        title = f" ({ctx['window_title']})" if ctx.get("window_title") else ""
        lines = [f"You're in {app}{title}."]
        if re.search(r"\bread\b", question, re.I) and ctx.get("visible_text"):
            lines.append("Here's the text I can read on screen:\n\n" + ctx["visible_text"][:1500])
        elif ctx.get("errors"):
            lines.append("I can see what looks like an error: “" + ctx["errors"][0][:200] + "”.")
        if not self.aw.cloud_consent:
            lines.append("To understand the screen in detail and answer questions about it, I need your permission "
                         "to send screenshots to an AI vision model — you can allow it in Settings → Screen awareness.")
        else:
            lines.append("No vision-capable AI model is reachable right now, so I could only read the text locally.")
        return " ".join(lines[:1]) + ("\n\n" + "\n\n".join(lines[1:]) if len(lines) > 1 else "")

    # --------------------------------------------------------------- handlers
    async def handle(self, kind: str, text: str, session_id: str | None) -> str:
        if kind == "unavailable":
            return (f"I'm sorry, {self.boss} — I'm running on a cloud server right now, so I can't see or control "
                    "your screen. Screen awareness works when LYRA runs on your Mac.")
        if kind == "clear":
            self.aw.clear_context(session_id)
            self._pending.pop(session_id or "_", None)
            return f"Done, {self.boss}. I've cleared what I saw on your screen."
        if kind == "confirm":
            return await self._confirm(text, session_id)
        if kind == "observe":
            return await self._observe(text, session_id)
        if kind == "followup":
            return await self._followup(text, session_id)
        if kind == "verify":
            return await self._verify(text, session_id)
        return await self._act(text, session_id)

    async def _observe(self, question: str, session_id: str | None) -> str:
        # "Which app is open?" needs no screenshot at all.
        if re.search(r"\bwhich (?:app|application)\b|\bwhat (?:app|application)\b|\bwhat(?:'s| is)? (?:currently )?open\b", question, re.I) \
                and not re.search(r"\bscreen\b|\bexplain\b|\bread\b", question, re.I):
            from lyra.vision.apps import active_window

            win = active_window()
            if win:
                title = f" — the window is “{win['title']}”" if win.get("title") else ""
                return f"You're currently using {win['app']}{title}."
        res = await self._screen(session_id, action="observe", question=question)
        if not res.success:
            return self._permission_reply(res.error) if res.metadata.get("permission") else \
                f"I'm sorry, {self.boss} — I couldn't capture your screen: {res.error}"
        ctx = res.output
        if ctx.get("analysis_source", "").startswith("vision") and (ctx.get("answer") or ctx.get("summary")):
            reply = ctx.get("answer") or ctx.get("summary")
            if ctx.get("errors") and re.search(r"\berror\b", question, re.I) and ctx["errors"][0] not in reply:
                reply += f"\n\nVisible error: “{ctx['errors'][0]}”"
            return reply
        return self._local_reply(ctx, question)

    async def _followup(self, question: str, session_id: str | None) -> str:
        ctx = self.aw.context(session_id)
        age = time.monotonic() - self.aw._contexts[session_id or "_"][0] if ctx else None
        if ctx is None or age is None or age > REUSE_CONTEXT_SECONDS or not self.aw.cloud_consent:
            return await self._observe(question, session_id)  # stale or local-only: look again
        req = AIRequest(
            messages=(Message(role=Role.USER, content=(
                "Answer the user's question about their screen using only this captured screen context.\n\n"
                f"{ctx.prompt_block()}\n\nQuestion: {question}")),),
            system_prompt="You are LYRA, a warm and concise assistant. Never invent things not in the context.",
            max_tokens=500,
        )
        try:
            return (await self.router.route(req)).content
        except Exception:
            return await self._observe(question, session_id)

    async def _verify(self, text: str, session_id: str | None) -> str:
        last = self._last_goal.get(session_id or "_")
        expected = (last or {}).get("expected") or (last or {}).get("goal") or "the requested task is completed"
        res = await self._screen(session_id, action="verify", expected=expected)
        out = res.output or {}
        if res.metadata.get("permission"):
            return self._permission_reply(res.error)
        if out.get("verified"):
            return f"I checked again, {self.boss} — it looks done. {out.get('evidence') or ''}".strip()
        if out.get("verified") is None:
            return f"I looked again, but I can't tell for sure from the screen. {out.get('screen') or ''}".strip()
        return f"I checked again and it doesn't look finished yet: {out.get('evidence') or 'the expected result is not visible'}."

    async def _confirm(self, text: str, session_id: str | None) -> str:
        pending = self._pending.pop(session_id or "_", None)
        if pending is None or _NO.match(text.strip()):
            return f"Okay, {self.boss}. I won't do that."
        return await self._act(pending.goal, session_id, preset=pending.action, confirmed=True)

    def _direct_action(self, text: str) -> dict[str, Any] | None:
        t = text.strip()
        if m := _DIRECT_SCROLL.match(t):
            return {"action": "scroll", "direction": m.group(1).lower(), "expected": ""}
        if m := _DIRECT_TYPE.match(t):
            return {"action": "type", "text": m.group(1), "target": m.group(2), "expected": m.group(1)}
        if (m := _DIRECT_CLICK.match(t)) and not re.search(r"\b(?:and|then)\b", t, re.I):
            target = re.sub(r"^(?:that|this|it)$", "", m.group(1).strip(), flags=re.I)
            if target:
                return {"action": "click", "target": target, "expected": ""}
        return None

    async def _act(self, goal_text: str, session_id: str | None, preset: dict[str, Any] | None = None,
                   confirmed: bool = False) -> str:
        sid = session_id or "_"
        goal = goal_text
        prev = self.aw.context(session_id)
        if _FOLLOW_ACT.search(goal_text) and prev is not None:
            focus = "; ".join(prev.errors[:2]) or prev.suggested_next_action or prev.summary
            goal = f"{goal_text} — regarding the current screen: {focus}"
        history: list[str] = []
        direct = preset or self._direct_action(goal_text)

        for step in range(MAX_STEPS):
            action = direct
            if action is None:
                obs = await self._screen(session_id, action="observe", use_ai=False)
                if not obs.success:
                    return self._permission_reply(obs.error) if obs.metadata.get("permission") else \
                        f"I'm sorry, {self.boss} — I couldn't look at the screen: {obs.error}"
                ctx = self.aw.context(session_id)
                shot = self.aw._contexts[sid][2]
                try:
                    action = await self.aw.analyzer.decide_action(
                        shot, goal, ctx.prompt_block(), history, local_only=not self.aw.cloud_consent)
                except Exception as err:
                    logger.info("Visual planning unavailable: %s", sanitize_text(str(err))[:160])
                    if not history:
                        return (f"I'm sorry, {self.boss} — planning multi-step screen tasks needs an AI vision model, "
                                "and none is available right now"
                                + ("" if self.aw.cloud_consent else " (screen sharing with cloud AI is off in Settings)")
                                + ". Simple commands like “click the Login button” still work locally.")
                    break
            kind = str(action.get("action") or "").lower()
            if kind == "done":
                self._last_goal[sid] = {"goal": goal, "expected": action.get("expected")}
                return (f"Done, {self.boss}. " if history else "It looks like that's already done. ") + \
                    (action.get("reason") or "The task looks complete on screen.")
            if kind == "blocked":
                return f"I'm sorry, {self.boss} — I can't finish this one: {action.get('reason') or 'I am blocked'}."

            args = {k: action.get(k) for k in ("target", "element_id", "text", "key", "direction") if action.get(k)}
            res = await self._screen(session_id, action=kind, confirmed=confirmed,
                                     sensitive=bool(action.get("sensitive")), **args)
            if res.metadata.get("requires_confirmation"):
                self._pending[sid] = _Pending(goal=goal, action=action)
                target = (res.output or {}).get("target") or action.get("target") or "that"
                return (f"Before I continue, {self.boss}: the next step is to {kind} “{target}”, which could be "
                        "irreversible. Should I go ahead?")
            if not res.success:
                if res.metadata.get("permission"):
                    return self._permission_reply(res.error)
                history.append(f"{step + 1}. {kind} {args} → FAILED: {res.error}")
                if direct is not None:
                    return f"I'm sorry, {self.boss} — {res.error}"
                continue  # adapt: re-observe and let the planner choose a different step
            confirmed = False  # confirmation covers only the step that was approved
            expected = str(action.get("expected") or "").strip()
            verdict = "not checked"
            if expected:
                ver = await self._screen(session_id, action="verify", expected=expected)
                vo = ver.output or {}
                verdict = "verified" if vo.get("verified") else ("unclear" if vo.get("verified") is None else "NOT verified")
                if vo.get("verified") is False and len([h for h in history if "NOT verified" in h]) >= MAX_RETRIES_PER_STEP + 1:
                    return (f"I tried, {self.boss}, but I couldn't confirm the result on screen "
                            f"({vo.get('evidence') or 'no evidence'}). You may want to take a look.")
            target = (res.output or {}).get("target") or args.get("target") or ""
            history.append(f"{step + 1}. {kind} {target or args} → done ({verdict})")
            self._last_goal[sid] = {"goal": goal, "expected": expected or None}
            if direct is not None:
                if kind == "click" and target:
                    return f"Done, {self.boss}. I clicked “{target}”." + (" I can see the expected result." if verdict == "verified" else "")
                if kind == "type":
                    return f"Done, {self.boss}. I typed that into “{target}”."
                return f"Done, {self.boss}. I scrolled {action.get('direction', 'down')}."
        steps = "\n".join(history) or "(no steps)"
        return (f"I worked on it step by step, {self.boss}, but stopped after {len(history)} steps without confirming "
                f"it's finished. Here's what I did:\n{steps}\nSay “check again” and I'll look at the screen.")
