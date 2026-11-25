"""Task understanding and multi-step action planning engine for LYRA."""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from typing import Any, Sequence
from urllib.parse import quote_plus

from lyra.companion.session import Session
from lyra.models.messages import AIRequest, Role
from lyra.models.tools import ToolRequest
from lyra.observability.logging import get_logger
from lyra.routing.router import ModelRouter
from lyra.tools.registry import ToolRegistry

logger = get_logger("companion.planner")


@dataclass
class ActionStep:
    """A single discrete step in a task execution plan."""

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    description: str | None = None

    def to_tool_request(self, session_id: str | None = None, user_id: str | None = None) -> ToolRequest:
        """Convert step into canonical ToolRequest."""
        return ToolRequest(
            tool_name=self.tool,
            arguments=self.arguments,
            session_id=session_id,
            user_id=user_id,
        )


@dataclass
class TaskPlan:
    """Structured plan containing intent and sequential action steps."""

    intent: str
    steps: list[ActionStep] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    user_confirmation_prompt: str | None = None

    @property
    def is_empty(self) -> bool:
        return len(self.steps) == 0

    @property
    def tool_name(self) -> str | None:
        return self.steps[0].tool if self.steps else None

    @property
    def arguments(self) -> dict[str, Any]:
        return self.steps[0].arguments if self.steps else {}

    @property
    def requires_confirmation(self) -> bool:
        return self.user_confirmation_prompt is not None


class ActionPlanner:
    """Understands user intent, decomposes multi-step tasks, and produces structured TaskPlans."""

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        router: ModelRouter | None = None,
        capability_registry: Any | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.router = router
        from lyra.core.capabilities import CapabilityRegistry
        from lyra.routing.intent_router import IntentRouter
        self.capability_registry = capability_registry or CapabilityRegistry()
        self.intent_router: IntentRouter = IntentRouter()
        self._session_task_contexts: dict[str, dict[str, Any]] = {}

    def get_task_context(self, session_id: str) -> dict[str, Any]:
        """Retrieve short-term task memory context for a session."""
        if session_id not in self._session_task_contexts:
            self._session_task_contexts[session_id] = {}
        return self._session_task_contexts[session_id]

    def update_task_context(self, session_id: str, updates: dict[str, Any]) -> None:
        """Update short-term task memory context for a session."""
        ctx = self.get_task_context(session_id)
        ctx.update(updates)

    def clear_pending_confirmation(self, session_id: str) -> None:
        """Clear any pending confirmation state."""
        ctx = self.get_task_context(session_id)
        ctx.pop("pending_confirmation", None)

    def _strip_wake_words(self, text: str) -> str:
        """Strip 'lyra', conversational prefixes, and common polite fillers."""
        cleaned = text.strip()
        cleaned = re.sub(r"(?i)^(?:hey|hi|hello|ok|okay)?\s*lyra[,:\s]*", "", cleaned)
        cleaned = re.sub(r"(?i)^(?:can|could|would)\s+you(?:\s+please)?\s+", "", cleaned)
        cleaned = re.sub(r"(?i)^please\s+", "", cleaned)
        cleaned = re.sub(r"(?i)[,\s]+please[.?]?$", "", cleaned)
        if cleaned and cleaned[-1] in ".?!" and not (len(cleaned) >= 2 and cleaned[-2] in "\"'"):
            cleaned = cleaned.rstrip(".?! \t")
        return cleaned.strip()

    def plan(
        self,
        raw_input: str,
        session: Session | None = None,
    ) -> TaskPlan | None:
        """Analyze user input and return a TaskPlan, maintaining short-term context across turns."""
        cleaned = self._strip_wake_words(raw_input)
        session_id = session.session_id if session else "default"
        context = self.get_task_context(session_id)

        # 0. Check for confirmation responses ("yes", "confirm", "proceed", "no", "cancel")
        norm_conf = re.sub(r"[^a-zA-Z0-9 ]+", " ", raw_input.lower()).strip()
        pending = context.get("pending_confirmation")
        if pending and isinstance(pending, ActionStep):
            if any(norm_conf.startswith(w) for w in ("yes", "yeah", "yep", "sure", "confirm", "proceed", "do it", "delete", "ok", "okay")):
                logger.info("User confirmed pending action: %s", pending.tool)
                confirmed_step = ActionStep(
                    tool=pending.tool,
                    arguments={**pending.arguments, "confirmed": True},
                    description=pending.description,
                )
                self.clear_pending_confirmation(session_id)
                return TaskPlan(
                    intent="confirmed_action",
                    steps=[confirmed_step],
                    context={"confirmed": True},
                )
            elif any(norm_conf.startswith(w) for w in ("no", "cancel", "stop", "don't", "dont", "abort", "nevermind")):
                logger.info("User cancelled pending action.")
                self.clear_pending_confirmation(session_id)
                return TaskPlan(
                    intent="cancel_action",
                    steps=[],
                    context={"cancelled": True},
                )

        # 1. Check for multi-step conjunctions (e.g. "create folder X, open it, and create file Y inside it")
        multi_step_plan = self._try_multi_step_plan(cleaned, session_id, context)
        if multi_step_plan:
            return multi_step_plan

        # 2. Check contextual follow-ups (e.g. "Search for Arijit Singh", "Play the first one")
        context_plan = self._try_contextual_follow_up(cleaned, session_id, context)
        if context_plan:
            return context_plan

        # 3. Check single-step fast patterns
        single_step_plan = self._try_single_step_plan(cleaned, session_id, context)
        if single_step_plan:
            return single_step_plan

        return None

    async def plan_async(
        self,
        raw_input: str,
        session: Session | None = None,
    ) -> TaskPlan | None:
        """Analyze user input asynchronously, falling back to ModelRouter for complex intents."""
        plan = self.plan(raw_input, session=session)
        if plan is not None:
            return plan

        if not self.router:
            return None

        prompt = (
            f"Analyze user command: \"{raw_input}\"\n"
            "Determine if this is an action or tool execution request (e.g. brightness, volume, browser, tabs, youtube, filesystem, applications).\n"
            "If it is an actionable command, return a JSON object ONLY with the following schema:\n"
            "{\n"
            "  \"intent\": \"<intent_name>\",\n"
            "  \"steps\": [\n"
            "    {\"tool\": \"<tool_name>\", \"arguments\": {<args>}, \"description\": \"<description>\"}\n"
            "  ]\n"
            "}\n"
            "Supported tools include:\n"
            "- system.increase_brightness: {\"action\": \"increase_brightness\", \"delta\": 0.1}\n"
            "- system.decrease_brightness: {\"action\": \"decrease_brightness\", \"delta\": 0.1}\n"
            "- system.set_brightness: {\"action\": \"set_brightness\", \"level\": 0.5}\n"
            "- system.increase_volume: {\"action\": \"increase_volume\", \"delta\": 10}\n"
            "- system.decrease_volume: {\"action\": \"decrease_volume\", \"delta\": 10}\n"
            "- system.set_volume: {\"action\": \"set_volume\", \"level\": 50}\n"
            "- system.mute: {\"action\": \"mute\"}\n"
            "- system.unmute: {\"action\": \"unmute\"}\n"
            "- computer.launch_app: {\"action\": \"launch_app\", \"app_name\": \"<app>\"}\n"
            "- browser.navigate: {\"action\": \"navigate\", \"url\": \"<url>\"}\n"
            "- browser.new_tab: {\"action\": \"new_tab\", \"url\": \"<url>\"}\n"
            "- browser.close_tab: {\"action\": \"close_tab\"}\n"
            "- browser.switch_tab: {\"action\": \"switch_tab\", \"direction\": \"next\"}\n"
            "- browser.search_web: {\"action\": \"search_web\", \"query\": \"<query>\"}\n"
            "- browser.search_youtube: {\"action\": \"search_youtube\", \"query\": \"<query>\"}\n"
            "- browser.play_media: {\"action\": \"play_media\", \"query\": \"<query>\"}\n"
            "- browser.open_search_result: {\"action\": \"open_search_result\", \"index\": 1}\n"
            "- filesystem.create_directory: {\"action\": \"create_directory\", \"path\": \"<path>\"}\n"
            "- filesystem.create_file: {\"action\": \"create_file\", \"path\": \"<path>\", \"content\": \"\"}\n"
            "- filesystem.open_path: {\"action\": \"open_path\", \"path\": \"<path>\"}\n"
            "- filesystem.delete: {\"action\": \"delete\", \"path\": \"<path>\", \"confirmed\": false}\n"
            "If it is not an action command, return {\"intent\": \"none\", \"steps\": []}.\n"
            "Return JSON only without markdown formatting."
        )
        from lyra.models.messages import AIRequest, Message, Role
        req = AIRequest(
            messages=[Message(role=Role.USER, content=prompt)],
            temperature=0.0,
        )
        try:
            resp = await self.router.route(req)
            content = resp.content.strip()
            if "```" in content:
                m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
                if m:
                    content = m.group(1)
            parsed = json.loads(content)
            intent = parsed.get("intent", "none")
            raw_steps = parsed.get("steps", [])
            if intent not in ("none", "") and raw_steps:
                steps = []
                for s in raw_steps:
                    tool_name = s.get("tool")
                    args = s.get("arguments", {})
                    if "path" in args and isinstance(args["path"], str):
                        p = args["path"]
                        if p.startswith("~/"):
                            args["path"] = str(Path.home() / p[2:])
                        elif "Desktop" in p and not p.startswith("/"):
                            args["path"] = str(Path.home() / "Desktop" / p.split("Desktop", 1)[-1].lstrip("/\\"))
                    steps.append(ActionStep(
                        tool=tool_name,
                        arguments=args,
                        description=s.get("description"),
                    ))
                return TaskPlan(intent=intent, steps=steps)
        except Exception as err:
            logger.debug("LLM planning route failed or returned non-JSON: %s", err)
            return None

        return None

    def _try_multi_step_plan(
        self,
        text: str,
        session_id: str,
        context: dict[str, Any],
    ) -> TaskPlan | None:
        """Parse multi-step commands."""
        lowered = text.lower()

        # Multi-step Notes: "Open Notes and write Hello Boss" / "Create a new note and write Hello Boss"
        m_notes_write = re.search(
            r"(?i)^(?:open\s+(?:the\s+)?notes(?:\s+app(?:lication)?)?(?:,\s*|\s+and\s+)|(?:create|make)\s+(?:a\s+)?(?:new\s+)?note\s+(?:and\s+)?)(?:write|type)\s+['\"]?(.+?)['\"]?$",
            text,
        )
        if m_notes_write:
            content = m_notes_write.group(1).strip()
            return TaskPlan(
                intent="notes_write",
                steps=[
                    ActionStep(
                        tool="notes.write_note",
                        arguments={"action": "write_note", "text": content},
                        description=f"Open Notes and write '{content}'",
                    )
                ],
            )

        m_notes_named_write = re.search(
            r"(?i)^(?:create|make)\s+(?:a\s+)?note\s+(?:called|named)\s+['\"]?([a-zA-Z0-9_\- ]+?)['\"]?\s+and\s+write\s+['\"]?(.+?)['\"]?$",
            text,
        )
        if m_notes_named_write:
            title = m_notes_named_write.group(1).strip()
            content = m_notes_named_write.group(2).strip()
            return TaskPlan(
                intent="notes_write",
                steps=[
                    ActionStep(
                        tool="notes.write_note",
                        arguments={"action": "write_note", "title": title, "text": content},
                        description=f"Create note '{title}' and write '{content}'",
                    )
                ],
            )

        m_write_in_notes = re.search(
            r"(?i)^write\s+(?:this\s+)?in\s+(?:my\s+)?notes\s*[:,-]?\s*['\"]?(.+?)['\"]?$",
            text,
        )
        if m_write_in_notes:
            content = m_write_in_notes.group(1).strip()
            return TaskPlan(
                intent="notes_write",
                steps=[
                    ActionStep(
                        tool="notes.write_note",
                        arguments={"action": "write_note", "text": content},
                        description=f"Write '{content}' in Notes",
                    )
                ],
            )

        m_write_in_notes2 = re.search(
            r"(?i)^write\s+['\"]?(.+?)['\"]?\s+in\s+(?:my\s+)?notes(?:\s+app)?$",
            text,
        )
        if m_write_in_notes2:
            content = m_write_in_notes2.group(1).strip()
            return TaskPlan(
                intent="notes_write",
                steps=[
                    ActionStep(
                        tool="notes.write_note",
                        arguments={"action": "write_note", "text": content},
                        description=f"Write '{content}' in Notes",
                    )
                ],
            )


        # Multi-step VS Code: "Open my Lyra project in VS Code"
        if re.search(r"(?i)\bopen\s+(?:my\s+)?lyra\s+(?:project|repo|codebase)\s+in\s+(?:vs\s*code|code)\b", text):
            lyra_path = "/Users/vikas/Desktop/Lyra"
            return TaskPlan(
                intent="open_vscode_project",
                steps=[
                    ActionStep(
                        tool="system.open_application",
                        arguments={"action": "open_application", "app_name": "Visual Studio Code", "target_path": lyra_path},
                        description="Open Lyra project in VS Code",
                    )
                ],
            )

        # "Open the file main.py in VS Code" / "Open the file main.py"
        m_vscode_file = re.search(
            r"(?i)\bopen\s+(?:the\s+)?file\s+['\"]?([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]+)['\"]?(?:\s+in\s+(?:vs\s*code|code))?\b",
            text,
        )
        if m_vscode_file:
            fname = m_vscode_file.group(1).strip()
            target = f"/Users/vikas/Desktop/Lyra/{fname}" if not fname.startswith("/") else fname
            return TaskPlan(
                intent="open_file_in_vscode",
                steps=[
                    ActionStep(
                        tool="system.open_application",
                        arguments={"action": "open_application", "app_name": "Visual Studio Code", "target_path": target},
                        description=f"Open '{fname}' in VS Code",
                    )
                ],
            )

        # Multi-step Folder Structure: "Create this structure: ..."
        m_struct = re.search(r"(?i)\b(?:create|make)\s+this\s+(?:project\s+|folder\s+)?structure(?:\s+on\s+(?:my\s+)?desktop)?\s*[:\n]\s*(.+)$", text, re.DOTALL)
        if m_struct:
            raw_struct = m_struct.group(1).strip()
            return TaskPlan(
                intent="create_folder_structure",
                steps=[
                    ActionStep(
                        tool="filesystem.create_structure",
                        arguments={"action": "create_structure", "structure": raw_struct},
                        description="Create requested folder structure on Desktop",
                    )
                ],
            )

        # "Create a folder structure called Project with src, tests and docs"
        m_struct_named = re.search(
            r"(?i)\b(?:create|make)\s+(?:a\s+)?folder\s+structure\s+(?:called|named)\s+['\"]?([a-zA-Z0-9_\- ]+?)['\"]?\s+(?:with\s+)?(.+)$",
            text,
        )
        if m_struct_named:
            root = m_struct_named.group(1).strip()
            rest = m_struct_named.group(2).strip()
            return TaskPlan(
                intent="create_folder_structure",
                steps=[
                    ActionStep(
                        tool="filesystem.create_structure",
                        arguments={"action": "create_structure", "root_name": root, "structure": rest},
                        description=f"Create folder structure '{root}' with {rest}",
                    )
                ],
            )

        # "Inside College create Projects, Notes and Documents"
        m_inside = re.search(
            r"(?i)\binside\s+['\"]?([a-zA-Z0-9_\- ]+?)['\"]?\s+(?:create|make)\s+(.+)$",
            text,
        )
        if m_inside:
            root = m_inside.group(1).strip()
            rest = m_inside.group(2).strip()
            return TaskPlan(
                intent="create_folder_structure",
                steps=[
                    ActionStep(
                        tool="filesystem.create_structure",
                        arguments={"action": "create_structure", "root_name": root, "structure": rest},
                        description=f"Create {rest} inside '{root}'",
                    )
                ],
            )

        # Multi-step 1: Create folder on desktop, open it, and create file inside it
        # E.g. "create a folder called College on my desktop, open it, and create a file called notes.txt inside it"
        m_combo = re.search(
            r"(?i)(?:create|make)\s+(?:a\s+)?folder\s+(?:called|named)?\s*['\"]?([a-zA-Z0-9_\- ]+?)['\"]?(?:\s+on\s+(?:my\s+)?desktop)?,\s*(?:then\s+)?open\s+it(?:,\s*and|\s+and)?\s*(?:create|make)\s+(?:a\s+)?file\s+(?:called|named)?\s*['\"]?([a-zA-Z0-9_\-.]+)['\"]?\s+inside\s+it",
            text,
        )
        if m_combo:
            folder_name = m_combo.group(1).strip()
            file_name = m_combo.group(2).strip()
            folder_path = str(Path.home() / "Desktop" / folder_name)
            file_path = str(Path.home() / "Desktop" / folder_name / file_name)

            self.update_task_context(session_id, {"last_folder_path": folder_path})
            return TaskPlan(
                intent="create_folder_and_file",
                steps=[
                    ActionStep(
                        tool="filesystem.create_directory",
                        arguments={"action": "create_directory", "path": folder_path},
                        description=f"Create folder '{folder_name}' on Desktop",
                    ),
                    ActionStep(
                        tool="filesystem.open_path",
                        arguments={"action": "open_path", "path": folder_path},
                        description=f"Open folder '{folder_name}'",
                    ),
                    ActionStep(
                        tool="filesystem.create_file",
                        arguments={"action": "create_file", "path": file_path, "content": ""},
                        description=f"Create file '{file_name}' inside '{folder_name}'",
                    ),
                ],
            )

        # Multi-step 2: Create folder and create file inside it
        # E.g. "create a folder called Projects on my desktop and create a file called todo.txt inside it"
        m_combo2 = re.search(
            r"(?i)(?:create|make)\s+(?:a\s+)?folder\s+(?:called|named)?\s*['\"]?([a-zA-Z0-9_\- ]+?)['\"]?(?:\s+on\s+(?:my\s+)?desktop)?\s+and\s+(?:create|make)\s+(?:a\s+)?file\s+(?:called|named)?\s*['\"]?([a-zA-Z0-9_\-.]+)['\"]?\s+inside\s+it",
            text,
        )
        if m_combo2:
            folder_name = m_combo2.group(1).strip()
            file_name = m_combo2.group(2).strip()
            folder_path = str(Path.home() / "Desktop" / folder_name)
            file_path = str(Path.home() / "Desktop" / folder_name / file_name)

            self.update_task_context(session_id, {"last_folder_path": folder_path})
            return TaskPlan(
                intent="create_folder_and_file",
                steps=[
                    ActionStep(
                        tool="filesystem.create_directory",
                        arguments={"action": "create_directory", "path": folder_path},
                        description=f"Create folder '{folder_name}' on Desktop",
                    ),
                    ActionStep(
                        tool="filesystem.create_file",
                        arguments={"action": "create_file", "path": file_path, "content": ""},
                        description=f"Create file '{file_name}' inside '{folder_name}'",
                    ),
                ],
            )

        # Multi-step 3: Open YouTube, search for X, and play the first suitable result / song
        # E.g. "open youtube, search for relaxing music, and play the first suitable result", "open youtube, search for Arijit Singh, and play the first song"
        m_yt_multi = re.search(
            r"(?i)open\s+youtube[,:\s]*(?:and\s+)?search\s+(?:youtube\s+)?for\s+['\"]?(.+?)['\"]?[,:\s]*(?:and\s+)?play\s+(?:the\s+)?(?:first\s+)?(?:suitable\s+)?(?:result|song|video|track|one)",
            text,
        )
        if m_yt_multi:
            query = m_yt_multi.group(1).strip()
            self.update_task_context(session_id, {"last_browser_domain": "youtube.com", "last_browser_query": query})
            return TaskPlan(
                intent="youtube_search_and_play",
                steps=[
                    ActionStep(
                        tool="browser.search_youtube",
                        arguments={"action": "search_youtube", "query": query},
                        description=f"Search YouTube for '{query}'",
                    ),
                    ActionStep(
                        tool="browser.play_media",
                        arguments={"action": "play_media", "query": query},
                        description=f"Play top result for '{query}'",
                    ),
                ],
            )

        # Multi-step 4: Open Chrome, create a new tab, search Google for X, and open the first result
        m_chrome_pipeline = re.search(
            r"(?i)open\s+(?:google\s+)?chrome,\s*(?:create|open)\s+(?:a\s+)?new\s+tab,\s*search\s+google\s+for\s+['\"]?(.+?)['\"]?,\s*and\s+open\s+(?:the\s+)?first\s+result",
            text,
        )
        if m_chrome_pipeline:
            query = m_chrome_pipeline.group(1).strip()
            self.update_task_context(session_id, {"last_browser_domain": "google.com", "last_browser_query": query})
            return TaskPlan(
                intent="chrome_tab_search_and_open",
                steps=[
                    ActionStep(
                        tool="system.open_application",
                        arguments={"action": "open_application", "app_name": "Google Chrome"},
                        description="Open Google Chrome",
                    ),
                    ActionStep(
                        tool="browser.new_tab",
                        arguments={"action": "new_tab", "url": "https://www.google.com"},
                        description="Create new tab and navigate to Google",
                    ),
                    ActionStep(
                        tool="browser.search_web",
                        arguments={"action": "search_web", "query": query},
                        description=f"Search Google for '{query}'",
                    ),
                    ActionStep(
                        tool="browser.open_search_result",
                        arguments={"action": "open_search_result", "index": 1},
                        description="Open the first search result",
                    ),
                ],
            )

        # Multi-step 5: Search Google for X and open the first relevant result
        m_google_multi = re.search(
            r"(?i)search\s+google\s+for\s+['\"]?(.+?)['\"]?\s+and\s+open\s+(?:the\s+)?(?:first\s+)?(?:relevant\s+)?result",
            text,
        )
        if m_google_multi:
            query = m_google_multi.group(1).strip()
            self.update_task_context(session_id, {"last_browser_domain": "google.com", "last_browser_query": query})
            return TaskPlan(
                intent="google_search_and_open",
                steps=[
                    ActionStep(
                        tool="browser.search_web",
                        arguments={"action": "search_web", "query": query},
                        description=f"Search Google for '{query}'",
                    ),
                    ActionStep(
                        tool="browser.open_search_result",
                        arguments={"action": "open_search_result", "index": 1},
                        description="Open the first search result",
                    ),
                ],
            )

        # Multi-step 6: Open a new tab and search Google for X
        m_tab_google = re.search(
            r"(?i)open\s+(?:a\s+)?new\s+(?:browser\s+)?tab\s+and\s+search\s+google\s+for\s+['\"]?(.+?)['\"]?(?:\.|$)",
            text,
        )
        if m_tab_google:
            query = m_tab_google.group(1).strip()
            self.update_task_context(session_id, {"last_browser_domain": "google.com", "last_browser_query": query})
            return TaskPlan(
                intent="new_tab_google_search",
                steps=[
                    ActionStep(
                        tool="browser.new_tab",
                        arguments={"action": "new_tab", "url": f"https://www.google.com/search?q={quote_plus(query)}"},
                        description=f"Open new tab and search Google for '{query}'",
                    ),
                ],
            )

        # Multi-step 7: Open a new tab and search YouTube for X
        m_tab_yt = re.search(
            r"(?i)open\s+(?:a\s+)?new\s+tab\s+and\s+search\s+youtube\s+for\s+['\"]?(.+?)['\"]?(?:\.|$)",
            text,
        )
        if m_tab_yt:
            query = m_tab_yt.group(1).strip()
            self.update_task_context(session_id, {"last_browser_domain": "youtube.com", "last_browser_query": query})
            return TaskPlan(
                intent="new_tab_youtube_search",
                steps=[
                    ActionStep(
                        tool="browser.new_tab",
                        arguments={"action": "new_tab", "url": f"https://www.youtube.com/results?search_query={quote_plus(query)}"},
                        description=f"Open new tab and search YouTube for '{query}'",
                    ),
                ],
            )

        # Multi-step 8: Search for X and play the first result / video
        m_search_play = re.search(
            r"(?i)(?:search\s+for\s+['\"]?(.+?)['\"]?\s+and\s+play\s+(?:the\s+)?first\s+(?:result|video|one)|search\s+youtube\s+for\s+['\"]?(.+?)['\"]?\s+and\s+play\s+(?:the\s+)?first\s+(?:result|video|one))",
            text,
        )
        if m_search_play:
            query = (m_search_play.group(1) or m_search_play.group(2)).strip()
            self.update_task_context(session_id, {"last_browser_domain": "youtube.com", "last_browser_query": query})
            return TaskPlan(
                intent="youtube_search_and_play",
                steps=[
                    ActionStep(
                        tool="browser.search_youtube",
                        arguments={"action": "search_youtube", "query": query},
                        description=f"Search YouTube for '{query}'",
                    ),
                    ActionStep(
                        tool="browser.play_media",
                        arguments={"action": "play_media", "query": query},
                        description=f"Play first video for '{query}'",
                    ),
                ],
            )

        return None

    def _try_single_step_plan(
        self,
        text: str,
        session_id: str,
        context: dict[str, Any],
    ) -> TaskPlan | None:
        """Parse single-step action commands."""
        lowered = text.lower()

        # ---------------- FILESYSTEM ----------------

        # 1. Create folder inside specific folder (e.g. "create a folder called Projects inside College")
        m_inside = re.search(
            r"(?i)(?:create|make)\s+(?:a\s+)?folder\s+(?:called|named)?\s*['\"]?([a-zA-Z0-9_\- ]+?)['\"]?\s+inside\s+['\"]?([a-zA-Z0-9_\- ]+?)['\"]?(?:\.|$)",
            text,
        )
        if m_inside:
            subfolder = m_inside.group(1).strip()
            parent = m_inside.group(2).strip()
            target_path = str(Path.home() / "Desktop" / parent / subfolder)
            self.update_task_context(session_id, {"last_folder_path": target_path})
            return TaskPlan(
                intent="create_folder",
                steps=[ActionStep(
                    tool="filesystem.create_directory",
                    arguments={"action": "create_directory", "path": target_path},
                    description=f"Create folder '{subfolder}' inside '{parent}'",
                )],
            )

        # 2. Create folder on desktop (e.g. "create a folder on my desktop named College", "make me a folder called Work on my desktop")
        m_folder = re.search(
            r"(?i)(?:create|make|new)(?:\s+me)?\s+(?:a\s+)?(?:folder|directory)\s+(?:on\s+(?:my\s+)?desktop\s+)?(?:called|named)?\s*['\"]?([a-zA-Z0-9_\- ]+?)['\"]?(?:\s+on\s+(?:my\s+)?desktop)?(?:\.|$|\?)",
            text,
        )
        if m_folder and not ("file" in lowered and "inside" in lowered):
            folder_name = m_folder.group(1).strip()
            # Clean trailing desktop references
            folder_name = re.sub(r"(?i)\s+(?:on|in|inside)\s+(?:my\s+)?desktop$", "", folder_name).strip()
            if folder_name and folder_name.lower() not in ("folder", "directory", "file"):
                target_path = str(Path.home() / "Desktop" / folder_name)
                self.update_task_context(session_id, {"last_folder_path": target_path})
                return TaskPlan(
                    intent="create_folder",
                    steps=[ActionStep(
                        tool="filesystem.create_directory",
                        arguments={"action": "create_directory", "path": target_path},
                        description=f"Create folder '{folder_name}' on Desktop",
                    )],
                )

        # 3. Create file inside specific folder (e.g. "create a file called notes.txt inside LYRA_TEST")
        m_file_inside = re.search(
            r"(?i)(?:create|make|write|touch)\s+(?:a\s+)?(?:file|document)\s+(?:called|named)?\s*['\"]?([a-zA-Z0-9_\-.]+\.[a-zA-Z0-9]+)['\"]?\s+(?:inside|in)\s+['\"]?([a-zA-Z0-9_\- ]+?)['\"]?(?:\.|$)",
            text,
        )
        if m_file_inside:
            filename = m_file_inside.group(1).strip()
            parent = m_file_inside.group(2).strip()
            parent_dir = Path.home() / "Desktop" / parent if not parent.startswith("/") else Path(parent)
            target_path = str(parent_dir / filename)
            return TaskPlan(
                intent="create_file",
                steps=[ActionStep(
                    tool="filesystem.create_file",
                    arguments={"action": "create_file", "path": target_path, "content": ""},
                    description=f"Create file '{filename}' inside '{parent}'",
                )],
            )

        # 4. Create file on desktop (supports optional 'with <content>')
        m_file = re.search(
            r"(?i)(?:create|make|write|touch)\s+(?:a\s+)?(?:file|document)\s+(?:called|named)?\s*['\"]?([a-zA-Z0-9_\-.]+\.[a-zA-Z0-9]+)['\"]?(?:\s+on\s+(?:my\s+)?desktop)?(?:\s+with\s+(?:content\s+)?['\"]?(.*?)['\"]?)?(?:\.|$)",
            text,
        )
        if m_file:
            filename = m_file.group(1).strip()
            content = m_file.group(2).strip() if m_file.group(2) else ""
            target_path = str(Path.home() / "Desktop" / filename)
            return TaskPlan(
                intent="create_file",
                steps=[ActionStep(
                    tool="filesystem.create_file",
                    arguments={"action": "create_file", "path": target_path, "content": content},
                    description=f"Create file '{filename}' on Desktop",
                )],
            )

        # 4. Open folder in Finder (e.g. "open my Desktop folder", "open Desktop")
        m_open_folder = re.search(
            r"(?i)open\s+(?:my\s+)?([a-zA-Z0-9_\- ]+?)\s+folder(?:\.|$)",
            text,
        )
        if m_open_folder:
            name = m_open_folder.group(1).strip()
            target_path = str(Path.home() / "Desktop") if name.lower() == "desktop" else str(Path.home() / "Desktop" / name)
            return TaskPlan(
                intent="open_path",
                steps=[ActionStep(
                    tool="filesystem.open_path",
                    arguments={"action": "open_path", "path": target_path},
                    description=f"Open '{name}' folder in Finder",
                )],
            )

        # 5. Rename folder / file
        m_rename = re.search(
            r"(?i)rename\s+(?:the\s+)?([a-zA-Z0-9_\- ]+?)(?:\s+folder)?\s+to\s+['\"]?([a-zA-Z0-9_\- ]+?)['\"]?(?:\.|$)",
            text,
        )
        if m_rename:
            src = m_rename.group(1).strip()
            dest = m_rename.group(2).strip()
            src_path = str(Path.home() / "Desktop" / src)
            dest_path = str(Path.home() / "Desktop" / dest)
            return TaskPlan(
                intent="rename",
                steps=[ActionStep(
                    tool="filesystem.rename",
                    arguments={"action": "rename", "path": src_path, "destination": dest_path},
                    description=f"Rename '{src}' to '{dest}'",
                )],
            )

        # 6. Delete folder / file (Destructive -> confirmation required)
        m_del = re.search(
            r"(?i)delete\s+(?:the\s+)?([a-zA-Z0-9_\- ]+?)(?:\s+folder|\s+file)?(?:\.|$)",
            text,
        )
        if m_del and not any(w in lowered for w in ("history", "message", "chat", "session", "my")):
            target = m_del.group(1).strip()
            if target and target.lower() not in ("folder", "file", "all"):
                target_path = str(Path.home() / "Desktop" / target)
                step = ActionStep(
                    tool="filesystem.delete",
                    arguments={"action": "delete", "path": target_path, "confirmed": False},
                    description=f"Delete '{target}'",
                )
                self.update_task_context(session_id, {"pending_confirmation": step})
                return TaskPlan(
                    intent="delete_requires_confirmation",
                    steps=[step],
                    user_confirmation_prompt=f"Deleting '{target}' is a destructive action. Are you sure you want to delete it?",
                )

        # ---------------- BROWSER ----------------

        # 7. Open YouTube and play X
        m_play = re.search(
            r"(?i)(?:open\s+youtube\s+and\s+play|play\s+(.+?)\s+on\s+youtube|put\s+(.+?)\s+on\s+youtube)\b",
            text,
        )
        if m_play:
            query = m_play.group(1) or m_play.group(2)
            if not query:
                m2 = re.search(r"(?i)open\s+youtube\s+and\s+play\s+['\"]?(.+?)['\"]?(?:\.|$)", text)
                query = m2.group(1).strip() if m2 else "music"
            query = query.strip()
            self.update_task_context(session_id, {"last_browser_domain": "youtube.com", "last_browser_query": query})
            return TaskPlan(
                intent="play_youtube",
                steps=[
                    ActionStep(
                        tool="browser.navigate",
                        arguments={"action": "navigate", "url": "https://www.youtube.com"},
                        description="Open YouTube",
                    ),
                    ActionStep(
                        tool="browser.play_media",
                        arguments={"action": "play_media", "query": query},
                        description=f"Play '{query}' on YouTube",
                    ),
                ],
            )

        # 8. Search Google for X / Open Google and search for X
        m_google = re.search(
            r"(?i)(?:open\s+google\s+(?:and\s+)?search\s+for|search\s+google\s+for)\s+['\"]?(.+?)['\"]?(?:\.|$)",
            text,
        )
        if not m_google:
            m_google = re.search(r"(?i)search\s+for\s+['\"]?(.+?)['\"]?\s+on\s+google(?:\.|$)", text)
        if m_google:
            query = m_google.group(1).strip()
            self.update_task_context(session_id, {"last_browser_domain": "google.com", "last_browser_query": query})
            return TaskPlan(
                intent="search_google",
                steps=[ActionStep(
                    tool="browser.search_web",
                    arguments={"action": "search_web", "query": query},
                    description=f"Search Google for '{query}'",
                )],
            )

        # 9. Search YouTube for X / Open YouTube and search for X
        m_yt = re.search(
            r"(?i)(?:open\s+youtube\s+(?:and\s+)?search\s+for|search\s+youtube\s+for)\s+['\"]?(.+?)['\"]?(?:\.|$)",
            text,
        )
        if not m_yt:
            m_yt = re.search(r"(?i)search\s+for\s+['\"]?(.+?)['\"]?\s+on\s+youtube(?:\.|$)", text)
        if m_yt:
            query = m_yt.group(1).strip()
            self.update_task_context(session_id, {"last_browser_domain": "youtube.com", "last_browser_query": query})
            return TaskPlan(
                intent="search_youtube",
                steps=[ActionStep(
                    tool="browser.search_youtube",
                    arguments={"action": "search_youtube", "query": query},
                    description=f"Search YouTube for '{query}'",
                )],
            )

        # ---------------- BROWSER TAB MANAGEMENT ----------------

        # 10. Open website in a new tab (e.g. "Open GitHub in a new tab")
        m_tab_site = re.search(
            r"(?i)open\s+(.+?)\s+in\s+(?:a\s+)?new\s+tab(?:\.|$)",
            text,
        )
        if m_tab_site:
            site = m_tab_site.group(1).strip().lower()
            site_url = site if site.startswith("http") else (
                f"https://www.{site}.com" if "." not in site else f"https://{site}"
            )
            return TaskPlan(
                intent="open_site_new_tab",
                steps=[ActionStep(
                    tool="browser.new_tab",
                    arguments={"action": "new_tab", "url": site_url},
                    description=f"Open {site} in a new tab",
                )],
            )

        # 11. Open website by name
        if re.search(r"(?i)\b(?:open|go\s+to|visit)\s+youtube\b", text):
            self.update_task_context(session_id, {"last_browser_domain": "youtube.com"})
            return TaskPlan(
                intent="open_youtube",
                steps=[ActionStep(
                    tool="browser.navigate",
                    arguments={"action": "navigate", "url": "https://www.youtube.com"},
                    description="Open YouTube",
                )],
            )
        if re.search(r"(?i)\b(?:open|go\s+to|visit)\s+github\b", text):
            self.update_task_context(session_id, {"last_browser_domain": "github.com"})
            return TaskPlan(
                intent="open_github",
                steps=[ActionStep(
                    tool="browser.navigate",
                    arguments={"action": "navigate", "url": "https://www.github.com"},
                    description="Open GitHub",
                )],
            )
        if re.search(r"(?i)\b(?:open|go\s+to|visit)\s+google(?:\.com)?(?!\s+chrome)\b", text):
            self.update_task_context(session_id, {"last_browser_domain": "google.com"})
            return TaskPlan(
                intent="open_google",
                steps=[ActionStep(
                    tool="browser.navigate",
                    arguments={"action": "navigate", "url": "https://www.google.com"},
                    description="Open Google",
                )],
            )

        # 12. Open new tab (e.g. "open a new tab", "create a new tab", "new tab")
        if re.search(r"(?i)\b(?:open|create|make)?\s*(?:a\s+)?new\s+tab\b", text):
            return TaskPlan(
                intent="new_tab",
                steps=[ActionStep(
                    tool="browser.new_tab",
                    arguments={"action": "new_tab", "url": "about:blank"},
                    description="Open a new browser tab",
                )],
            )

        # 13. Close tab (e.g. "close this tab", "close current tab", "close tab")
        if re.search(r"(?i)\bclose\s+(?:this|the|current)?\s*tab\b", text):
            return TaskPlan(
                intent="close_tab",
                steps=[ActionStep(
                    tool="browser.close_tab",
                    arguments={"action": "close_tab"},
                    description="Close current browser tab",
                )],
            )

        # 14. Switch tab (e.g. "switch to previous tab", "switch to next tab", "switch tabs", "previous tab", "next tab")
        if re.search(r"(?i)\b(?:switch\s+to\s+(?:the\s+)?)?previous\s+tab\b", text):
            return TaskPlan(
                intent="switch_tab_prev",
                steps=[ActionStep(
                    tool="browser.switch_tab",
                    arguments={"action": "switch_tab", "direction": "previous"},
                    description="Switch to previous tab",
                )],
            )
        if re.search(r"(?i)\b(?:switch\s+to\s+(?:the\s+)?)?next\s+tab\b", text):
            return TaskPlan(
                intent="switch_tab_next",
                steps=[ActionStep(
                    tool="browser.switch_tab",
                    arguments={"action": "switch_tab", "direction": "next"},
                    description="Switch to next tab",
                )],
            )
        tab_num_match = re.search(r"(?i)\bswitch\s+to\s+tab\s+(\d+)\b", text)
        if tab_num_match:
            idx = int(tab_num_match.group(1))
            return TaskPlan(
                intent="switch_tab_index",
                steps=[ActionStep(
                    tool="browser.switch_tab",
                    arguments={"action": "switch_tab", "index": idx},
                    description=f"Switch to tab {idx}",
                )],
            )
        if re.search(r"(?i)\bswitch\s+tabs?\b", text):
            return TaskPlan(
                intent="switch_tab_next",
                steps=[ActionStep(
                    tool="browser.switch_tab",
                    arguments={"action": "switch_tab", "direction": "next"},
                    description="Switch tab",
                )],
            )

        # 15. Browser navigation (scroll down/up, go back, refresh)
        if re.search(r"(?i)\bscroll\s+down(?:\s+on\s+youtube)?\b", text):
            return TaskPlan(
                intent="scroll_down",
                steps=[ActionStep(
                    tool="browser.scroll",
                    arguments={"action": "scroll", "direction": "down"},
                    description="Scroll down on page",
                )],
            )
        if re.search(r"(?i)\bscroll\s+up\b", text):
            return TaskPlan(
                intent="scroll_up",
                steps=[ActionStep(
                    tool="browser.scroll",
                    arguments={"action": "scroll", "direction": "up"},
                    description="Scroll up on page",
                )],
            )
        if re.search(r"(?i)\bgo\s+back\b", text):
            return TaskPlan(
                intent="go_back",
                steps=[ActionStep(
                    tool="browser.go_back",
                    arguments={"action": "go_back"},
                    description="Navigate back in browser history",
                )],
            )

        # 16. YouTube / Media playback controls & click video
        # "Click the first video", "play the first video", "click the first result", "open this video", "click result"
        if re.search(r"(?i)\b(?:click|play|open)\s+(?:the\s+)?(?:first|top|this)\s+(?:video|result|one)\b", text):
            query = context.get("last_browser_query", "")
            return TaskPlan(
                intent="open_first_result",
                steps=[ActionStep(
                    tool="browser.open_search_result",
                    arguments={"action": "open_search_result", "index": 1, "query": query},
                    description="Open first result/video",
                )],
            )

        # "Play <song>" (direct play request e.g. "Play Believer")
        m_direct_play = re.search(r"(?i)^play\s+['\"]?(.+?)['\"]?(?:\.|$)", text)
        if m_direct_play and not any(w in lowered for w in ("game", "video", "first", "next", "previous", "music")):
            song = m_direct_play.group(1).strip()
            self.update_task_context(session_id, {"last_browser_domain": "youtube.com", "last_browser_query": song})
            return TaskPlan(
                intent="play_media",
                steps=[ActionStep(
                    tool="browser.play_media",
                    arguments={"action": "play_media", "query": song},
                    description=f"Play '{song}' on YouTube",
                )],
            )

        # "Pause the video", "pause the music", "pause"
        if re.search(r"(?i)\bpause(?:\s+(?:the\s+)?(?:video|music|song|playback))?\b", text):
            return TaskPlan(
                intent="pause_media",
                steps=[ActionStep(
                    tool="media.pause",
                    arguments={"action": "pause"},
                    description="Pause video/audio playback",
                )],
            )

        # "Resume the video", "resume the music", "resume"
        if re.search(r"(?i)\bresume(?:\s+(?:the\s+)?(?:video|music|song|playback))?\b", text) or text.strip().lower() == "play":
            return TaskPlan(
                intent="resume_media",
                steps=[ActionStep(
                    tool="media.resume",
                    arguments={"action": "resume"},
                    description="Resume video/audio playback",
                )],
            )

        # "Play the next video", "next song", "next video", "next track"
        if re.search(r"(?i)\b(?:play\s+)?(?:the\s+)?next\s+(?:video|song|track)\b", text):
            return TaskPlan(
                intent="next_media",
                steps=[ActionStep(
                    tool="media.next",
                    arguments={"action": "next"},
                    description="Play next video/track",
                )],
            )

        # "Previous song", "previous track"
        if re.search(r"(?i)\b(?:the\s+)?previous\s+(?:video|song|track)\b", text):
            return TaskPlan(
                intent="previous_media",
                steps=[ActionStep(
                    tool="media.previous",
                    arguments={"action": "previous"},
                    description="Play previous video/track",
                )],
            )

        # "Stop the music", "stop the video"
        if re.search(r"(?i)\bstop\s+(?:the\s+)?(?:music|video|song|playback)\b", text):
            return TaskPlan(
                intent="stop_media",
                steps=[ActionStep(
                    tool="media.stop",
                    arguments={"action": "stop"},
                    description="Stop media playback",
                )],
            )

        # ---------------- DISPLAY BRIGHTNESS CONTROL ----------------

        # Increase brightness by delta: "decrease brightness by 20 percent", "increase brightness by 20 percent"
        m_b_inc = re.search(r"(?i)\bincrease\s+(?:the\s+)?brightness\s+by\s+(\d+)(?:\s*percent|%)?\b", text)
        if m_b_inc:
            d = float(m_b_inc.group(1)) / 100.0
            return TaskPlan(
                intent="increase_brightness",
                steps=[ActionStep(
                    tool="system.increase_brightness",
                    arguments={"action": "increase_brightness", "delta": d},
                    description=f"Increase display brightness by {int(d * 100)}%",
                )],
            )

        m_b_dec = re.search(r"(?i)\bdecrease\s+(?:the\s+)?brightness\s+by\s+(\d+)(?:\s*percent|%)?\b", text)
        if m_b_dec:
            d = float(m_b_dec.group(1)) / 100.0
            return TaskPlan(
                intent="decrease_brightness",
                steps=[ActionStep(
                    tool="system.decrease_brightness",
                    arguments={"action": "decrease_brightness", "delta": d},
                    description=f"Decrease display brightness by {int(d * 100)}%",
                )],
            )

        # Increase brightness: "Increase brightness", "Make screen brighter", "Make it brighter", "Brightness up", "Turn the brightness up"
        if re.search(r"(?i)\b(?:increase\s+(?:the\s+)?brightness|brightness\s+up|turn\s+(?:the\s+)?brightness\s+up|make\s+(?:the\s+|my\s+)?(?:screen|it)\s+brighter|brighter)\b", text):
            return TaskPlan(
                intent="increase_brightness",
                steps=[ActionStep(
                    tool="system.increase_brightness",
                    arguments={"action": "increase_brightness", "delta": 0.1},
                    description="Increase display brightness by 10%",
                )],
            )

        # Decrease brightness: "Decrease brightness", "Make screen darker", "Make my screen darker", "Brightness down", "Turn the brightness down"
        if re.search(r"(?i)\b(?:decrease\s+(?:the\s+)?brightness|brightness\s+down|turn\s+(?:the\s+)?brightness\s+down|make\s+(?:the\s+|my\s+)?(?:screen|it)\s+darker|darker)\b", text):
            return TaskPlan(
                intent="decrease_brightness",
                steps=[ActionStep(
                    tool="system.decrease_brightness",
                    arguments={"action": "decrease_brightness", "delta": 0.1},
                    description="Decrease display brightness by 10%",
                )],
            )

        # Set brightness: "Set brightness to 50 percent", "Set brightness to 50", "Set brightness to maximum", "Set brightness to minimum"
        m_b_set = re.search(r"(?i)\bset\s+(?:the\s+)?brightness\s+to\s+([a-zA-Z0-9.]+)(?:\s*percent|%)?\b", text)
        if m_b_set:
            raw_val = m_b_set.group(1).strip().lower()
            if raw_val in ("max", "maximum", "full", "100"):
                lvl = 1.0
            elif raw_val in ("min", "minimum", "zero", "0"):
                lvl = 0.1
            else:
                try:
                    num = float(raw_val)
                    lvl = num / 100.0 if num > 1.0 else num
                except ValueError:
                    lvl = 0.5
            return TaskPlan(
                intent="set_brightness",
                steps=[ActionStep(
                    tool="system.set_brightness",
                    arguments={"action": "set_brightness", "level": lvl},
                    description=f"Set display brightness to {int(lvl * 100)}%",
                )],
            )

        # ---------------- SYSTEM VOLUME CONTROL ----------------

        # Mute: "Mute", "Mute the computer", "Mute audio"
        if re.search(r"(?i)\bmute(?:\s+(?:the\s+)?(?:computer|audio|volume|system|sound))?\b", text) and "unmute" not in lowered:
            return TaskPlan(
                intent="mute",
                steps=[ActionStep(
                    tool="system.mute",
                    arguments={"action": "mute"},
                    description="Mute system volume",
                )],
            )

        # Unmute: "Unmute", "Unmute the computer"
        if re.search(r"(?i)\bunmute(?:\s+(?:the\s+)?(?:computer|audio|volume|system|sound))?\b", text):
            return TaskPlan(
                intent="unmute",
                steps=[ActionStep(
                    tool="system.unmute",
                    arguments={"action": "unmute"},
                    description="Unmute system volume",
                )],
            )

        # Increase volume: "Increase volume", "Turn the volume up", "Volume up", "Make the volume louder", "Make it louder", "Louder"
        if re.search(r"(?i)\b(?:increase\s+(?:the\s+)?volume|turn\s+(?:the\s+)?volume\s+up|volume\s+up|make\s+(?:the\s+)?volume\s+louder|make\s+it\s+louder|louder)\b", text):
            return TaskPlan(
                intent="increase_volume",
                steps=[ActionStep(
                    tool="system.increase_volume",
                    arguments={"action": "increase_volume", "delta": 10},
                    description="Increase volume by 10%",
                )],
            )

        # Decrease volume: "Decrease volume", "Turn the volume down", "Volume down", "Quieter", "Make it quieter", "Lower the volume"
        if re.search(r"(?i)\b(?:decrease\s+(?:the\s+)?volume|turn\s+(?:the\s+)?volume\s+down|volume\s+down|make\s+it\s+quieter|quieter|lower\s+(?:the\s+)?volume)\b", text):
            return TaskPlan(
                intent="decrease_volume",
                steps=[ActionStep(
                    tool="system.decrease_volume",
                    arguments={"action": "decrease_volume", "delta": 10},
                    description="Decrease volume by 10%",
                )],
            )

        # Set volume: "Set volume to 50 percent", "Set volume to 30", "Set my volume to 30"
        m_vol_set = re.search(r"(?i)\bset\s+(?:my\s+)?volume\s+to\s+(\d+)(?:\s*percent|%)?\b", text)
        if m_vol_set:
            val = int(m_vol_set.group(1))
            return TaskPlan(
                intent="set_volume",
                steps=[ActionStep(
                    tool="system.set_volume",
                    arguments={"action": "set_volume", "level": val},
                    description=f"Set system volume to {val}%",
                )],
            )

        # ---------------- KEYBOARD AUTOMATION ----------------

        if re.search(r"(?i)\bpress\s+(?:enter|return)\b", text):
            return TaskPlan(
                intent="press_enter",
                steps=[ActionStep(
                    tool="keyboard.press",
                    arguments={"action": "press", "key": "enter"},
                    description="Press Enter key",
                )],
            )

        if re.search(r"(?i)\bpress\s+escape\b", text):
            return TaskPlan(
                intent="press_escape",
                steps=[ActionStep(
                    tool="keyboard.press",
                    arguments={"action": "press", "key": "escape"},
                    description="Press Escape key",
                )],
            )

        if re.search(r"(?i)\bpress\s+command\s+l\b", text):
            return TaskPlan(
                intent="press_cmd_l",
                steps=[ActionStep(
                    tool="keyboard.hotkey",
                    arguments={"action": "hotkey", "keys": ["command", "l"]},
                    description="Press Command + L",
                )],
            )

        if re.search(r"(?i)\b(?:copy\s+this|copy)\b", text) and "paste" not in lowered:
            return TaskPlan(
                intent="copy",
                steps=[ActionStep(
                    tool="keyboard.hotkey",
                    arguments={"action": "hotkey", "keys": ["command", "c"]},
                    description="Copy to clipboard",
                )],
            )

        if re.search(r"(?i)\bpaste\b", text) and "copy" not in lowered:
            return TaskPlan(
                intent="paste",
                steps=[ActionStep(
                    tool="keyboard.hotkey",
                    arguments={"action": "hotkey", "keys": ["command", "v"]},
                    description="Paste from clipboard",
                )],
            )

        if re.search(r"(?i)\bselect\s+all\b", text):
            return TaskPlan(
                intent="select_all",
                steps=[ActionStep(
                    tool="keyboard.hotkey",
                    arguments={"action": "hotkey", "keys": ["command", "a"]},
                    description="Select all content",
                )],
            )

        # ---------------- APPLICATION CONTROL ----------------

        # 17. Open / Switch to / Close desktop applications
        # "Open Chrome", "Open Finder", "Open Terminal", "Open VS Code", "Open Notes", "Open Calculator"
        m_app = re.search(
            r"(?i)^(?:open|launch)\s+(?:the\s+)?(chrome|google\s+chrome|finder|terminal|vs\s*code|visual\s+studio\s+code|safari|calculator|notes|textedit)(?:\.|$)",
            text,
        )
        if m_app:
            raw_app = m_app.group(1).strip().lower()
            app_map = {
                "chrome": "Google Chrome",
                "google chrome": "Google Chrome",
                "finder": "Finder",
                "terminal": "Terminal",
                "vs code": "Visual Studio Code",
                "vscode": "Visual Studio Code",
                "visual studio code": "Visual Studio Code",
                "safari": "Safari",
                "calculator": "Calculator",
                "notes": "Notes",
                "textedit": "TextEdit",
            }
            app_name = app_map.get(raw_app, raw_app.capitalize())
            if app_name == "Notes":
                return TaskPlan(
                    intent="open_notes",
                    steps=[ActionStep(
                        tool="notes.open_notes",
                        arguments={"action": "open_notes"},
                        description="Open Notes",
                    )],
                )
            return TaskPlan(
                intent="open_application",
                steps=[ActionStep(
                    tool="computer.launch_app",
                    arguments={"action": "launch_app", "app_name": app_name},
                    description=f"Open application '{app_name}'",
                )],
            )

        # "Switch to Finder", "Switch to Chrome"
        m_switch_app = re.search(
            r"(?i)^switch\s+to\s+(?:the\s+)?(chrome|google\s+chrome|finder|terminal|vs\s*code|safari|notes|calculator)(?:\.|$)",
            text,
        )
        if m_switch_app:
            raw_app = m_switch_app.group(1).strip().lower()
            app_map = {"chrome": "Google Chrome", "finder": "Finder", "terminal": "Terminal", "vs code": "Visual Studio Code"}
            app_name = app_map.get(raw_app, raw_app.capitalize())
            return TaskPlan(
                intent="focus_application",
                steps=[ActionStep(
                    tool="system.focus_application",
                    arguments={"action": "focus_application", "app_name": app_name},
                    description=f"Switch to '{app_name}'",
                )],
            )

        # "Close Chrome", "Close Finder"
        m_close_app = re.search(
            r"(?i)^close\s+(?:the\s+)?(chrome|google\s+chrome|finder|terminal|vs\s*code|safari|notes|calculator)(?:\.|$)",
            text,
        )
        if m_close_app:
            raw_app = m_close_app.group(1).strip().lower()
            app_map = {"chrome": "Google Chrome", "finder": "Finder", "terminal": "Terminal"}
            app_name = app_map.get(raw_app, raw_app.capitalize())
            return TaskPlan(
                intent="close_application",
                steps=[ActionStep(
                    tool="system.close_application",
                    arguments={"action": "close_application", "app_name": app_name},
                    description=f"Close application '{app_name}'",
                )],
            )

        return None

    def _try_contextual_follow_up(
        self,
        text: str,
        session_id: str,
        context: dict[str, Any],
    ) -> TaskPlan | None:
        """Resolve short-term follow-up requests using existing session context."""
        lowered = text.lower()
        last_domain = context.get("last_browser_domain")

        # Contextual Search: "Search for Arijit Singh" when in YouTube context
        m_search_for = re.search(r"(?i)^search\s+for\s+['\"]?(.+?)['\"]?(?:\.|$)", text)
        if m_search_for:
            query = m_search_for.group(1).strip()
            if last_domain == "youtube.com":
                self.update_task_context(session_id, {"last_browser_query": query})
                return TaskPlan(
                    intent="contextual_youtube_search",
                    steps=[ActionStep(
                        tool="browser.search_youtube",
                        arguments={"action": "search_youtube", "query": query},
                        description=f"Search YouTube for '{query}' in active session",
                    )],
                )
            else:
                self.update_task_context(session_id, {"last_browser_query": query, "last_browser_domain": "google.com"})
                return TaskPlan(
                    intent="contextual_web_search",
                    steps=[ActionStep(
                        tool="browser.search_web",
                        arguments={"action": "search_web", "query": query},
                        description=f"Search Google for '{query}'",
                    )],
                )

        # Contextual Play / Open Result: "Play the first one", "Play the first result", "Open the first one", "Play the first song"
        if re.search(r"(?i)\b(?:play|open)\s+(?:the\s+)?first\s+(?:one|result|video|song|track)?\b", text):
            query = context.get("last_browser_query", "")
            if last_domain == "youtube.com":
                return TaskPlan(
                    intent="contextual_play_top_result",
                    steps=[ActionStep(
                        tool="browser.play_media",
                        arguments={"action": "play_media", "query": query},
                        description=f"Play top YouTube result for '{query}'",
                    )],
                )
            else:
                return TaskPlan(
                    intent="contextual_open_top_result",
                    steps=[ActionStep(
                        tool="browser.open_search_result",
                        arguments={"action": "open_search_result", "index": 1, "query": query, "domain": last_domain or "google.com"},
                        description="Open top search result",
                    )],
                )

        # Contextual Search: "Search Python", "Search machine learning"
        m_search_plain = re.search(r"(?i)^search\s+['\"]?(.+?)['\"]?(?:\.|$)", text)
        if m_search_plain and not any(w in lowered for w in ("youtube", "google", "for")):
            query = m_search_plain.group(1).strip()
            self.update_task_context(session_id, {"last_browser_query": query})
            if last_domain == "youtube.com":
                return TaskPlan(
                    intent="contextual_youtube_search",
                    steps=[ActionStep(
                        tool="browser.search_youtube",
                        arguments={"action": "search_youtube", "query": query},
                        description=f"Search YouTube for '{query}'",
                    )],
                )
            else:
                return TaskPlan(
                    intent="contextual_web_search",
                    steps=[ActionStep(
                        tool="browser.search_web",
                        arguments={"action": "search_web", "query": query},
                        description=f"Search Google for '{query}'",
                    )],
                )

        return None
