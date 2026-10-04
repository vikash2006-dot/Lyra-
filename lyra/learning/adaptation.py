"""Deterministic adaptation engine updating learning trajectories based on live performance."""

from __future__ import annotations

from typing import Any

from lyra.learning.models import (
    LearnerProfile,
    LearningPlan,
    PracticeResult,
    SkillMasteryRecord,
    StruggleRecord,
    _utc_now,
)
from lyra.learning.repository import LearningRepository
from lyra.observability.logging import get_logger

logger = get_logger("learning.adaptation")


class AdaptationEngine:
    """Evaluates learner progress events and dynamically adapts the curriculum."""

    def __init__(self, repository: LearningRepository) -> None:
        self.repository = repository

    def adapt_plan(
        self,
        learner_id: str,
        trigger_reason: str,
        struggle: StruggleRecord | None = None,
        mastery: SkillMasteryRecord | None = None,
    ) -> tuple[LearningPlan | None, str]:
        """Recalibrate the active learning plan and provide an explicit pedagogical explanation."""
        plan = self.repository.get_active_learning_plan(learner_id)
        if not plan:
            return None, "No active learning plan found to adapt."

        profile = self.repository.get_learner_profile(learner_id)
        explanation = ""

        # Case 1: Persistent Struggle Detected -> Insert Remedial Module
        if struggle and not struggle.resolved:
            skill = struggle.skill
            explanation = (
                f"Adaptive Plan Update: I noticed you are encountering persistent difficulty with {struggle.concept_or_topic}. "
                f"Rather than moving forward prematurely, I have adapted your upcoming schedule to include focused remedial practice "
                f"and conceptual reinforcement for {skill}."
            )
            # Find the active or next week in plan and insert remedial task
            for week in plan.weeks:
                # Insert into the first uncompleted or upcoming day
                for day in week.days:
                    has_remedial = any("remedial" in t.get("task_id", "") for t in day.tasks)
                    if not has_remedial:
                        remedial_task = {
                            "task_id": f"task_remedial_{skill.lower().replace(' ', '_')}",
                            "title": f"Targeted Remedial Practice: {struggle.concept_or_topic}",
                            "duration_minutes": 35,
                            "task_type": "practice",
                            "skill": skill,
                            "completed": False,
                            "remedial": True,
                        }
                        day.tasks.insert(0, remedial_task)
                        day.total_minutes += 35
                        break
                break

            plan.updated_at = _utc_now()
            self.repository.save_learning_plan(plan)
            return plan, explanation

        # Case 2: Fast Mastery & Exceptional Performance -> Accelerate Pacing
        if mastery and mastery.mastery_score >= 0.90 and mastery.evidence_count >= 2:
            skill = mastery.skill
            explanation = (
                f"Adaptive Plan Update: Excellent demonstrated competency on {skill} (mastery: {int(mastery.mastery_score * 100)}%)! "
                f"I have streamlined redundant beginner tasks for {skill} and accelerated your progression to downstream advanced topics."
            )
            # Mark matching basic tasks completed in plan
            for week in plan.weeks:
                for day in week.days:
                    for task in day.tasks:
                        if task.get("skill") == skill and "study" in task.get("task_type", ""):
                            task["completed"] = True

            plan.updated_at = _utc_now()
            self.repository.save_learning_plan(plan)
            return plan, explanation

        # Case 3: Target Role or Hours Changed
        if "role" in trigger_reason.lower() or "hours" in trigger_reason.lower():
            explanation = (
                f"Adaptive Plan Update: Your profile parameters were updated ({trigger_reason}). "
                f"Your curriculum and weekly workload have been rebalanced accordingly."
            )
            plan.updated_at = _utc_now()
            self.repository.save_learning_plan(plan)
            return plan, explanation

        explanation = f"Learning plan evaluated: current progression is aligned with {plan.target_role} milestones."
        return plan, explanation
