"""Unit tests for LearningService coordination, memory sync, and telemetry."""

import asyncio
from pathlib import Path
import tempfile
import pytest

from lyra.learning.models import (
    ObjectiveStatus,
    SkillLevel,
)
from lyra.learning.repository import SQLiteLearningRepository
from lyra.learning.service import LearningService
from lyra.memory.manager import MemoryManager
from lyra.memory.policy import MemoryPolicy
from lyra.memory.sqlite_repository import SQLiteMemoryRepository


def test_learning_service_onboarding_and_memory_sync() -> None:
    async def _runner() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            learn_db = str(Path(tmpdir) / "learn.db")
            mem_db = str(Path(tmpdir) / "mem.db")

            mem_repo = SQLiteMemoryRepository(db_path=mem_db)
            mem_manager = MemoryManager(repository=mem_repo, policy=MemoryPolicy())
            learn_repo = SQLiteLearningRepository(db_path=learn_db)

            service = LearningService(
                repository=learn_repo,
                memory_manager=mem_manager,
                db_path=learn_db,
            )

            user_id = "test_learner_42"

            # 1. Process intake text
            extracted = service.process_intake(
                user_id,
                "I want to become a Backend Developer. I know JavaScript and basic SQL. I can study 8 hours per week.",
            )
            assert extracted["target_role"] == "Backend Developer"
            assert extracted["weekly_learning_hours"] == 8.0
            assert "JavaScript" in extracted["skills"]

            # 2. Check MemoryManager sync
            memories = mem_manager.list_memories(user_id=user_id)
            assert len(memories) >= 1
            content_blob = " ".join(m.content for m in memories)
            assert "Backend Developer" in content_blob

            # 3. Gap analysis
            gaps = service.analyze_gaps(user_id)
            assert len(gaps) > 0
            gap_skills = [g.skill for g in gaps]
            assert "HTTP Basics" in gap_skills
            assert "REST APIs" in gap_skills

            # 4. Create Plan
            plan = await service.create_learning_plan(user_id, duration_weeks=8)
            assert plan.duration_weeks == 8
            assert plan.weekly_hours == 8.0

            # 5. Fast-path today tasks
            today = service.get_today_tasks(user_id)
            assert today["has_plan"] is True
            assert len(today["tasks"]) >= 1

            # 6. Mark task complete
            first_tid = today["tasks"][0]["task_id"]
            completed = service.mark_task_complete(user_id, first_tid)
            assert completed is True

            # 7. Progress report
            report = service.get_progress_report(user_id)
            assert report.target_role == "Backend Developer"
            assert len(report.remaining_gaps) >= 1

    asyncio.run(_runner())
