"""Unit tests for VisionTool capability discovery and safe image loading."""

import asyncio
from pathlib import Path
import pytest

from lyra.models.tools import ToolRequest
from lyra.tools.permissions import ToolPermissionLevel
from lyra.tools.vision_tool import VisionTool


def test_vision_tool_metadata():
    tool = VisionTool()
    assert tool.name == "vision"
    assert tool.permission_level == ToolPermissionLevel.READ_ONLY
    assert "image_path" in tool.input_schema["required"]


def test_vision_tool_execution_success(tmp_path: Path):
    img_path = tmp_path / "photo.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\nfakeimagecontent")

    tool = VisionTool()
    req = ToolRequest(tool_name="vision", arguments={"image_path": str(img_path)})
    res = asyncio.run(tool.execute(req))

    assert res.is_success()
    assert res.output["image_path"] == str(img_path)
    assert res.output["mime_type"] == "image/png"
    assert "image_part" in res.metadata

    formatted = tool.format_result(res)
    assert "Successfully loaded image" in formatted


def test_vision_tool_execution_missing_image(tmp_path: Path):
    tool = VisionTool()
    req = ToolRequest(tool_name="vision", arguments={"image_path": str(tmp_path / "missing.jpg")})
    res = asyncio.run(tool.execute(req))

    assert not res.is_success()
    assert "File not found" in res.error


def test_vision_tool_can_handle():
    tool = VisionTool()
    handled = tool.can_handle("inspect image /tmp/photo.jpg")
    assert handled is not None
    assert handled["image_path"] == "/tmp/photo.jpg"

    assert tool.can_handle("tell me the time") is None
