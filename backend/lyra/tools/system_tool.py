"""System control tools for LYRA.

Provides display brightness, volume, and application management under the 'system' namespace.
"""

import logging
from typing import Any, Optional

from lyra.computer.brightness import BrightnessController
from lyra.computer.volume import VolumeController
from lyra.models.tools import ToolRequest, ToolResult
from lyra.tools.base import Tool
from lyra.tools.permissions import ToolPermissionLevel

logger = logging.getLogger("tools.system")


class SystemTool(Tool):
    """System tool controlling display brightness, volume, and macOS applications."""

    def __init__(
        self,
        brightness_controller: Optional[BrightnessController] = None,
        volume_controller: Optional[VolumeController] = None,
    ) -> None:
        self.brightness = brightness_controller or BrightnessController()
        self.volume = volume_controller or VolumeController()

    @property
    def name(self) -> str:
        return "system"

    @property
    def description(self) -> str:
        return (
            "Control Mac display brightness, volume, mute state, and launch/close desktop applications."
        )

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.LOW_RISK

    @property
    def requires_network(self) -> bool:
        return False

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "get_brightness",
                        "set_brightness",
                        "increase_brightness",
                        "decrease_brightness",
                        "get_volume",
                        "set_volume",
                        "increase_volume",
                        "decrease_volume",
                        "mute",
                        "unmute",
                        "open_application",
                        "close_application",
                        "focus_application",
                    ],
                },
                "level": {
                    "type": "number",
                    "description": "Target brightness level (0-100 or 0.0-1.0) or volume level (0-100).",
                },
                "delta": {
                    "type": "number",
                    "description": "Step amount to increase or decrease brightness or volume.",
                },
                "app_name": {
                    "type": "string",
                    "description": "Name of the application to open, close, or focus.",
                },
            },
            "required": ["action"],
        }

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        """Inspect user query for intent to control brightness, volume, or applications."""
        import re
        text = user_input.strip()
        lowered = text.lower()
        cleaned = re.sub(r"(?i)^(?:hey|hi|hello|ok|okay)?\s*lyra[,:\s]*", "", text).strip()
        c_lowered = cleaned.lower()

        # 1. Brightness intents
        # Increase brightness
        if re.search(r"(?i)\b(?:increase\s+(?:the\s+)?brightness|brightness\s+up|make\s+(?:the\s+)?(?:screen|it)\s+brighter|turn\s+(?:the\s+)?brightness\s+up|brighter)\b", cleaned):
            return {"action": "increase_brightness", "delta": 0.1}

        # Decrease brightness
        if re.search(r"(?i)\b(?:decrease\s+(?:the\s+)?brightness|brightness\s+down|make\s+(?:the\s+)?(?:screen|it)\s+darker|turn\s+(?:the\s+)?brightness\s+down|darker)\b", cleaned):
            return {"action": "decrease_brightness", "delta": 0.1}

        # Set brightness
        m_bset = re.search(r"(?i)\bset\s+(?:the\s+)?brightness\s+to\s+([a-zA-Z0-9.]+)(?:\s*percent|%)?\b", cleaned)
        if m_bset:
            raw = m_bset.group(1).strip().lower()
            if raw in ("max", "maximum", "full", "100"):
                lvl = 1.0
            elif raw in ("min", "minimum", "zero", "0"):
                lvl = 0.1
            else:
                try:
                    val = float(raw)
                    lvl = val / 100.0 if val > 1.0 else val
                except ValueError:
                    lvl = 0.5
            return {"action": "set_brightness", "level": lvl}

        # Get brightness
        if re.search(r"(?i)\b(?:what\s+is|get|check)\s+(?:the\s+)?brightness\b", cleaned):
            return {"action": "get_brightness"}

        # 2. Volume intents
        # Mute
        if re.search(r"(?i)\bmute(?:\s+(?:the\s+)?(?:computer|audio|volume|system|sound))?\b", cleaned) and "unmute" not in c_lowered:
            return {"action": "mute"}

        # Unmute
        if re.search(r"(?i)\bunmute(?:\s+(?:the\s+)?(?:computer|audio|volume|system|sound))?\b", cleaned):
            return {"action": "unmute"}

        # Increase volume
        if re.search(r"(?i)\b(?:increase\s+(?:the\s+)?volume|volume\s+up|turn\s+(?:the\s+)?volume\s+up|make\s+(?:it\s+)?louder|louder)\b", cleaned):
            return {"action": "increase_volume", "delta": 10}

        # Decrease volume
        if re.search(r"(?i)\b(?:decrease\s+(?:the\s+)?volume|volume\s+down|turn\s+(?:the\s+)?volume\s+down|quieter|lower\s+(?:the\s+)?volume)\b", cleaned):
            return {"action": "decrease_volume", "delta": 10}

        # Set volume
        m_vset = re.search(r"(?i)\bset\s+(?:the\s+|my\s+)?volume\s+to\s+(\d+)(?:\s*percent|%)?\b", cleaned)
        if m_vset:
            return {"action": "set_volume", "level": int(m_vset.group(1))}

        # Get volume
        if re.search(r"(?i)\b(?:what\s+is|get|check)\s+(?:the\s+)?volume\b", cleaned):
            return {"action": "get_volume"}

        # 3. Application intents
        # Open app: "open Finder", "open Chrome", etc.
        m_open = re.search(
            r"(?i)^(?:open|launch)\s+(?:the\s+)?(finder|chrome|google\s+chrome|terminal|vs\s*code|visual\s+studio\s+code|safari|calculator|notes|textedit)(?:\.|$)",
            cleaned,
        )
        if m_open:
            raw_app = m_open.group(1).strip().lower()
            app_map = {
                "finder": "Finder",
                "chrome": "Google Chrome",
                "google chrome": "Google Chrome",
                "terminal": "Terminal",
                "vs code": "Visual Studio Code",
                "vscode": "Visual Studio Code",
                "visual studio code": "Visual Studio Code",
                "safari": "Safari",
                "calculator": "Calculator",
                "notes": "Notes",
                "textedit": "TextEdit",
            }
            return {"action": "open_application", "app_name": app_map.get(raw_app, raw_app.capitalize())}

        # Close app
        m_close = re.search(
            r"(?i)^close\s+(?:the\s+)?(finder|chrome|google\s+chrome|terminal|vs\s*code|safari|calculator|notes)(?:\.|$)",
            cleaned,
        )
        if m_close:
            raw_app = m_close.group(1).strip().lower()
            app_map = {
                "finder": "Finder",
                "chrome": "Google Chrome",
                "google chrome": "Google Chrome",
                "terminal": "Terminal",
                "vs code": "Visual Studio Code",
                "safari": "Safari",
            }
            return {"action": "close_application", "app_name": app_map.get(raw_app, raw_app.capitalize())}

        return None

    def format_result(self, result: ToolResult) -> str:
        """Format system tool result for user display."""
        if not result.success:
            return f"System action failed: {result.error}"

        data = result.output if isinstance(result.output, dict) else {}
        action = data.get("action", "")

        if action in ("get_brightness", "set_brightness", "increase_brightness", "decrease_brightness"):
            pct = int(round(data.get("brightness", 0.0) * 100))
            if action == "set_brightness":
                return f"Done. Set display brightness to {pct}%."
            elif action == "increase_brightness":
                return f"Done. Increased brightness to {pct}%."
            elif action == "decrease_brightness":
                return f"Done. Decreased brightness to {pct}%."
            return f"Current display brightness is {pct}%."

        elif action in ("get_volume", "set_volume", "increase_volume", "decrease_volume", "mute", "unmute"):
            vol = data.get("volume", 0)
            muted = data.get("muted", False)
            if action == "mute":
                return "Done. Muted the computer."
            elif action == "unmute":
                return f"Done. Unmuted the computer. Volume is at {vol}%."
            elif action == "increase_volume":
                return f"Done. Turned volume up to {vol}%."
            elif action == "decrease_volume":
                return f"Done. Turned volume down to {vol}%."
            elif action == "set_volume":
                return f"Done. Set volume to {vol}%."
            return f"Current volume is {vol}%{' (muted)' if muted else ''}."

        elif action in ("open_application", "focus_application"):
            app = data.get("app_name", "Application")
            target = data.get("target_path")
            if target:
                from pathlib import Path
                target_name = Path(target).name
                return f"Done. Opened {target_name} in {app}."
            return f"Done. Opened {app}."
        elif action == "close_application":
            app = data.get("app_name", "Application")
            return f"Done. Closed {app}."

        return result.to_text()

    async def execute(self, request: ToolRequest) -> ToolResult:
        """Execute system brightness, volume, or application control action."""
        args = request.arguments
        action_name = args.get("action", "")

        # Handle dotted tool action names (e.g. tool_name='system.set_brightness')
        if not action_name and "." in request.tool_name:
            action_name = request.tool_name.split(".", 1)[1]

        # 1. Display Brightness Actions
        if action_name == "get_brightness":
            val = self.brightness.get_brightness()
            return ToolResult(tool_name=self.name, success=True, output={"action": action_name, "brightness": val})

        elif action_name == "set_brightness":
            raw_lvl = args.get("level", 0.5)
            # Support 0-100 or 0.0-1.0
            lvl = float(raw_lvl) / 100.0 if float(raw_lvl) > 1.0 else float(raw_lvl)
            val = self.brightness.set_brightness(lvl)
            return ToolResult(tool_name=self.name, success=True, output={"action": action_name, "brightness": val})

        elif action_name == "increase_brightness":
            raw_delta = args.get("delta", 0.1)
            delta = float(raw_delta) / 100.0 if float(raw_delta) > 1.0 else float(raw_delta)
            val = self.brightness.increase_brightness(delta)
            return ToolResult(tool_name=self.name, success=True, output={"action": action_name, "brightness": val})

        elif action_name == "decrease_brightness":
            raw_delta = args.get("delta", 0.1)
            delta = float(raw_delta) / 100.0 if float(raw_delta) > 1.0 else float(raw_delta)
            val = self.brightness.decrease_brightness(delta)
            return ToolResult(tool_name=self.name, success=True, output={"action": action_name, "brightness": val})

        # 2. System Volume Actions
        elif action_name == "get_volume":
            v_data = self.volume.get_volume()
            return ToolResult(tool_name=self.name, success=True, output={"action": action_name, **v_data})

        elif action_name == "set_volume":
            lvl = int(float(args.get("level", 50)))
            v_data = self.volume.set_volume(lvl)
            return ToolResult(tool_name=self.name, success=True, output={"action": action_name, **v_data})

        elif action_name == "increase_volume":
            delta = int(float(args.get("delta", 10)))
            v_data = self.volume.increase_volume(delta)
            return ToolResult(tool_name=self.name, success=True, output={"action": action_name, **v_data})

        elif action_name == "decrease_volume":
            delta = int(float(args.get("delta", 10)))
            v_data = self.volume.decrease_volume(delta)
            return ToolResult(tool_name=self.name, success=True, output={"action": action_name, **v_data})

        elif action_name == "mute":
            v_data = self.volume.mute()
            return ToolResult(tool_name=self.name, success=True, output={"action": action_name, **v_data})

        elif action_name == "unmute":
            v_data = self.volume.unmute()
            return ToolResult(tool_name=self.name, success=True, output={"action": action_name, **v_data})

        # 3. Application Actions
        elif action_name in ("open_application", "focus_application"):
            app_name = args.get("app_name", "")
            target_path = args.get("target_path") or args.get("path")
            if not app_name:
                return ToolResult(tool_name=self.name, success=False, error="Action requires 'app_name'.")
            import os, subprocess, sys
            if sys.platform == "darwin":
                try:
                    cmd = ["open", "-a", app_name]
                    if target_path:
                        expanded_path = os.path.abspath(os.path.expanduser(str(target_path)))
                        cmd.append(expanded_path)
                    res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=5)
                    if res.returncode != 0:
                        return ToolResult(
                            tool_name=self.name,
                            success=False,
                            error=f"Could not open {app_name}: {res.stderr.strip()}",
                        )

                    # Verify application is running
                    check_proc = subprocess.run(
                        ["osascript", "-e", f'application "{app_name}" is running'],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=3,
                    )
                    is_running = check_proc.stdout.strip().lower() == "true"

                    return ToolResult(
                        tool_name=self.name,
                        success=True,
                        output={
                            "action": action_name,
                            "app_name": app_name,
                            "target_path": str(target_path) if target_path else None,
                            "verified": is_running,
                        },
                    )
                except Exception as err:
                    return ToolResult(tool_name=self.name, success=False, error=f"Could not open {app_name}: {err}")
            return ToolResult(
                tool_name=self.name,
                success=True,
                output={"action": action_name, "app_name": app_name, "target_path": str(target_path) if target_path else None},
            )

        elif action_name == "close_application":
            app_name = args.get("app_name", "")
            if not app_name:
                return ToolResult(tool_name=self.name, success=False, error="Action requires 'app_name'.")
            import subprocess, sys
            if sys.platform == "darwin":
                try:
                    script = f'tell application "{app_name}" to quit'
                    subprocess.run(["osascript", "-e", script], check=False, timeout=5)
                    return ToolResult(tool_name=self.name, success=True, output={"action": action_name, "app_name": app_name})
                except Exception as err:
                    return ToolResult(tool_name=self.name, success=False, error=f"Could not close {app_name}: {err}")
            return ToolResult(tool_name=self.name, success=True, output={"action": action_name, "app_name": app_name})

        return ToolResult(tool_name=self.name, success=False, error=f"Unknown system action: '{action_name}'.")
