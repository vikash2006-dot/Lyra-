"""Unit tests for ComputerController safety, confirmation, and fail-closed behavior."""

import asyncio
from pathlib import Path
import pytest

from lyra.computer.controller import ComputerController
from lyra.computer.emergency_stop import EmergencyStop
from lyra.computer.mock import (
    MockApplicationController,
    MockKeyboardController,
    MockMouseController,
    MockScreenCapture,
)
from lyra.computer.models import (
    ComputerAction,
    ComputerActionType,
    MouseButton,
    Point,
)
from lyra.computer.policy import ComputerPolicy
from lyra.core.exceptions import (
    ComputerDisabledError,
    ComputerEmergencyStopError,
    ComputerPolicyViolationError,
)


def test_computer_controller_disabled_state():
    async def _test():
        controller = ComputerController(enabled=False)

        # Non-emergency actions fail when disabled
        action = ComputerAction(action_type=ComputerActionType.INSPECT_SCREEN)
        with pytest.raises(ComputerDisabledError, match="globally disabled by configuration"):
            await controller.execute_action(action)

        # Emergency stop action is always permitted even when disabled
        estop_action = ComputerAction(action_type=ComputerActionType.EMERGENCY_STOP, text="User stop")
        res = await controller.execute_action(estop_action)
        assert res.success
        assert controller.emergency_stop.is_stopped

    asyncio.run(_test())


def test_computer_controller_screenshot_and_inspection(tmp_path: Path):
    async def _test():
        screenshot_dir = tmp_path / "test_screenshots"
        controller = ComputerController(
            enabled=True,
            screenshot_dir=screenshot_dir,
        )

        # 1. Screenshot
        shot_action = ComputerAction(action_type=ComputerActionType.SCREENSHOT)
        res_shot = await controller.execute_action(shot_action)
        assert res_shot.success
        assert "screenshot_" in res_shot.output["path"]
        assert Path(res_shot.output["path"]).exists()
        assert res_shot.output["size_bytes"] > 0

        # 2. Inspect screen
        inspect_action = ComputerAction(action_type=ComputerActionType.INSPECT_SCREEN)
        res_inspect = await controller.execute_action(inspect_action)
        assert res_inspect.success
        assert res_inspect.output["screen_size"]["width"] == 1920
        assert res_inspect.output["cursor_position"]["x"] == 0
        assert "Finder" in res_inspect.output["running_applications"]

    asyncio.run(_test())


def test_computer_controller_confirmation_and_safe_dispatch():
    async def _test():
        controller = ComputerController(enabled=True)

        # 1. Move cursor does not require confirmation
        move_action = ComputerAction(
            action_type=ComputerActionType.MOVE_CURSOR,
            point=Point(200, 300),
        )
        res_move = await controller.execute_action(move_action)
        assert res_move.success
        assert res_move.output["x"] == 200 and res_move.output["y"] == 300

        # 2. Click without confirmation requires confirmation
        click_unconfirmed = ComputerAction(
            action_type=ComputerActionType.CLICK,
            point=Point(200, 300),
            confirmed=False,
        )
        res_click_unconf = await controller.execute_action(click_unconfirmed)
        assert not res_click_unconf.success
        assert res_click_unconf.requires_confirmation
        assert "Confirmation required" in res_click_unconf.error

        # 3. Click with confirmed=True succeeds
        click_confirmed = ComputerAction(
            action_type=ComputerActionType.CLICK,
            point=Point(200, 300),
            button=MouseButton.LEFT,
            confirmed=True,
        )
        res_click_conf = await controller.execute_action(click_confirmed)
        assert res_click_conf.success
        assert res_click_conf.output["clicked_point"] == {"x": 200, "y": 300}

        # 4. Type text confirmation
        type_unconf = ComputerAction(
            action_type=ComputerActionType.TYPE_TEXT,
            text="Testing text typing",
            confirmed=False,
        )
        res_type_unconf = await controller.execute_action(type_unconf)
        assert not res_type_unconf.success
        assert res_type_unconf.requires_confirmation

        type_conf = ComputerAction(
            action_type=ComputerActionType.TYPE_TEXT,
            text="Testing text typing",
            confirmed=True,
        )
        res_type_conf = await controller.execute_action(type_conf)
        assert res_type_conf.success
        assert res_type_conf.output["typed_length"] == len("Testing text typing")

    asyncio.run(_test())


def test_computer_controller_credential_masking():
    # Sensitive text or keyword matches are masked in safe_repr()
    password_action = ComputerAction(
        action_type=ComputerActionType.TYPE_TEXT,
        text="my_super_secret_password_123!",
        is_sensitive=True,
    )
    assert "my_super_secret_password_123!" not in password_action.safe_repr()
    assert "***REDACTED***" in password_action.safe_repr()

    token_action = ComputerAction(
        action_type=ComputerActionType.TYPE_TEXT,
        text="secret_token_abc_xyz",
    )
    assert "secret_token_abc_xyz" not in token_action.safe_repr()
    assert "***REDACTED***" in token_action.safe_repr()


def test_computer_controller_application_safety():
    async def _test():
        controller = ComputerController(
            enabled=True,
            policy=ComputerPolicy(
                allowed_applications=("Calculator", "TextEdit"),
                blocked_applications=("Terminal", "System Settings"),
            ),
        )

        # Blocked application is rejected
        launch_terminal = ComputerAction(
            action_type=ComputerActionType.LAUNCH_APP,
            app_name="Terminal",
            confirmed=True,
        )
        res_term = await controller.execute_action(launch_terminal)
        assert not res_term.success
        assert "blocked by security policy" in res_term.error

        # Unallowlisted application is rejected
        launch_unlisted = ComputerAction(
            action_type=ComputerActionType.LAUNCH_APP,
            app_name="RandomGame",
            confirmed=True,
        )
        res_unlisted = await controller.execute_action(launch_unlisted)
        assert not res_unlisted.success
        assert "not in the allowed applications list" in res_unlisted.error

        # Allowed app with confirmation launches
        launch_calc = ComputerAction(
            action_type=ComputerActionType.LAUNCH_APP,
            app_name="Calculator",
            confirmed=True,
        )
        res_calc = await controller.execute_action(launch_calc)
        assert res_calc.success
        assert res_calc.output["launched"] is True

    asyncio.run(_test())


def test_computer_controller_emergency_stop_and_fail_closed():
    async def _test():
        estop = EmergencyStop()
        controller = ComputerController(enabled=True, emergency_stop=estop)

        # Trigger emergency stop via action
        res_stop = await controller.execute_action(
            ComputerAction(action_type=ComputerActionType.EMERGENCY_STOP, text="User pressed panic button")
        )
        assert res_stop.success
        assert estop.is_stopped

        # Subsequent actions immediately raise ComputerEmergencyStopError
        with pytest.raises(ComputerEmergencyStopError, match="Emergency stop is active"):
            await controller.execute_action(ComputerAction(action_type=ComputerActionType.INSPECT_SCREEN))

        # Reset emergency stop allows actions again
        estop.reset()
        res_ok = await controller.execute_action(ComputerAction(action_type=ComputerActionType.INSPECT_SCREEN))
        assert res_ok.success

    asyncio.run(_test())
