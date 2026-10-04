"""Mock controllers for safe, deterministic testing of computer interactions."""

from typing import Any

from lyra.computer.controllers import (
    ApplicationController,
    KeyboardController,
    MouseController,
    ScreenCapture,
)
from lyra.computer.models import MouseButton, Point, ScreenSize
from lyra.core.exceptions import ComputerDriverError

# Minimal valid 1x1 PNG header bytes for realistic test processing
MINIMAL_PNG_BYTES: bytes = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
    b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class MockScreenCapture(ScreenCapture):
    """Mock screen capture implementation."""

    def __init__(self, width: int = 1920, height: int = 1080) -> None:
        self.size = ScreenSize(width=width, height=height)
        self.screenshot_bytes = MINIMAL_PNG_BYTES
        self.simulate_error = False

    async def capture_screen(self) -> bytes:
        if self.simulate_error:
            raise ComputerDriverError("Mock screen capture device failure.")
        return self.screenshot_bytes

    async def get_screen_size(self) -> ScreenSize:
        return self.size


class MockMouseController(MouseController):
    """Mock mouse controller tracking cursor and clicks."""

    def __init__(self, initial_position: Point = Point(0, 0)) -> None:
        self.position = initial_position
        self.move_history: list[Point] = [initial_position]
        self.click_history: list[dict[str, Any]] = []
        self.simulate_error = False

    async def get_position(self) -> Point:
        return self.position

    async def move(self, point: Point) -> None:
        if self.simulate_error:
            raise ComputerDriverError("Mock mouse move hardware error.")
        self.position = point
        self.move_history.append(point)

    async def click(
        self,
        point: Point | None = None,
        button: MouseButton = MouseButton.LEFT,
        clicks: int = 1,
    ) -> None:
        if self.simulate_error:
            raise ComputerDriverError("Mock mouse click hardware error.")
        target_pt = point if point is not None else self.position
        if point is not None:
            self.position = point
            self.move_history.append(point)

        self.click_history.append({
            "point": target_pt,
            "button": button,
            "clicks": clicks,
        })


class MockKeyboardController(KeyboardController):
    """Mock keyboard controller tracking typed strings and pressed keys."""

    def __init__(self) -> None:
        self.typed_text: list[str] = []
        self.pressed_keys: list[str] = []
        self.hotkeys: list[tuple[str, ...]] = []
        self.simulate_error = False

    async def type_text(self, text: str) -> None:
        if self.simulate_error:
            raise ComputerDriverError("Mock keyboard typing error.")
        self.typed_text.append(text)

    async def press_key(self, key: str) -> None:
        if self.simulate_error:
            raise ComputerDriverError("Mock key press error.")
        self.pressed_keys.append(key)

    async def hotkey(self, *keys: str) -> None:
        if self.simulate_error:
            raise ComputerDriverError("Mock hotkey error.")
        self.hotkeys.append(keys)


class MockApplicationController(ApplicationController):
    """Mock application controller tracking running and launched applications."""

    def __init__(self, initial_apps: list[str] | None = None) -> None:
        self.running_apps: list[str] = initial_apps or ["Finder", "Calculator"]
        self.launch_history: list[str] = []
        self.terminate_history: list[str] = []
        self.simulate_error = False

    @property
    def launched_apps(self) -> list[str]:
        return list(self.launch_history)

    async def list_running_apps(self) -> list[str]:
        return list(self.running_apps)

    async def launch_app(self, app_name: str) -> bool:
        if self.simulate_error:
            raise ComputerDriverError(f"Failed to launch mock app '{app_name}'.")
        self.launch_history.append(app_name)
        if app_name not in self.running_apps:
            self.running_apps.append(app_name)
        return True

    async def terminate_app(self, app_name: str) -> bool:
        if self.simulate_error:
            raise ComputerDriverError(f"Failed to terminate mock app '{app_name}'.")
        self.terminate_history.append(app_name)
        if app_name in self.running_apps:
            self.running_apps.remove(app_name)
            return True
        return False
