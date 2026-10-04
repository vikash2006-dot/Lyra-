"""Unit tests for SkillGapAnalyzer."""

from pathlib import Path
import tempfile
import pytest

from lyra.learning.gap_analyzer import SkillGapAnalyzer
from lyra.learning.models import LearnerProfile, SkillLevel, StruggleRecord
from lyra.learning.repository import SQLiteLearningRepository
from lyra.learning.skill_engine import SkillEngine


@pytest.fixture
def analyzer_setup():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = SQLiteLearningRepository(db_path=str(Path(tmpdir) / "test_gaps.db"))
        engine = SkillEngine(repository=repo)
        analyzer = SkillGapAnalyzer(repository=repo, skill_engine=engine)
        yield analyzer, repo, engine


def test_gap_analysis_backend_developer(analyzer_setup) -> None:
    analyzer, repo, engine = analyzer_setup

    profile = LearnerProfile(learner_id="test_dev", target_role="Backend Developer")
    profile.add_or_update_skill("JavaScript Fundamentals", assessed=SkillLevel.INTERMEDIATE)
    profile.add_or_update_skill("MongoDB & Document Stores", assessed=SkillLevel.BEGINNER)
    repo.save_learner_profile(profile)

    gaps = analyzer.analyze_gaps(profile)
    assert len(gaps) > 0

    gap_skills = [g.skill for g in gaps]
    assert "HTTP Basics" in gap_skills
    assert "REST APIs" in gap_skills
    assert "SQL Fundamentals" in gap_skills
    assert "SQL Joins & Relational Queries" in gap_skills

    # Check topological ordering in prioritized gaps: HTTP Basics must precede REST APIs
    http_idx = gap_skills.index("HTTP Basics")
    rest_idx = gap_skills.index("REST APIs")
    assert http_idx < rest_idx


def test_gap_analysis_prioritizes_struggles(analyzer_setup) -> None:
    analyzer, repo, engine = analyzer_setup

    profile = LearnerProfile(learner_id="struggler", target_role="Backend Developer")
    repo.save_learner_profile(profile)

    # Record a struggle with SQL Joins
    struggle = StruggleRecord(
        struggle_id="st_sql",
        learner_id="struggler",
        skill="SQL Joins & Relational Queries",
        concept_or_topic="JOIN condition",
        failure_count=3,
    )
    repo.save_struggle(struggle)

    gaps = analyzer.analyze_gaps(profile)
    join_gap = next(g for g in gaps if g.skill == "SQL Joins & Relational Queries")
    assert join_gap.priority == 1
