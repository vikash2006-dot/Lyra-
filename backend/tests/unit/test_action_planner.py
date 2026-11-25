"""Unit tests for ActionPlanner: intent detection, multi-step decomposition, and context memory."""

from pathlib import Path
import pytest

from lyra.companion.planner import ActionPlanner
from lyra.companion.session import Session


def test_action_planner_filesystem_intents():
    planner = ActionPlanner()
    session = Session()

    # 1. Create folder on desktop
    plan1 = planner.plan("Lyra, create a folder on my desktop named College", session=session)
    assert plan1 is not None
    assert plan1.intent == "create_folder"
    assert len(plan1.steps) == 1
    assert plan1.steps[0].tool == "filesystem.create_directory"
    assert "Desktop/College" in plan1.steps[0].arguments["path"]

    # Natural variations
    plan1b = planner.plan("Can you make me a folder called Work on my desktop?", session=session)
    assert plan1b is not None
    assert "Desktop/Work" in plan1b.steps[0].arguments["path"]

    # 2. Create subfolder inside folder
    plan2 = planner.plan("Create a folder called Projects inside College", session=session)
    assert plan2 is not None
    assert plan2.intent == "create_folder"
    assert "College/Projects" in plan2.steps[0].arguments["path"]

    # 3. Create file on desktop
    plan3 = planner.plan("Create a file called notes.txt on my desktop", session=session)
    assert plan3 is not None
    assert plan3.intent == "create_file"
    assert "Desktop/notes.txt" in plan3.steps[0].arguments["path"]

    # 4. Open folder in Finder
    plan4 = planner.plan("Open my Desktop folder", session=session)
    assert plan4 is not None
    assert plan4.intent == "open_path"
    assert plan4.steps[0].tool == "filesystem.open_path"

    # 5. Rename folder
    plan5 = planner.plan("Rename the College folder to University", session=session)
    assert plan5 is not None
    assert plan5.intent == "rename"
    assert "College" in plan5.steps[0].arguments["path"]
    assert "University" in plan5.steps[0].arguments["destination"]

    # 6. Delete folder (requires confirmation)
    plan6 = planner.plan("Delete the test folder", session=session)
    assert plan6 is not None
    assert plan6.intent == "delete_requires_confirmation"
    assert plan6.user_confirmation_prompt is not None
    assert "test" in plan6.user_confirmation_prompt


def test_action_planner_browser_and_media_intents():
    planner = ActionPlanner()
    session = Session()

    # 1. Open YouTube
    plan_yt = planner.plan("Lyra, open YouTube", session=session)
    assert plan_yt is not None
    assert plan_yt.intent == "open_youtube"
    assert plan_yt.steps[0].arguments["url"] == "https://www.youtube.com"

    # 2. Open YouTube and play media
    plan_play = planner.plan("Open YouTube and play Believer", session=session)
    assert plan_play is not None
    assert plan_play.intent == "play_youtube"
    assert len(plan_play.steps) == 2
    assert plan_play.steps[1].tool == "browser.play_media"
    assert plan_play.steps[1].arguments["query"] == "Believer"

    # 3. Search Google
    plan_google = planner.plan("Search Google for the best Python courses", session=session)
    assert plan_google is not None
    assert plan_google.intent == "search_google"
    assert plan_google.steps[0].arguments["query"] == "the best Python courses"

    # 4. Search YouTube
    plan_yt_search = planner.plan("Search YouTube for Codeforces tutorials", session=session)
    assert plan_yt_search is not None
    assert plan_yt_search.intent == "search_youtube"
    assert plan_yt_search.steps[0].arguments["query"] == "Codeforces tutorials"

    # 5. Open GitHub
    plan_gh = planner.plan("Open GitHub", session=session)
    assert plan_gh is not None
    assert plan_gh.intent == "open_github"
    assert plan_gh.steps[0].arguments["url"] == "https://www.github.com"


def test_action_planner_application_control():
    planner = ActionPlanner()
    session = Session()

    for app, expected_name in [
        ("Open Chrome", "Google Chrome"),
        ("Open Finder", "Finder"),
        ("Open Terminal", "Terminal"),
        ("Open VS Code", "Visual Studio Code"),
    ]:
        plan = planner.plan(app, session=session)
        assert plan is not None
        assert plan.intent == "open_application"
        assert plan.steps[0].tool == "computer.launch_app"
        assert plan.steps[0].arguments["app_name"] == expected_name


def test_action_planner_multi_step_decomposition():
    planner = ActionPlanner()
    session = Session()

    # Multi-step 1: create folder, open it, and create file inside it
    prompt1 = "Lyra, create a folder called College on my desktop, open it, and create a file called notes.txt inside it."
    plan1 = planner.plan(prompt1, session=session)
    assert plan1 is not None
    assert plan1.intent == "create_folder_and_file"
    assert len(plan1.steps) == 3
    assert plan1.steps[0].tool == "filesystem.create_directory"
    assert "Desktop/College" in plan1.steps[0].arguments["path"]
    assert plan1.steps[1].tool == "filesystem.open_path"
    assert plan1.steps[2].tool == "filesystem.create_file"
    assert "College/notes.txt" in plan1.steps[2].arguments["path"]

    # Multi-step 2: create folder on desktop and create file inside it
    prompt2 = "create a folder called Projects on my desktop and create a file called todo.txt inside it"
    plan2 = planner.plan(prompt2, session=session)
    assert plan2 is not None
    assert len(plan2.steps) == 2
    assert "Projects" in plan2.steps[0].arguments["path"]
    assert "Projects/todo.txt" in plan2.steps[1].arguments["path"]

    # Multi-step 3: open youtube, search for relaxing music, and play first suitable result
    prompt3 = "open youtube, search for relaxing music, and play the first suitable result"
    plan3 = planner.plan(prompt3, session=session)
    assert plan3 is not None
    assert len(plan3.steps) == 2
    assert plan3.steps[0].tool == "browser.search_youtube"
    assert plan3.steps[1].tool == "browser.play_media"

    # Multi-step 4: search google for X and open first relevant result
    prompt4 = "search google for React authentication tutorial and open the first relevant result"
    plan4 = planner.plan(prompt4, session=session)
    assert plan4 is not None
    assert len(plan4.steps) == 2
    assert plan4.steps[0].tool == "browser.search_web"
    assert plan4.steps[1].tool == "browser.open_search_result"


def test_action_planner_contextual_memory_and_confirmation():
    planner = ActionPlanner()
    session = Session()

    # Turn 1: Open YouTube
    p1 = planner.plan("Open YouTube", session=session)
    assert p1 is not None

    # Turn 2: "Search for Arijit Singh" should understand YouTube context!
    p2 = planner.plan("Search for Arijit Singh", session=session)
    assert p2 is not None
    assert p2.intent == "contextual_youtube_search"
    assert p2.steps[0].tool == "browser.search_youtube"
    assert p2.steps[0].arguments["query"] == "Arijit Singh"

    # Turn 3: "Play the first one" should understand playing top YouTube result!
    p3 = planner.plan("Play the first one", session=session)
    assert p3 is not None
    assert p3.intent == "contextual_play_top_result"
    assert p3.steps[0].tool == "browser.play_media"

    # Confirmation flow
    # Ask to delete
    p_del = planner.plan("Delete the test folder", session=session)
    assert p_del.intent == "delete_requires_confirmation"

    # Confirm with "yes"
    p_confirm = planner.plan("Yes, please", session=session)
    assert p_confirm is not None
    assert p_confirm.intent == "confirmed_action"
    assert p_confirm.steps[0].tool == "filesystem.delete"
    assert p_confirm.steps[0].arguments["confirmed"] is True

    # Another confirmation flow with "no"
    planner.plan("Delete the test folder", session=session)
    p_cancel = planner.plan("No, stop", session=session)
    assert p_cancel is not None
    assert p_cancel.intent == "cancel_action"
    assert len(p_cancel.steps) == 0
