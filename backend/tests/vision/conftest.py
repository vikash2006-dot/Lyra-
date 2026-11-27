"""Fixtures for visual-awareness tests: fake capture (rendered screens), scripted vision model, mock computer."""

from __future__ import annotations

import sys
from typing import Any

import pytest

from lyra.computer.controller import ComputerController
from lyra.config.settings import load_settings
from lyra.vision import apps, service as service_mod
from lyra.vision.analyzer import VisionUnavailableError
from lyra.vision.capture import ScreenPermissionError
from lyra.vision.models import Screenshot

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Apple Vision OCR / AppKit rendering need macOS")


class FakeCapture:
    """Returns a rendered screen as if captured on a Retina display (2 image px per screen point)."""

    supported = True

    def __init__(self, png: bytes, width: int = 1200, height: int = 760) -> None:
        self.png, self.width, self.height = png, width, height
        self.permission = "granted"
        self.captures = 0

    def permission_status(self) -> str:
        return self.permission

    def request_permission(self) -> str:
        return self.permission

    def displays(self) -> list[dict[str, Any]]:
        return [{"index": 1, "id": 1, "main": True, "x": 0, "y": 0, "width": self.width / 2,
                 "height": self.height / 2, "scale": 2.0}]

    async def capture(self, display=None, window_id=None, window_info=None) -> Screenshot:
        if self.permission != "granted":
            raise ScreenPermissionError("Screen Recording permission is required.")
        self.captures += 1
        return Screenshot(png=self.png, width=self.width, height=self.height, scale=2.0, display_id=1)


class ScriptedAnalyzer:
    """Stands in for the cloud vision model; records whether images would have been sent."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.actions: list[dict[str, Any]] = []
        self.analysis: dict[str, Any] = {
            "summary": "Acme Portal sign-in page with an invalid password error.",
            "page_state": "login form with error",
            "elements": [{"id": "t4", "type": "button", "label": "Login", "actionable": True}],
            "errors": ["Error: Invalid password. Please try again."],
            "answer": "Your password was rejected. The Login button is just below the error message.",
            "suggested_next_action": "Re-enter the password and click Login.",
            "confidence": 0.9, "_source": "fake/vision-model", "_factor": 1.0,
        }
        self.verify_result = {"verified": True, "evidence": "Welcome text visible", "_source": "fake/vision-model"}

    def status(self) -> dict[str, Any]:
        return {"available": True, "models": ["fake:vision"], "last_used": None}

    async def analyze(self, shot, lines, els, app, question=None, local_only=False):
        if local_only:
            raise VisionUnavailableError("local only")
        self.calls.append("analyze")
        return dict(self.analysis)

    async def decide_action(self, shot, goal, block, history, local_only=False):
        if local_only:
            raise VisionUnavailableError("local only")
        self.calls.append("decide")
        return self.actions.pop(0) if self.actions else {"action": "done", "reason": "Finished."}

    async def verify(self, shot, expectation, local_only=False):
        if local_only:
            raise VisionUnavailableError("local only")
        self.calls.append("verify")
        return dict(self.verify_result)


@pytest.fixture
def login_png() -> bytes:
    from tests.vision.fake_screen import LOGIN_BOXES, LOGIN_SCREEN, render_screen

    return render_screen(LOGIN_SCREEN, boxes=LOGIN_BOXES)


@pytest.fixture
def fake_window(monkeypatch):
    state = {"app": "Safari", "title": "Acme Portal", "pid": 0, "window_id": None, "bounds": None, "bundle_id": ""}
    monkeypatch.setattr(apps, "active_window", lambda: dict(state))
    monkeypatch.setattr(service_mod.apps, "active_window", lambda: dict(state))
    return state


def install_fakes(awareness, png: bytes) -> tuple[FakeCapture, ScriptedAnalyzer]:
    cap, an = FakeCapture(png), ScriptedAnalyzer()
    awareness.capture_service = cap
    awareness.analyzer = an
    awareness.monitor.aw = awareness
    return cap, an


@pytest.fixture
def computer():
    ctrl = ComputerController.from_settings(load_settings(), use_mock=True)
    ctrl.enabled = True
    return ctrl
