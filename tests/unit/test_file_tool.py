"""Unit tests for FileTool capability discovery, execution, and safety."""

import asyncio
from pathlib import Path
import pytest

from lyra.models.tools import ToolRequest
from lyra.tools.file_tool import FileTool
from lyra.tools.permissions import ToolPermissionLevel


def test_file_tool_metadata():
    tool = FileTool()
    assert tool.name == "file"
    assert tool.permission_level == ToolPermissionLevel.READ_ONLY
    assert "file_path" in tool.input_schema["required"]


def test_file_tool_execution_success(tmp_path: Path):
    doc = tmp_path / "hello.txt"
    doc.write_text("Hello from file tool!", encoding="utf-8")

    tool = FileTool()
    req = ToolRequest(tool_name="file", arguments={"file_path": str(doc)})
    res = asyncio.run(tool.execute(req))

    assert res.is_success()
    assert res.output["filename"] == "hello.txt"
    assert "Hello from file tool!" in res.output["raw_text"]
    assert '<untrusted_external_content source="filehellotxt">' in res.output["content"]


    formatted = tool.format_result(res)
    assert "Hello from file tool!" in formatted


def test_file_tool_execution_missing_file(tmp_path: Path):
    tool = FileTool()
    req = ToolRequest(tool_name="file", arguments={"file_path": str(tmp_path / "ghost.txt")})
    res = asyncio.run(tool.execute(req))

    assert not res.is_success()
    assert "File not found" in res.error


def test_file_tool_execution_blocks_executable(tmp_path: Path):
    bad = tmp_path / "script.sh"
    bad.write_text("#!/bin/bash\necho bad", encoding="utf-8")

    tool = FileTool()
    req = ToolRequest(tool_name="file", arguments={"file_path": str(bad)})
    res = asyncio.run(tool.execute(req))

    assert not res.is_success()
    assert "blocked" in res.error.lower()


def test_file_tool_can_handle():
    tool = FileTool()
    assert tool.can_handle("read file /path/to/notes.md") == {"file_path": "/path/to/notes.md"}
    assert tool.can_handle("cat file data.csv") == {"file_path": "data.csv"}
    assert tool.can_handle("what is the weather today?") is None
