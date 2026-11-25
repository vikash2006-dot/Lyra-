"""Unit tests for MasteryEngine, StruggleDetector, and AdaptationEngine."""

from pathlib import Path
import tempfile
import pytest

from lyra.learning.adaptation import AdaptationEngine
from lyra.learning.mastery import MasteryEngine
from lyra.learning.models import (
    LearnerProfile,
    ObjectiveStatus,
    PracticeResult,
    SkillEvidence,
    SkillLevel,
    _utc_now,
)
from lyra.learning.planner import WeeklyPlanner
from lyra.learning.practice import PracticeEngine
from lyra.learning.repository import SQLiteLearningRepository
from lyra.learning.struggle_detector import StruggleDetector


@pytest.fixture
def system_setup():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = SQLiteLearningRepository(db_path=str(Path(tmpdir) / "test_mastery.db"))
        mastery_engine = MasteryEngine(repository=repo)
        struggle_detector = StruggleDetector(repository=repo)
        adaptation_engine = AdaptationEngine(repository=repo)
        planner = WeeklyPlanner(repository=repo)
        yield repo, mastery_engine, struggle_detector, adaptation_engine, planner


def test_mastery_requires_multiple_evidence(system_setup) -> None:
    repo, mastery_engine, struggle_detector, adaptation_engine, planner = system_setup

    profile = LearnerProfile(learner_id="u_learner", target_role="Backend Developer")
    repo.save_learner_profile(profile)

    # 1. User completes ONE task with 100% score
    res1 = PracticeResult(
        task_id="t1",
        learner_id="u_learner",
        skill="SQL Joins",
        submission="SELECT * FROM a JOIN b ON a.id = b.id;",
        passed=True,
        score=1.0,
        feedback="Perfect",
    )
    repo.record_practice_result(res1)
    record1 = mastery_engine.calculate_mastery("u_learner", "SQL Joins")

    # MUST NOT be completed after only 1 task!
    assert record1.status == ObjectiveStatus.IN_PROGRESS
    assert record1.confidence < 0.7

    # 2. Add 2 more successful practice tasks
    res2 = PracticeResult(task_id="t2", learner_id="u_learner", skill="SQL Joins", submission="...", passed=True, score=0.9, feedback="")
    res3 = PracticeResult(task_id="t3", learner_id="u_learner", skill="SQL Joins", submission="...", passed=True, score=0.95, feedback="")
    repo.record_practice_result(res2)
    repo.record_practice_result(res3)

    record2 = mastery_engine.calculate_mastery("u_learner", "SQL Joins")
    assert record2.status == ObjectiveStatus.COMPLETED
    assert record2.confidence >= 0.70


def test_struggle_detection_on_repeated_failures(system_setup) -> None:
    repo, mastery_engine, struggle_detector, adaptation_engine, planner = system_setup

    profile = LearnerProfile(learner_id="u_struggle", target_role="Backend Developer")
    repo.save_learner_profile(profile)

    # User fails 3 consecutive SQL JOIN exercises
    for i in range(3):
        res = PracticeResult(
            task_id=f"t_fail_{i}",
            learner_id="u_struggle",
            skill="SQL Joins & Relational Queries",
            submission="SELECT * FROM customers INNER JOIN orders...",
            passed=False,
            score=0.3,
            feedback="Incorrect join type",
            mistakes=["Used INNER JOIN instead of LEFT JOIN"],
        )
        repo.record_practice_result(res)

    struggle = struggle_detector.analyze_practice_performance("u_struggle", "SQL Joins & Relational Queries")
    assert struggle is not None
    assert struggle.failure_count == 3
    assert "INNER vs LEFT JOIN" in struggle.concept_or_topic

    # Profile should now list SQL Joins in weak_topics
    updated_prof = repo.get_learner_profile("u_struggle")
    assert "SQL Joins & Relational Queries" in updated_prof.weak_topics


def test_adaptation_inserts_remedial_practice(system_setup) -> None:
    repo, mastery_engine, struggle_detector, adaptation_engine, planner = system_setup

    profile = LearnerProfile(learner_id="u_adapt", target_role="Backend Developer", weekly_learning_hours=8.0)
    repo.save_learner_profile(profile)
    plan = planner.generate_plan(profile, [], duration_weeks=4)

    # Simulate struggle
    for i in range(2):
        res = PracticeResult(
            task_id=f"f_{i}",
            learner_id="u_adapt",
            skill="SQL Joins",
            submission="wrong query",
            passed=False,
            score=0.2,
            feedback="Fail",
            mistakes=["Misunderstood join conditions"],
        )
        repo.record_practice_result(res)

    struggle = struggle_detector.analyze_practice_performance("u_adapt", "SQL Joins")
    assert struggle is not None

    adapted_plan, explanation = adaptation_engine.adapt_plan("u_adapt", "Struggle in SQL Joins", struggle=struggle)
    assert adapted_plan is not None
    assert "remedial practice" in explanation.lower()

    # Check that a remedial task was inserted into the plan
    all_tasks = [t for w in adapted_plan.weeks for d in w.days for t in d.tasks]
    remedial = [t for t in all_tasks if t.get("remedial") is True]
    assert len(remedial) >= 1
    assert "SQL Joins" in remedial[0]["skill"]
