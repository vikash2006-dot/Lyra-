"""Unit tests for LYRA Learning Tools."""

import asyncio
from pathlib import Path
import tempfile
import pytest

from lyra.learning.models import LearnerProfile
from lyra.learning.repository import SQLiteLearningRepository
from lyra.learning.service import LearningService
from lyra.models.tools import ToolRequest
from lyra.tools.learning_tools import (
    DetectLearningStrugglesTool,
    GeneratePracticeTaskTool,
    GetLearnerProfileTool,
    GetLearningProgressTool,
    GetTodayLearningTasksTool,
    UpdateLearnerProfileTool,
    create_learning_tools,
)
from lyra.tools.permissions import ToolPermissionLevel


def test_tool_permission_levels() -> None:
    async def _runner() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = SQLiteLearningRepository(db_path=str(Path(tmpdir) / "tools_test.db"))
            service = LearningService(repository=repo)
            tools = create_learning_tools(service)
            tool_map = {t.name: t for t in tools}

            assert tool_map["get_learner_profile"].permission_level == ToolPermissionLevel.READ_ONLY
            assert tool_map["get_today_learning_tasks"].permission_level == ToolPermissionLevel.READ_ONLY
            assert tool_map["get_learning_progress"].permission_level == ToolPermissionLevel.READ_ONLY
            assert tool_map["detect_learning_struggles"].permission_level == ToolPermissionLevel.READ_ONLY
            assert tool_map["update_learner_profile"].permission_level == ToolPermissionLevel.LOW_RISK
            assert tool_map["generate_learning_plan"].permission_level == ToolPermissionLevel.LOW_RISK
    asyncio.run(_runner())


def test_can_handle_natural_language_queries() -> None:
    async def _runner() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = SQLiteLearningRepository(db_path=str(Path(tmpdir) / "tools_test.db"))
            service = LearningService(repository=repo)
            tools = create_learning_tools(service)
            tool_map = {t.name: t for t in tools}

            # "what should I study today"
            today_tool = tool_map["get_today_learning_tasks"]
            assert today_tool.can_handle("What should I study today?") is not None

            # "give me a practice problem"
            practice_tool = tool_map["generate_practice_task"]
            assert practice_tool.can_handle("Give me a practice problem") is not None

            # "how am I progressing"
            progress_tool = tool_map["get_learning_progress"]
            assert progress_tool.can_handle("How am I progressing?") is not None

            # "what am I weak at"
            struggles_tool = tool_map["detect_learning_struggles"]
            assert struggles_tool.can_handle("What am I weak at?") is not None
    asyncio.run(_runner())


def test_update_profile_and_today_tasks_execution() -> None:
    async def _runner() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = SQLiteLearningRepository(db_path=str(Path(tmpdir) / "tools_test.db"))
            service = LearningService(repository=repo)
            tools = create_learning_tools(service)
            tool_map = {t.name: t for t in tools}

            update_tool = tool_map["update_learner_profile"]
            req = ToolRequest(
                tool_name=update_tool.name,
                arguments={"user_input": "I want to become a Backend Developer and I can study 8 hours per week."},
                user_id="u_tool_test",
            )
            res = await update_tool.execute(req)
            assert res.is_success()
            assert res.output["profile"]["target_role"] == "Backend Developer"
            assert res.output["plan_created"] is True

            # Now get today's tasks
            today_tool = tool_map["get_today_learning_tasks"]
            req_today = ToolRequest(tool_name=today_tool.name, arguments={}, user_id="u_tool_test")
            res_today = await today_tool.execute(req_today)
            assert res_today.is_success()
            assert res_today.output["has_plan"] is True
            assert len(res_today.output["tasks"]) >= 1
    asyncio.run(_runner())
