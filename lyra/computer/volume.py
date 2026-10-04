"""Native macOS System Volume Controller for LYRA.

Controls macOS output volume and mute state via osascript with fallback support.
"""

import logging
import subprocess
import sys
from typing import Any

logger = logging.getLogger("computer.volume")


class VolumeController:
    """Controls system output volume and mute state."""

    def __init__(self, use_mock: bool = False) -> None:
        self._is_mac = sys.platform == "darwin"
        self._use_mock = use_mock or not self._is_mac
        self._mock_volume: int = 50
        self._mock_muted: bool = False

    def get_volume(self) -> dict[str, Any]:
        """Return dict with 'volume' (0-100) and 'muted' (bool)."""
        if self._use_mock:
            return {"volume": self._mock_volume, "muted": self._mock_muted}

        try:
            cmd = "output volume of (get volume settings) & \",\" & output muted of (get volume settings)"
            res = subprocess.run(["osascript", "-e", cmd], capture_output=True, text=True, check=False, timeout=3)
            if res.returncode == 0 and res.stdout.strip():
                parts = [p.strip() for p in res.stdout.strip().split(",")]
                vol = int(parts[0]) if parts and parts[0].isdigit() else self._mock_volume
                muted = parts[1].lower() == "true" if len(parts) > 1 else False
                return {"volume": vol, "muted": muted}
        except Exception as err:
            logger.error("Failed to query macOS volume settings: %s", err)

        return {"volume": self._mock_volume, "muted": self._mock_muted}

    def set_volume(self, level: int) -> dict[str, Any]:
        """Set output volume (0-100) and return verified state."""
        clamped = max(0, min(100, int(level)))
        if self._use_mock:
            self._mock_volume = clamped
            self._mock_muted = False
            return {"volume": self._mock_volume, "muted": self._mock_muted}

        try:
            subprocess.run(
                ["osascript", "-e", f"set volume output volume {clamped}"],
                capture_output=True,
                check=False,
                timeout=3,
            )
            return self.get_volume()
        except Exception as err:
            logger.error("Failed to set macOS volume: %s", err)
            self._mock_volume = clamped
            return {"volume": self._mock_volume, "muted": self._mock_muted}

    def increase_volume(self, delta: int = 10) -> dict[str, Any]:
        """Increase system volume by delta (default 10)."""
        curr = self.get_volume()
        new_vol = min(100, curr["volume"] + delta)
        return self.set_volume(new_vol)

    def decrease_volume(self, delta: int = 10) -> dict[str, Any]:
        """Decrease system volume by delta (default 10)."""
        curr = self.get_volume()
        new_vol = max(0, curr["volume"] - delta)
        return self.set_volume(new_vol)

    def mute(self) -> dict[str, Any]:
        """Mute system output audio."""
        if self._use_mock:
            self._mock_muted = True
            return {"volume": self._mock_volume, "muted": True}

        try:
            subprocess.run(
                ["osascript", "-e", "set volume output muted true"],
                capture_output=True,
                check=False,
                timeout=3,
            )
            return self.get_volume()
        except Exception as err:
            logger.error("Failed to mute macOS volume: %s", err)
            self._mock_muted = True
            return {"volume": self._mock_volume, "muted": True}

    def unmute(self) -> dict[str, Any]:
        """Unmute system output audio."""
        if self._use_mock:
            self._mock_muted = False
            return {"volume": self._mock_volume, "muted": False}

        try:
            subprocess.run(
                ["osascript", "-e", "set volume output muted false"],
                capture_output=True,
                check=False,
                timeout=3,
            )
            return self.get_volume()
        except Exception as err:
            logger.error("Failed to unmute macOS volume: %s", err)
            self._mock_muted = False
            return {"volume": self._mock_volume, "muted": False}
