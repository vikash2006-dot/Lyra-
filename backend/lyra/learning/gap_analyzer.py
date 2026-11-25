"""Skill Gap Analysis and Prerequisite-Driven Prioritization Engine."""

from __future__ import annotations

from typing import Any

from lyra.learning.models import (
    LearnerProfile,
    SkillGap,
    SkillLevel,
    TargetRole,
)
from lyra.learning.repository import LearningRepository
from lyra.learning.skill_engine import SkillEngine
from lyra.observability.logging import get_logger

logger = get_logger("learning.gap_analyzer")


class SkillGapAnalyzer:
    """Computes differences between learner competencies and target role expectations."""

    def __init__(
        self,
        repository: LearningRepository,
        skill_engine: SkillEngine,
    ) -> None:
        self.repository = repository
        self.skill_engine = skill_engine

    def analyze_gaps(
        self,
        profile: LearnerProfile,
        target_role: TargetRole | None = None,
    ) -> list[SkillGap]:
        """Perform comprehensive gap analysis and prioritize learning objectives."""
        role_name = (target_role.role_name if target_role else profile.target_role) or "Backend Developer"
        role = target_role or self.skill_engine.get_target_role(role_name)

        if not role:
            # Create a dynamic fallback target role if not in registry
            role = TargetRole(
                role_name=role_name,
                required_skills={
                    "HTTP Basics": SkillLevel.INTERMEDIATE,
                    "REST APIs": SkillLevel.INTERMEDIATE,
                    "SQL Fundamentals": SkillLevel.INTERMEDIATE,
                    "Git Basics": SkillLevel.BEGINNER,
                },
            )

        gaps: list[SkillGap] = []
        struggles = self.repository.get_active_struggles(profile.learner_id)
        struggling_skills = {s.skill.lower() for s in struggles}

        # 1. Analyze Required Skills
        for skill_name, req_level in role.required_skills.items():
            curr_lvl = profile.get_effective_level(skill_name)
            curr_rank = curr_lvl.rank if curr_lvl else 0
            req_rank = req_level.rank

            if curr_rank < req_rank:
                gap_size = req_rank - curr_rank
                skill_obj = self.skill_engine.get_skill(skill_name)
                prereqs = list(skill_obj.prerequisites) if skill_obj else []

                # Baseline priority from gap size
                priority = max(1, 6 - gap_size)

                # Prioritize skills that are active struggle points
                if skill_name.lower() in struggling_skills:
                    priority = 1

                # Prioritize foundational skills with zero prerequisites
                if not prereqs:
                    priority = max(1, priority - 1)

                evidence = []
                rec = profile.skill_levels.get(skill_name)
                if rec:
                    evidence = list(rec.evidence)

                action = (
                    f"Acquire foundational mastery of {skill_name} up to {req_level.value.capitalize()} level."
                    if not curr_lvl
                    else f"Advance {skill_name} from {curr_lvl.value.capitalize()} to {req_level.value.capitalize()}."
                )

                gaps.append(
                    SkillGap(
                        skill=skill_name,
                        current_level=curr_lvl,
                        required_level=req_level,
                        gap_size=gap_size,
                        priority=priority,
                        evidence=evidence,
                        prerequisites=prereqs,
                        recommended_action=action,
                    )
                )

        # 2. Analyze Preferred Skills (lower initial priority)
        for skill_name, pref_level in role.preferred_skills.items():
            curr_lvl = profile.get_effective_level(skill_name)
            curr_rank = curr_lvl.rank if curr_lvl else 0
            req_rank = pref_level.rank
            if curr_rank < req_rank:
                gap_size = req_rank - curr_rank
                skill_obj = self.skill_engine.get_skill(skill_name)
                prereqs = list(skill_obj.prerequisites) if skill_obj else []
                gaps.append(
                    SkillGap(
                        skill=skill_name,
                        current_level=curr_lvl,
                        required_level=pref_level,
                        gap_size=gap_size,
                        priority=4,  # Preferred skills priority 4-5
                        evidence=[],
                        prerequisites=prereqs,
                        recommended_action=f"Optional expansion: Build proficiency in {skill_name}.",
                    )
                )

        # 3. Prerequisite-aware Topological Ordering & Refined Prioritization
        ordered_skill_names = self.skill_engine.topological_sort([g.skill for g in gaps])
        order_index = {name: idx for idx, name in enumerate(ordered_skill_names)}

        # Sort gaps by:
        # 1. Prerequisite topological order (foundations first)
        # 2. Priority level (1 is most urgent)
        # 3. Gap size (larger gaps first)
        gaps.sort(key=lambda g: (order_index.get(g.skill, 999), g.priority, -g.gap_size))

        self.repository.save_skill_gaps(profile.learner_id, gaps)
        logger.info(
            "Identified and prioritized %d skill gaps for learner '%s' towards '%s'",
            len(gaps),
            profile.learner_id,
            role.role_name,
        )
        return gaps
