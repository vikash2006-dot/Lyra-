"""Unit tests for LYRA IntentRouter and Task Classification."""

import pytest

from lyra.routing.intent_router import IntentCategory, IntentRouter


@pytest.fixture
def router() -> IntentRouter:
    return IntentRouter()


def test_classify_brightness_controls(router: IntentRouter) -> None:
    res_inc = router.classify("Lyra, increase brightness")
    assert res_inc.category == IntentCategory.BRIGHTNESS_CONTROL
    assert res_inc.entities.get("action") == "increase"
    assert res_inc.suggested_tool == "system"

    res_dec = router.classify("Decrease brightness please")
    assert res_dec.category == IntentCategory.BRIGHTNESS_CONTROL
    assert res_dec.entities.get("action") == "decrease"

    res_set = router.classify("Set brightness to 50%")
    assert res_set.category == IntentCategory.BRIGHTNESS_CONTROL
    assert res_set.entities.get("level") == 50


def test_classify_volume_controls(router: IntentRouter) -> None:
    res_mute = router.classify("Lyra, mute the Mac")
    assert res_mute.category == IntentCategory.VOLUME_CONTROL
    assert res_mute.entities.get("action") == "mute"

    res_unmute = router.classify("Lyra, unmute")
    assert res_unmute.category == IntentCategory.VOLUME_CONTROL
    assert res_unmute.entities.get("action") == "unmute"

    res_up = router.classify("Turn volume up")
    assert res_up.category == IntentCategory.VOLUME_CONTROL
    assert res_up.entities.get("action") == "increase"


def test_classify_notes_write_and_read(router: IntentRouter) -> None:
    res_write = router.classify("Lyra, open Notes and write Hello Boss")
    assert res_write.category == IntentCategory.WRITE_TEXT
    assert "Hello Boss" in res_write.entities.get("text", "")
    assert res_write.suggested_tool == "notes"

    res_read = router.classify("Read notes")
    assert res_read.category == IntentCategory.READ_TEXT
    assert res_read.suggested_tool == "notes"


def test_classify_browser_and_youtube(router: IntentRouter) -> None:
    res_yt = router.classify("Lyra, open YouTube and play Believer")
    assert res_yt.category == IntentCategory.PLAY_MEDIA
    assert "Believer" in res_yt.entities.get("query", "")
    assert res_yt.suggested_tool == "browser"

    res_google = router.classify("Lyra, open a new browser tab and search Google for Python internships")
    assert res_google.category == IntentCategory.SEARCH_GOOGLE
    assert "Python internships" in res_google.entities.get("query", "")
    assert res_google.entities.get("in_new_tab") is True

    res_new_tab = router.classify("Open a new tab")
    assert res_new_tab.category == IntentCategory.NEW_TAB

    res_close_tab = router.classify("Close the current tab")
    assert res_close_tab.category == IntentCategory.CLOSE_TAB

    res_nav = router.classify("Go back")
    assert res_nav.category == IntentCategory.BROWSER_NAVIGATION

    res_scroll = router.classify("Scroll down")
    assert res_scroll.category == IntentCategory.SCROLL

    res_click = router.classify("Click the first result")
    assert res_click.category == IntentCategory.CLICK_ELEMENT

    res_url = router.classify("Open https://github.com")
    assert res_url.category == IntentCategory.OPEN_URL


def test_classify_filesystem_and_app_controls(router: IntentRouter) -> None:
    res_folder = router.classify("Lyra, create a folder called AI Projects on my Desktop")
    assert res_folder.category == IntentCategory.CREATE_FOLDER

    res_struct = router.classify("Create this folder structure on my Desktop: AI/backend/frontend/data")
    assert res_struct.category == IntentCategory.CREATE_FOLDER

    res_app = router.classify("Lyra, open VS Code")
    assert res_app.category == IntentCategory.OPEN_APP
    assert res_app.entities.get("app_name") == "Visual Studio Code"

    res_close_app = router.classify("Close Chrome")
    assert res_close_app.category == IntentCategory.CLOSE_APP

    res_del = router.classify("Delete file old_notes.txt")
    assert res_del.category == IntentCategory.DELETE_FILE
    assert res_del.requires_confirmation is True
    assert res_del.risk_level == "HIGH"

    res_move = router.classify("Move draft.txt into Archive")
    assert res_move.category == IntentCategory.MOVE_FILE

    res_rename = router.classify("Rename folder Old to New")
    assert res_rename.category == IntentCategory.RENAME_FILE


def test_classify_research_learning_and_anakin_workflow(router: IntentRouter) -> None:
    res_research = router.classify("Lyra, research the best free Python resources")
    assert res_research.category == IntentCategory.RESEARCH
    assert "Python resources" in res_research.entities.get("topic", "")

    res_resume = router.classify("Lyra, analyze my resume")
    assert res_research.category in (IntentCategory.RESEARCH, IntentCategory.ANAKIN_WORKFLOW)
    assert res_resume.category == IntentCategory.ANAKIN_WORKFLOW

    res_learn = router.classify("Show my weekly learning plan")
    assert res_learn.category == IntentCategory.LEARNING

    res_query = router.classify("What is the capital of France?")
    assert res_query.category == IntentCategory.AI_QUERY
