"""Unit tests for advanced natural language intent understanding and task planning."""

from lyra.companion.planner import ActionPlanner
from lyra.companion.session import Session


def test_planner_brightness_intents():
    planner = ActionPlanner()
    session = Session()

    for phrase in ["Increase brightness", "Make the screen brighter", "Brightness up", "Turn the brightness up"]:
        p = planner.plan(phrase, session=session)
        assert p is not None, f"Failed to plan: {phrase}"
        assert p.intent == "increase_brightness"
        assert p.steps[0].tool == "system.increase_brightness"

    for phrase in ["Decrease brightness", "Make the screen darker", "Brightness down", "Turn the brightness down"]:
        p = planner.plan(phrase, session=session)
        assert p is not None, f"Failed to plan: {phrase}"
        assert p.intent == "decrease_brightness"
        assert p.steps[0].tool == "system.decrease_brightness"

    p_set = planner.plan("Set brightness to 50 percent", session=session)
    assert p_set is not None
    assert p_set.intent == "set_brightness"
    assert p_set.steps[0].arguments["level"] == 0.5


def test_planner_volume_intents():
    planner = ActionPlanner()
    session = Session()

    for phrase in ["Increase volume", "Turn the volume up", "Volume up"]:
        p = planner.plan(phrase, session=session)
        assert p is not None, f"Failed to plan: {phrase}"
        assert p.intent == "increase_volume"
        assert p.steps[0].tool == "system.increase_volume"

    for phrase in ["Decrease volume", "Turn the volume down", "Volume down"]:
        p = planner.plan(phrase, session=session)
        assert p is not None, f"Failed to plan: {phrase}"
        assert p.intent == "decrease_volume"
        assert p.steps[0].tool == "system.decrease_volume"

    p_vol = planner.plan("Set volume to 50 percent", session=session)
    assert p_vol is not None
    assert p_vol.intent == "set_volume"
    assert p_vol.steps[0].arguments["level"] == 50

    p_mute = planner.plan("Mute the computer", session=session)
    assert p_mute is not None
    assert p_mute.intent == "mute"

    p_unmute = planner.plan("Unmute", session=session)
    assert p_unmute is not None
    assert p_unmute.intent == "unmute"


def test_planner_browser_tab_intents():
    planner = ActionPlanner()
    session = Session()

    p_new = planner.plan("Open a new tab", session=session)
    assert p_new is not None
    assert p_new.intent == "new_tab"
    assert p_new.steps[0].tool == "browser.new_tab"

    p_close = planner.plan("Close this tab", session=session)
    assert p_close is not None
    assert p_close.intent == "close_tab"
    assert p_close.steps[0].tool == "browser.close_tab"

    p_prev = planner.plan("Switch to the previous tab", session=session)
    assert p_prev is not None
    assert p_prev.intent == "switch_tab_prev"

    p_next = planner.plan("Switch to the next tab", session=session)
    assert p_next is not None
    assert p_next.intent == "switch_tab_next"

    p_git = planner.plan("Open GitHub in a new tab", session=session)
    assert p_git is not None
    assert p_git.intent == "open_site_new_tab"
    assert "github" in p_git.steps[0].arguments["url"]


def test_planner_keyboard_intents():
    planner = ActionPlanner()
    session = Session()

    p_enter = planner.plan("Press Enter", session=session)
    assert p_enter is not None
    assert p_enter.intent == "press_enter"
    assert p_enter.steps[0].arguments["key"] == "enter"

    p_esc = planner.plan("Press Escape", session=session)
    assert p_esc is not None
    assert p_esc.intent == "press_escape"

    p_cmd_l = planner.plan("Press Command L", session=session)
    assert p_cmd_l is not None
    assert p_cmd_l.intent == "press_cmd_l"
    assert p_cmd_l.steps[0].arguments["keys"] == ["command", "l"]


def test_planner_multi_step_pipelines():
    planner = ActionPlanner()
    session = Session()

    # Chrome + tab + Google search + open result
    p_chrome = planner.plan(
        "Open Chrome, create a new tab, search Google for Python courses, and open the first result",
        session=session,
    )
    assert p_chrome is not None
    assert p_chrome.intent == "chrome_tab_search_and_open"
    assert len(p_chrome.steps) == 4
    assert p_chrome.steps[0].tool == "system.open_application"
    assert p_chrome.steps[1].tool == "browser.new_tab"
    assert p_chrome.steps[2].tool == "browser.search_web"
    assert p_chrome.steps[3].tool == "browser.open_search_result"

    # Tab + Google search
    p_tab_google = planner.plan("Open a new tab and search Google for Python tutorials", session=session)
    assert p_tab_google is not None
    assert p_tab_google.intent == "new_tab_google_search"

    # Tab + YouTube search
    p_tab_yt = planner.plan("Open a new tab and search YouTube for Codeforces tutorials", session=session)
    assert p_tab_yt is not None
    assert p_tab_yt.intent == "new_tab_youtube_search"

    # Search for X and play first result
    p_play_res = planner.plan("Search for Arijit Singh and play the first result", session=session)
    assert p_play_res is not None
    assert p_play_res.intent == "youtube_search_and_play"
    assert p_play_res.steps[0].tool == "browser.search_youtube"
    assert p_play_res.steps[1].tool == "browser.play_media"
