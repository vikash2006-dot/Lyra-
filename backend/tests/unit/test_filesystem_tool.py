"""Unit tests for FilesystemTool: path safety, CRUD operations, confirmation, and formatting."""

import asyncio
from pathlib import Path
import pytest

from lyra.core.exceptions import ToolPermissionError, ToolValidationError
from lyra.models.tools import ToolRequest
from lyra.tools.filesystem import FilesystemTool, resolve_safe_path
from lyra.tools.permissions import ToolPermissionLevel


def test_filesystem_tool_metadata():
    tool = FilesystemTool()
    assert tool.name == "filesystem"
    assert tool.permission_level == ToolPermissionLevel.LOW_RISK
    schema = tool.input_schema
    assert "action" in schema["required"]
    actions = schema["properties"]["action"]["enum"]
    assert "create_directory" in actions
    assert "create_file" in actions
    assert "delete" in actions
    assert "open_path" in actions


def test_resolve_safe_path_expansion_and_boundaries(tmp_path: Path):
    # Empty path raises ToolValidationError
    with pytest.raises(ToolValidationError):
        resolve_safe_path("")

    # Tilde expansion
    home_dir = Path.home()
    resolved_home = resolve_safe_path("~")
    assert resolved_home == home_dir.resolve()

    # Desktop expansion
    resolved_desktop = resolve_safe_path("~/Desktop/MyFolder")
    assert resolved_desktop == (home_dir / "Desktop" / "MyFolder").resolve()

    # Forbidden system paths
    with pytest.raises(ToolPermissionError, match="protected"):
        resolve_safe_path("/etc/passwd")

    with pytest.raises(ToolPermissionError, match="protected"):
        resolve_safe_path("~/.ssh/id_rsa")

    with pytest.raises(ToolPermissionError, match="protected"):
        resolve_safe_path("~/.env")


def test_filesystem_tool_crud_lifecycle(tmp_path: Path):
    async def _test():
        tool = FilesystemTool(default_base_dir=tmp_path)
        folder = tmp_path / "Projects"
        file_path = folder / "notes.txt"

        # 1. Create Directory
        res_dir = await tool.execute(ToolRequest(
            tool_name="filesystem",
            arguments={"action": "create_directory", "path": str(folder)},
        ))
        assert res_dir.success
        assert folder.exists() and folder.is_dir()
        assert "Projects" in tool.format_result(res_dir)

        # 2. Create File
        res_file = await tool.execute(ToolRequest(
            tool_name="filesystem",
            arguments={"action": "create_file", "path": str(file_path), "content": "Hello LYRA"},
        ))
        assert res_file.success
        assert file_path.exists() and file_path.is_file()
        assert file_path.read_text(encoding="utf-8") == "Hello LYRA"

        # 3. Read File
        res_read = await tool.execute(ToolRequest(
            tool_name="filesystem",
            arguments={"action": "read_file", "path": str(file_path)},
        ))
        assert res_read.success
        assert "Hello LYRA" in res_read.output["content"]

        # 4. List Directory
        res_list = await tool.execute(ToolRequest(
            tool_name="filesystem",
            arguments={"action": "list_directory", "path": str(folder)},
        ))
        assert res_list.success
        names = [e["name"] for e in res_list.output["entries"]]
        assert "notes.txt" in names

        # 5. Rename File
        renamed_file = folder / "renamed_notes.txt"
        res_rename = await tool.execute(ToolRequest(
            tool_name="filesystem",
            arguments={"action": "rename", "path": str(file_path), "destination": str(renamed_file)},
        ))
        assert res_rename.success
        assert not file_path.exists()
        assert renamed_file.exists()

        # 6. Delete without confirmation fails and requests confirmation
        res_del_unconf = await tool.execute(ToolRequest(
            tool_name="filesystem",
            arguments={"action": "delete", "path": str(folder), "confirmed": False},
        ))
        assert not res_del_unconf.success
        assert res_del_unconf.metadata.get("requires_confirmation") is True
        assert folder.exists()  # Not deleted

        # 7. Delete with confirmed=True succeeds
        res_del_conf = await tool.execute(ToolRequest(
            tool_name="filesystem",
            arguments={"action": "delete", "path": str(folder), "confirmed": True},
        ))
        assert res_del_conf.success
        assert not folder.exists()

    asyncio.run(_test())


def test_filesystem_tool_can_handle():
    tool = FilesystemTool()

    # Create folder on desktop
    res_folder = tool.can_handle("Lyra, create a folder on my desktop named TestFolder")
    assert res_folder is not None
    assert res_folder["action"] == "create_directory"
    assert "TestFolder" in res_folder["path"]

    # Create file
    res_file = tool.can_handle("Create a file called notes.txt on my desktop")
    assert res_file is not None
    assert res_file["action"] == "create_file"
    assert "notes.txt" in res_file["path"]

    # Open folder
    res_open = tool.can_handle("Open my Desktop folder")
    assert res_open is not None
    assert res_open["action"] == "open_path"

    # Delete folder
    res_del = tool.can_handle("Delete the test folder")
    assert res_del is not None
    assert res_del["action"] == "delete"
    assert res_del["confirmed"] is False

    # Rename
    res_ren = tool.can_handle("Rename the College folder to University")
    assert res_ren is not None
    assert res_ren["action"] == "rename"
    assert "College" in res_ren["path"]
    assert "University" in res_ren["destination"]
