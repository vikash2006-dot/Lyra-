"""Unit tests for MockComputerDriver and SystemComputerDriver."""

import asyncio
import pytest

from lyra.computer.mock import (
    MockApplicationController,
    MockKeyboardController,
    MockMouseController,
    MockScreenCapture,
)
from lyra.computer.models import MouseButton, Point
from lyra.computer.system import (
    SystemApplicationController,
    SystemKeyboardController,
    SystemMouseController,
    SystemScreenCapture,
)
from lyra.core.exceptions import ComputerDriverError


def test_mock_screen_capture():
    async def _test():
        capture = MockScreenCapture(width=2560, height=1440)
        size = await capture.get_screen_size()
        assert size.width == 2560
        assert size.height == 1440

        png_bytes = await capture.capture_screen()
        assert len(png_bytes) > 0
        assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

        # Simulate error
        capture.simulate_error = True
        with pytest.raises(ComputerDriverError, match="Mock screen capture device failure"):
            await capture.capture_screen()

    asyncio.run(_test())


def test_mock_mouse_controller():
    async def _test():
        mouse = MockMouseController(initial_position=Point(100, 100))
        assert (await mouse.get_position()) == Point(100, 100)

        # Move
        await mouse.move(Point(250, 350))
        assert (await mouse.get_position()) == Point(250, 350)
        assert len(mouse.move_history) == 2

        # Click
        await mouse.click(point=Point(300, 400), button=MouseButton.RIGHT)
        assert (await mouse.get_position()) == Point(300, 400)
        assert len(mouse.click_history) == 1
        assert mouse.click_history[0]["button"] == MouseButton.RIGHT

        # Double click
        await mouse.click(button=MouseButton.DOUBLE, clicks=2)
        assert len(mouse.click_history) == 2

        # Simulate error
        mouse.simulate_error = True
        with pytest.raises(ComputerDriverError, match="Mock mouse move hardware error"):
            await mouse.move(Point(0, 0))

    asyncio.run(_test())


def test_mock_keyboard_controller():
    async def _test():
        keyboard = MockKeyboardController()

        await keyboard.type_text("Hello World!")
        assert keyboard.typed_text == ["Hello World!"]

        await keyboard.press_key("Return")
        assert keyboard.pressed_keys == ["Return"]

        await keyboard.hotkey("ctrl", "shift", "p")
        assert keyboard.hotkeys == [("ctrl", "shift", "p")]

        # Simulate error
        keyboard.simulate_error = True
        with pytest.raises(ComputerDriverError, match="Mock keyboard typing error"):
            await keyboard.type_text("fail")

    asyncio.run(_test())


def test_mock_application_controller():
    async def _test():
        app_ctrl = MockApplicationController(initial_apps=["Finder", "Calculator"])
        apps = await app_ctrl.list_running_apps()
        assert "Finder" in apps
        assert "Calculator" in apps

        # Launch
        assert await app_ctrl.launch_app("TextEdit")
        assert "TextEdit" in (await app_ctrl.list_running_apps())

        # Terminate
        assert await app_ctrl.terminate_app("Calculator")
        assert "Calculator" not in (await app_ctrl.list_running_apps())

        # Terminate non-running app
        assert not await app_ctrl.terminate_app("NonExistentApp")

        # Simulate error
        app_ctrl.simulate_error = True
        with pytest.raises(ComputerDriverError, match="Failed to launch"):
            await app_ctrl.launch_app("AnyApp")

    asyncio.run(_test())


def test_system_controllers_graceful_handling():
    async def _test():
        mouse = SystemMouseController()
        pos = await mouse.get_position()
        assert pos.x == 0 and pos.y == 0
        await mouse.move(Point(100, 100))
        assert (await mouse.get_position()) == Point(100, 100)

        kb = SystemKeyboardController()
        await kb.type_text("test")
        await kb.press_key("Enter")
        await kb.hotkey("ctrl", "c")

    asyncio.run(_test())
