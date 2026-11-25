"""Unit tests for SQLiteLearningRepository."""

import os
from pathlib import Path
import tempfile
import pytest

from lyra.learning.models import (
    ActivityType,
    LearnerProfile,
    LearningActivity,
    LearningPlan,
    ObjectiveStatus,
    PracticeResult,
    Skill,
    SkillEvidence,
    SkillGap,
    SkillLevel,
    SkillMasteryRecord,
    StruggleRecord,
    TargetRole,
)
from lyra.learning.repository import SQLiteLearningRepository


@pytest.fixture
def temp_repo() -> SQLiteLearningRepository:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_learning.db")
        repo = SQLiteLearningRepository(db_path=db_path)
        yield repo


def test_repository_profile_crud(temp_repo: SQLiteLearningRepository) -> None:
    profile = LearnerProfile(learner_id="u123", name="Bob", target_role="Backend Developer")
    profile.add_or_update_skill("Python", self_reported=SkillLevel.INTERMEDIATE, assessed=SkillLevel.BEGINNER)

    temp_repo.save_learner_profile(profile)
    fetched = temp_repo.get_learner_profile("u123")

    assert fetched is not None
    assert fetched.learner_id == "u123"
    assert fetched.name == "Bob"
    assert fetched.target_role == "Backend Developer"
    assert "Python" in fetched.current_skills
    assert fetched.skill_levels["Python"].assessed_level == SkillLevel.BEGINNER


def test_repository_skills_and_roles(temp_repo: SQLiteLearningRepository) -> None:
    skill = Skill(
        id="s_react",
        name="React Basics",
        category="Frontend",
        prerequisites=["JavaScript Fundamentals"],
        difficulty=SkillLevel.ELEMENTARY,
    )
    temp_repo.save_skill(skill)
    fetched_skill = temp_repo.get_skill("s_react")
    assert fetched_skill is not None
    assert fetched_skill.name == "React Basics"

    role = TargetRole(
        role_name="Frontend Specialist",
        required_skills={"React Basics": SkillLevel.ADVANCED},
    )
    temp_repo.save_target_role(role)
    fetched_role = temp_repo.get_target_role("Frontend Specialist")
    assert fetched_role is not None
    assert fetched_role.role_name == "Frontend Specialist"


def test_repository_evidence_and_gaps(temp_repo: SQLiteLearningRepository) -> None:
    ev = SkillEvidence(
        skill="SQL",
        source="self_reported",
        evidence="Completed beginner database course",
        confidence=0.8,
    )
    temp_repo.add_skill_evidence("u123", ev)
    evidence_list = temp_repo.list_skill_evidence("u123", "SQL")
    assert len(evidence_list) == 1
    assert evidence_list[0].skill == "SQL"

    gap = SkillGap(
        skill="REST APIs",
        current_level=None,
        required_level=SkillLevel.INTERMEDIATE,
        gap_size=3,
        priority=1,
    )
    temp_repo.save_skill_gaps("u123", [gap])
    gaps = temp_repo.get_skill_gaps("u123")
    assert len(gaps) == 1
    assert gaps[0].skill == "REST APIs"


def test_repository_struggles_and_mastery(temp_repo: SQLiteLearningRepository) -> None:
    struggle = StruggleRecord(
        struggle_id="st1",
        learner_id="u123",
        skill="SQL Joins",
        concept_or_topic="LEFT vs INNER JOIN",
        failure_count=3,
    )
    temp_repo.save_struggle(struggle)
    active_st = temp_repo.get_active_struggles("u123")
    assert len(active_st) == 1
    assert active_st[0].concept_or_topic == "LEFT vs INNER JOIN"

    mastery = SkillMasteryRecord(
        learner_id="u123",
        skill="SQL Joins",
        mastery_score=0.6,
        confidence=0.7,
        status=ObjectiveStatus.NEEDS_REVIEW,
    )
    temp_repo.save_mastery(mastery)
    fetched_m = temp_repo.get_mastery("u123", "SQL Joins")
    assert fetched_m is not None
    assert fetched_m.status == ObjectiveStatus.NEEDS_REVIEW
