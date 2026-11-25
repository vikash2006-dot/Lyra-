"""Personalized Weekly Learning Planner respecting strict learner time budgets."""

from __future__ import annotations

import math
from typing import Any
import uuid

from lyra.learning.models import (
    DailyPlan,
    LearnerProfile,
    LearningObjective,
    LearningPlan,
    WeekPlan,
    _utc_now,
)
from lyra.learning.repository import LearningRepository
from lyra.observability.logging import get_logger

logger = get_logger("learning.planner")


class WeeklyPlanner:
    """Generates structured, time-bounded weekly schedules aligned with learner goals."""

    def __init__(self, repository: LearningRepository) -> None:
        self.repository = repository

    def generate_plan(
        self,
        profile: LearnerProfile,
        objectives: list[LearningObjective],
        duration_weeks: int = 8,
    ) -> LearningPlan:
        """Create a personalized curriculum strictly budgeted by weekly learning hours."""
        weekly_hours = max(1.0, profile.weekly_learning_hours or 8.0)
        total_weekly_minutes = int(weekly_hours * 60)
        target_role = profile.target_role or "Backend Developer"

        # Days distribution: Mon - Sun (7 days)
        # Allocate roughly: 5 study/practice days + 1 revision day + 1 review day
        days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        daily_target_minutes = max(20, total_weekly_minutes // 6)

        weeks: list[WeekPlan] = []
        obj_pool = list(objectives)
        obj_index = 0

        for w in range(1, duration_weeks + 1):
            # Select 1-2 core skills/objectives for this week
            week_objectives: list[LearningObjective] = []
            if obj_pool:
                while obj_index < len(obj_pool) and len(week_objectives) < 2:
                    week_objectives.append(obj_pool[obj_index])
                    obj_index += 1
                if not week_objectives:
                    # Loop back or consolidate previous
                    week_objectives.append(obj_pool[w % len(obj_pool)])
            else:
                week_objectives.append(
                    LearningObjective(
                        id=f"obj_week_{w}",
                        skill=f"Core Competencies Sprint {w}",
                        title=f"Advanced Applications in {target_role}",
                        description="Deepen practical project execution and system design.",
                    )
                )

            primary_skill = week_objectives[0].skill
            theme = f"Week {w}: {primary_skill} Mastery"
            milestone = f"Complete practical implementation and verification for {primary_skill}"

            daily_plans: list[DailyPlan] = []
            for day_idx, day_name in enumerate(days_of_week):
                tasks: list[dict[str, Any]] = []
                obj_titles = [o.title for o in week_objectives]

                if day_name in ("Monday", "Tuesday", "Wednesday", "Thursday"):
                    study_mins = int(daily_target_minutes * 0.55)
                    practice_mins = daily_target_minutes - study_mins
                    tasks.append({
                        "task_id": f"task_w{w}_d{day_idx+1}_study",
                        "title": f"Study {primary_skill} fundamentals & patterns",
                        "duration_minutes": study_mins,
                        "task_type": "study",
                        "skill": primary_skill,
                        "completed": False,
                    })
                    tasks.append({
                        "task_id": f"task_w{w}_d{day_idx+1}_practice",
                        "title": f"Hands-on coding exercise: {primary_skill}",
                        "duration_minutes": practice_mins,
                        "task_type": "practice",
                        "skill": primary_skill,
                        "completed": False,
                    })
                elif day_name == "Friday":
                    tasks.append({
                        "task_id": f"task_w{w}_d5_mini_project",
                        "title": f"Mini-project integration: Apply {primary_skill}",
                        "duration_minutes": daily_target_minutes,
                        "task_type": "project",
                        "skill": primary_skill,
                        "completed": False,
                    })
                elif day_name == "Saturday":
                    rev_mins = int(daily_target_minutes * 0.5)
                    tasks.append({
                        "task_id": f"task_w{w}_d6_revision",
                        "title": f"Revision & Self-Assessment: {primary_skill}",
                        "duration_minutes": rev_mins,
                        "task_type": "revision",
                        "skill": primary_skill,
                        "completed": False,
                    })
                elif day_name == "Sunday":
                    tasks.append({
                        "task_id": f"task_w{w}_d7_progress_review",
                        "title": "Weekly Progress & Adaptation Review with LYRA",
                        "duration_minutes": min(30, daily_target_minutes),
                        "task_type": "assessment",
                        "skill": primary_skill,
                        "completed": False,
                    })

                day_total = sum(t["duration_minutes"] for t in tasks)
                daily_plans.append(
                    DailyPlan(
                        day=day_name,
                        objectives=obj_titles,
                        tasks=tasks,
                        total_minutes=day_total,
                    )
                )

            week_total_mins = sum(d.total_minutes for d in daily_plans)
            weeks.append(
                WeekPlan(
                    week_number=w,
                    theme=theme,
                    days=daily_plans,
                    target_weekly_minutes=week_total_mins,
                    milestone=milestone,
                )
            )

        plan_id = f"plan_{profile.learner_id}_{uuid.uuid4().hex[:8]}"
        plan = LearningPlan(
            plan_id=plan_id,
            learner_id=profile.learner_id,
            target_role=target_role,
            duration_weeks=duration_weeks,
            weekly_hours=weekly_hours,
            weeks=weeks,
            objectives=[o.title for o in objectives],
            milestones=[w.milestone for w in weeks],
            created_at=_utc_now(),
            updated_at=_utc_now(),
            status="active",
        )

        self.repository.save_learning_plan(plan)
        profile.current_learning_plan_id = plan_id
        self.repository.save_learner_profile(profile)

        logger.info(
            "Created %d-week plan (%g hrs/week) for learner '%s' (plan_id: %s)",
            duration_weeks,
            weekly_hours,
            profile.learner_id,
            plan_id,
        )
        return plan
