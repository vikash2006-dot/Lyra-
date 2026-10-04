"""High-level ComputerController coordinating screen, mouse, keyboard, and applications."""

from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any

from lyra.computer.controllers import (
    ApplicationController,
    KeyboardController,
    MouseController,
    ScreenCapture,
)
from lyra.computer.emergency_stop import EmergencyStop
from lyra.computer.mock import (
    MockApplicationController,
    MockKeyboardController,
    MockMouseController,
    MockScreenCapture,
)
from lyra.computer.models import (
    ComputerAction,
    ComputerActionResult,
    ComputerActionType,
    Point,
    ScreenSize,
)
from lyra.computer.policy import ComputerPolicy
from lyra.config.settings import Settings
from lyra.core.exceptions import (
    ComputerConfirmationRequiredError,
    ComputerDisabledError,
    ComputerDriverError,
    ComputerEmergencyStopError,
    ComputerError,
    ComputerPolicyViolationError,
)

logger = logging.getLogger(__name__)


class ComputerController:
    """Central safety coordinator and dispatcher for local computer interaction."""

    def __init__(
        self,
        screen_capture: ScreenCapture | None = None,
        mouse: MouseController | None = None,
        keyboard: KeyboardController | None = None,
        applications: ApplicationController | None = None,
        policy: ComputerPolicy | None = None,
        emergency_stop: EmergencyStop | None = None,
        screenshot_dir: Path | None = None,
        enabled: bool = False,
    ) -> None:
        self.screen_capture = screen_capture or MockScreenCapture()
        self.mouse = mouse or MockMouseController()
        self.keyboard = keyboard or MockKeyboardController()
        self.applications = applications or MockApplicationController()
        self.policy = policy or ComputerPolicy()
        self.emergency_stop = emergency_stop or EmergencyStop()
        self.screenshot_dir = screenshot_dir or Path("screenshots")
        self.enabled = enabled

    @classmethod
    def from_settings(cls, settings: Settings, use_mock: bool = True) -> "ComputerController":
        """Factory creating controller instance according to configuration."""
        policy = ComputerPolicy(
            allowed_applications=settings.computer_allow_apps,
            blocked_applications=settings.computer_blocked_apps,
            require_confirmation=settings.computer_require_confirmation,
        )
        screenshot_dir = Path(settings.computer_screenshot_dir)

        if use_mock:
            return cls(
                policy=policy,
                screenshot_dir=screenshot_dir,
                enabled=settings.computer_enabled,
            )

        from lyra.computer.system import (
            SystemApplicationController,
            SystemKeyboardController,
            SystemMouseController,
            SystemScreenCapture,
        )

        return cls(
            screen_capture=SystemScreenCapture(),
            mouse=SystemMouseController(),
            keyboard=SystemKeyboardController(),
            applications=SystemApplicationController(),
            policy=policy,
            screenshot_dir=screenshot_dir,
            enabled=settings.computer_enabled,
        )

    async def execute_action(self, action: ComputerAction) -> ComputerActionResult:
        """Validate, authorize, and execute a computer action safely."""
        # 1. Check emergency stop
        self.emergency_stop.check()

        # 2. Emergency stop action can always be invoked even if globally disabled
        if action.action_type == ComputerActionType.EMERGENCY_STOP:
            reason = action.text or "User engaged emergency stop"
            self.emergency_stop.trigger(reason=reason)
            return ComputerActionResult(
                success=True,
                action_type=action.action_type.value,
                output={"status": "stopped", "reason": reason},
            )

        # 3. Check enabled state
        if not self.enabled:
            raise ComputerDisabledError(
                "Computer interaction is globally disabled by configuration (COMPUTER_ENABLED=False). "
                "Enable it explicitly in settings to use computer control."
            )

        # 4. Enforce confirmation policy
        req_conf, reason = self.policy.check_action(action)
        if req_conf and not action.confirmed:
            return ComputerActionResult(
                success=False,
                action_type=action.action_type.value,
                error=f"Confirmation required: {reason}",
                requires_confirmation=True,
                metadata={"reason": reason, "requires_confirmation": True},
            )

        try:
            # 5. Dispatch validated action
            action_name = action.action_type.value

            if action.action_type == ComputerActionType.SCREENSHOT:
                if not self.policy.allow_screenshots:
                    raise ComputerPolicyViolationError("Screenshots are disabled by policy.")

                raw_bytes = await self.screen_capture.capture_screen()
                self.screenshot_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
                filepath = self.screenshot_dir / f"screenshot_{timestamp}.png"
                filepath.write_bytes(raw_bytes)

                logger.info("Screenshot saved ephemerally to '%s' (%d bytes).", filepath, len(raw_bytes))
                return ComputerActionResult(
                    success=True,
                    action_type=action_name,
                    output={
                        "path": str(filepath),
                        "size_bytes": len(raw_bytes),
                    },
                )

            elif action.action_type == ComputerActionType.INSPECT_SCREEN:
                size = await self.screen_capture.get_screen_size()
                pos = await self.mouse.get_position()
                running_apps = await self.applications.list_running_apps()
                return ComputerActionResult(
                    success=True,
                    action_type=action_name,
                    output={
                        "screen_size": {"width": size.width, "height": size.height},
                        "cursor_position": {"x": pos.x, "y": pos.y},
                        "running_applications": running_apps,
                    },
                )

            elif action.action_type == ComputerActionType.MOVE_CURSOR:
                if action.point is None:
                    raise ComputerPolicyViolationError("MOVE_CURSOR requires 'point' coordinates.")
                size = await self.screen_capture.get_screen_size()
                self.policy.verify_point(action.point, screen_size=size)
                await self.mouse.move(action.point)
                return ComputerActionResult(
                    success=True,
                    action_type=action_name,
                    output={"x": action.point.x, "y": action.point.y},
                )

            elif action.action_type == ComputerActionType.CLICK:
                if action.point is not None:
                    size = await self.screen_capture.get_screen_size()
                    self.policy.verify_point(action.point, screen_size=size)
                await self.mouse.click(
                    point=action.point,
                    button=action.button,
                    clicks=2 if action.button.value == "double" else 1,
                )
                pos = await self.mouse.get_position()
                return ComputerActionResult(
                    success=True,
                    action_type=action_name,
                    output={
                        "clicked_point": {"x": pos.x, "y": pos.y},
                        "button": action.button.value,
                    },
                )

            elif action.action_type == ComputerActionType.TYPE_TEXT:
                if action.text is None:
                    raise ComputerPolicyViolationError("TYPE_TEXT requires 'text' argument.")
                await self.keyboard.type_text(action.text)
                return ComputerActionResult(
                    success=True,
                    action_type=action_name,
                    output={"typed_length": len(action.text)},
                )

            elif action.action_type == ComputerActionType.PRESS_KEY:
                if not action.key:
                    raise ComputerPolicyViolationError("PRESS_KEY requires 'key' argument.")
                await self.keyboard.press_key(action.key)
                return ComputerActionResult(
                    success=True,
                    action_type=action_name,
                    output={"key": action.key},
                )

            elif action.action_type == ComputerActionType.HOTKEY:
                if not action.keys:
                    raise ComputerPolicyViolationError("HOTKEY requires 'keys' argument.")
                self.policy.verify_hotkey(action.keys)
                await self.keyboard.hotkey(*action.keys)
                return ComputerActionResult(
                    success=True,
                    action_type=action_name,
                    output={"keys": list(action.keys)},
                )

            elif action.action_type == ComputerActionType.LAUNCH_APP:
                if not action.app_name:
                    raise ComputerPolicyViolationError("LAUNCH_APP requires 'app_name' argument.")
                self.policy.verify_application(action.app_name)
                launched = await self.applications.launch_app(action.app_name)
                return ComputerActionResult(
                    success=launched,
                    action_type=action_name,
                    output={"app_name": action.app_name, "launched": launched},
                )

            elif action.action_type == ComputerActionType.TERMINATE_APP:
                if not action.app_name:
                    raise ComputerPolicyViolationError("TERMINATE_APP requires 'app_name' argument.")
                self.policy.verify_application(action.app_name)
                terminated = await self.applications.terminate_app(action.app_name)
                return ComputerActionResult(
                    success=terminated,
                    action_type=action_name,
                    output={"app_name": action.app_name, "terminated": terminated},
                )

            else:
                raise ComputerPolicyViolationError(f"Unsupported computer action '{action.action_type}'.")

        except ComputerError as err:
            logger.warning("Computer action '%s' failed policy or driver check: %s", action.action_type.value, err)
            return ComputerActionResult(
                success=False,
                action_type=action.action_type.value,
                error=str(err),
            )
        except Exception as err:
            logger.critical("Unexpected error in computer controller; engaging fail-closed emergency stop: %s", err)
            self.emergency_stop.fail_closed(f"Unexpected controller fault: {err}")
            return ComputerActionResult(
                success=False,
                action_type=action.action_type.value,
                error=f"Critical controller fault: {err}. Emergency stop triggered.",
            )
        finally:
            # Mask credentials in execution logging
            logger.debug("Computer interaction logged: %s", action.safe_repr())
