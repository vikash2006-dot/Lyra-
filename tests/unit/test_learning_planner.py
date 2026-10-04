"""Unit tests for WeeklyPlanner."""

from pathlib import Path
import tempfile
import pytest

from lyra.learning.models import (
    LearnerProfile,
    LearningObjective,
    SkillLevel,
)
from lyra.learning.planner import WeeklyPlanner
from lyra.learning.repository import SQLiteLearningRepository


@pytest.fixture
def planner_setup():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = SQLiteLearningRepository(db_path=str(Path(tmpdir) / "test_plan.db"))
        planner = WeeklyPlanner(repository=repo)
        yield planner, repo


def test_planner_respects_weekly_hours_budget(planner_setup) -> None:
    planner, repo = planner_setup

    profile = LearnerProfile(
        learner_id="u_budget",
        target_role="Backend Developer",
        weekly_learning_hours=8.0,
    )
    repo.save_learner_profile(profile)

    objs = [
        LearningObjective(id="o1", skill="HTTP Basics", title="HTTP Fundamentals", description=""),
        LearningObjective(id="o2", skill="REST APIs", title="REST API Design", description=""),
        LearningObjective(id="o3", skill="SQL Fundamentals", title="Relational Schemas", description=""),
    ]

    plan = planner.generate_plan(profile, objs, duration_weeks=8)

    assert plan.duration_weeks == 8
    assert plan.weekly_hours == 8.0
    assert len(plan.weeks) == 8

    # Verify that weekly minutes do not exceed target budget significantly (approx 480 min)
    for week in plan.weeks:
        assert len(week.days) == 7
        assert week.target_weekly_minutes <= 550  # roughly 8 hours, never 15 hours (900 min)!
        assert week.target_weekly_minutes >= 400


def test_planner_low_hours_budget(planner_setup) -> None:
    planner, repo = planner_setup

    profile = LearnerProfile(
        learner_id="u_busy",
        target_role="Backend Developer",
        weekly_learning_hours=4.0,  # Only 4 hours/week
    )
    repo.save_learner_profile(profile)

    objs = [
        LearningObjective(id="o1", skill="HTTP Basics", title="HTTP Fundamentals", description=""),
    ]

    plan = planner.generate_plan(profile, objs, duration_weeks=4)
    # Total weekly minutes should be around 240 min, NOT 600 or 900 min
    assert plan.weeks[0].target_weekly_minutes <= 300
