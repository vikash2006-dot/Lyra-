"""Real-World Acceptance Test implementing Section 31 end-to-end scenario."""

import asyncio
from pathlib import Path
import tempfile
import pytest

from lyra.learning.models import ObjectiveStatus, SkillLevel
from lyra.learning.repository import SQLiteLearningRepository
from lyra.learning.service import LearningService
from lyra.memory.manager import MemoryManager
from lyra.memory.policy import MemoryPolicy
from lyra.memory.sqlite_repository import SQLiteMemoryRepository
from lyra.models.tools import ToolRequest
from lyra.tools.learning_tools import create_learning_tools


def test_real_world_acceptance_scenario() -> None:
    """Executes the exact 20-step real-world acceptance workflow from Section 31."""
    async def _runner() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            learn_db = str(Path(tmpdir) / "accept_learn.db")
            mem_db = str(Path(tmpdir) / "accept_mem.db")

            mem_repo = SQLiteMemoryRepository(db_path=mem_db)
            mem_manager = MemoryManager(repository=mem_repo, policy=MemoryPolicy())
            learn_repo = SQLiteLearningRepository(db_path=learn_db)

            service = LearningService(
                repository=learn_repo,
                memory_manager=mem_manager,
                db_path=learn_db,
            )
            tools = create_learning_tools(service)
            tool_map = {t.name: t for t in tools}

            learner_id = "real_world_learner"

            # =========================================================================
            # PHASE 1: User Onboarding Statement
            # "I want to become a backend developer. I know JavaScript and basic MongoDB.
            #  I have built one small Node.js project. I can study 8 hours per week."
            # =========================================================================
            intake_statement = (
                "I want to become a backend developer. I know JavaScript and basic MongoDB. "
                "I have built one small Node.js project. I can study 8 hours per week."
            )

            update_tool = tool_map["update_learner_profile"]
            onboarding_res = await update_tool.execute(
                ToolRequest(
                    tool_name=update_tool.name,
                    arguments={"user_input": intake_statement},
                    user_id=learner_id,
                )
            )
            assert onboarding_res.is_success()
            out = onboarding_res.output

            # 1. Create/update learner profile
            profile = service.get_profile(learner_id)
            assert profile is not None

            # 2. Set target role
            assert profile.target_role == "Backend Developer"
            assert profile.weekly_learning_hours == 8.0

            # 3. Analyze current capabilities
            assert "JavaScript" in profile.current_skills
            assert "Mongodb" in [s.title() for s in profile.current_skills]
            assert len(profile.projects_completed) >= 1

            # 4. Identify missing backend skills
            gaps = service.analyze_gaps(learner_id)
            assert len(gaps) > 0
            gap_names = [g.skill for g in gaps]
            assert "HTTP Basics" in gap_names
            assert "REST APIs" in gap_names
            assert "SQL Fundamentals" in gap_names
            assert "SQL Joins & Relational Queries" in gap_names
            assert "API Authentication & Security" in gap_names

            # 5. Prioritize skill gaps (Prerequisite topological order: HTTP before REST before Auth)
            http_idx = gap_names.index("HTTP Basics")
            rest_idx = gap_names.index("REST APIs")
            auth_idx = gap_names.index("API Authentication & Security")
            assert http_idx < rest_idx < auth_idx

            # 6. Create learning objectives
            objs = await service.generate_objectives(learner_id)
            assert len(objs) >= 5

            # 7. Recommend resources
            resources = await service.recommend_resources_for_skill("REST APIs")
            assert len(resources) >= 1
            assert any("http" in r.url for r in resources)

            # 8. Generate an 8-hour/week learning plan
            plan = service.get_active_plan(learner_id)
            assert plan is not None
            assert plan.duration_weeks == 8
            assert plan.weekly_hours == 8.0
            # Check weekly hour bounding (approx 480 min, not 15 hours!)
            assert plan.weeks[0].target_weekly_minutes <= 550

            # 9. Generate today's task
            today = service.get_today_tasks(learner_id)
            assert today["has_plan"] is True
            assert len(today["tasks"]) >= 1

            # 10. Generate a practice task
            practice = service.generate_practice_task(learner_id, skill="REST APIs")
            assert practice is not None
            assert practice.skill == "REST APIs"
            assert len(practice.prompt) > 10

            # =========================================================================
            # PHASE 2: User completes today's task successfully
            # =========================================================================
            today_task_id = today["tasks"][0]["task_id"]
            completed = service.mark_task_complete(learner_id, today_task_id)

            # 11. Record the activity
            assert completed is True
            activities = service.repository.list_activities(learner_id)
            assert any(a.type.value == "study" for a in activities)

            # 12. Update mastery (Simulate successful practice task submission)
            eval_result = await service.submit_practice(
                learner_id=learner_id,
                task=practice,
                submission="async def create_item(payload: dict):\n    if not payload.get('title'): raise HTTPException(400)\n    return {'status': 'created'}, 201",
            )
            assert eval_result["result"].passed is True

            # 13. Recalculate relevant gaps
            updated_mastery = service.mastery_engine.calculate_mastery(learner_id, "REST APIs")
            assert updated_mastery.mastery_score > 0.5

            # 14. Update future plan if necessary
            updated_plan = service.get_active_plan(learner_id)
            assert updated_plan is not None

            # =========================================================================
            # PHASE 3: User fails three SQL JOIN exercises
            # =========================================================================
            join_task = service.practice_engine.generate_task("SQL Joins & Relational Queries", level=SkillLevel.ELEMENTARY)
            for i in range(3):
                eval_join = await service.submit_practice(
                    learner_id=learner_id,
                    task=join_task,
                    submission="SELECT * FROM customers c INNER JOIN orders o ON c.id = o.customer_id; -- wrong join type",
                )
                assert eval_join["result"].passed is False

            # 15. Detect SQL JOIN as a struggle
            struggles = service.repository.get_active_struggles(learner_id)
            assert len(struggles) >= 1
            join_struggle = next(s for s in struggles if "join" in s.skill.lower())
            assert join_struggle.consecutive_failures == 3

            # 16. Record the repeated weakness
            prof_after = service.get_profile(learner_id)
            assert any("join" in w.lower() for w in prof_after.weak_topics)

            # 17. Generate targeted remedial learning & 18. Add additional SQL practice
            assert any("remedial" in act.lower() for act in join_struggle.remedial_actions_taken)

            # 19. Adjust the plan & 20. Explain the reason for the change
            assert "remedial practice" in eval_join["adaptation_message"].lower()

            # Check adapted plan contains remedial task
            adapted_plan = service.get_active_plan(learner_id)
            remedial_tasks = [
                t for w in adapted_plan.weeks for d in w.days for t in d.tasks if t.get("remedial") is True
            ]
            assert len(remedial_tasks) >= 1

            # =========================================================================
            # PHASE 4: User asks: "What should I learn next?"
            # =========================================================================
            answer_tool = tool_map["answer_learning_question"]
            ans_res = await answer_tool.execute(
                ToolRequest(
                    tool_name=answer_tool.name,
                    arguments={"question": "What should I learn next?"},
                    user_id=learner_id,
                )
            )
            assert ans_res.is_success()
            ans_text = str(ans_res.output["answer"])
            assert "next" in ans_text.lower()
            # Answers truthfully from updated learner state
            assert len(ans_res.output.get("topic", "")) > 0

    asyncio.run(_runner())
