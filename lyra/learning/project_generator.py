"""Progressive milestone project generator for practical competency consolidation."""

from __future__ import annotations

import json
from typing import Any
import uuid

from lyra.learning.models import (
    LearnerProfile,
    ProjectSpecification,
    SkillLevel,
)
from lyra.observability.logging import get_logger
from lyra.routing.router import ModelRouter

logger = get_logger("learning.project_generator")


class ProjectGenerator:
    """Generates progressive real-world projects calibrated to learner skill gaps and tier."""

    def __init__(self, router: ModelRouter | None = None) -> None:
        self.router = router

    def generate_project(
        self,
        profile: LearnerProfile,
        difficulty: SkillLevel | None = None,
        skill_focus: list[str] | None = None,
    ) -> ProjectSpecification:
        """Generate a project tailored to the learner's current target role and level."""
        target_role = profile.target_role or "Backend Developer"
        diff = difficulty or SkillLevel.BEGINNER

        # Determine tier if not explicitly specified
        completed_count = len(profile.projects_completed)
        if difficulty is None:
            if completed_count == 0:
                diff = SkillLevel.BEGINNER
            elif completed_count == 1:
                diff = SkillLevel.INTERMEDIATE
            else:
                diff = SkillLevel.ADVANCED

        focus = skill_focus or (["REST APIs", "SQL Fundamentals"] if "Backend" in target_role else ["Python Fundamentals", "REST APIs"])

        if diff == SkillLevel.BEGINNER:
            return ProjectSpecification(
                project_id=f"proj_{uuid.uuid4().hex[:8]}",
                title="Personal Task & Notes REST API",
                difficulty=SkillLevel.BEGINNER,
                objective="Design and build a clean, stateless REST API to create, read, update, and filter personal tasks and tags.",
                requirements=[
                    "Implement semantic HTTP routes (GET, POST, PUT, DELETE)",
                    "Persist task data in a relational SQLite database",
                    "Validate request payloads and return appropriate HTTP status codes",
                ],
                technologies=["Python / FastAPI or Node.js / Express", "SQLite", "Git"],
                expected_features=[
                    "Task creation with title, description, and status",
                    "Task completion toggle endpoint",
                    "Filter tasks by status (active/completed)",
                ],
                milestones=[
                    "Milestone 1: Project setup and database schema creation",
                    "Milestone 2: Implement and test CRUD endpoints",
                    "Milestone 3: Request validation and clean error handling",
                ],
                evaluation_criteria=[
                    "Stateless API design following REST conventions",
                    "Correct HTTP status codes (200, 201, 400, 404)",
                    "Clean code structure with separated route handlers",
                ],
                skills_practiced=["HTTP Basics", "REST APIs", "SQL Fundamentals", "Git Basics"],
                extension_ideas=[
                    "Add pagination support (limit and offset)",
                    "Add full-text search across task descriptions",
                ],
            )

        elif diff == SkillLevel.INTERMEDIATE:
            return ProjectSpecification(
                project_id=f"proj_{uuid.uuid4().hex[:8]}",
                title="Auth-Protected Multi-User Task Collaboration Platform",
                difficulty=SkillLevel.INTERMEDIATE,
                objective="Build a secure multi-user backend with token authentication, relational data models, and automated tests.",
                requirements=[
                    "Implement user signup and login with secure password hashing (bcrypt)",
                    "Issue and verify JSON Web Tokens (JWT) for protected routes",
                    "Design relational tables with foreign keys and multi-table SQL queries",
                    "Write automated test suite achieving at least 80% route coverage",
                ],
                technologies=["FastAPI or Express", "PostgreSQL or SQLite", "JWT", "pytest or Jest"],
                expected_features=[
                    "User registration, login, and profile endpoints",
                    "Role-based authorization (admin vs standard member)",
                    "Task assignment and status change tracking with relational joins",
                    "Comprehensive automated unit and integration tests",
                ],
                milestones=[
                    "Milestone 1: Authentication and password hashing pipeline",
                    "Milestone 2: Relational database schema with customer/task relationships",
                    "Milestone 3: Protected middleware and automated test coverage",
                ],
                evaluation_criteria=[
                    "Robust security: secrets in environment, secure token expiry",
                    "Proper relational join queries without N+1 query issues",
                    "Passing automated integration tests",
                ],
                skills_practiced=[
                    "API Authentication & Security",
                    "SQL Joins & Relational Queries",
                    "Automated Testing & TDD",
                    "REST APIs",
                ],
                extension_ideas=[
                    "Add database migration tooling (Alembic or Prisma)",
                    "Add email confirmation or password reset workflows",
                ],
            )

        else:
            return ProjectSpecification(
                project_id=f"proj_{uuid.uuid4().hex[:8]}",
                title="High-Concurrency Microservice with Caching, Queues, and Docker",
                difficulty=SkillLevel.ADVANCED,
                objective="Architect a production-grade distributed backend supporting high-throughput workloads and background task queues.",
                requirements=[
                    "Containerize application using multi-stage Dockerfiles",
                    "Implement Redis caching layer for read-heavy query endpoints",
                    "Implement background job processing for asynchronous tasks",
                    "Provide comprehensive API documentation and CI/CD workflow",
                ],
                technologies=["FastAPI / Node.js", "PostgreSQL", "Redis", "Docker", "GitHub Actions"],
                expected_features=[
                    "Cache-aside pattern with automatic invalidation on writes",
                    "Asynchronous worker processing long-running tasks",
                    "Docker Compose local orchestration environment",
                    "Continuous integration pipeline running automated tests",
                ],
                milestones=[
                    "Milestone 1: Multi-stage Docker containerization",
                    "Milestone 2: Redis caching and invalidation architecture",
                    "Milestone 3: Background queue workers and CI automation",
                ],
                evaluation_criteria=[
                    "Measurable latency improvement via caching",
                    "Resilient worker error recovery and retry semantics",
                    "Clean container lifecycle and health check probes",
                ],
                skills_practiced=[
                    "Docker & Containerization",
                    "Database Indexing & Optimization",
                    "Cloud Deployment & CI/CD",
                    "System Design & Architecture",
                ],
                extension_ideas=[
                    "Add rate limiting per API key",
                    "Set up Prometheus metrics and structured JSON logging",
                ],
            )
