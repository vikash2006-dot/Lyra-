"""Unit tests for SkillEngine, DAG topological sorting, and role registry."""

import pytest

from lyra.learning.models import Skill, SkillLevel, TargetRole
from lyra.learning.skill_engine import SkillEngine


def test_seed_skills_and_roles_loaded() -> None:
    engine = SkillEngine()
    skills = engine.list_skills()
    assert len(skills) >= 10

    http = engine.get_skill("HTTP Basics")
    assert http is not None
    assert http.category == "Web Development"

    role = engine.get_target_role("Backend Developer")
    assert role is not None
    assert "REST APIs" in role.required_skills


def test_topological_sort_prerequisites() -> None:
    engine = SkillEngine()
    # REST APIs requires HTTP Basics
    # SQL Joins requires SQL Fundamentals
    unordered = ["REST APIs", "SQL Joins & Relational Queries", "HTTP Basics", "SQL Fundamentals"]
    ordered = engine.topological_sort(unordered)

    http_idx = ordered.index("HTTP Basics")
    rest_idx = ordered.index("REST APIs")
    assert http_idx < rest_idx, "HTTP Basics must be ordered before REST APIs"

    sql_idx = ordered.index("SQL Fundamentals")
    joins_idx = ordered.index("SQL Joins & Relational Queries")
    assert sql_idx < joins_idx, "SQL Fundamentals must be ordered before SQL Joins"


def test_dynamic_skill_and_role_registration() -> None:
    engine = SkillEngine()
    custom_skill = Skill(
        id="quantum_prog",
        name="Quantum Computing Qiskit",
        category="Emerging Tech",
        prerequisites=["Python Fundamentals"],
        difficulty=SkillLevel.ADVANCED,
    )
    engine.register_skill(custom_skill)
    assert engine.get_skill("Quantum Computing Qiskit") is not None

    custom_role = TargetRole(
        role_name="Quantum Algorithms Researcher",
        required_skills={"Quantum Computing Qiskit": SkillLevel.EXPERT},
    )
    engine.register_target_role(custom_role)
    assert engine.get_target_role("Quantum Algorithms Researcher") is not None
