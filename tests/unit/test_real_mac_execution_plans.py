"""Unit tests for ActionPlanner intent decomposition and real Mac execution plans."""

import pytest

from lyra.companion.planner import ActionPlanner


def test_planner_notes_open_and_write():
    planner = ActionPlanner()

    # Test 1: "Lyra, open Notes and write Hello Boss."
    plan1 = planner.plan("Lyra, open Notes and write Hello Boss.")
    assert plan1 is not None
    assert plan1.intent == "notes_write"
    assert len(plan1.steps) == 1
    assert plan1.steps[0].tool == "notes.write_note"
    assert plan1.steps[0].arguments["text"] == "Hello Boss"

    # Test 1b: "Create a note called Meeting and write Hello Boss"
    plan1b = planner.plan("Create a note called Meeting and write Hello Boss")
    assert plan1b is not None
    assert plan1b.intent == "notes_write"
    assert plan1b.steps[0].arguments["title"] == "Meeting"
    assert plan1b.steps[0].arguments["text"] == "Hello Boss"

    # Test 1c: "Open Notes"
    plan1c = planner.plan("Open Notes")
    assert plan1c is not None
    assert plan1c.steps[0].tool == "notes.open_notes"


def test_planner_vscode_intents():
    planner = ActionPlanner()

    # Test 2: "Lyra, open VS Code."
    plan2 = planner.plan("Lyra, open VS Code.")
    assert plan2 is not None
    assert plan2.intent == "open_application"
    assert plan2.steps[0].arguments["app_name"] == "Visual Studio Code"

    # Test 2b: "Open my Lyra project in VS Code."
    plan2b = planner.plan("Open my Lyra project in VS Code.")
    assert plan2b is not None
    assert plan2b.intent == "open_vscode_project"
    assert plan2b.steps[0].arguments["target_path"] == "/Users/vikas/Desktop/Lyra"

    # Test 2c: "Open the file main.py in VS Code"
    plan2c = planner.plan("Open the file main.py in VS Code")
    assert plan2c is not None
    assert plan2c.intent == "open_file_in_vscode"
    assert "main.py" in plan2c.steps[0].arguments["target_path"]


def test_planner_folder_structure_intents():
    planner = ActionPlanner()

    # Test 3: "Lyra, create a folder called LYRA_TEST on my Desktop."
    plan3 = planner.plan("Lyra, create a folder called LYRA_TEST on my Desktop.")
    assert plan3 is not None
    assert plan3.steps[0].tool == "filesystem.create_directory"
    assert "LYRA_TEST" in plan3.steps[0].arguments["path"]

    # Test 4: "Lyra, create a folder structure called Project with src, tests and docs."
    plan4 = planner.plan("Lyra, create a folder structure called Project with src, tests and docs.")
    assert plan4 is not None
    assert plan4.intent == "create_folder_structure"
    assert plan4.steps[0].tool == "filesystem.create_structure"
    assert plan4.steps[0].arguments["root_name"] == "Project"


def test_planner_youtube_and_google_search():
    planner = ActionPlanner()

    # Test 5: "Lyra, open YouTube."
    plan5 = planner.plan("Lyra, open YouTube.")
    assert plan5 is not None
    assert "youtube" in plan5.intent or "youtube" in plan5.steps[0].arguments.get("url", "")

    # Test 6: "Lyra, search YouTube for Believer."
    plan6 = planner.plan("Lyra, search YouTube for Believer.")
    assert plan6 is not None
    assert plan6.steps[0].arguments["query"] == "Believer"

    # Test 7: "Lyra, open YouTube and play Believer."
    plan7 = planner.plan("Lyra, open YouTube and play Believer.")
    assert plan7 is not None
    assert plan7.intent == "play_youtube"
    assert plan7.steps[1].arguments["query"] == "Believer"

    # Test 8: "Lyra, open a new tab and search Google for Python tutorials."
    plan8 = planner.plan("Lyra, open a new tab and search Google for Python tutorials.")
    assert plan8 is not None
    assert plan8.intent == "new_tab_google_search"
    assert "Python+tutorials" in plan8.steps[0].arguments["url"] or "Python tutorials" in plan8.steps[0].arguments["url"]


def test_planner_brightness_and_volume():
    planner = ActionPlanner()

    # Test 10: "Lyra, decrease the brightness."
    plan10 = planner.plan("Lyra, decrease the brightness.")
    assert plan10 is not None
    assert "decrease_brightness" in plan10.steps[0].tool

    # Test 11: "Lyra, increase the volume."
    plan11 = planner.plan("Lyra, increase the volume.")
    assert plan11 is not None
    assert "increase_volume" in plan11.steps[0].tool
