"""Unit tests for MemoryTool capability discovery, execution, and presentation."""

import asyncio
import pytest

from lyra.memory.manager import MemoryManager
from lyra.memory.policy import MemoryPolicy
from lyra.memory.sqlite_repository import SQLiteMemoryRepository
from lyra.models.tools import ToolRequest
from lyra.tools.memory_tool import MemoryTool
from lyra.tools.permissions import ToolPermissionLevel


@pytest.fixture
def memory_tool(tmp_path):
    db_file = str(tmp_path / "test_tool_memory.db")
    repo = SQLiteMemoryRepository(db_path=db_file)
    mgr = MemoryManager(repository=repo, policy=MemoryPolicy())
    tool = MemoryTool(memory_manager=mgr, default_user_id="alice")
    yield tool
    repo.close()


def test_memory_tool_metadata(memory_tool):
    assert memory_tool.name == "memory"
    assert memory_tool.permission_level == ToolPermissionLevel.LOW_RISK
    assert "action" in memory_tool.input_schema["required"]


def test_memory_tool_can_handle(memory_tool):
    # Remember intent
    res_rem = memory_tool.can_handle("Please remember that I prefer dark mode")
    assert res_rem is not None
    assert res_rem["action"] == "remember"
    assert "dark mode" in res_rem["content"]
    assert res_rem["memory_type"] == "preference"

    # List intent
    res_list = memory_tool.can_handle("What do you remember about me?")
    assert res_list is not None
    assert res_list["action"] == "list"

    # Search intent
    res_search = memory_tool.can_handle("Do you remember anything about coffee?")
    assert res_search is not None
    assert res_search["action"] == "search"
    assert res_search["query"] == "coffee"

    # Forget intent
    res_forget = memory_tool.can_handle("Forget that I drink coffee")
    assert res_forget is not None
    assert res_forget["action"] == "forget"
    assert res_forget["query"] == "i drink coffee"

    # Unrelated
    assert memory_tool.can_handle("What is the weather in Tokyo?") is None


def test_memory_tool_execution_flow(memory_tool):
    # 1. Remember action
    rem_req = ToolRequest(
        tool_name="memory",
        arguments={
            "action": "remember",
            "content": "Prefers mechanical keyboards with tactile switches",
            "memory_type": "preference",
            "user_id": "alice",
        },
    )
    rem_res = asyncio.run(memory_tool.execute(rem_req))
    assert rem_res.is_success()
    mem_id = rem_res.output["memory"]["id"]
    formatted = memory_tool.format_result(rem_res)
    assert "mechanical keyboards" in formatted

    # 2. List action
    list_req = ToolRequest(
        tool_name="memory",
        arguments={"action": "list", "user_id": "alice"},
    )
    list_res = asyncio.run(memory_tool.execute(list_req))
    assert list_res.is_success()
    assert list_res.output["count"] == 1
    list_text = memory_tool.format_result(list_res)
    assert "mechanical keyboards" in list_text

    # 3. Search action
    search_req = ToolRequest(
        tool_name="memory",
        arguments={"action": "search", "query": "tactile", "user_id": "alice"},
    )
    search_res = asyncio.run(memory_tool.execute(search_req))
    assert search_res.is_success()
    assert search_res.output["count"] == 1

    # 4. Forget action
    forget_req = ToolRequest(
        tool_name="memory",
        arguments={"action": "forget", "memory_id": mem_id, "user_id": "alice"},
    )
    forget_res = asyncio.run(memory_tool.execute(forget_req))
    assert forget_res.is_success()
    forget_text = memory_tool.format_result(forget_res)
    assert "removed that memory" in forget_text


def test_memory_tool_policy_rejection(memory_tool):
    rem_req = ToolRequest(
        tool_name="memory",
        arguments={
            "action": "remember",
            "content": "Secret password: mySuperSecretPassword123",
            "user_id": "alice",
        },
    )
    res = asyncio.run(memory_tool.execute(rem_req))
    assert not res.is_success()
    assert "sensitive" in res.error.lower()
