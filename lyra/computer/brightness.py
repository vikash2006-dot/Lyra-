"""Native macOS Display Brightness Controller for LYRA.

Uses macOS private framework DisplayServices via ctypes for direct, zero-lag brightness
adjustment with state verification. Falls back gracefully on non-macOS or test environments.
"""

import ctypes
import logging
import sys
from typing import Optional

logger = logging.getLogger("computer.brightness")


class BrightnessController:
    """Controls display brightness on macOS using DisplayServices framework."""

    def __init__(self, use_mock: bool = False) -> None:
        self._is_mac = sys.platform == "darwin"
        self._use_mock = use_mock or not self._is_mac
        self._mock_brightness: float = 0.5
        self._ds: Optional[ctypes.CDLL] = None
        self._cg: Optional[ctypes.CDLL] = None
        self._display_id: Optional[int] = None

        if not self._use_mock:
            self._init_native_frameworks()

    def _init_native_frameworks(self) -> None:
        try:
            self._ds = ctypes.CDLL(
                "/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices"
            )
            # int DisplayServicesGetBrightness(CGDirectDisplayID display, float *brightness)
            self._ds.DisplayServicesGetBrightness.restype = ctypes.c_int
            self._ds.DisplayServicesGetBrightness.argtypes = [
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_float),
            ]
            # int DisplayServicesSetBrightness(CGDirectDisplayID display, float brightness)
            self._ds.DisplayServicesSetBrightness.restype = ctypes.c_int
            self._ds.DisplayServicesSetBrightness.argtypes = [
                ctypes.c_uint32,
                ctypes.c_float,
            ]

            self._cg = ctypes.CDLL(
                "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
            )
            self._cg.CGMainDisplayID.restype = ctypes.c_uint32
            self._cg.CGMainDisplayID.argtypes = []
            self._display_id = self._cg.CGMainDisplayID()
        except Exception as err:
            logger.warning("Failed to initialize native DisplayServices: %s. Falling back to mock.", err)
            self._use_mock = True

    def get_brightness(self) -> float:
        """Return current display brightness as a float between 0.0 and 1.0."""
        if self._use_mock or self._ds is None or self._display_id is None:
            return round(self._mock_brightness, 2)

        try:
            b = ctypes.c_float()
            ret = self._ds.DisplayServicesGetBrightness(self._display_id, ctypes.byref(b))
            if ret == 0:
                val = max(0.0, min(1.0, float(b.value)))
                return round(val, 2)
            logger.warning("DisplayServicesGetBrightness returned non-zero code: %d", ret)
            return round(self._mock_brightness, 2)
        except Exception as err:
            logger.error("Error reading display brightness: %s", err)
            return round(self._mock_brightness, 2)

    def set_brightness(self, level: float) -> float:
        """Set display brightness to level (0.0 to 1.0) and return verified new level."""
        clamped = max(0.0, min(1.0, float(level)))
        if self._use_mock or self._ds is None or self._display_id is None:
            self._mock_brightness = clamped
            return round(self._mock_brightness, 2)

        try:
            ret = self._ds.DisplayServicesSetBrightness(self._display_id, ctypes.c_float(clamped))
            if ret != 0:
                logger.warning("DisplayServicesSetBrightness returned code %d", ret)
            # Verify and return actual level
            verified = self.get_brightness()
            return verified
        except Exception as err:
            logger.error("Error setting display brightness: %s", err)
            self._mock_brightness = clamped
            return clamped

    def increase_brightness(self, delta: float = 0.1) -> float:
        """Increase display brightness by delta (default 0.10 / 10%)."""
        current = self.get_brightness()
        new_val = min(1.0, current + delta)
        return self.set_brightness(new_val)

    def decrease_brightness(self, delta: float = 0.1) -> float:
        """Decrease display brightness by delta (default 0.10 / 10%)."""
        current = self.get_brightness()
        new_val = max(0.0, current - delta)
        return self.set_brightness(new_val)
