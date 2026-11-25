from pathlib import Path
import re
from typing import Any, TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from lyra.browser.manager import BrowserManager

from lyra.browser.models import BrowserAction, BrowserActionType
from lyra.browser.policy import BrowserPolicy
from lyra.core.exceptions import (
    BrowserConfirmationRequiredError,
    BrowserDownloadLimitError,
    BrowserError,
    BrowserNavigationError,
    BrowserPolicyViolationError,
    BrowserTimeoutError,
)
from lyra.models.tools import ToolRequest, ToolResult
from lyra.tools.base import Tool
from lyra.tools.permissions import ToolPermissionLevel


class BrowserTool(Tool):
    """Controlled browser automation tool for LYRA."""

    def __init__(
        self,
        manager: Any | None = None,
        policy: BrowserPolicy | None = None,
        native_controller: Any | None = None,
    ) -> None:
        if manager is None:
            from lyra.browser.manager import BrowserManager
            manager = BrowserManager(policy=policy)
        self.manager: BrowserManager = manager
        self.policy = policy or self.manager.policy
        if native_controller is None:
            from lyra.browser.native_browser import NativeBrowserController
            import sys
            use_mock = "pytest" in sys.modules or sys.platform != "darwin"
            native_controller = NativeBrowserController(use_mock=use_mock)
        self.native = native_controller

    @property
    def name(self) -> str:
        return "browser"

    @property
    def description(self) -> str:
        return (
            "Safely open websites, navigate pages, manage tabs, search Google/YouTube, "
            "control media playback, click elements, fill forms, and download files."
        )

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.LOW_RISK

    @property
    def requires_network(self) -> bool:
        return True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "navigate",
                        "open_url",
                        "new_tab",
                        "close_tab",
                        "switch_tab",
                        "list_tabs",
                        "focus_tab",
                        "search_web",
                        "search_youtube",
                        "play_media",
                        "pause_media",
                        "resume_media",
                        "open_search_result",
                        "click_result",
                        "extract",
                        "click",
                        "fill",
                        "type",
                        "scroll",
                        "press_key",
                        "go_back",
                        "download",
                        "close",
                    ],
                    "description": "Browser action to execute.",
                },
                "url": {
                    "type": "string",
                    "description": "Target website URL for navigate, open_url, or download actions.",
                },
                "query": {
                    "type": "string",
                    "description": "Search query or video title for search_web, search_youtube, or play_media.",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector or element identifier for click or fill actions.",
                },
                "value": {
                    "type": "string",
                    "description": "Text value to fill into an input field.",
                },
                "index": {
                    "type": "integer",
                    "description": "Result index (1-based) to open for open_search_result.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Must be true if confirming a sensitive, destructive, or download action.",
                },
                "session_id": {
                    "type": "string",
                    "description": "Optional session ID to maintain persistent page context.",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        """Inspect user query for intent to browse, search websites, or play media."""
        import urllib.parse
        text = user_input.strip()
        lowered = text.lower()
        cleaned = re.sub(r"(?i)^(?:hey|hi|hello|ok|okay)?\s*lyra[,:\s]*", "", text).strip()

        # Tab management intents
        if re.search(r"(?i)\b(?:open|create|make)?\s*(?:a\s+)?new\s+tab\b", cleaned):
            return {"action": "new_tab", "url": "about:blank"}
        if re.search(r"(?i)\bclose\s+(?:this|the|current)?\s*tab\b", cleaned):
            return {"action": "close_tab"}
        if re.search(r"(?i)\b(?:switch\s+to\s+(?:the\s+)?)?previous\s+tab\b", cleaned):
            return {"action": "switch_tab", "direction": "previous"}
        if re.search(r"(?i)\b(?:switch\s+to\s+(?:the\s+)?)?next\s+tab\b", cleaned):
            return {"action": "switch_tab", "direction": "next"}
        if re.search(r"(?i)\bswitch\s+tabs?\b", cleaned):
            return {"action": "switch_tab", "direction": "next"}

        # Result selection intent: "open the first result", "play the first result", "click the first result"
        if re.search(r"(?i)\b(?:open|click|play)\s+(?:the\s+)?first\s+(?:result|video|one|link)\b", cleaned):
            return {"action": "open_search_result", "index": 1}

        # YouTube and media playback: "open youtube and play <title>", "play <title> on youtube"
        match_play = re.search(
            r"(?i)\b(?:open\s+youtube\s+and\s+play|play\s+(.+?)\s+on\s+youtube|play\s+media|put\s+(.+?)\s+on\s+youtube)\b",
            cleaned,
        )
        if match_play:
            query = match_play.group(1) or match_play.group(2)
            if not query:
                m2 = re.search(r"(?i)\b(?:open\s+youtube\s+and\s+play)\s+['\"]?(.+?)['\"]?(?:\.|$)", cleaned)
                query = m2.group(1).strip() if m2 else "music"
            return {"action": "play_media", "query": query.strip()}

        # YouTube search: "search youtube for <query>"
        match_yt = re.search(r"(?i)\bsearch\s+youtube\s+for\s+['\"]?(.+?)['\"]?(?:\.|$)", cleaned)
        if match_yt:
            return {"action": "search_youtube", "query": match_yt.group(1).strip()}

        # Google / Web search: "search google for <query>", "search the web for <query>"
        match_search = re.search(r"(?i)\bsearch\s+(?:google|the\s+web|web)\s+for\s+['\"]?(.+?)['\"]?(?:\.|$)", cleaned)
        if match_search:
            return {"action": "search_web", "query": match_search.group(1).strip()}

        # Specific popular websites without URL prefix: "open youtube", "open github", "open google"
        if re.search(r"(?i)\b(?:open|go\s+to|visit)\s+youtube\b", cleaned):
            return {"action": "navigate", "url": "https://www.youtube.com"}
        if re.search(r"(?i)\b(?:open|go\s+to|visit)\s+github\b", cleaned):
            return {"action": "navigate", "url": "https://www.github.com"}
        if re.search(r"(?i)\b(?:open|go\s+to|visit)\s+google\b", cleaned):
            return {"action": "navigate", "url": "https://www.google.com"}

        # URL extraction pattern
        url_match = re.search(r"https?://[^\s\"'>]+", cleaned)
        url = url_match.group(0) if url_match else None

        # Download requests
        if re.search(r"(?i)\bdownload\b", cleaned) and url:
            return {"action": "download", "url": url}

        # Navigation requests
        if re.search(r"(?i)\b(open|browse|visit|go to|check|load)\s+(the\s+)?(website|page|site|link|url)\b", cleaned) and url:
            return {"action": "navigate", "url": url}

        if url and (cleaned.startswith("http://") or cleaned.startswith("https://") or "open" in cleaned.lower()):
            return {"action": "navigate", "url": url}

        # Extraction requests
        if re.search(r"(?i)\b(read|inspect|extract|get|show)\s+(the\s+)?(current\s+)?(page|website|site|webpage)\b", cleaned):
            return {"action": "extract"}

        return None

    def format_result(self, result: ToolResult) -> str:
        """Format browser action result for conversational display."""
        if not result.success:
            return f"Browser action failed: {result.error}"

        data = result.output if isinstance(result.output, dict) else {}
        action = data.get("action", "")
        if action in ("navigate", "open_url"):
            url_str = data.get("url", "")
            if "youtube.com" in url_str:
                return "Done. Opened YouTube."
            elif "google.com" in url_str:
                return "Done. Opened Google."
            elif "github.com" in url_str:
                return "Done. Opened GitHub."
            return f"Done. Navigated to '{url_str}'."
        elif action == "search_web":
            query = data.get("query", "")
            return f"Done. Searched Google for '{query}'."
        elif action == "search_youtube":
            query = data.get("query", "")
            return f"Done. Searched YouTube for '{query}'."
        elif action == "play_media":
            query = data.get("query", "")
            if query:
                return f"Done. {query.strip().capitalize()} is playing."
            return "Done. Video is playing."
        elif action in ("open_search_result", "click_result"):
            return "Done. Opened the first result."
        elif action == "new_tab":
            return "Done. Opened a new tab."
        elif action == "close_tab":
            return "Done. Closed the tab."
        elif action == "switch_tab":
            target = data.get("target") or data.get("direction") or "tab"
            return f"Done. Switched to {target}."
        elif action == "list_tabs":
            tabs = data.get("tabs", [])
            return f"Found {len(tabs)} open tabs."
        elif action == "focus_tab":
            return "Done. Focused browser."
        elif action == "pause_media":
            return "Done. Paused playback."
        elif action == "resume_media":
            return "Done. Resumed playback."
        elif action == "scroll":
            direction = data.get("direction", "down")
            return f"Done. Scrolled {direction}."
        elif action == "extract":
            return f"Current page: '{data.get('title')}' ({data.get('url')}):\n\n{data.get('content', '')}"
        elif action == "click":
            return f"Clicked element '{data.get('selector')}' on page {data.get('url')}."
        elif action == "fill":
            return f"Filled input '{data.get('selector')}' successfully."
        elif action == "download":
            return f"Downloaded file to '{data.get('downloaded_path')}' ({data.get('size_bytes')} bytes)."
        elif action == "close":
            return "Browser session closed successfully."

        return result.to_text()

    @staticmethod
    def _launch_system_browser(url: str) -> None:
        """Launch visible desktop browser on macOS without popping windows during automated unit tests."""
        import subprocess, sys, webbrowser
        try:
            if "pytest" not in sys.modules:
                if sys.platform == "darwin":
                    subprocess.run(["open", url], check=False, capture_output=True)
                else:
                    webbrowser.open(url)
        except Exception:
            pass

    async def execute(self, request: ToolRequest) -> ToolResult:
        """Execute browser action within an isolated session."""
        import urllib.parse
        args = request.arguments
        action_name = args.get("action")
        session_id = args.get("session_id") or f"session_{request.user_id or 'default'}"
        confirmed = bool(args.get("confirmed", False))

        try:
            session = await self.manager.get_or_create_session(
                session_id=session_id,
                user_id=request.user_id,
                policy_override=self.policy,
            )

            if action_name in ("navigate", "open_url"):
                url = args.get("url")
                if not url:
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error=f"Action '{action_name}' requires a 'url' argument.",
                    )
                if not url.startswith("http://") and not url.startswith("https://"):
                    url = f"https://{url}"
                native_res = self.native.navigate(url)
                try:
                    page = await session.navigate(url=url)
                    title = page.title
                    text_content = (await page.extract_content()).text_content
                except Exception:
                    title = native_res.get("title", "Browser")
                    text_content = ""
                session.log_action(BrowserAction(
                    action_type=BrowserActionType.NAVIGATE,
                    target=url,
                    confirmed=confirmed,
                    session_id=session_id,
                ))
                return ToolResult(
                    tool_name=self.name,
                    success=native_res.get("success", True),
                    output={
                        "action": action_name,
                        "url": url,
                        "title": title,
                        "content": text_content,
                        **native_res,
                    },
                )

            elif action_name == "search_web":
                query = args.get("query") or args.get("value") or ""
                in_new_tab = bool(args.get("in_new_tab", False))
                native_res = self.native.search_google(query, in_new_tab=in_new_tab)
                url = native_res.get("url", f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}")
                try:
                    page = await session.navigate(url=url)
                    title = page.title
                    text_content = (await page.extract_content()).text_content
                except Exception:
                    title = "Google Search"
                    text_content = ""
                session.log_action(BrowserAction(
                    action_type=BrowserActionType.NAVIGATE,
                    target=url,
                    confirmed=confirmed,
                    session_id=session_id,
                ))
                return ToolResult(
                    tool_name=self.name,
                    success=native_res.get("success", True),
                    output={
                        "action": "search_web",
                        "query": query,
                        "url": url,
                        "title": title,
                        "content": text_content,
                        **native_res,
                    },
                )

            elif action_name == "search_youtube":
                query = args.get("query") or args.get("value") or ""
                in_new_tab = bool(args.get("in_new_tab", False))
                native_res = self.native.search_youtube(query, in_new_tab=in_new_tab)
                url = native_res.get("url", f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}")
                try:
                    page = await session.navigate(url=url)
                    title = page.title
                    text_content = (await page.extract_content()).text_content
                except Exception:
                    title = "YouTube"
                    text_content = ""
                session.log_action(BrowserAction(
                    action_type=BrowserActionType.NAVIGATE,
                    target=url,
                    confirmed=confirmed,
                    session_id=session_id,
                ))
                return ToolResult(
                    tool_name=self.name,
                    success=native_res.get("success", True),
                    output={
                        "action": "search_youtube",
                        "query": query,
                        "url": url,
                        "title": title,
                        "content": text_content,
                        **native_res,
                    },
                )

            elif action_name == "new_tab":
                url = args.get("url", "about:blank")
                if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("about:"):
                    url = f"https://{url}"
                res = self.native.new_tab(url)
                # Also navigate session driver if possible
                try:
                    await session.navigate(url=url)
                except Exception:
                    pass
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={"action": "new_tab", "url": url, **res},
                )

            elif action_name == "close_tab":
                idx = args.get("index")
                res = self.native.close_tab(index=int(idx) if idx is not None else None)
                return ToolResult(
                    tool_name=self.name,
                    success=res.get("success", True),
                    output={"action": "close_tab", **res},
                )

            elif action_name == "switch_tab":
                target = args.get("target") or args.get("index") or args.get("direction") or "next"
                res = self.native.switch_tab(target)
                return ToolResult(
                    tool_name=self.name,
                    success=res.get("success", True),
                    output={"action": "switch_tab", "target": target, **res},
                )

            elif action_name == "list_tabs":
                tabs = self.native.list_tabs()
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={"action": "list_tabs", "tabs": tabs, "count": len(tabs)},
                )

            elif action_name == "focus_tab":
                self.native.focus_browser()
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={"action": "focus_tab"},
                )

            elif action_name == "pause_media":
                res = self.native.toggle_playback("pause")
                return ToolResult(
                    tool_name=self.name,
                    success=res.get("success", True),
                    output={"action": "pause_media", **res},
                )

            elif action_name == "resume_media":
                res = self.native.toggle_playback("resume")
                return ToolResult(
                    tool_name=self.name,
                    success=res.get("success", True),
                    output={"action": "resume_media", **res},
                )

            elif action_name == "click_result":
                res = self.native.click_first_result()
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={"action": "click_result", **res},
                )

            elif action_name == "play_media":
                query = args.get("query") or args.get("value") or ""
                in_new_tab = bool(args.get("in_new_tab", False))
                # Attempt native direct video playback resolution with tab reuse
                native_res = self.native.play_youtube(query, in_new_tab=in_new_tab) if hasattr(self.native, "play_youtube") else {}
                url = (
                    f"https://www.youtube.com/watch?v={native_res['video_id']}&search_query={urllib.parse.quote_plus(query)}"
                    if isinstance(native_res, dict) and "video_id" in native_res
                    else f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
                )
                try:
                    page = await session.navigate(url=url)
                    title = page.title
                    text_content = (await page.extract_content()).text_content
                except Exception:
                    title = "YouTube Playback"
                    text_content = ""
                session.log_action(BrowserAction(
                    action_type=BrowserActionType.NAVIGATE,
                    target=url,
                    confirmed=confirmed,
                    session_id=session_id,
                ))
                return ToolResult(
                    tool_name=self.name,
                    success=native_res.get("success", True),
                    output={
                        "action": "play_media",
                        "query": query,
                        "url": url,
                        "title": title,
                        "content": text_content,
                        "native": native_res,
                    },
                )

            elif action_name in ("open_search_result", "click_result"):
                idx = int(args.get("index", 1))
                query = args.get("query")
                domain = args.get("domain")

                # Try native controller first for real Mac browser
                native_res = self.native.click_first_result(last_query=query, last_domain=domain)

                # Also try session page if available
                page = await session.get_current_page()
                if page is not None:
                    try:
                        content = await page.extract_content()
                        links = content.links or []
                        link_idx = idx - 1
                        if 0 <= link_idx < len(links):
                            chosen_url = links[link_idx].get("href", "")
                            if chosen_url:
                                nav_page = await session.navigate(url=chosen_url)
                                nav_content = await nav_page.extract_content()
                                return ToolResult(
                                    tool_name=self.name,
                                    success=True,
                                    output={
                                        "action": "open_search_result",
                                        "index": idx,
                                        "url": nav_page.url,
                                        "title": nav_page.title,
                                        "content": nav_content.text_content,
                                    },
                                )
                    except Exception:
                        pass

                return ToolResult(
                    tool_name=self.name,
                    success=native_res.get("success", True),
                    output={"action": "open_search_result", "index": idx, **native_res},
                )

            elif action_name == "extract":
                page = await session.get_current_page()
                if page is None:
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error="No active webpage open in this session. Please navigate to a URL first.",
                    )
                content = await page.extract_content()
                session.log_action(BrowserAction(
                    action_type=BrowserActionType.EXTRACT,
                    target=page.url,
                    confirmed=confirmed,
                    session_id=session_id,
                ))
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={
                        "action": "extract",
                        "url": page.url,
                        "title": page.title,
                        "content": content.text_content,
                    },
                )

            elif action_name == "click":
                selector = args.get("selector")
                if not selector:
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error="Action 'click' requires a 'selector' argument.",
                    )
                page = await session.get_current_page()
                if page is None:
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error="No active webpage open in this session. Please navigate to a URL first.",
                    )

                action_obj = BrowserAction(
                    action_type=BrowserActionType.CLICK,
                    target=selector,
                    confirmed=confirmed,
                    session_id=session_id,
                )
                req_conf, reason = self.policy.check_action(action_obj)
                if req_conf and not confirmed:
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error=f"Explicit confirmation required: {reason}",
                        output={"requires_confirmation": True, "action": "click", "selector": selector},
                        metadata={"requires_confirmation": True},
                    )

                await page.click(selector=selector, confirmed=confirmed)
                session.log_action(action_obj)
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={
                        "action": "click",
                        "selector": selector,
                        "url": page.url,
                    },
                )

            elif action_name == "fill":
                selector = args.get("selector")
                value = args.get("value", "")
                if not selector:
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error="Action 'fill' requires a 'selector' argument.",
                    )
                page = await session.get_current_page()
                if page is None:
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error="No active webpage open in this session. Please navigate to a URL first.",
                    )

                action_obj = BrowserAction(
                    action_type=BrowserActionType.FILL,
                    target=selector,
                    value=value,
                    confirmed=confirmed,
                    session_id=session_id,
                )
                req_conf, reason = self.policy.check_action(action_obj)
                if req_conf and not confirmed:
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error=f"Explicit confirmation required: {reason}",
                        output={"requires_confirmation": True, "action": "fill", "selector": selector},
                        metadata={"requires_confirmation": True},
                    )

                await page.fill(selector=selector, value=value, confirmed=confirmed)
                session.log_action(action_obj)
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={
                        "action": "fill",
                        "selector": selector,
                        "url": page.url,
                    },
                )

            elif action_name == "download":
                target = args.get("url") or args.get("selector")
                if not target:
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error="Action 'download' requires a 'url' or 'selector' argument.",
                    )

                action_obj = BrowserAction(
                    action_type=BrowserActionType.DOWNLOAD,
                    target=target,
                    confirmed=confirmed,
                    session_id=session_id,
                )
                req_conf, reason = self.policy.check_action(action_obj)
                if req_conf and not confirmed:
                    return ToolResult(
                        tool_name=self.name,
                        success=False,
                        error=f"Explicit confirmation required: {reason}",
                        output={"requires_confirmation": True, "action": "download", "target": target},
                        metadata={"requires_confirmation": True},
                    )

                page = await session.get_current_page()
                if page is None:
                    # If no page currently open, navigate to target domain or download directly
                    if target.startswith("http://") or target.startswith("https://") or target.startswith("file://"):
                        page = await session.navigate(url=target)
                    else:
                        return ToolResult(
                            tool_name=self.name,
                            success=False,
                            error="No active page open to download from selector.",
                        )

                dest_path = await page.download(target=target, confirmed=confirmed)
                session.log_action(action_obj)
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={
                        "action": "download",
                        "downloaded_path": str(dest_path),
                        "size_bytes": dest_path.stat().st_size,
                    },
                )

            elif action_name == "close":
                await self.manager.close_session(session_id)
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    output={"action": "close", "session_id": session_id},
                )

            else:
                return ToolResult(
                    tool_name=self.name,
                    success=False,
                    error=f"Unrecognized browser action '{action_name}'.",
                )

        except (
            BrowserPolicyViolationError,
            BrowserConfirmationRequiredError,
            BrowserDownloadLimitError,
            BrowserNavigationError,
            BrowserTimeoutError,
            BrowserError,
        ) as err:
            return ToolResult(tool_name=self.name, success=False, error=str(err))
        except Exception as err:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Unexpected error during browser action: {err}",
            )
