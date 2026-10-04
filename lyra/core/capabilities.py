"""Central Capability Registry and definition system for LYRA.

Defines all supported system, filesystem, browser, media, and hardware capabilities,
mapping natural language operations to registered tools, actions, schemas, and permissions.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from lyra.tools.permissions import ToolPermissionLevel


class CapabilityNamespace(str, Enum):
    """Namespaces grouping related computer and assistant capabilities."""

    SYSTEM = "system"
    FILESYSTEM = "filesystem"
    BROWSER = "browser"
    YOUTUBE = "youtube"
    MEDIA = "media"
    KEYBOARD = "keyboard"
    MOUSE = "mouse"
    SCREEN = "screen"
    APPLICATIONS = "applications"
    NOTES = "notes"


@dataclass
class Capability:
    """A registered discrete capability that LYRA can execute."""

    name: str
    namespace: CapabilityNamespace
    tool_name: str
    action: str
    description: str
    parameters_schema: dict[str, Any] = field(default_factory=dict)
    permission_level: ToolPermissionLevel = ToolPermissionLevel.LOW_RISK
    fast_path_patterns: list[str] = field(default_factory=list)


class CapabilityRegistry:
    """Maintains universal capabilities and routes intents to underlying tools."""

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}
        self._register_default_capabilities()

    def register(self, capability: Capability) -> None:
        """Register a new capability."""
        self._capabilities[capability.name.lower().strip()] = capability

    def get(self, name: str) -> Capability | None:
        """Retrieve capability by name (e.g. 'system.set_brightness' or 'set_brightness')."""
        norm = name.lower().strip()
        if norm in self._capabilities:
            return self._capabilities[norm]
        if "." in norm:
            action = norm.split(".", 1)[1]
            if action in self._capabilities:
                return self._capabilities[action]
        return None

    def list_capabilities(self, namespace: CapabilityNamespace | None = None) -> list[Capability]:
        """List all registered capabilities, optionally filtered by namespace."""
        caps = list(self._capabilities.values())
        if namespace:
            caps = [c for c in caps if c.namespace == namespace]
        return caps

    def _register_default_capabilities(self) -> None:
        """Register the standard universal capabilities required by LYRA."""

        # ---------------- SYSTEM ----------------
        self.register(Capability(
            name="get_brightness",
            namespace=CapabilityNamespace.SYSTEM,
            tool_name="system",
            action="get_brightness",
            description="Get current Mac display brightness level.",
            permission_level=ToolPermissionLevel.READ_ONLY,
        ))
        self.register(Capability(
            name="set_brightness",
            namespace=CapabilityNamespace.SYSTEM,
            tool_name="system",
            action="set_brightness",
            description="Set Mac display brightness to a specific level (0.0 - 1.0 or 0 - 100%).",
            parameters_schema={"level": {"type": "number"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="increase_brightness",
            namespace=CapabilityNamespace.SYSTEM,
            tool_name="system",
            action="increase_brightness",
            description="Increase Mac display brightness by a step amount.",
            parameters_schema={"delta": {"type": "number", "default": 0.1}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="decrease_brightness",
            namespace=CapabilityNamespace.SYSTEM,
            tool_name="system",
            action="decrease_brightness",
            description="Decrease Mac display brightness by a step amount.",
            parameters_schema={"delta": {"type": "number", "default": 0.1}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="get_volume",
            namespace=CapabilityNamespace.SYSTEM,
            tool_name="system",
            action="get_volume",
            description="Get current system audio volume and mute state.",
            permission_level=ToolPermissionLevel.READ_ONLY,
        ))
        self.register(Capability(
            name="set_volume",
            namespace=CapabilityNamespace.SYSTEM,
            tool_name="system",
            action="set_volume",
            description="Set system audio volume (0 - 100%).",
            parameters_schema={"level": {"type": "integer"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="increase_volume",
            namespace=CapabilityNamespace.SYSTEM,
            tool_name="system",
            action="increase_volume",
            description="Increase system audio volume.",
            parameters_schema={"delta": {"type": "integer", "default": 10}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="decrease_volume",
            namespace=CapabilityNamespace.SYSTEM,
            tool_name="system",
            action="decrease_volume",
            description="Decrease system audio volume.",
            parameters_schema={"delta": {"type": "integer", "default": 10}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="mute",
            namespace=CapabilityNamespace.SYSTEM,
            tool_name="system",
            action="mute",
            description="Mute system audio.",
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="unmute",
            namespace=CapabilityNamespace.SYSTEM,
            tool_name="system",
            action="unmute",
            description="Unmute system audio.",
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))

        # ---------------- APPLICATIONS ----------------
        self.register(Capability(
            name="open_application",
            namespace=CapabilityNamespace.APPLICATIONS,
            tool_name="system",
            action="open_application",
            description="Open or launch a desktop application (e.g. Finder, Chrome, VS Code).",
            parameters_schema={"app_name": {"type": "string"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="close_application",
            namespace=CapabilityNamespace.APPLICATIONS,
            tool_name="system",
            action="close_application",
            description="Close or quit a running desktop application.",
            parameters_schema={"app_name": {"type": "string"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="focus_application",
            namespace=CapabilityNamespace.APPLICATIONS,
            tool_name="system",
            action="focus_application",
            description="Switch focus to a desktop application.",
            parameters_schema={"app_name": {"type": "string"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))

        # ---------------- FILESYSTEM ----------------
        self.register(Capability(
            name="create_directory",
            namespace=CapabilityNamespace.FILESYSTEM,
            tool_name="filesystem",
            action="create_directory",
            description="Create a directory or folder on the filesystem.",
            parameters_schema={"path": {"type": "string"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="create_file",
            namespace=CapabilityNamespace.FILESYSTEM,
            tool_name="filesystem",
            action="create_file",
            description="Create a file with optional content on the filesystem.",
            parameters_schema={"path": {"type": "string"}, "content": {"type": "string", "default": ""}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="create_structure",
            namespace=CapabilityNamespace.FILESYSTEM,
            tool_name="filesystem",
            action="create_structure",
            description="Create a hierarchical folder structure on the filesystem.",
            parameters_schema={"structure": {"type": "string"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))

        # ---------------- NOTES ----------------
        self.register(Capability(
            name="open_notes",
            namespace=CapabilityNamespace.NOTES,
            tool_name="notes",
            action="open_notes",
            description="Open and activate macOS Apple Notes.",
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="write_note",
            namespace=CapabilityNamespace.NOTES,
            tool_name="notes",
            action="write_note",
            description="Create or write text into a note in macOS Notes and verify.",
            parameters_schema={"text": {"type": "string"}, "title": {"type": "string"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="create_note",
            namespace=CapabilityNamespace.NOTES,
            tool_name="notes",
            action="create_note",
            description="Create a new note in macOS Notes with optional title and content.",
            parameters_schema={"text": {"type": "string"}, "title": {"type": "string"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="read_file",
            namespace=CapabilityNamespace.FILESYSTEM,
            tool_name="filesystem",
            action="read_file",
            description="Read content of a file.",
            parameters_schema={"path": {"type": "string"}},
            permission_level=ToolPermissionLevel.READ_ONLY,
        ))
        self.register(Capability(
            name="list_directory",
            namespace=CapabilityNamespace.FILESYSTEM,
            tool_name="filesystem",
            action="list_directory",
            description="List contents of a directory.",
            parameters_schema={"path": {"type": "string"}},
            permission_level=ToolPermissionLevel.READ_ONLY,
        ))
        self.register(Capability(
            name="rename",
            namespace=CapabilityNamespace.FILESYSTEM,
            tool_name="filesystem",
            action="rename",
            description="Rename a file or folder.",
            parameters_schema={"path": {"type": "string"}, "destination": {"type": "string"}},
            permission_level=ToolPermissionLevel.CONFIRMATION_REQUIRED,
        ))
        self.register(Capability(
            name="move",
            namespace=CapabilityNamespace.FILESYSTEM,
            tool_name="filesystem",
            action="move",
            description="Move a file or folder to a new location.",
            parameters_schema={"path": {"type": "string"}, "destination": {"type": "string"}},
            permission_level=ToolPermissionLevel.CONFIRMATION_REQUIRED,
        ))
        self.register(Capability(
            name="delete",
            namespace=CapabilityNamespace.FILESYSTEM,
            tool_name="filesystem",
            action="delete",
            description="Delete a file or folder (requires explicit user confirmation).",
            parameters_schema={"path": {"type": "string"}, "confirmed": {"type": "boolean", "default": False}},
            permission_level=ToolPermissionLevel.CONFIRMATION_REQUIRED,
        ))
        self.register(Capability(
            name="open_path",
            namespace=CapabilityNamespace.FILESYSTEM,
            tool_name="filesystem",
            action="open_path",
            description="Open a file or folder in macOS Finder.",
            parameters_schema={"path": {"type": "string"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))

        # ---------------- BROWSER ----------------
        self.register(Capability(
            name="open_browser",
            namespace=CapabilityNamespace.BROWSER,
            tool_name="browser",
            action="navigate",
            description="Open or focus the browser.",
            parameters_schema={"url": {"type": "string", "default": "https://www.google.com"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="open_url",
            namespace=CapabilityNamespace.BROWSER,
            tool_name="browser",
            action="navigate",
            description="Navigate browser to a specified URL.",
            parameters_schema={"url": {"type": "string"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="new_tab",
            namespace=CapabilityNamespace.BROWSER,
            tool_name="browser",
            action="new_tab",
            description="Open a new browser tab.",
            parameters_schema={"url": {"type": "string", "default": "about:blank"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="close_tab",
            namespace=CapabilityNamespace.BROWSER,
            tool_name="browser",
            action="close_tab",
            description="Close the active browser tab or tab by index.",
            parameters_schema={"index": {"type": "integer"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="switch_tab",
            namespace=CapabilityNamespace.BROWSER,
            tool_name="browser",
            action="switch_tab",
            description="Switch browser tabs by direction or index.",
            parameters_schema={"direction": {"type": "string"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="list_tabs",
            namespace=CapabilityNamespace.BROWSER,
            tool_name="browser",
            action="list_tabs",
            description="List open browser tabs.",
            permission_level=ToolPermissionLevel.READ_ONLY,
        ))
        self.register(Capability(
            name="search_google",
            namespace=CapabilityNamespace.BROWSER,
            tool_name="browser",
            action="search_web",
            description="Search Google in the browser.",
            parameters_schema={"query": {"type": "string"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="search_web",
            namespace=CapabilityNamespace.BROWSER,
            tool_name="browser",
            action="search_web",
            description="Search the web in the browser.",
            parameters_schema={"query": {"type": "string"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="navigate",
            namespace=CapabilityNamespace.BROWSER,
            tool_name="browser",
            action="navigate",
            description="Navigate active tab to a URL.",
            parameters_schema={"url": {"type": "string"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="go_back",
            namespace=CapabilityNamespace.BROWSER,
            tool_name="browser",
            action="go_back",
            description="Navigate back in browser history.",
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="scroll",
            namespace=CapabilityNamespace.BROWSER,
            tool_name="browser",
            action="scroll",
            description="Scroll the active page.",
            parameters_schema={"direction": {"type": "string", "default": "down"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))

        # ---------------- YOUTUBE ----------------
        self.register(Capability(
            name="open_youtube",
            namespace=CapabilityNamespace.YOUTUBE,
            tool_name="browser",
            action="navigate",
            description="Open YouTube in the browser.",
            parameters_schema={"url": {"type": "string", "default": "https://www.youtube.com"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="search_youtube",
            namespace=CapabilityNamespace.YOUTUBE,
            tool_name="browser",
            action="search_youtube",
            description="Search YouTube for videos.",
            parameters_schema={"query": {"type": "string"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="play_youtube",
            namespace=CapabilityNamespace.YOUTUBE,
            tool_name="browser",
            action="play_media",
            description="Search and play a video/song directly on YouTube.",
            parameters_schema={"query": {"type": "string"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="click_result",
            namespace=CapabilityNamespace.YOUTUBE,
            tool_name="browser",
            action="open_search_result",
            description="Open the first or specified search result on YouTube or Google.",
            parameters_schema={"index": {"type": "integer", "default": 1}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))

        # ---------------- MEDIA CONTROLS ----------------
        self.register(Capability(
            name="pause_media",
            namespace=CapabilityNamespace.MEDIA,
            tool_name="media",
            action="pause",
            description="Pause audio/video playback.",
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="resume_media",
            namespace=CapabilityNamespace.MEDIA,
            tool_name="media",
            action="resume",
            description="Resume audio/video playback.",
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="stop_media",
            namespace=CapabilityNamespace.MEDIA,
            tool_name="media",
            action="stop",
            description="Stop audio/video playback.",
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="next_media",
            namespace=CapabilityNamespace.MEDIA,
            tool_name="media",
            action="next",
            description="Skip to next media track or video.",
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="previous_media",
            namespace=CapabilityNamespace.MEDIA,
            tool_name="media",
            action="previous",
            description="Skip to previous media track or video.",
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))

        # ---------------- KEYBOARD & MOUSE ----------------
        self.register(Capability(
            name="press_key",
            namespace=CapabilityNamespace.KEYBOARD,
            tool_name="keyboard",
            action="press",
            description="Press a keyboard key.",
            parameters_schema={"key": {"type": "string"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="type_text",
            namespace=CapabilityNamespace.KEYBOARD,
            tool_name="keyboard",
            action="type",
            description="Type text via keyboard.",
            parameters_schema={"text": {"type": "string"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="hotkey",
            namespace=CapabilityNamespace.KEYBOARD,
            tool_name="keyboard",
            action="hotkey",
            description="Trigger a keyboard hotkey combination.",
            parameters_schema={"keys": {"type": "array"}},
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))
        self.register(Capability(
            name="mouse_click",
            namespace=CapabilityNamespace.MOUSE,
            tool_name="mouse",
            action="click",
            description="Click mouse button.",
            permission_level=ToolPermissionLevel.LOW_RISK,
        ))

        # ---------------- SCREEN ----------------
        self.register(Capability(
            name="screenshot",
            namespace=CapabilityNamespace.SCREEN,
            tool_name="vision",
            action="screenshot",
            description="Take a screenshot of the current screen.",
            permission_level=ToolPermissionLevel.READ_ONLY,
        ))
