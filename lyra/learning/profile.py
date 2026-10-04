"""Learner Profile Management and Progressive Conversational Intake."""

from __future__ import annotations

import re
from typing import Any

from lyra.learning.models import (
    EvidenceSource,
    LearnerProfile,
    SkillEvidence,
    SkillLevel,
    _utc_now,
)
from lyra.learning.repository import LearningRepository
from lyra.memory.manager import MemoryManager
from lyra.observability.logging import get_logger

logger = get_logger("learning.profile")


class LearnerProfileManager:
    """Manages profile lifecycle, progressive conversational extraction, and memory sync."""

    def __init__(
        self,
        repository: LearningRepository,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self.repository = repository
        self.memory_manager = memory_manager

    def get_or_create_profile(self, learner_id: str, name: str = "Learner") -> LearnerProfile:
        profile = self.repository.get_learner_profile(learner_id)
        if not profile:
            profile = LearnerProfile(learner_id=learner_id, name=name)
            self.repository.save_learner_profile(profile)
            logger.info("Created new learner profile for '%s'", learner_id)
        return profile

    def update_profile(self, profile: LearnerProfile) -> None:
        profile.updated_at = _utc_now()
        self.repository.save_learner_profile(profile)
        self._sync_with_memory(profile)

    def _sync_with_memory(self, profile: LearnerProfile) -> None:
        """Sync key learner goals, target roles, and preferences to LYRA's MemoryManager."""
        if not self.memory_manager:
            return
        uid = profile.learner_id
        try:
            if profile.target_role:
                self.memory_manager.remember(
                    user_id=uid,
                    content=f"Career goal: Target role is {profile.target_role}. Goal: {profile.career_goal or profile.target_role}.",
                    memory_type="goal",
                    source="learning_system",
                    importance=0.9,
                    confidence=0.95,
                )
            if profile.weekly_learning_hours:
                self.memory_manager.remember(
                    user_id=uid,
                    content=f"Learning schedule commitment: {profile.weekly_learning_hours} hours per week with {profile.preferred_learning_style} learning style.",
                    memory_type="preference",
                    source="learning_system",
                    importance=0.7,
                    confidence=0.9,
                )
        except Exception as err:
            logger.warning("Failed to sync learning profile into MemoryManager: %s", err)

    def parse_conversational_intake(self, user_text: str, profile: LearnerProfile) -> dict[str, Any]:
        """Extract profile information (target role, skills, hours, projects) from natural dialogue."""
        text = user_text.strip()
        lowered = text.lower()
        extracted: dict[str, Any] = {}

        # 1. Target Role & Career Goal
        role_match = re.search(
            r"(?:want to become|aiming to be|goal is to be|become|target role is|aspire to be|looking to become)\s+(?:a|an)?\s*([a-zA-Z0-9\s/\-]+?)(?:\.|\,|$|\band\b|\bwith\b|\bi know\b)",
            lowered,
        )
        if role_match:
            candidate_role = role_match.group(1).strip().title()
            if len(candidate_role) > 2 and len(candidate_role) < 40:
                profile.target_role = candidate_role
                profile.career_goal = f"Become a {candidate_role}"
                extracted["target_role"] = candidate_role

        # 2. Weekly Available Hours
        hours_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s*(?:per|a|every)?\s*week", lowered)
        if not hours_match:
            hours_match = re.search(r"(?:study|learn|commit|have)\s*(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)", lowered)
        if hours_match:
            hours = float(hours_match.group(1))
            profile.weekly_learning_hours = hours
            extracted["weekly_learning_hours"] = hours

        # 3. Known Skills extraction (self-reported)
        skill_patterns = [
            r"(?:i know|i have experience with|familiar with|skilled in|i understand|background in)\s+([^.\n]+)",
            r"(?:skills?:\s*)([^.\n]+)",
        ]
        detected_skills: list[str] = []
        for pat in skill_patterns:
            m = re.search(pat, lowered)
            if m:
                raw_chunk = m.group(1)
                tokens = re.split(r",|\band\b|;|\+", raw_chunk)
                for t in tokens:
                    cl = t.strip()
                    if not cl or len(cl) > 30:
                        continue
                    # Check for basic/intermediate modifiers
                    lvl = SkillLevel.BEGINNER
                    if "basic" in cl or "beginner" in cl or "elementary" in cl:
                        lvl = SkillLevel.BEGINNER
                    elif "intermediate" in cl or "medium" in cl:
                        lvl = SkillLevel.INTERMEDIATE
                    elif "advanced" in cl or "expert" in cl:
                        lvl = SkillLevel.ADVANCED

                    cleaned_name = re.sub(r"\b(basic|intermediate|advanced|expert|some|good|solid|a bit of)\b", "", cl).strip()
                    canonical_names = {
                        "javascript": "JavaScript",
                        "typescript": "TypeScript",
                        "mongodb": "MongoDB",
                        "python": "Python",
                        "sql": "SQL",
                        "postgresql": "PostgreSQL",
                        "mysql": "MySQL",
                        "nosql": "NoSQL",
                        "nodejs": "Node.js",
                        "node.js": "Node.js",
                        "express": "Express",
                        "rest": "REST APIs",
                        "rest apis": "REST APIs",
                        "http": "HTTP Basics",
                        "docker": "Docker",
                        "html": "HTML",
                        "css": "CSS",
                        "git": "Git",
                    }
                    cleaned_name = canonical_names.get(cleaned_name.lower(), cleaned_name.title())
                    if cleaned_name and len(cleaned_name) >= 2:
                        profile.add_or_update_skill(
                            skill=cleaned_name,
                            self_reported=lvl,
                            assessed=lvl,
                            confidence=0.60,
                            evidence_item=f"Self-reported in conversation: '{cl}'",
                        )
                        detected_skills.append(cleaned_name)
                        self.repository.add_skill_evidence(
                            profile.learner_id,
                            SkillEvidence(
                                skill=cleaned_name,
                                source=EvidenceSource.SELF_REPORTED,
                                evidence=f"User conversational input: '{cl}'",
                                confidence=0.60,
                            ),
                        )
        if detected_skills:
            extracted["skills"] = detected_skills

        # 4. Built Projects
        proj_match = re.search(r"(?:built|have built|created|have created|developed|worked on)\s+([^,;:\n]+?project[^,;:\n]*)", lowered)
        if proj_match:
            p_desc = proj_match.group(1).strip()
            # Clean trailing punctuation
            p_desc = p_desc.rstrip(" .!?,;")
            if p_desc and p_desc not in profile.projects_completed:
                profile.projects_completed.append(p_desc.capitalize())
                extracted["project"] = p_desc

        self.update_profile(profile)
        return extracted

    def get_missing_intake_fields(self, profile: LearnerProfile) -> list[str]:
        """Identify missing essential profile fields without overwhelming with 20 questions."""
        missing = []
        if not profile.target_role:
            missing.append("target_role")
        if not profile.current_skills:
            missing.append("current_skills")
        if profile.weekly_learning_hours <= 0:
            missing.append("weekly_hours")
        return missing

    def generate_next_intake_question(self, profile: LearnerProfile) -> str | None:
        """Formulate a gentle, natural single follow-up question if information is incomplete."""
        missing = self.get_missing_intake_fields(profile)
        if not missing:
            return None
        if "target_role" in missing:
            return "What career or engineering role are you aiming for (for instance, Backend Developer, AI Engineer, or Fullstack)?"
        if "current_skills" in missing:
            return f"Great! To tailor your path to {profile.target_role}, what programming languages, frameworks, or tools do you currently have experience with?"
        if "weekly_hours" in missing:
            return "How many hours per week would you like to dedicate to your learning plan?"
        return None
