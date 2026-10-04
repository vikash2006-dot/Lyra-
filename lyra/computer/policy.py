"""Security policy and containment rules for computer control."""

from dataclasses import dataclass, field
import os
import re

from lyra.computer.models import (
    ComputerAction,
    ComputerActionType,
    Point,
    ScreenSize,
)
from lyra.core.exceptions import (
    ComputerConfirmationRequiredError,
    ComputerPolicyViolationError,
)
from lyra.tools.permissions import ToolPermissionLevel

# Dangerous hotkeys that could kill essential processes, reboot, or bypass security
DEFAULT_BLOCKED_HOTKEYS: tuple[tuple[str, ...], ...] = (
    ("ctrl", "alt", "del"),
    ("ctrl", "alt", "delete"),
    ("cmd", "opt", "esc"),
    ("cmd", "opt", "escape"),
    ("command", "option", "escape"),
    ("alt", "f4"),
)

# Applications blocked by default to prevent destructive system tampering or raw script injection
DEFAULT_BLOCKED_APPS: tuple[str, ...] = (
    "iTerm",
    "iTerm2",
    "Console",
    "System Settings",
    "System Preferences",
    "Disk Utility",
    "Activity Monitor",
    "Keychain Access",
    "Registry Editor",
    "Powershell",
    "cmd.exe",
)

# Safe default apps allowed for local automation
DEFAULT_ALLOWED_APPS: tuple[str, ...] = (
    "Calculator",
    "TextEdit",
    "Notes",
    "Finder",
    "Preview",
    "Safari",
    "Chrome",
    "Google Chrome",
    "Terminal",
    "VS Code",
    "Visual Studio Code",
    "Code",
)


@dataclass(frozen=True)
class ComputerPolicy:
    """Security policy controlling all computer interactions."""

    allowed_applications: tuple[str, ...] = DEFAULT_ALLOWED_APPS
    blocked_applications: tuple[str, ...] = DEFAULT_BLOCKED_APPS
    blocked_key_combinations: tuple[tuple[str, ...], ...] = DEFAULT_BLOCKED_HOTKEYS
    screen_bounds: tuple[int, int, int, int] | None = None  # (min_x, min_y, max_x, max_y)
    allow_screenshots: bool = True
    require_confirmation: bool = True

    def verify_point(self, point: Point, screen_size: ScreenSize | None = None) -> None:
        """Verify screen coordinate is non-negative and within permitted bounds."""
        if point.x < 0 or point.y < 0:
            raise ComputerPolicyViolationError(
                f"Coordinates ({point.x}, {point.y}) cannot be negative."
            )

        if self.screen_bounds is not None:
            min_x, min_y, max_x, max_y = self.screen_bounds
            if not (min_x <= point.x <= max_x and min_y <= point.y <= max_y):
                raise ComputerPolicyViolationError(
                    f"Point ({point.x}, {point.y}) is outside permitted bounds "
                    f"[{min_x}, {min_y}, {max_x}, {max_y}]."
                )

        if screen_size is not None:
            if point.x >= screen_size.width or point.y >= screen_size.height:
                raise ComputerPolicyViolationError(
                    f"Point ({point.x}, {point.y}) exceeds screen resolution "
                    f"({screen_size.width}x{screen_size.height})."
                )

    def verify_application(self, app_name: str) -> None:
        """Verify target application is in allowlist and not in denylist."""
        if not app_name or not isinstance(app_name, str):
            raise ComputerPolicyViolationError("Application name cannot be empty.")

        clean_name = os.path.basename(app_name.strip()).lower()

        # 1. Denylist check
        for blocked in self.blocked_applications:
            if clean_name == blocked.lower() or blocked.lower() in clean_name:
                raise ComputerPolicyViolationError(
                    f"Application '{app_name}' is blocked by security policy."
                )

        # 2. Allowlist check
        if self.allowed_applications:
            matched = False
            for allowed in self.allowed_applications:
                if clean_name == allowed.lower() or allowed.lower() in clean_name:
                    matched = True
                    break
            if not matched:
                raise ComputerPolicyViolationError(
                    f"Application '{app_name}' is not in the allowed applications list: {self.allowed_applications}."
                )

    def verify_hotkey(self, keys: tuple[str, ...]) -> None:
        """Check key combination against blocked hotkey denylist."""
        normalized_keys = tuple(k.strip().lower() for k in keys if k.strip())
        sorted_keys = sorted(normalized_keys)

        for blocked in self.blocked_key_combinations:
            sorted_blocked = sorted(k.lower() for k in blocked)
            if sorted_keys == sorted_blocked:
                raise ComputerPolicyViolationError(
                    f"Key combination '{'+'.join(keys)}' is blocked by security policy."
                )

    def get_permission_level(self, action_type: ComputerActionType) -> ToolPermissionLevel:
        """Determine required tool permission level for an action type."""
        if action_type in (
            ComputerActionType.SCREENSHOT,
            ComputerActionType.INSPECT_SCREEN,
            ComputerActionType.EMERGENCY_STOP,
        ):
            return ToolPermissionLevel.READ_ONLY

        if action_type in (
            ComputerActionType.MOVE_CURSOR,
            ComputerActionType.LAUNCH_APP,
        ):
            return ToolPermissionLevel.LOW_RISK

        if action_type in (
            ComputerActionType.CLICK,
            ComputerActionType.TYPE_TEXT,
            ComputerActionType.PRESS_KEY,
            ComputerActionType.HOTKEY,
            ComputerActionType.TERMINATE_APP,
        ):
            return ToolPermissionLevel.CONFIRMATION_REQUIRED

        return ToolPermissionLevel.HIGH_RISK

    def check_action(self, action: ComputerAction) -> tuple[bool, str | None]:
        """Check if action requires explicit user confirmation.

        Returns:
            tuple[bool, str | None]: (requires_confirmation, reason)
        """
        # Read-only, cursor movement, or safe application launching does not require confirmation
        if action.action_type in (
            ComputerActionType.SCREENSHOT,
            ComputerActionType.INSPECT_SCREEN,
            ComputerActionType.MOVE_CURSOR,
            ComputerActionType.EMERGENCY_STOP,
            ComputerActionType.LAUNCH_APP,
        ):
            return False, None

        if not self.require_confirmation or action.confirmed:
            return False, None

        # Consequential actions require explicit confirmation
        if action.action_type == ComputerActionType.CLICK:
            return True, f"Clicking at {action.point or 'current position'} requires explicit confirmation."

        if action.action_type == ComputerActionType.TYPE_TEXT:
            preview = action.text[:20] if action.text else ""
            if action.is_sensitive:
                preview = "***REDACTED***"
            return True, f"Typing text '{preview}' requires explicit confirmation."

        if action.action_type == ComputerActionType.PRESS_KEY:
            return True, f"Pressing key '{action.key}' requires explicit confirmation."

        if action.action_type == ComputerActionType.HOTKEY:
            return True, f"Pressing key combination '{'+'.join(action.keys or ())}' requires explicit confirmation."

        if action.action_type == ComputerActionType.TERMINATE_APP:
            return True, f"Terminating application '{action.app_name}' requires explicit confirmation."

        return True, "Action requires explicit user confirmation."

    def enforce_confirmation(self, action: ComputerAction) -> None:
        """Enforce confirmation check or raise ComputerConfirmationRequiredError."""
        req, reason = self.check_action(action)
        if req and not action.confirmed:
            raise ComputerConfirmationRequiredError(reason or "Action requires user confirmation.")
