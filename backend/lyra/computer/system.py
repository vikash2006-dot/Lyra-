"""Platform-isolated system controller implementation for macOS/POSIX environments."""

import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from lyra.computer.controllers import (
    ApplicationController,
    KeyboardController,
    MouseController,
    ScreenCapture,
)
from lyra.computer.models import MouseButton, Point, ScreenSize
from lyra.core.exceptions import ComputerDriverError


class SystemScreenCapture(ScreenCapture):
    """Screen capture using isolated system tools (e.g. screencapture on macOS)."""

    def __init__(self) -> None:
        self._is_mac = sys.platform == "darwin"

    async def capture_screen(self) -> bytes:
        if not self._is_mac:
            raise ComputerDriverError("System screen capture currently supports macOS.")

        screencapture_bin = shutil.which("screencapture")
        if not screencapture_bin:
            raise ComputerDriverError("screencapture utility not found on system.")

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            # -x: mute sound, -C: capture cursor
            proc = await asyncio.to_thread(
                subprocess.run,
                [screencapture_bin, "-x", str(tmp_path)],
                capture_output=True,
                check=False,
                timeout=10,
            )
            if proc.returncode != 0 or not tmp_path.exists():
                raise ComputerDriverError(
                    f"screencapture failed with exit code {proc.returncode}: {proc.stderr.decode('utf-8', errors='ignore')}"
                )
            return tmp_path.read_bytes()
        except Exception as err:
            raise ComputerDriverError(f"Failed to capture screen: {err}") from err
        finally:
            tmp_path.unlink(missing_ok=True)

    async def get_screen_size(self) -> ScreenSize:
        # Default fallback resolution
        return ScreenSize(width=1920, height=1080)


class SystemMouseController(MouseController):
    """Platform mouse controller using CoreGraphics on macOS with fallback."""

    def __init__(self) -> None:
        self._is_mac = sys.platform == "darwin"
        self._current_pos = Point(0, 0)
        self._cg = None
        self._cf = None
        if self._is_mac:
            try:
                import ctypes

                class CGPoint(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

                self._CGPoint = CGPoint
                self._cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
                self._cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
                self._cg.CGEventCreate.restype = ctypes.c_void_p
                self._cg.CGEventCreate.argtypes = [ctypes.c_void_p]
                self._cg.CGEventGetLocation.restype = CGPoint
                self._cg.CGEventGetLocation.argtypes = [ctypes.c_void_p]
                self._cg.CGEventCreateMouseEvent.argtypes = [
                    ctypes.c_void_p,
                    ctypes.c_uint32,
                    CGPoint,
                    ctypes.c_uint32,
                ]
                self._cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
                self._cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
                self._cg.CGEventPost.restype = None
                self._cf.CFRelease.argtypes = [ctypes.c_void_p]
                self._cf.CFRelease.restype = None
            except Exception:
                self._cg = None

    async def get_position(self) -> Point:
        return self._current_pos

    async def get_live_position(self) -> Point:
        if self._is_mac and self._cg is not None:
            try:
                ev = self._cg.CGEventCreate(None)
                if ev:
                    loc = self._cg.CGEventGetLocation(ev)
                    self._cf.CFRelease(ev)
                    self._current_pos = Point(int(loc.x), int(loc.y))
                    return self._current_pos
            except Exception:
                pass
        return self._current_pos

    async def move(self, point: Point) -> None:
        self._current_pos = point
        if self._is_mac and self._cg is not None:
            try:
                # kCGEventMouseMoved = 5
                ev = self._cg.CGEventCreateMouseEvent(
                    None, 5, self._CGPoint(point.x, point.y), 0
                )
                if ev:
                    # kCGHIDEventTap = 0
                    self._cg.CGEventPost(0, ev)
                    self._cf.CFRelease(ev)
            except Exception:
                pass

    async def click(
        self,
        point: Point | None = None,
        button: MouseButton = MouseButton.LEFT,
        clicks: int = 1,
    ) -> None:
        target_pt = point or self._current_pos
        self._current_pos = target_pt
        if self._is_mac and self._cg is not None:
            try:
                # 1 = LeftMouseDown, 2 = LeftMouseUp, 3 = RightMouseDown, 4 = RightMouseUp
                down_type = 1 if button == MouseButton.LEFT else 3
                up_type = 2 if button == MouseButton.LEFT else 4
                cg_pt = self._CGPoint(target_pt.x, target_pt.y)
                for _ in range(clicks):
                    down_ev = self._cg.CGEventCreateMouseEvent(None, down_type, cg_pt, 0)
                    up_ev = self._cg.CGEventCreateMouseEvent(None, up_type, cg_pt, 0)
                    if down_ev:
                        self._cg.CGEventPost(0, down_ev)
                        self._cf.CFRelease(down_ev)
                    if up_ev:
                        self._cg.CGEventPost(0, up_ev)
                        self._cf.CFRelease(up_ev)
            except Exception:
                pass


class SystemKeyboardController(KeyboardController):
    """Platform keyboard controller using AppleScript System Events on macOS."""

    KEY_CODE_MAP = {
        "return": 36,
        "enter": 36,
        "tab": 48,
        "space": 49,
        "delete": 51,
        "backspace": 51,
        "escape": 53,
        "esc": 53,
        "command": 55,
        "shift": 56,
        "capslock": 57,
        "option": 58,
        "control": 59,
        "up": 126,
        "down": 125,
        "left": 123,
        "right": 124,
        "pageup": 116,
        "pagedown": 121,
    }

    def __init__(self) -> None:
        self._is_mac = sys.platform == "darwin"

    async def type_text(self, text: str) -> None:
        if not self._is_mac:
            return
        # Escape double quotes and backslashes for AppleScript string literal
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        cmd = f'tell application "System Events" to keystroke "{escaped}"'
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", cmd],
                capture_output=True,
                check=False,
                timeout=5,
            )
        except Exception:
            pass

    async def press_key(self, key: str) -> None:
        if not self._is_mac:
            return
        norm_key = key.strip().lower()
        if norm_key in self.KEY_CODE_MAP:
            code = self.KEY_CODE_MAP[norm_key]
            cmd = f'tell application "System Events" to key code {code}'
        else:
            escaped = norm_key.replace("\\", "\\\\").replace('"', '\\"')
            cmd = f'tell application "System Events" to keystroke "{escaped}"'
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", cmd],
                capture_output=True,
                check=False,
                timeout=5,
            )
        except Exception:
            pass

    async def hotkey(self, *keys: str) -> None:
        if not self._is_mac or not keys:
            return
        modifiers = []
        main_key = ""
        for k in keys:
            kl = k.lower().strip()
            if kl in ("command", "cmd"):
                modifiers.append("command down")
            elif kl in ("shift",):
                modifiers.append("shift down")
            elif kl in ("option", "alt"):
                modifiers.append("option down")
            elif kl in ("control", "ctrl"):
                modifiers.append("control down")
            else:
                main_key = kl

        using_clause = f" using {{{', '.join(modifiers)}}}" if modifiers else ""
        if main_key in self.KEY_CODE_MAP:
            code = self.KEY_CODE_MAP[main_key]
            cmd = f'tell application "System Events" to key code {code}{using_clause}'
        else:
            cmd = f'tell application "System Events" to keystroke "{main_key}"{using_clause}'

        try:
            await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", cmd],
                capture_output=True,
                check=False,
                timeout=5,
            )
        except Exception:
            pass


class SystemApplicationController(ApplicationController):
    """Narrow application controller using strict non-shell process arguments."""

    def __init__(self) -> None:
        self._is_mac = sys.platform == "darwin"

    async def list_running_apps(self) -> list[str]:
        if not self._is_mac:
            return []
        try:
            # Narrowly query macOS System Profiler or osascript for running GUI apps
            proc = await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", 'tell application "System Events" to get name of (processes where background only is false)'],
                capture_output=True,
                check=False,
                timeout=5,
            )
            if proc.returncode == 0:
                raw = proc.stdout.decode("utf-8", errors="ignore").strip()
                return [app.strip() for app in raw.split(",") if app.strip()]
            return []
        except Exception:
            return []

    async def launch_app(self, app_name: str) -> bool:
        if not self._is_mac:
            raise ComputerDriverError("Application launching currently supports macOS.")

        # Strict argument vector without shell=True or string concatenation
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                ["open", "-a", app_name],
                capture_output=True,
                check=False,
                timeout=10,
            )
            return proc.returncode == 0
        except Exception as err:
            raise ComputerDriverError(f"Failed to launch application '{app_name}': {err}") from err

    async def terminate_app(self, app_name: str) -> bool:
        if not self._is_mac:
            raise ComputerDriverError("Application termination currently supports macOS.")

        try:
            script = f'tell application "{app_name}" to quit'
            proc = await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", script],
                capture_output=True,
                check=False,
                timeout=5,
            )
            return proc.returncode == 0
        except Exception as err:
            raise ComputerDriverError(f"Failed to terminate application '{app_name}': {err}") from err
