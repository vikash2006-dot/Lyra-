"""Learning Objective Engine converting gaps into structured curriculum milestones."""

from __future__ import annotations

import json
from typing import Any
import uuid

from lyra.learning.models import (
    LearningObjective,
    ObjectiveStatus,
    SkillGap,
    SkillLevel,
)
from lyra.learning.repository import LearningRepository
from lyra.models.messages import AIRequest, Message, Role
from lyra.observability.logging import get_logger
from lyra.routing.router import ModelRouter

logger = get_logger("learning.objective_engine")

_PRESET_OBJECTIVES: dict[str, list[dict[str, Any]]] = {
    "HTTP Basics": [
        {
            "title": "Understand HTTP Request/Response Lifecycle & Verbs",
            "desc": "Study how client-server communication functions, mastering GET, POST, PUT, PATCH, and DELETE verbs.",
            "est": 45,
            "diff": SkillLevel.BEGINNER,
        },
        {
            "title": "Master HTTP Status Codes & Headers",
            "desc": "Understand status code classes (2xx, 3xx, 4xx, 5xx) and essential headers (Content-Type, Authorization).",
            "est": 45,
            "diff": SkillLevel.BEGINNER,
        },
    ],
    "REST APIs": [
        {
            "title": "RESTful Resource Modeling & URL Conventions",
            "desc": "Design clean, noun-based REST resource paths and stateless interactions.",
            "est": 60,
            "diff": SkillLevel.ELEMENTARY,
        },
        {
            "title": "Building CRUD Endpoints with Request Validation",
            "desc": "Implement endpoints to create, read, update, and delete resources with schema validation.",
            "est": 90,
            "diff": SkillLevel.INTERMEDIATE,
        },
        {
            "title": "Standardized Error Handling & RFC 7807",
            "desc": "Construct predictable, structured error payloads with appropriate status codes.",
            "est": 45,
            "diff": SkillLevel.INTERMEDIATE,
        },
    ],
    "SQL Fundamentals": [
        {
            "title": "Relational Tables, Constraints, and Data Types",
            "desc": "Define tables with primary keys, foreign keys, nullability, and distinct column data types.",
            "est": 60,
            "diff": SkillLevel.BEGINNER,
        },
        {
            "title": "Core SQL CRUD & Filtering",
            "desc": "Write queries utilizing SELECT, WHERE, ORDER BY, LIMIT, and arithmetic expressions.",
            "est": 60,
            "diff": SkillLevel.BEGINNER,
        },
    ],
    "SQL Joins & Relational Queries": [
        {
            "title": "Mastering INNER JOIN vs LEFT JOIN",
            "desc": "Clarify relational matching semantics, comparing complete intersections with preserve-all left joins.",
            "est": 60,
            "diff": SkillLevel.ELEMENTARY,
        },
        {
            "title": "Multi-Table Aggregations & GROUP BY",
            "desc": "Aggregate joined data across multiple tables using COUNT, SUM, GROUP BY, and HAVING.",
            "est": 60,
            "diff": SkillLevel.INTERMEDIATE,
        },
    ],
    "API Authentication & Security": [
        {
            "title": "Authentication vs Authorization Core Principles",
            "desc": "Distinguish verifying user identity from enforcing resource permissions and roles.",
            "est": 45,
            "diff": SkillLevel.INTERMEDIATE,
        },
        {
            "title": "Implementing JWT Token Issuance & Verification",
            "desc": "Generate signed JSON Web Tokens, validate expiration, and build protected route middleware.",
            "est": 90,
            "diff": SkillLevel.INTERMEDIATE,
        },
    ],
    "Automated Testing & TDD": [
        {
            "title": "Unit Testing Controllers & Utility Functions",
            "desc": "Write isolated tests for core business logic without external network dependencies.",
            "est": 60,
            "diff": SkillLevel.INTERMEDIATE,
        },
        {
            "title": "API Integration Testing with Mock Databases",
            "desc": "Simulate end-to-end HTTP requests and verify database state and response contracts.",
            "est": 90,
            "diff": SkillLevel.INTERMEDIATE,
        },
    ],
}


class ObjectiveEngine:
    """Transforms skill gaps into concrete, measurable learning objectives."""

    def __init__(
        self,
        repository: LearningRepository,
        router: ModelRouter | None = None,
    ) -> None:
        self.repository = repository
        self.router = router

    async def generate_objectives_for_gaps(
        self,
        learner_id: str,
        gaps: list[SkillGap],
    ) -> list[LearningObjective]:
        """Generate structured objectives for each prioritized skill gap."""
        objectives: list[LearningObjective] = []

        for gap in gaps:
            # Check preset objectives first
            presets = _PRESET_OBJECTIVES.get(gap.skill)
            if presets:
                for idx, p in enumerate(presets, 1):
                    obj_id = f"obj_{gap.skill.lower().replace(' ', '_')}_{idx}"
                    objectives.append(
                        LearningObjective(
                            id=obj_id,
                            skill=gap.skill,
                            title=p["title"],
                            description=p["desc"],
                            prerequisites=list(gap.prerequisites),
                            difficulty=p["diff"],
                            estimated_time_minutes=p["est"],
                            status=ObjectiveStatus.NOT_STARTED,
                            mastery_level=0.0,
                        )
                    )
            elif self.router and not getattr(self.router, "offline_mode", False):
                # Use LLM for custom or novel skill gaps
                prompt = (
                    f"Create 2-3 specific learning objectives for the skill '{gap.skill}' "
                    f"(target level: {gap.required_level.value}).\n"
                    "Return a JSON array ONLY where each item has: "
                    "{'title': string, 'description': string, 'estimated_minutes': int, 'difficulty': 'beginner'|'intermediate'|'advanced'}."
                )
                try:
                    req = AIRequest(messages=(Message(role=Role.USER, content=prompt),), max_tokens=600)
                    resp = await self.router.route(req)
                    text = resp.content.strip()
                    if "```json" in text:
                        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
                    elif "```" in text:
                        text = text.split("```", 1)[1].split("```", 1)[0].strip()
                    items = json.loads(text)
                    for idx, it in enumerate(items, 1):
                        obj_id = f"obj_{gap.skill.lower().replace(' ', '_')}_{idx}"
                        objectives.append(
                            LearningObjective(
                                id=obj_id,
                                skill=gap.skill,
                                title=it["title"],
                                description=it["description"],
                                prerequisites=list(gap.prerequisites),
                                difficulty=SkillLevel.from_str(it.get("difficulty", gap.required_level.value)),
                                estimated_time_minutes=int(it.get("estimated_minutes", 60)),
                                status=ObjectiveStatus.NOT_STARTED,
                                mastery_level=0.0,
                            )
                        )
                except Exception as err:
                    logger.warning("LLM objective generation failed for %s: %s. Using fallback.", gap.skill, err)
                    obj_id = f"obj_{gap.skill.lower().replace(' ', '_')}_1"
                    objectives.append(
                        LearningObjective(
                            id=obj_id,
                            skill=gap.skill,
                            title=f"Core Concepts & Practice: {gap.skill}",
                            description=f"Study fundamentals and build hands-on competency in {gap.skill}.",
                            prerequisites=list(gap.prerequisites),
                            difficulty=gap.required_level,
                            estimated_time_minutes=60,
                            status=ObjectiveStatus.NOT_STARTED,
                            mastery_level=0.0,
                        )
                    )
            else:
                # Deterministic fallback
                obj_id = f"obj_{gap.skill.lower().replace(' ', '_')}_1"
                objectives.append(
                    LearningObjective(
                        id=obj_id,
                        skill=gap.skill,
                        title=f"Core Concepts & Practice: {gap.skill}",
                        description=f"Study fundamentals and build hands-on competency in {gap.skill}.",
                        prerequisites=list(gap.prerequisites),
                        difficulty=gap.required_level,
                        estimated_time_minutes=60,
                        status=ObjectiveStatus.NOT_STARTED,
                        mastery_level=0.0,
                    )
                )

        return objectives
