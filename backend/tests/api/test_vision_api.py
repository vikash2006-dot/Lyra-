"""Vision API endpoints and screen requests through chat (tracked as tasks)."""

import sys

import pytest

from tests.vision.conftest import install_fakes
from tests.vision.fake_screen import LOGIN_BOXES, LOGIN_SCREEN, render_screen

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")


@pytest.fixture
def vision(client, monkeypatch):
    from lyra.vision import apps, service

    win = {"app": "Safari", "title": "Acme Portal", "pid": 0, "window_id": None, "bounds": None, "bundle_id": ""}
    monkeypatch.setattr(apps, "active_window", lambda: dict(win))
    monkeypatch.setattr(service.apps, "active_window", lambda: dict(win))
    screen = client.app.state.services.runtime.screen
    cap, an = install_fakes(screen, render_screen(LOGIN_SCREEN, boxes=LOGIN_BOXES))
    return screen, cap, an


def test_status_and_privacy_defaults(client, vision):
    data = client.get("/api/vision/status").json()["data"]
    assert data["enabled"] is True and data["cloud_consent"] is False
    assert data["screen_permission"] == "granted" and data["monitoring"]["running"] is False


def test_capture_and_analyze_and_context(client, vision):
    screen, cap, an = vision
    cap_res = client.post("/api/vision/capture", json={"session_id": "s1"}).json()["data"]
    assert cap_res["preview"]["mime_type"] == "image/jpeg" and cap_res["context"]["ocr_lines"] >= 5
    assert an.calls == []  # capture never calls AI
    res = client.post("/api/vision/analyze", json={"session_id": "s1", "question": "what's wrong?"}).json()["data"]
    assert res["context"]["analysis_source"] == "local"  # no consent yet → local only
    client.put("/api/vision/settings", json={"cloud_consent": True})
    res = client.post("/api/vision/analyze", json={"session_id": "s1", "question": "what's wrong?"}).json()["data"]
    assert res["context"]["analysis_source"].startswith("vision:")
    assert client.app.state.services.store.get_preferences()["vision_cloud_consent"] is True
    assert client.get("/api/vision/context?session_id=s1").json()["data"]["context"]["answer"]
    client.delete("/api/vision/context?session_id=s1")
    assert client.get("/api/vision/context?session_id=s1").json()["data"]["context"] is None


def test_permission_denied_maps_to_403(client, vision):
    vision[1].permission = "denied"
    r = client.post("/api/vision/capture", json={})
    assert r.status_code == 403 and r.json()["error"]["code"] == "SCREEN_PERMISSION_DENIED"


def test_screen_question_via_chat_is_a_tracked_task(client, vision):
    client.put("/api/vision/settings", json={"cloud_consent": True})
    body = client.post("/api/chat", json={"message": "Lyra, look at my screen. What went wrong?"}).json()
    assert body["response"].startswith("Your password was rejected")
    assert body["task"]["steps"][0]["tool"] == "screen" and body["task"]["status"] == "completed"
    click = client.post("/api/chat", json={"message": "Click the Login button", "session_id": body["session_id"]}).json()
    assert "I clicked “Login”" in click["response"]
    assert [s["tool"] for s in click["task"]["steps"]] == ["screen"]


def test_monitor_controls_and_disable(client, vision):
    started = client.post("/api/vision/monitor/start", json={"interval_seconds": 5}).json()["data"]
    assert started["running"] is True and started["interval_seconds"] == 5
    assert client.post("/api/vision/monitor/stop").json()["data"]["running"] is False
    client.put("/api/vision/settings", json={"enabled": False})
    assert client.post("/api/vision/monitor/start").status_code == 409
    body = client.post("/api/chat", json={"message": "Look at my screen"}).json()
    assert body["task"] is None or body["task"]["steps"][0]["tool"] != "screen"
