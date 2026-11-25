"""Unit tests for ComputerPolicy security boundaries and permission levels."""

import pytest

from lyra.computer.models import (
    ComputerAction,
    ComputerActionType,
    Point,
    ScreenSize,
)
from lyra.computer.policy import ComputerPolicy
from lyra.core.exceptions import (
    ComputerConfirmationRequiredError,
    ComputerPolicyViolationError,
)
from lyra.tools.permissions import ToolPermissionLevel


def test_computer_policy_permission_level_mapping():
    policy = ComputerPolicy()

    assert policy.get_permission_level(ComputerActionType.SCREENSHOT) == ToolPermissionLevel.READ_ONLY
    assert policy.get_permission_level(ComputerActionType.INSPECT_SCREEN) == ToolPermissionLevel.READ_ONLY
    assert policy.get_permission_level(ComputerActionType.EMERGENCY_STOP) == ToolPermissionLevel.READ_ONLY

    assert policy.get_permission_level(ComputerActionType.MOVE_CURSOR) == ToolPermissionLevel.LOW_RISK
    assert policy.get_permission_level(ComputerActionType.LAUNCH_APP) == ToolPermissionLevel.LOW_RISK

    assert policy.get_permission_level(ComputerActionType.CLICK) == ToolPermissionLevel.CONFIRMATION_REQUIRED
    assert policy.get_permission_level(ComputerActionType.TYPE_TEXT) == ToolPermissionLevel.CONFIRMATION_REQUIRED
    assert policy.get_permission_level(ComputerActionType.PRESS_KEY) == ToolPermissionLevel.CONFIRMATION_REQUIRED
    assert policy.get_permission_level(ComputerActionType.HOTKEY) == ToolPermissionLevel.CONFIRMATION_REQUIRED
    assert policy.get_permission_level(ComputerActionType.TERMINATE_APP) == ToolPermissionLevel.CONFIRMATION_REQUIRED


def test_computer_policy_point_validation():
    policy = ComputerPolicy(screen_bounds=(0, 0, 1920, 1080))
    screen = ScreenSize(width=1920, height=1080)

    # Valid points
    policy.verify_point(Point(100, 200), screen_size=screen)
    policy.verify_point(Point(0, 0), screen_size=screen)
    policy.verify_point(Point(1919, 1079), screen_size=screen)

    # Negative coordinates
    with pytest.raises(ComputerPolicyViolationError, match="cannot be negative"):
        policy.verify_point(Point(-1, 50))
    with pytest.raises(ComputerPolicyViolationError, match="cannot be negative"):
        policy.verify_point(Point(50, -5))

    # Out of resolution
    policy_unbounded = ComputerPolicy()
    with pytest.raises(ComputerPolicyViolationError, match="exceeds screen resolution"):
        policy_unbounded.verify_point(Point(2000, 500), screen_size=screen)

    # Out of bounding box
    restricted_policy = ComputerPolicy(screen_bounds=(100, 100, 500, 500))
    with pytest.raises(ComputerPolicyViolationError, match="outside permitted bounds"):
        restricted_policy.verify_point(Point(50, 250))


def test_computer_policy_application_allowlist_and_denylist():
    policy = ComputerPolicy(
        allowed_applications=("Calculator", "TextEdit", "Notes"),
        blocked_applications=("Terminal", "iTerm", "System Settings", "Disk Utility"),
    )

    # Allowed apps
    policy.verify_application("Calculator")
    policy.verify_application("TextEdit.app")
    policy.verify_application("/Applications/Notes.app")

    # Blocked apps (denylist)
    with pytest.raises(ComputerPolicyViolationError, match="blocked by security policy"):
        policy.verify_application("Terminal")
    with pytest.raises(ComputerPolicyViolationError, match="blocked by security policy"):
        policy.verify_application("/Applications/Utilities/Terminal.app")
    with pytest.raises(ComputerPolicyViolationError, match="blocked by security policy"):
        policy.verify_application("iTerm")
    with pytest.raises(ComputerPolicyViolationError, match="blocked by security policy"):
        policy.verify_application("System Settings")

    # Unlisted app not in allowlist
    with pytest.raises(ComputerPolicyViolationError, match="not in the allowed applications list"):
        policy.verify_application("MaliciousApp")


def test_computer_policy_blocked_hotkeys():
    policy = ComputerPolicy()

    # Blocked hotkeys
    with pytest.raises(ComputerPolicyViolationError, match="blocked by security policy"):
        policy.verify_hotkey(("ctrl", "alt", "del"))
    with pytest.raises(ComputerPolicyViolationError, match="blocked by security policy"):
        policy.verify_hotkey(("cmd", "opt", "esc"))
    with pytest.raises(ComputerPolicyViolationError, match="blocked by security policy"):
        policy.verify_hotkey(("alt", "f4"))

    # Allowed hotkey
    policy.verify_hotkey(("ctrl", "s"))
    policy.verify_hotkey(("cmd", "c"))


def test_computer_policy_confirmation_checks():
    policy = ComputerPolicy(require_confirmation=True)

    # Safe read-only actions do not require confirmation
    req_shot, _ = policy.check_action(ComputerAction(action_type=ComputerActionType.SCREENSHOT))
    assert not req_shot

    req_inspect, _ = policy.check_action(ComputerAction(action_type=ComputerActionType.INSPECT_SCREEN))
    assert not req_inspect

    req_move, _ = policy.check_action(ComputerAction(action_type=ComputerActionType.MOVE_CURSOR, point=Point(50, 50)))
    assert not req_move

    req_stop, _ = policy.check_action(ComputerAction(action_type=ComputerActionType.EMERGENCY_STOP))
    assert not req_stop

    # Consequential actions require confirmation
    req_click, reason_click = policy.check_action(
        ComputerAction(action_type=ComputerActionType.CLICK, point=Point(100, 100), confirmed=False)
    )
    assert req_click
    assert "Clicking" in reason_click

    req_type, reason_type = policy.check_action(
        ComputerAction(action_type=ComputerActionType.TYPE_TEXT, text="hello", confirmed=False)
    )
    assert req_type
    assert "Typing" in reason_type

    # With confirmed=True, check passes
    req_click_conf, _ = policy.check_action(
        ComputerAction(action_type=ComputerActionType.CLICK, point=Point(100, 100), confirmed=True)
    )
    assert not req_click_conf


def test_computer_policy_enforce_confirmation_raises():
    policy = ComputerPolicy(require_confirmation=True)
    action = ComputerAction(
        action_type=ComputerActionType.CLICK,
        point=Point(50, 50),
        confirmed=False,
    )
    with pytest.raises(ComputerConfirmationRequiredError, match="requires explicit confirmation"):
        policy.enforce_confirmation(action)
