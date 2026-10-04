"""Unit tests for NotesController and NotesTool."""

import pytest

from lyra.computer.notes import NotesController
from lyra.models.tools import ToolRequest, ToolResult
from lyra.tools.notes_tool import NotesTool


def test_notes_controller_mock_lifecycle():
    controller = NotesController(use_mock=True)
    assert controller.is_available() is True
    assert controller.is_running() is True

    # 1. Open notes
    res_open = controller.open_notes()
    assert res_open["success"] is True
    assert res_open["action"] == "open_notes"

    # 2. Create note with title and body
    res_create = controller.create_note(body_text="Hello Boss", title="Greeting")
    assert res_create["success"] is True
    assert res_create["verified"] is True
    assert res_create["title"] == "Greeting"
    assert res_create["text"] == "Hello Boss"

    # 3. Verify content
    assert controller.verify_note_content("Hello Boss") is True
    assert controller.verify_note_content("Nonexistent text") is False

    # 4. Front note inspection
    front = controller.get_front_note_content()
    assert front["success"] is True
    assert front["body"] == "Hello Boss"


def test_notes_tool_can_handle_intents():
    tool = NotesTool(controller=NotesController(use_mock=True))

    # Pattern 1: "open Notes and write Hello Boss"
    h1 = tool.can_handle("Lyra, open Notes and write Hello Boss")
    assert h1 is not None
    assert h1["action"] == "write_note"
    assert h1["text"] == "Hello Boss"

    # Pattern 2: "create a note called Meeting and write Discuss roadmap"
    h2 = tool.can_handle("Create a note called Meeting and write Discuss roadmap")
    assert h2 is not None
    assert h2["action"] == "write_note"
    assert h2["title"] == "Meeting"
    assert h2["text"] == "Discuss roadmap"

    # Pattern 3: "write this in Notes: Hello Boss"
    h3 = tool.can_handle("Write this in Notes: Hello Boss")
    assert h3 is not None
    assert h3["action"] == "write_note"
    assert h3["text"] == "Hello Boss"

    # Pattern 4: "write Hello Boss in Notes"
    h4 = tool.can_handle("Write Hello Boss in Notes")
    assert h4 is not None
    assert h4["action"] == "write_note"
    assert h4["text"] == "Hello Boss"

    # Pattern 5: "open Notes"
    h5 = tool.can_handle("Lyra, open Notes")
    assert h5 is not None
    assert h5["action"] == "open_notes"


def test_notes_tool_execution_flow():
    import asyncio
    tool = NotesTool(controller=NotesController(use_mock=True))

    async def _run():
        req = ToolRequest(
            tool_name="notes",
            arguments={"action": "write_note", "text": "Hello Boss", "title": "Greeting"},
        )
        result = await tool.execute(req)
        assert result.success is True
        assert result.output["verified"] is True
        assert result.output["text"] == "Hello Boss"

        msg = tool.format_result(result)
        assert "Done, I wrote 'Hello Boss' in Notes." == msg

    asyncio.run(_run())


def test_notes_tool_failure_reporting():
    import asyncio
    controller = NotesController(use_mock=True)
    tool = NotesTool(controller=controller)

    async def _run():
        req = ToolRequest(tool_name="notes", arguments={"action": "write_note", "text": "", "title": ""})
        result = await tool.execute(req)
        assert result.success is False
        assert "Cannot create note without content or title" in str(result.error)

    asyncio.run(_run())
