"""High-level LearningService unifying the Adaptive Learning Agent subsystems."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import uuid

from lyra.learning.adaptation import AdaptationEngine
from lyra.learning.document_analyzer import DocumentAnalyzer
from lyra.learning.gap_analyzer import SkillGapAnalyzer
from lyra.learning.mastery import MasteryEngine
from lyra.learning.models import (
    ActivityType,
    LearnerProfile,
    LearningActivity,
    LearningObjective,
    LearningPlan,
    LearningResource,
    PracticeResult,
    PracticeTask,
    ProgressReport,
    ProjectSpecification,
    SkillGap,
    SkillLevel,
    SkillMasteryRecord,
    StruggleRecord,
    TaskType,
    _utc_now,
)
from lyra.learning.objective_engine import ObjectiveEngine
from lyra.learning.planner import WeeklyPlanner
from lyra.learning.practice import PracticeEngine
from lyra.learning.profile import LearnerProfileManager
from lyra.learning.progress import ProgressReportGenerator
from lyra.learning.project_generator import ProjectGenerator
from lyra.learning.repository import LearningRepository, SQLiteLearningRepository
from lyra.learning.resource_recommender import ResourceRecommender
from lyra.learning.skill_engine import SkillEngine
from lyra.learning.struggle_detector import StruggleDetector
from lyra.memory.manager import MemoryManager
from lyra.observability.logging import get_logger
from lyra.routing.router import ModelRouter
from lyra.tools.registry import ToolRegistry

logger = get_logger("learning.service")


class LearningService:
    """Unified façade orchestrating profiles, gaps, plans, practice, telemetry, and adaptation."""

    def __init__(
        self,
        repository: LearningRepository | None = None,
        router: ModelRouter | None = None,
        tool_registry: ToolRegistry | None = None,
        memory_manager: MemoryManager | None = None,
        db_path: str = "lyra_learning.db",
    ) -> None:
        self.repository = repository or SQLiteLearningRepository(db_path=db_path)
        self.router = router
        self.tool_registry = tool_registry
        self.memory_manager = memory_manager

        # Subsystems
        self.skill_engine = SkillEngine(repository=self.repository)
        self.profile_manager = LearnerProfileManager(
            repository=self.repository,
            memory_manager=self.memory_manager,
        )
        self.document_analyzer = DocumentAnalyzer(
            repository=self.repository,
            router=self.router,
        )
        self.gap_analyzer = SkillGapAnalyzer(
            repository=self.repository,
            skill_engine=self.skill_engine,
        )
        self.objective_engine = ObjectiveEngine(
            repository=self.repository,
            router=self.router,
        )
        self.resource_recommender = ResourceRecommender(
            tool_registry=self.tool_registry,
        )
        self.planner = WeeklyPlanner(repository=self.repository)
        self.practice_engine = PracticeEngine(
            repository=self.repository,
            router=self.router,
        )
        self.project_generator = ProjectGenerator(router=self.router)
        self.mastery_engine = MasteryEngine(repository=self.repository)
        self.struggle_detector = StruggleDetector(repository=self.repository)
        self.adaptation_engine = AdaptationEngine(repository=self.repository)
        self.progress_generator = ProgressReportGenerator(repository=self.repository)

    # 1. Profile Management & Intake
    def get_profile(self, learner_id: str) -> LearnerProfile:
        return self.profile_manager.get_or_create_profile(learner_id)

    def update_profile(self, profile: LearnerProfile) -> None:
        self.profile_manager.update_profile(profile)

    def process_intake(self, learner_id: str, user_text: str) -> dict[str, Any]:
        profile = self.get_profile(learner_id)
        extracted = self.profile_manager.parse_conversational_intake(user_text, profile)
        return extracted

    # 2. Document & Resume Analysis
    async def analyze_document(self, learner_id: str, file_path: str | Path) -> dict[str, Any]:
        profile = self.get_profile(learner_id)
        result = await self.document_analyzer.analyze_document(file_path, profile)
        return result

    # 3. Gap Analysis
    def analyze_gaps(self, learner_id: str, target_role_name: str | None = None) -> list[SkillGap]:
        profile = self.get_profile(learner_id)
        if target_role_name:
            profile.target_role = target_role_name
            self.update_profile(profile)
        role = self.skill_engine.get_target_role(profile.target_role or target_role_name or "Backend Developer")
        return self.gap_analyzer.analyze_gaps(profile, target_role=role)

    # 4. Objectives & Curriculum Generation
    async def generate_objectives(self, learner_id: str) -> list[LearningObjective]:
        gaps = self.analyze_gaps(learner_id)
        return await self.objective_engine.generate_objectives_for_gaps(learner_id, gaps)

    # 5. Resource Recommendation
    async def recommend_resources_for_skill(self, skill_name: str, max_results: int = 3) -> list[LearningResource]:
        dummy_obj = LearningObjective(
            id="temp_obj",
            skill=skill_name,
            title=f"Mastery of {skill_name}",
            description="",
            difficulty=SkillLevel.BEGINNER,
        )
        return await self.resource_recommender.recommend_resources(dummy_obj, max_results=max_results)

    # 6. Learning Plan Lifecycle
    async def create_learning_plan(self, learner_id: str, duration_weeks: int = 8) -> LearningPlan:
        profile = self.get_profile(learner_id)
        objectives = await self.generate_objectives(learner_id)
        plan = self.planner.generate_plan(profile, objectives, duration_weeks=duration_weeks)
        return plan

    def get_active_plan(self, learner_id: str) -> LearningPlan | None:
        return self.repository.get_active_learning_plan(learner_id)

    # 7. Today's Learning Tasks (Fast Path)
    def get_today_tasks(self, learner_id: str) -> dict[str, Any]:
        plan = self.get_active_plan(learner_id)
        if not plan or not plan.weeks:
            return {
                "has_plan": False,
                "message": "No active learning plan found. Tell me your target role to generate one!",
                "tasks": [],
            }
        current_week = plan.weeks[0]
        # Find current day
        current_day = next((d for d in current_week.days if any(not t.get("completed") for t in d.tasks)), current_week.days[0])
        return {
            "has_plan": True,
            "target_role": plan.target_role,
            "week_number": current_week.week_number,
            "day": current_day.day,
            "tasks": current_day.tasks,
            "total_minutes": current_day.total_minutes,
        }

    # 8. Practice & Assessment Loop
    def generate_practice_task(
        self,
        learner_id: str,
        skill: str | None = None,
        weakness_focus: str | None = None,
    ) -> PracticeTask:
        profile = self.get_profile(learner_id)
        target_skill = skill
        if not target_skill:
            # Pick from active struggle or highest priority gap
            struggles = self.repository.get_active_struggles(learner_id)
            if struggles:
                target_skill = struggles[0].skill
                weakness_focus = struggles[0].concept_or_topic
            else:
                gaps = self.repository.get_skill_gaps(learner_id)
                target_skill = gaps[0].skill if gaps else "REST APIs"

        task = self.practice_engine.generate_task(
            skill=target_skill,
            level=profile.get_effective_level(target_skill) or SkillLevel.BEGINNER,
            weakness_focus=weakness_focus,
        )
        return task

    async def submit_practice(
        self,
        learner_id: str,
        task: PracticeTask,
        submission: str,
    ) -> dict[str, Any]:
        """Evaluate submission, update telemetry, check struggles, and trigger adaptation."""
        # 1. Evaluate
        result = await self.practice_engine.evaluate_submission(task, learner_id, submission)

        # 2. Record Activity
        act = LearningActivity(
            activity_id=f"act_{uuid.uuid4().hex[:8]}",
            learner_id=learner_id,
            type=ActivityType.PRACTICE,
            skill=task.skill,
            started_at=_utc_now(),
            completed_at=_utc_now(),
            duration_minutes=15,
            score=result.score,
            difficulty=task.level,
            result="Passed" if result.passed else "Failed",
            mistakes=result.mistakes,
            notes=result.feedback,
        )
        self.repository.record_activity(act)

        # 3. Update Mastery
        mastery = self.mastery_engine.update_from_practice_result(result)

        # 4. Detect Struggles
        struggle = self.struggle_detector.analyze_practice_performance(learner_id, task.skill)

        # 5. Adapt Plan if necessary
        plan, adaptation_msg = self.adaptation_engine.adapt_plan(
            learner_id=learner_id,
            trigger_reason=f"Practice task evaluation: {task.skill}",
            struggle=struggle,
            mastery=mastery,
        )

        return {
            "result": result,
            "mastery": mastery,
            "struggle_detected": struggle is not None,
            "struggle": struggle,
            "adaptation_message": adaptation_msg,
        }

    # 9. Project Generation
    def generate_project(
        self,
        learner_id: str,
        difficulty: SkillLevel | None = None,
    ) -> ProjectSpecification:
        profile = self.get_profile(learner_id)
        return self.project_generator.generate_project(profile, difficulty=difficulty)

    # 10. Progress Reports
    def get_progress_report(self, learner_id: str) -> ProgressReport:
        return self.progress_generator.generate_report(learner_id)

    # 11. Task Completion
    def mark_task_complete(self, learner_id: str, task_id: str) -> bool:
        plan = self.get_active_plan(learner_id)
        if not plan:
            return False
        found = False
        completed_skill = "General"
        for w in plan.weeks:
            for d in w.days:
                for t in d.tasks:
                    if t.get("task_id") == task_id or task_id.lower() in t.get("title", "").lower():
                        t["completed"] = True
                        found = True
                        completed_skill = t.get("skill", "General")
                        break
        if found:
            self.repository.save_learning_plan(plan)
            # Record activity
            act = LearningActivity(
                activity_id=f"act_comp_{uuid.uuid4().hex[:8]}",
                learner_id=learner_id,
                type=ActivityType.STUDY,
                skill=completed_skill,
                started_at=_utc_now(),
                completed_at=_utc_now(),
                duration_minutes=30,
                score=1.0,
                difficulty=SkillLevel.BEGINNER,
                result="Completed",
                notes=f"Marked task {task_id} complete",
            )
            self.repository.record_activity(act)
        return found
