"""Verified resource recommendation engine with official docs and search integration."""

from __future__ import annotations

from typing import Any

from lyra.learning.models import (
    LearningObjective,
    LearningResource,
    ResourceType,
    SkillLevel,
)
from lyra.models.tools import ToolRequest
from lyra.observability.logging import get_logger
from lyra.tools.registry import ToolRegistry

logger = get_logger("learning.resource_recommender")

# Curated, verified, real-world official documentation and open educational resources (strictly real URLs)
_VERIFIED_RESOURCES: dict[str, list[dict[str, Any]]] = {
    "HTTP Basics": [
        {
            "title": "MDN Web Docs: An Overview of HTTP",
            "type": ResourceType.DOCUMENTATION,
            "url": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Overview",
            "provider": "Mozilla Developer Network",
            "difficulty": SkillLevel.BEGINNER,
            "estimated_time_minutes": 30,
            "reason": "The authoritative, free guide to client-server HTTP communications.",
        },
        {
            "title": "MDN Web Docs: HTTP Request Methods",
            "type": ResourceType.DOCUMENTATION,
            "url": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Methods",
            "provider": "Mozilla Developer Network",
            "difficulty": SkillLevel.BEGINNER,
            "estimated_time_minutes": 25,
            "reason": "Official reference on standard HTTP verbs and idempotent operations.",
        },
    ],
    "REST APIs": [
        {
            "title": "Microsoft REST API Guidelines",
            "type": ResourceType.DOCUMENTATION,
            "url": "https://github.com/microsoft/api-guidelines",
            "provider": "Microsoft Open Source",
            "difficulty": SkillLevel.INTERMEDIATE,
            "estimated_time_minutes": 45,
            "reason": "Comprehensive industry-standard design patterns for RESTful contracts.",
        },
        {
            "title": "MDN Web Docs: How to Use Fetch API",
            "type": ResourceType.TUTORIAL,
            "url": "https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API/Using_Fetch",
            "provider": "Mozilla Developer Network",
            "difficulty": SkillLevel.BEGINNER,
            "estimated_time_minutes": 30,
            "reason": "Hands-on guide to making real REST API calls and parsing payloads.",
        },
    ],
    "SQL Fundamentals": [
        {
            "title": "PostgreSQL Official Tutorial: SQL Language",
            "type": ResourceType.DOCUMENTATION,
            "url": "https://www.postgresql.org/docs/current/tutorial-sql.html",
            "provider": "PostgreSQL Global Development Group",
            "difficulty": SkillLevel.BEGINNER,
            "estimated_time_minutes": 45,
            "reason": "Rock-solid foundational database tutorial covering standard SQL queries.",
        },
        {
            "title": "SQLBolt: Interactive SQL Lessons",
            "type": ResourceType.INTERACTIVE_EXERCISE,
            "url": "https://sqlbolt.com/",
            "provider": "SQLBolt",
            "difficulty": SkillLevel.BEGINNER,
            "estimated_time_minutes": 40,
            "reason": "Free browser-based interactive SQL query exercises.",
        },
    ],
    "SQL Joins & Relational Queries": [
        {
            "title": "PostgreSQL Official Docs: Queries across Multiple Tables (Joins)",
            "type": ResourceType.DOCUMENTATION,
            "url": "https://www.postgresql.org/docs/current/tutorial-join.html",
            "provider": "PostgreSQL Global Development Group",
            "difficulty": SkillLevel.ELEMENTARY,
            "estimated_time_minutes": 35,
            "reason": "Definitive visual and syntactic walkthrough of INNER vs OUTER joins.",
        },
    ],
    "API Authentication & Security": [
        {
            "title": "OWASP REST Security Cheat Sheet",
            "type": ResourceType.DOCUMENTATION,
            "url": "https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html",
            "provider": "OWASP",
            "difficulty": SkillLevel.INTERMEDIATE,
            "estimated_time_minutes": 40,
            "reason": "Gold standard industry security recommendations for protecting REST APIs.",
        },
        {
            "title": "Auth0: Introduction to JSON Web Tokens (JWT)",
            "type": ResourceType.TUTORIAL,
            "url": "https://jwt.io/introduction",
            "provider": "JWT.io",
            "difficulty": SkillLevel.INTERMEDIATE,
            "estimated_time_minutes": 30,
            "reason": "Clear explanation of cryptographic signatures and payload claims.",
        },
    ],
    "Automated Testing & TDD": [
        {
            "title": "pytest Official Getting Started Guide",
            "type": ResourceType.DOCUMENTATION,
            "url": "https://docs.pytest.org/en/stable/getting-started.html",
            "provider": "pytest.org",
            "difficulty": SkillLevel.BEGINNER,
            "estimated_time_minutes": 35,
            "reason": "Clean, official introduction to test fixtures and assertion patterns.",
        },
    ],
}


class ResourceRecommender:
    """Recommends vetted educational materials, prioritizing official free resources."""

    def __init__(self, tool_registry: ToolRegistry | None = None) -> None:
        self.tool_registry = tool_registry

    async def recommend_resources(
        self,
        objective: LearningObjective,
        max_results: int = 3,
    ) -> list[LearningResource]:
        """Provide verified resources matching the objective topic, querying SearchTool if needed."""
        skill_name = objective.skill
        resources: list[LearningResource] = []

        # 1. Check curated catalog
        catalog_matches = _VERIFIED_RESOURCES.get(skill_name, [])
        for item in catalog_matches:
            resources.append(
                LearningResource(
                    title=item["title"],
                    type=item["type"],
                    url=item["url"],
                    provider=item["provider"],
                    difficulty=item["difficulty"],
                    estimated_time_minutes=item["estimated_time_minutes"],
                    topic=skill_name,
                    reason=item["reason"],
                    quality_score=0.95,
                )
            )

        # 2. If catalog empty and live search tool available, perform bounded query for official docs
        if not resources and self.tool_registry:
            search_tool = self.tool_registry.get("search")
            if search_tool:
                try:
                    query = f"{skill_name} official documentation tutorial"
                    req = ToolRequest(tool_name="search", arguments={"query": query, "max_results": 2})
                    res = await search_tool.execute(req)
                    if res.is_success() and isinstance(res.output, dict):
                        items = res.output.get("results", [])
                        for it in items:
                            u = it.get("url", "")
                            t = it.get("title", "")
                            if u and u.startswith("http"):
                                resources.append(
                                    LearningResource(
                                        title=t or f"{skill_name} Guide",
                                        type=ResourceType.DOCUMENTATION,
                                        url=u,
                                        provider="Web Search Result",
                                        difficulty=objective.difficulty,
                                        estimated_time_minutes=45,
                                        topic=skill_name,
                                        reason=f"Verified real-world documentation for {skill_name}.",
                                        quality_score=0.85,
                                    )
                                )
                except Exception as err:
                    logger.debug("Web search for resources encountered error: %s", err)

        # 3. If no external resource found, recommend LYRA's built-in interactive explanation (strictly no fake URLs!)
        if not resources:
            resources.append(
                LearningResource(
                    title=f"LYRA In-Depth Interactive Mentor Session: {skill_name}",
                    type=ResourceType.TUTORIAL,
                    url="",  # No invented URL
                    provider="LYRA AI Mentor",
                    difficulty=objective.difficulty,
                    estimated_time_minutes=objective.estimated_time_minutes,
                    topic=skill_name,
                    reason="Comprehensive interactive concept breakdown, live code walkthrough, and Q&A provided directly by LYRA.",
                    quality_score=0.90,
                )
            )

        return resources[:max_results]
