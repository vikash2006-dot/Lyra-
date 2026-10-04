"""Unit tests for folder structure parsing, creation, and verification in FilesystemTool."""

from pathlib import Path
import pytest
import tempfile

from lyra.models.tools import ToolRequest
from lyra.tools.filesystem import FilesystemTool, parse_folder_structure


def test_parse_folder_structure_formats():
    # 1. Natural language comma/and list
    res1 = parse_folder_structure("with src, tests and docs", root_name="Project")
    assert "Project" in res1
    assert "Project/src" in res1
    assert "Project/tests" in res1
    assert "Project/docs" in res1

    # 2. Inside X create Y, Z
    res2 = parse_folder_structure("Projects, Notes and Documents", root_name="College")
    assert "College/Projects" in res2
    assert "College/Notes" in res2
    assert "College/Documents" in res2

    # 3. Indented tree
    tree = """
MyProject/
    src/
    tests/
    docs/
    assets/
"""
    res3 = parse_folder_structure(tree)
    assert "MyProject" in res3
    assert "MyProject/src" in res3
    assert "MyProject/tests" in res3
    assert "MyProject/docs" in res3
    assert "MyProject/assets" in res3

    # 4. Relative paths list
    paths = """
src
src/tools
src/browser
src/system
tests
"""
    res4 = parse_folder_structure(paths)
    assert res4 == ["src", "src/tools", "src/browser", "src/system", "tests"]


def test_filesystem_tool_create_structure_execution():
    import asyncio

    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            tool = FilesystemTool(default_base_dir=base_dir)

            req = ToolRequest(
                tool_name="filesystem",
                arguments={
                    "action": "create_structure",
                    "base_path": str(base_dir),
                    "root_name": "MyProject",
                    "structure": "with src, tests, docs and main.py",
                },
            )
            result = await tool.execute(req)
            assert result.success is True
            assert result.output["verified"] is True
            assert result.output["count"] >= 4

            # Real verification on filesystem
            assert (base_dir / "MyProject").is_dir()
            assert (base_dir / "MyProject" / "src").is_dir()
            assert (base_dir / "MyProject" / "tests").is_dir()
            assert (base_dir / "MyProject" / "docs").is_dir()
            assert (base_dir / "MyProject" / "main.py").is_file()

            # Formatting
            msg = tool.format_result(result)
            assert "Done, I created the MyProject folder structure" in msg

    asyncio.run(_run())
