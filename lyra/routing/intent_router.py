"""Intent Router and Task Classification Engine for LYRA.

Classifies natural language commands into standardized intent categories, extracts entities,
and maps user intent directly to appropriate tools, executors, or Anakin workflows.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import re
from typing import Any

from lyra.observability.logging import get_logger

logger = get_logger("routing.intent_router")


class IntentCategory(str, Enum):
    """Canonical intent categories for task classification."""

    OPEN_APP = "OPEN_APP"
    CLOSE_APP = "CLOSE_APP"
    CREATE_FOLDER = "CREATE_FOLDER"
    DELETE_FILE = "DELETE_FILE"
    MOVE_FILE = "MOVE_FILE"
    RENAME_FILE = "RENAME_FILE"
    WRITE_TEXT = "WRITE_TEXT"
    READ_TEXT = "READ_TEXT"
    OPEN_URL = "OPEN_URL"
    SEARCH_WEB = "SEARCH_WEB"
    SEARCH_GOOGLE = "SEARCH_GOOGLE"
    PLAY_MEDIA = "PLAY_MEDIA"
    BROWSER_NAVIGATION = "BROWSER_NAVIGATION"
    CLICK_ELEMENT = "CLICK_ELEMENT"
    TYPE_TEXT = "TYPE_TEXT"
    SCROLL = "SCROLL"
    NEW_TAB = "NEW_TAB"
    CLOSE_TAB = "CLOSE_TAB"
    BRIGHTNESS_CONTROL = "BRIGHTNESS_CONTROL"
    VOLUME_CONTROL = "VOLUME_CONTROL"
    SYSTEM_CONTROL = "SYSTEM_CONTROL"
    FILE_OPERATION = "FILE_OPERATION"
    CODE_OPERATION = "CODE_OPERATION"
    AI_QUERY = "AI_QUERY"
    RESEARCH = "RESEARCH"
    LEARNING = "LEARNING"
    ANAKIN_WORKFLOW = "ANAKIN_WORKFLOW"
    OTHER = "OTHER"


@dataclass
class IntentClassificationResult:
    """Structured result of natural language intent classification."""

    category: IntentCategory
    confidence: float
    entities: dict[str, Any] = field(default_factory=dict)
    suggested_tool: str | None = None
    suggested_action: str | None = None
    risk_level: str = "LOW"  # LOW, MEDIUM, HIGH
    requires_confirmation: bool = False
    raw_input: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "confidence": self.confidence,
            "entities": self.entities,
            "suggested_tool": self.suggested_tool,
            "suggested_action": self.suggested_action,
            "risk_level": self.risk_level,
            "requires_confirmation": self.requires_confirmation,
            "raw_input": self.raw_input,
        }


class IntentRouter:
    """Routes and classifies user natural language utterances into discrete intent categories."""

    def __init__(self, workflow_registry: list[dict[str, Any]] | None = None) -> None:
        self.workflow_registry = workflow_registry or []

    def _clean_input(self, text: str) -> str:
        """Strip conversational wake words and polite prefixes."""
        cleaned = text.strip()
        cleaned = re.sub(r"(?i)^(?:hey|hi|hello|ok|okay)?\s*lyra[,:\s]*", "", cleaned).strip()
        cleaned = re.sub(r"(?i)^(?:can|could|would)\s+you(?:\s+please)?\s+", "", cleaned)
        cleaned = re.sub(r"(?i)^please\s+", "", cleaned)
        cleaned = re.sub(r"(?i)[,\s]+please[.?]?$", "", cleaned)
        if cleaned and cleaned[-1] in ".?!" and not (len(cleaned) >= 2 and cleaned[-2] in "\"'"):
            cleaned = cleaned.rstrip(".?! \t")
        return cleaned.strip()

    def classify(self, user_input: str) -> IntentClassificationResult:
        """Classify user natural language input into a canonical IntentCategory."""
        raw = user_input.strip()
        cleaned = self._clean_input(raw)
        lowered = cleaned.lower()

        # 1. BRIGHTNESS CONTROL
        if any(w in lowered for w in ("brightness", "brighter", "darker", "screen light")):
            if any(w in lowered for w in ("increase", "turn up", "make screen brighter", "brighter", "more brightness")):
                return IntentClassificationResult(
                    category=IntentCategory.BRIGHTNESS_CONTROL,
                    confidence=0.98,
                    entities={"action": "increase", "delta": 0.1},
                    suggested_tool="system",
                    suggested_action="increase_brightness",
                    risk_level="LOW",
                    raw_input=raw,
                )
            if any(w in lowered for w in ("decrease", "turn down", "make screen darker", "darker", "dimmer", "less brightness")):
                return IntentClassificationResult(
                    category=IntentCategory.BRIGHTNESS_CONTROL,
                    confidence=0.98,
                    entities={"action": "decrease", "delta": 0.1},
                    suggested_tool="system",
                    suggested_action="decrease_brightness",
                    risk_level="LOW",
                    raw_input=raw,
                )
            m_set = re.search(r"(?i)set\s+brightness\s+(?:to\s+)?(\d+)(?:%|\s*percent)?", cleaned)
            if m_set:
                pct = int(m_set.group(1))
                return IntentClassificationResult(
                    category=IntentCategory.BRIGHTNESS_CONTROL,
                    confidence=0.99,
                    entities={"action": "set", "level": pct},
                    suggested_tool="system",
                    suggested_action="set_brightness",
                    risk_level="LOW",
                    raw_input=raw,
                )

        # 2. VOLUME CONTROL
        if any(w in lowered for w in ("volume", "mute", "unmute", "sound")):
            if "unmute" in lowered:
                return IntentClassificationResult(
                    category=IntentCategory.VOLUME_CONTROL,
                    confidence=0.99,
                    entities={"action": "unmute"},
                    suggested_tool="system",
                    suggested_action="unmute",
                    risk_level="LOW",
                    raw_input=raw,
                )
            if "mute" in lowered:
                return IntentClassificationResult(
                    category=IntentCategory.VOLUME_CONTROL,
                    confidence=0.99,
                    entities={"action": "mute"},
                    suggested_tool="system",
                    suggested_action="mute",
                    risk_level="LOW",
                    raw_input=raw,
                )
            if (
                any(w in lowered for w in ("increase", "turn up", "louder", "raise"))
                or re.search(r"\b(?:turn|bring)\s+(?:the\s+)?volume\s+up\b", lowered)
                or re.search(r"\bvolume\s+up\b", lowered)
            ):
                return IntentClassificationResult(
                    category=IntentCategory.VOLUME_CONTROL,
                    confidence=0.98,
                    entities={"action": "increase", "delta": 10},
                    suggested_tool="system",
                    suggested_action="increase_volume",
                    risk_level="LOW",
                    raw_input=raw,
                )
            if (
                any(w in lowered for w in ("decrease", "turn down", "softer", "lower", "drop"))
                or re.search(r"\b(?:turn|bring)\s+(?:the\s+)?volume\s+down\b", lowered)
                or re.search(r"\bvolume\s+down\b", lowered)
            ):
                return IntentClassificationResult(
                    category=IntentCategory.VOLUME_CONTROL,
                    confidence=0.98,
                    entities={"action": "decrease", "delta": 10},
                    suggested_tool="system",
                    suggested_action="decrease_volume",
                    risk_level="LOW",
                    raw_input=raw,
                )

        # 3. WRITE TEXT / NOTES
        if "notes" in lowered and any(w in lowered for w in ("write", "type", "create a note", "take a note")):
            m_write = re.search(r"(?i)(?:write|type)\s+['\"]?(.+?)['\"]?(?:\s+in\s+notes|$)", cleaned)
            text = m_write.group(1).strip() if m_write else ""
            return IntentClassificationResult(
                category=IntentCategory.WRITE_TEXT,
                confidence=0.99,
                entities={"application": "Notes", "text": text, "action": "write_note"},
                suggested_tool="notes",
                suggested_action="write_note",
                risk_level="MEDIUM",
                raw_input=raw,
            )

        if "notes" in lowered and any(w in lowered for w in ("read notes", "show my notes", "get notes")):
            return IntentClassificationResult(
                category=IntentCategory.READ_TEXT,
                confidence=0.95,
                entities={"application": "Notes", "action": "read_notes"},
                suggested_tool="notes",
                suggested_action="read_notes",
                risk_level="LOW",
                raw_input=raw,
            )

        # 4. YOUTUBE / MEDIA PLAYBACK
        if "youtube" in lowered and any(w in lowered for w in ("play", "listen to", "watch", "song", "video")):
            m_play = re.search(r"(?i)(?:play|listen to|watch)\s+['\"]?(.+?)['\"]?(?:\s+on\s+youtube|$)", cleaned)
            track = m_play.group(1).strip() if m_play else ""
            return IntentClassificationResult(
                category=IntentCategory.PLAY_MEDIA,
                confidence=0.99,
                entities={"service": "YouTube", "query": track},
                suggested_tool="browser",
                suggested_action="play_media",
                risk_level="LOW",
                raw_input=raw,
            )
        if re.search(r"(?i)^play\s+['\"]?(.+?)['\"]?$", cleaned) and not any(w in lowered for w in ("game", "sports")):
            track = re.search(r"(?i)^play\s+['\"]?(.+?)['\"]?$", cleaned).group(1).strip()
            return IntentClassificationResult(
                category=IntentCategory.PLAY_MEDIA,
                confidence=0.95,
                entities={"service": "YouTube", "query": track},
                suggested_tool="browser",
                suggested_action="play_media",
                risk_level="LOW",
                raw_input=raw,
            )

        # 5. GOOGLE SEARCH / WEB SEARCH
        if "google" in lowered and ("search" in lowered or "look up" in lowered):
            m_search = re.search(r"(?i)search\s+google\s+for\s+['\"]?(.+?)['\"]?(?:$|\.)", cleaned)
            if not m_search:
                m_search = re.search(r"(?i)google\s+['\"]?(.+?)['\"]?(?:$|\.)", cleaned)
            query = m_search.group(1).strip() if m_search else ""
            in_new_tab = "new tab" in lowered or "new browser tab" in lowered
            return IntentClassificationResult(
                category=IntentCategory.SEARCH_GOOGLE,
                confidence=0.99,
                entities={"query": query, "in_new_tab": in_new_tab, "search_engine": "Google"},
                suggested_tool="browser",
                suggested_action="search_google",
                risk_level="LOW",
                raw_input=raw,
            )

        if re.search(r"(?i)\bsearch\s+(?:the\s+)?web\s+for\s+['\"]?(.+?)['\"]?", cleaned):
            m_q = re.search(r"(?i)\bsearch\s+(?:the\s+)?web\s+for\s+['\"]?(.+?)['\"]?", cleaned)
            query = m_q.group(1).strip() if m_q else ""
            return IntentClassificationResult(
                category=IntentCategory.SEARCH_WEB,
                confidence=0.98,
                entities={"query": query},
                suggested_tool="browser",
                suggested_action="search_web",
                risk_level="LOW",
                raw_input=raw,
            )

        # 6. TAB CONTROLS (NEW TAB, CLOSE TAB)
        if re.search(r"(?i)\b(?:open|create)\s+(?:a\s+)?new\s+(?:browser\s+)?tab\b", cleaned):
            return IntentClassificationResult(
                category=IntentCategory.NEW_TAB,
                confidence=0.98,
                entities={"action": "new_tab"},
                suggested_tool="browser",
                suggested_action="new_tab",
                risk_level="LOW",
                raw_input=raw,
            )
        if re.search(r"(?i)\bclose\s+(?:the\s+|this\s+)?(?:current\s+)?tab\b", cleaned):
            return IntentClassificationResult(
                category=IntentCategory.CLOSE_TAB,
                confidence=0.98,
                entities={"action": "close_tab"},
                suggested_tool="browser",
                suggested_action="close_tab",
                risk_level="LOW",
                raw_input=raw,
            )

        # 7. BROWSER NAVIGATION & CONTROLS
        if re.search(r"(?i)\b(?:go\s+back|previous\s+page)\b", cleaned):
            return IntentClassificationResult(
                category=IntentCategory.BROWSER_NAVIGATION,
                confidence=0.98,
                entities={"action": "go_back"},
                suggested_tool="browser",
                suggested_action="go_back",
                risk_level="LOW",
                raw_input=raw,
            )
        if re.search(r"(?i)\bscroll\s+(?:down|up)\b", cleaned):
            direction = "down" if "down" in lowered else "up"
            return IntentClassificationResult(
                category=IntentCategory.SCROLL,
                confidence=0.98,
                entities={"direction": direction},
                suggested_tool="browser",
                suggested_action="scroll",
                risk_level="LOW",
                raw_input=raw,
            )
        if re.search(r"(?i)\bclick\s+(?:the\s+)?(?:first\s+)?(?:search\s+)?result\b", cleaned):
            return IntentClassificationResult(
                category=IntentCategory.CLICK_ELEMENT,
                confidence=0.98,
                entities={"index": 1, "target": "search_result"},
                suggested_tool="browser",
                suggested_action="open_search_result",
                risk_level="LOW",
                raw_input=raw,
            )
        if re.search(r"(?i)\bopen\s+(?:this\s+|the\s+)?(?:link|result)\s+in\s+(?:a\s+)?new\s+tab\b", cleaned):
            return IntentClassificationResult(
                category=IntentCategory.NEW_TAB,
                confidence=0.98,
                entities={"action": "new_tab", "source": "current_link"},
                suggested_tool="browser",
                suggested_action="new_tab",
                risk_level="LOW",
                raw_input=raw,
            )
        if re.search(r"(?i)^open\s+(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9.\-]+\.(?:com|org|io|dev|ai|net))", cleaned):
            m_url = re.search(r"(?i)^open\s+(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9.\-]+\.(?:com|org|io|dev|ai|net))", cleaned)
            url = m_url.group(1).strip()
            return IntentClassificationResult(
                category=IntentCategory.OPEN_URL,
                confidence=0.99,
                entities={"url": url},
                suggested_tool="browser",
                suggested_action="navigate",
                risk_level="LOW",
                raw_input=raw,
            )

        # 8. RESEARCH INTENT
        if re.search(r"(?i)\bresearch\s+(?:the\s+)?(.+?)(?:$|\.)", cleaned):
            topic = re.search(r"(?i)\bresearch\s+(?:the\s+)?(.+?)(?:$|\.)", cleaned).group(1).strip()
            return IntentClassificationResult(
                category=IntentCategory.RESEARCH,
                confidence=0.98,
                entities={"topic": topic, "task_type": "research"},
                suggested_tool="research_workflow",
                suggested_action="run_workflow",
                risk_level="LOW",
                raw_input=raw,
            )

        # 9. ANAKIN WORKFLOWS / RESUME ANALYSIS
        if "resume" in lowered and any(w in lowered for w in ("analyze", "review", "evaluate", "check")):
            return IntentClassificationResult(
                category=IntentCategory.ANAKIN_WORKFLOW,
                confidence=0.98,
                entities={"workflow": "resume_analyzer", "task_type": "workflow"},
                suggested_tool="resume_analyzer",
                suggested_action="run_workflow",
                risk_level="LOW",
                raw_input=raw,
            )

        # 10. FOLDER & FILE DESTRUCTION (HIGH RISK)
        if re.search(r"(?i)\b(?:delete|remove|erase)\s+(?:the\s+)?(?:file|folder|directory)\s+['\"]?(.+?)['\"]?", cleaned):
            target = re.search(r"(?i)\b(?:delete|remove|erase)\s+(?:the\s+)?(?:file|folder|directory)\s+['\"]?(.+?)['\"]?", cleaned).group(1).strip()
            return IntentClassificationResult(
                category=IntentCategory.DELETE_FILE,
                confidence=0.98,
                entities={"target": target, "action": "delete"},
                suggested_tool="filesystem",
                suggested_action="delete",
                risk_level="HIGH",
                requires_confirmation=True,
                raw_input=raw,
            )

        # 11. MOVE & RENAME FILE
        if re.search(r"(?i)\bmove\s+['\"]?(.+?)['\"]?\s+(?:in)?to\s+['\"]?(.+?)['\"]?", cleaned):
            m_move = re.search(r"(?i)\bmove\s+['\"]?(.+?)['\"]?\s+(?:in)?to\s+['\"]?(.+?)['\"]?", cleaned)
            src, dest = m_move.group(1).strip(), m_move.group(2).strip()
            return IntentClassificationResult(
                category=IntentCategory.MOVE_FILE,
                confidence=0.98,
                entities={"source": src, "destination": dest},
                suggested_tool="filesystem",
                suggested_action="move",
                risk_level="MEDIUM",
                raw_input=raw,
            )
        if re.search(r"(?i)\brename\s+(?:folder\s+|file\s+)?['\"]?(.+?)['\"]?\s+to\s+['\"]?(.+?)['\"]?", cleaned):
            m_ren = re.search(r"(?i)\brename\s+(?:folder\s+|file\s+)?['\"]?(.+?)['\"]?\s+to\s+['\"]?(.+?)['\"]?", cleaned)
            src, dest = m_ren.group(1).strip(), m_ren.group(2).strip()
            return IntentClassificationResult(
                category=IntentCategory.RENAME_FILE,
                confidence=0.98,
                entities={"source": src, "new_name": dest},
                suggested_tool="filesystem",
                suggested_action="rename",
                risk_level="MEDIUM",
                raw_input=raw,
            )

        # 12. CREATE FOLDER / FOLDER STRUCTURE
        if any(w in lowered for w in ("create a folder", "make a folder", "create this structure", "create this folder structure", "folder structure")):
            return IntentClassificationResult(
                category=IntentCategory.CREATE_FOLDER,
                confidence=0.99,
                entities={"raw_command": cleaned},
                suggested_tool="filesystem",
                suggested_action="create_directory",
                risk_level="MEDIUM",
                raw_input=raw,
            )

        # 13. CODE OPERATION
        if any(w in lowered for w in ("create a python file", "create a python project", "write this code into", "open main.py")):
            return IntentClassificationResult(
                category=IntentCategory.CODE_OPERATION,
                confidence=0.95,
                entities={"raw_command": cleaned},
                suggested_tool="filesystem",
                suggested_action="create_file",
                risk_level="MEDIUM",
                raw_input=raw,
            )

        # 14. OPEN APP & CLOSE APP
        if re.search(r"(?i)^(?:open|launch)\s+(?:the\s+)?([a-zA-Z0-9_\- ]+?)(?:app)?(?:$|\.)", cleaned):
            app = re.search(r"(?i)^(?:open|launch)\s+(?:the\s+)?([a-zA-Z0-9_\- ]+?)(?:app)?(?:$|\.)", cleaned).group(1).strip()
            # Normalize app name
            app_lower = app.lower()
            if "vs code" in app_lower or "vscode" in app_lower or "visual studio code" in app_lower:
                app = "Visual Studio Code"
            elif "chrome" in app_lower:
                app = "Google Chrome"
            elif "notes" in app_lower:
                app = "Notes"
            elif "terminal" in app_lower:
                app = "Terminal"
            elif "finder" in app_lower:
                app = "Finder"

            return IntentClassificationResult(
                category=IntentCategory.OPEN_APP,
                confidence=0.98,
                entities={"app_name": app},
                suggested_tool="system" if app != "Notes" else "notes",
                suggested_action="open_application" if app != "Notes" else "open_notes",
                risk_level="LOW",
                raw_input=raw,
            )

        if re.search(r"(?i)^(?:close|quit)\s+(?:the\s+)?([a-zA-Z0-9_\- ]+?)(?:app)?(?:$|\.)", cleaned):
            app = re.search(r"(?i)^(?:close|quit)\s+(?:the\s+)?([a-zA-Z0-9_\- ]+?)(?:app)?(?:$|\.)", cleaned).group(1).strip()
            return IntentClassificationResult(
                category=IntentCategory.CLOSE_APP,
                confidence=0.98,
                entities={"app_name": app},
                suggested_tool="system",
                suggested_action="close_application",
                risk_level="LOW",
                raw_input=raw,
            )

        # 15. SYSTEM CONTROLS (WI-FI, ETC.)
        if "wi-fi" in lowered or "wifi" in lowered:
            state = "off" if "off" in lowered else ("on" if "on" in lowered else "status")
            return IntentClassificationResult(
                category=IntentCategory.SYSTEM_CONTROL,
                confidence=0.95,
                entities={"component": "wifi", "state": state},
                suggested_tool="system",
                suggested_action="network_control",
                risk_level="HIGH" if state == "off" else "LOW",
                raw_input=raw,
            )

        # 16. LEARNING
        if any(w in lowered for w in ("learning plan", "weekly learning", "learning progress", "study roadmap")):
            return IntentClassificationResult(
                category=IntentCategory.LEARNING,
                confidence=0.95,
                entities={"topic": cleaned},
                suggested_tool="learning",
                suggested_action="get_plan",
                risk_level="LOW",
                raw_input=raw,
            )

        # 17. DEFAULT AI QUERY / GENERAL CONVERSATION
        return IntentClassificationResult(
            category=IntentCategory.AI_QUERY,
            confidence=0.85,
            entities={"prompt": cleaned},
            suggested_tool=None,
            suggested_action=None,
            risk_level="LOW",
            raw_input=raw,
        )
