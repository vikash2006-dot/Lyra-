"""Screen awareness: capture → OCR/elements → (vision) → context → act → verify, plus privacy & monitoring."""

import asyncio

import pytest

from lyra.vision.agent import VisualAgent
from lyra.vision.service import ScreenAwareness
from tests.vision.conftest import install_fakes
from tests.vision.fake_screen import render_screen


def _aw(computer, png):
    aw = ScreenAwareness(router=None, computer_controller=computer)
    cap, an = install_fakes(aw, png)
    return aw, cap, an


def run(coro):
    return asyncio.run(coro)


def test_observe_without_consent_stays_local(computer, login_png, fake_window):
    aw, cap, an = _aw(computer, login_png)
    ctx = run(aw.observe("s1", question="what's wrong?"))
    assert ctx.analysis_source == "local" and an.calls == []  # no image left the machine
    assert "Invalid password" in ctx.visible_text
    assert any("Invalid password" in e for e in ctx.errors)
    login = next(e for e in ctx.elements if e.label == "Login")
    assert login.type == "button" and login.actionable
    assert ctx.active_app == "Safari" and ctx.screenshot["scale"] == 2.0


def test_observe_with_consent_uses_vision_and_merges_elements(computer, login_png, fake_window):
    aw, cap, an = _aw(computer, login_png)
    aw.cloud_consent = True
    ctx = run(aw.observe("s1", question="what's wrong?"))
    assert ctx.analysis_source == "vision:fake/vision-model" and an.calls == ["analyze"]
    assert ctx.answer.startswith("Your password was rejected")
    assert ctx.to_dict()["elements"][0]["label"] == "Login"
    assert aw.context("s1") is ctx and aw.context("other") is None
    aw.clear_context("s1")
    assert aw.context("s1") is None


@pytest.mark.parametrize("text,expected", [
    ("Lyra, look at my screen.", "observe"),
    ("What is currently open?", "observe"),
    ("Explain what's happening here.", "observe"),
    ("Read this screen for me", "observe"),
    ("Find the error in this code", "observe"),
    ("Where is the Submit button?", "observe"),
    ("What should I do next?", "observe"),
    ("Click the Login button", "act"),
    ("Fill out this form", "act"),
    ("Do the next step", "act"),
    ("What's the weather today?", None),
    ("click at 300, 400", None),
    ("Create a folder called Projects on my Desktop", None),
])
def test_visual_intent_routing(computer, login_png, text, expected):
    aw, _, _ = _aw(computer, login_png)
    assert VisualAgent(aw, router=None).classify(text, "s1") == expected


def test_contextual_followups_need_recent_context(computer, login_png, fake_window):
    aw, _, _ = _aw(computer, login_png)
    agent = VisualAgent(aw, router=None)
    assert agent.classify("What's wrong here?", "s1") is None
    assert agent.classify("Fix it", "s1") is None
    run(aw.observe("s1", use_ai=False))
    assert agent.classify("What's wrong here?", "s1") == "followup"
    assert agent.classify("Fix it", "s1") == "act"
    assert agent.classify("Now check again", "s1") == "verify"


def test_direct_click_maps_retina_coordinates(computer, login_png, fake_window):
    aw, _, _ = _aw(computer, login_png)
    reply = run(VisualAgent(aw, router=None).handle("act", "Click the Login button", "s1"))
    assert reply.startswith("Done, Boss. I clicked “Login”")
    click = computer.mouse.click_history[-1]["point"]
    # Login text center ≈ (588, 526) image px → (294, 263) screen points at 2x scale
    assert abs(click.x - 294) <= 6 and abs(click.y - 263) <= 6
    assert aw.context("s1") is None  # coordinates invalidated after acting


def test_sensitive_click_requires_confirmation(computer, fake_window):
    png = render_screen([("Settings", 100, 60, 26), ("Delete account", 100, 200, 22)])
    aw, _, _ = _aw(computer, png)
    agent = VisualAgent(aw, router=None)
    reply = run(agent.handle("act", "Click the Delete account button", "s1"))
    assert "Should I go ahead" in reply and computer.mouse.click_history == []
    assert agent.classify("yes", "s1") == "confirm"
    reply = run(agent.handle("confirm", "yes", "s1"))
    assert reply.startswith("Done") and len(computer.mouse.click_history) == 1


def test_never_types_passwords(computer, login_png, fake_window):
    aw, _, _ = _aw(computer, login_png)
    reply = run(VisualAgent(aw, router=None).handle("act", "Type 'hunter2' into the Password field", "s1"))
    assert "don't type passwords" in reply and computer.keyboard.typed_text == []


def test_permission_denied_is_explained(computer, login_png, fake_window):
    aw, cap, _ = _aw(computer, login_png)
    cap.permission = "denied"
    reply = run(VisualAgent(aw, router=None).handle("observe", "Look at my screen", "s1"))
    assert "Screen Recording" in reply and "System Settings" in reply


def test_local_reply_asks_for_consent(computer, login_png, fake_window):
    aw, _, _ = _aw(computer, login_png)
    reply = run(VisualAgent(aw, router=None).handle("observe", "Explain this screen", "s1"))
    assert "Safari" in reply and "permission" in reply and "Settings" in reply


def test_multistep_task_with_verification_and_adaptation(computer, login_png, fake_window):
    aw, _, an = _aw(computer, login_png)
    aw.cloud_consent = True
    an.actions = [
        {"action": "click", "target": "Nonexistent", "expected": ""},          # fails → agent adapts
        {"action": "click", "element_id": "t4", "target": "Login", "expected": "Welcome"},
        {"action": "done", "reason": "You're signed in."},
    ]
    reply = run(VisualAgent(aw, router=None).handle("act", "Help me complete this task", "s1"))
    assert reply.startswith("Done, Boss.") and "signed in" in reply
    assert len(computer.mouse.click_history) == 1
    assert "verify" in an.calls  # expected result was checked after the click


def test_verify_detects_missing_result(computer, login_png, fake_window):
    aw, _, an = _aw(computer, login_png)
    out = run(aw.verify("'Welcome back' is shown", "s1", use_ai=False))
    assert out["verified"] is False and out["method"] == "ocr"
    out = run(aw.verify("'Invalid password' is shown", "s1", use_ai=False))
    assert out["verified"] is True


def test_monitor_detects_app_switch_and_errors(computer, login_png, fake_window):
    aw, cap, _ = _aw(computer, render_screen([("Inbox", 100, 100, 24)]))
    events = []
    aw.add_listener(events.append)

    async def scenario():
        await aw.monitor.tick()                      # baseline
        fake_window["app"] = "Visual Studio Code"
        cap.png = login_png                          # new app with an error on screen
        await aw.monitor.tick()

    run(scenario())
    changes = [e["change"] for e in events if e.get("type") == "screen_change"]
    assert "app_switch" in changes and "error_appeared" in changes


def test_disabled_awareness_ignores_requests(computer, login_png):
    aw, _, _ = _aw(computer, login_png)
    aw.enabled = False
    assert VisualAgent(aw, router=None).classify("Look at my screen", "s1") is None
