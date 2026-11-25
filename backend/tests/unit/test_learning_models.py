"""Unit tests for LYRA Adaptive Learning Agent domain models."""

from datetime import datetime, timezone
import pytest

from lyra.learning.models import (
    ActivityType,
    DailyPlan,
    EvidenceSource,
    LearnerProfile,
    LearningActivity,
    LearningObjective,
    LearningPlan,
    LearningResource,
    ObjectiveStatus,
    PracticeResult,
    PracticeTask,
    ProgressReport,
    ProjectSpecification,
    ResourceType,
    Skill,
    SkillEvidence,
    SkillGap,
    SkillLevel,
    SkillLevelRecord,
    SkillMasteryRecord,
    StruggleRecord,
    TargetRole,
    TaskType,
    WeekPlan,
)


def test_skill_level_ranks_and_parsing() -> None:
    assert SkillLevel.BEGINNER.rank == 1
    assert SkillLevel.ELEMENTARY.rank == 2
    assert SkillLevel.INTERMEDIATE.rank == 3
    assert SkillLevel.ADVANCED.rank == 4
    assert SkillLevel.EXPERT.rank == 5

    assert SkillLevel.from_rank(1) == SkillLevel.BEGINNER
    assert SkillLevel.from_rank(5) == SkillLevel.EXPERT
    assert SkillLevel.from_rank(99) == SkillLevel.EXPERT
    assert SkillLevel.from_rank(-5) == SkillLevel.BEGINNER

    assert SkillLevel.from_str("basic") == SkillLevel.BEGINNER
    assert SkillLevel.from_str("Intermediate") == SkillLevel.INTERMEDIATE
    assert SkillLevel.from_str("expert") == SkillLevel.EXPERT


def test_skill_evidence_serialization() -> None:
    ev = SkillEvidence(
        skill="Node.js",
        source=EvidenceSource.DOCUMENT_EVIDENCE,
        evidence="Built REST API using Express",
        confidence=0.72,
    )
    d = ev.to_dict()
    assert d["skill"] == "Node.js"
    assert d["source"] == "document_evidence"
    assert d["confidence"] == 0.72

    restored = SkillEvidence.from_dict(d)
    assert restored.skill == ev.skill
    assert restored.source == EvidenceSource.DOCUMENT_EVIDENCE
    assert restored.confidence == 0.72


def test_learner_profile_skill_addition_and_effective_level() -> None:
    profile = LearnerProfile(learner_id="test_user", name="Alice")
    assert profile.get_effective_level("Python") is None

    # Self-report Python as intermediate, but assessed as beginner
    profile.add_or_update_skill(
        skill="Python",
        self_reported=SkillLevel.INTERMEDIATE,
        assessed=SkillLevel.BEGINNER,
        confidence=0.6,
        evidence_item="Self-reported basic proficiency",
    )

    assert "Python" in profile.current_skills
    rec = profile.skill_levels["Python"]
    assert rec.self_reported_level == SkillLevel.INTERMEDIATE
    assert rec.assessed_level == SkillLevel.BEGINNER
    assert profile.get_effective_level("Python") == SkillLevel.BEGINNER

    # Serialization roundtrip
    data = profile.to_dict()
    restored = LearnerProfile.from_dict(data)
    assert restored.learner_id == "test_user"
    assert "Python" in restored.current_skills
    assert restored.skill_levels["Python"].assessed_level == SkillLevel.BEGINNER


def test_learning_plan_structure() -> None:
    d = DailyPlan(day="Monday", tasks=[{"title": "HTTP", "duration_minutes": 45}], total_minutes=45)
    w = WeekPlan(week_number=1, theme="Foundations", days=[d], target_weekly_minutes=45, milestone="M1")
    plan = LearningPlan(
        plan_id="p1",
        learner_id="u1",
        target_role="Backend Developer",
        duration_weeks=1,
        weekly_hours=5.0,
        weeks=[w],
        objectives=["HTTP Basics"],
        milestones=["M1"],
    )

    data = plan.to_dict()
    restored = LearningPlan.from_dict(data)
    assert restored.plan_id == "p1"
    assert restored.target_role == "Backend Developer"
    assert len(restored.weeks) == 1
    assert restored.weeks[0].days[0].day == "Monday"


def test_struggle_and_mastery_models() -> None:
    st = StruggleRecord(
        struggle_id="s1",
        learner_id="u1",
        skill="SQL Joins",
        concept_or_topic="INNER JOIN vs LEFT JOIN",
        signals=["Failed practice"],
        failure_count=2,
    )
    st_dict = st.to_dict()
    assert StruggleRecord.from_dict(st_dict).concept_or_topic == "INNER JOIN vs LEFT JOIN"

    mastery = SkillMasteryRecord(
        learner_id="u1",
        skill="SQL Joins",
        mastery_score=0.75,
        confidence=0.8,
        status=ObjectiveStatus.IN_PROGRESS,
    )
    m_dict = mastery.to_dict()
    assert SkillMasteryRecord.from_dict(m_dict).mastery_score == 0.75
