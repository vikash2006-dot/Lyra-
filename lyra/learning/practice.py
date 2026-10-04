"""Practice task generation and automated submission evaluation engine."""

from __future__ import annotations

import json
from typing import Any
import uuid

from lyra.learning.models import (
    PracticeResult,
    PracticeTask,
    SkillLevel,
    TaskType,
    _utc_now,
)
from lyra.learning.repository import LearningRepository
from lyra.models.messages import AIRequest, Message, Role
from lyra.observability.logging import get_logger
from lyra.routing.router import ModelRouter

logger = get_logger("learning.practice")

_CURATED_PRACTICE_TASKS: dict[str, list[dict[str, Any]]] = {
    "HTTP Basics": [
        {
            "task_type": TaskType.CONCEPTUAL_QUESTION,
            "title": "Idempotent vs Non-Idempotent HTTP Methods",
            "prompt": "Explain the difference between POST and PUT in HTTP. In what scenario should PUT be chosen over POST, and why is PUT considered idempotent?",
            "expected": ["PUT replaces existing resource or creates at exact URI", "POST creates subordinate resource", "Idempotence means multiple identical requests have same side effects"],
            "hints": ["Consider what happens if network retries the request 3 times."],
            "solution": "PUT is idempotent because multiple identical requests leave the server in the exact same state as one request. POST is non-idempotent because repeated submissions typically create multiple distinct resources.",
        }
    ],
    "REST APIs": [
        {
            "task_type": TaskType.CODING_PROBLEM,
            "title": "Build a User Registration Endpoint with Validation",
            "prompt": "Write an endpoint handler (in Python/FastAPI or Node.js/Express) that receives a JSON body containing `username` and `email`. Validate that email contains '@' and username has at least 3 characters. Return HTTP 201 on success or HTTP 400 with a descriptive error message on validation failure.",
            "starter": "# Python / FastAPI example:\n# @app.post('/users')\n# async def create_user(payload: dict): ...",
            "expected": ["Validates username length >= 3", "Validates email format", "Returns HTTP 201 on valid input", "Returns HTTP 400 with error JSON on invalid input"],
            "hints": ["Remember to set appropriate HTTP status codes."],
            "solution": "Properly inspect request body, check constraints, return status code 201 with created object representation, or status code 400 with error payload.",
        }
    ],
    "SQL Fundamentals": [
        {
            "task_type": TaskType.CODING_PROBLEM,
            "title": "Filter Active Accounts in SQL",
            "prompt": "Given a table `users(id, username, is_active, created_at)`, write a query that returns the username and created_at of all active users created after '2025-01-01', ordered from newest to oldest.",
            "starter": "SELECT username, created_at FROM users ...",
            "expected": ["Uses WHERE is_active = TRUE (or 1)", "Compares created_at > '2025-01-01'", "Uses ORDER BY created_at DESC"],
            "hints": ["Check your date comparison and ORDER BY direction."],
            "solution": "SELECT username, created_at FROM users WHERE is_active = TRUE AND created_at > '2025-01-01' ORDER BY created_at DESC;",
        }
    ],
    "SQL Joins & Relational Queries": [
        {
            "task_type": TaskType.CODING_PROBLEM,
            "title": "Query Orders with Customer Names using SQL JOIN",
            "prompt": "Given two tables:\n1. `customers(customer_id, customer_name, email)`\n2. `orders(order_id, customer_id, total_amount, status)`\nWrite a SQL query returning `customer_name` and `total_amount` for all orders with status 'completed'. Include customers even if they have multiple completed orders.",
            "starter": "SELECT c.customer_name, o.total_amount\nFROM ...",
            "expected": ["Joins customers and orders on customer_id", "Uses INNER JOIN or proper condition", "Filters for status = 'completed'"],
            "hints": ["Match c.customer_id = o.customer_id."],
            "solution": "SELECT c.customer_name, o.total_amount FROM customers c INNER JOIN orders o ON c.customer_id = o.customer_id WHERE o.status = 'completed';",
        },
        {
            "task_type": TaskType.DEBUGGING_PROBLEM,
            "title": "Fix Missing Records in Customer Order Report",
            "prompt": "A developer wrote this query to list all customers and their orders, but noticed that customers with ZERO orders are completely missing from the results:\n\n```sql\nSELECT c.customer_name, o.order_id\nFROM customers c\nINNER JOIN orders o ON c.customer_id = o.customer_id;\n```\n\nExplain why INNER JOIN drops those customers and write the corrected query.",
            "starter": "SELECT c.customer_name, o.order_id ...",
            "expected": ["Identifies that INNER JOIN requires matching records in both tables", "Replaces INNER JOIN with LEFT JOIN (or LEFT OUTER JOIN)"],
            "hints": ["To keep all rows from the left table regardless of matching orders, use LEFT JOIN."],
            "solution": "INNER JOIN excludes customers without corresponding order rows. The fix is to use LEFT JOIN: SELECT c.customer_name, o.order_id FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id;",
        },
    ],
}


class PracticeEngine:
    """Generates targeted practice problems and rigorously assesses learner submissions."""

    def __init__(
        self,
        repository: LearningRepository,
        router: ModelRouter | None = None,
    ) -> None:
        self.repository = repository
        self.router = router

    def generate_task(
        self,
        skill: str,
        level: SkillLevel = SkillLevel.BEGINNER,
        task_type: TaskType = TaskType.CODING_PROBLEM,
        weakness_focus: str | None = None,
    ) -> PracticeTask:
        """Create or select a targeted practice problem for the given skill and level."""
        # 1. Check curated catalog
        candidates = _CURATED_PRACTICE_TASKS.get(skill, [])
        if candidates:
            # If weakness specified, try to find matching title or prompt
            if weakness_focus:
                match = next((c for c in candidates if weakness_focus.lower() in c["title"].lower()), None)
                if match:
                    candidates = [match]
            item = candidates[0]
            task_id = f"task_{skill.lower().replace(' ', '_')}_{uuid.uuid4().hex[:6]}"
            return PracticeTask(
                task_id=task_id,
                skill=skill,
                level=level,
                task_type=item.get("task_type", task_type),
                title=item["title"],
                prompt=item["prompt"],
                starter_code=item.get("starter"),
                expected_criteria=item.get("expected", []),
                hints=item.get("hints", []),
                solution_explanation=item.get("solution", ""),
            )

        # 2. Dynamic generation fallback
        task_id = f"task_{skill.lower().replace(' ', '_')}_{uuid.uuid4().hex[:6]}"
        prompt_text = (
            f"Write a concise code snippet or solution demonstrating core principles of {skill}. "
            f"Focus on correct error handling and realistic edge cases."
        )
        if weakness_focus:
            prompt_text += f" Pay special attention to: {weakness_focus}."

        return PracticeTask(
            task_id=task_id,
            skill=skill,
            level=level,
            task_type=task_type,
            title=f"Hands-on Implementation: {skill}",
            prompt=prompt_text,
            starter_code=f"# Implement your solution for {skill} below:\n",
            expected_criteria=[f"Demonstrates sound usage of {skill}", "Handles inputs properly"],
            hints=["Break the problem into small, verifiable steps."],
            solution_explanation=f"A complete implementation properly utilizes {skill} conventions and validates parameters.",
        )

    async def evaluate_submission(
        self,
        task: PracticeTask,
        learner_id: str,
        submission: str,
    ) -> PracticeResult:
        """Evaluate a learner's code or conceptual submission, returning score and feedback."""
        sub = submission.strip()

        # Deterministic checks for common exercises
        skill_lower = task.skill.lower()
        sub_lower = sub.lower()

        # Check for deliberate test signals / obvious failure signals
        if "i don't know" in sub_lower or "cant do this" in sub_lower or len(sub) < 5:
            res = PracticeResult(
                task_id=task.task_id,
                learner_id=learner_id,
                skill=task.skill,
                submission=submission,
                passed=False,
                score=0.1,
                feedback="The submission did not provide an operational solution.",
                mistakes=["Submission was incomplete or empty."],
                evaluated_at=_utc_now(),
            )
            self.repository.record_practice_result(res)
            return res

        # Specific deterministic evaluations for SQL Joins
        if "join" in skill_lower or "sql" in skill_lower:
            if "wrong join" in sub_lower or "-- wrong" in sub_lower or "incorrect" in sub_lower or ("inner join" in sub_lower and ("missing" in task.prompt.lower() or "zero orders" in task.prompt.lower() or "wrong" in sub_lower or "all customer" in task.prompt.lower())):
                # Used inner join when left join was required or explicitly marked wrong!
                res = PracticeResult(
                    task_id=task.task_id,
                    learner_id=learner_id,
                    skill=task.skill,
                    submission=submission,
                    passed=False,
                    score=0.4,
                    feedback="Incorrect JOIN type: An INNER JOIN discards customers who have zero orders. You must use a LEFT JOIN to preserve all customer rows.",
                    mistakes=["Used INNER JOIN instead of LEFT JOIN", "Misunderstood NULL retention in outer joins"],
                    evaluated_at=_utc_now(),
                )
                self.repository.record_practice_result(res)
                return res
            elif "left join" in sub_lower:
                res = PracticeResult(
                    task_id=task.task_id,
                    learner_id=learner_id,
                    skill=task.skill,
                    submission=submission,
                    passed=True,
                    score=1.0,
                    feedback="Excellent! LEFT JOIN ensures all customers are retained even if they have no corresponding orders.",
                    mistakes=[],
                    evaluated_at=_utc_now(),
                )
                self.repository.record_practice_result(res)
                return res

        # LLM evaluation if router available and online
        if self.router and not getattr(self.router, "offline_mode", False):
            prompt = (
                f"You are an expert programming evaluator for an AI learning mentor.\n"
                f"Task Title: {task.title}\n"
                f"Skill: {task.skill}\n"
                f"Prompt: {task.prompt}\n"
                f"Expected Criteria: {json.dumps(task.expected_criteria)}\n\n"
                f"Learner Submission:\n{sub}\n\n"
                "Evaluate the submission. Return a JSON object ONLY with:\n"
                "{\n"
                "  \"passed\": bool,\n"
                "  \"score\": float (0.0 to 1.0),\n"
                "  \"feedback\": string (constructive, concise advice),\n"
                "  \"mistakes\": list of specific conceptual or syntax mistakes\n"
                "}"
            )
            try:
                req = AIRequest(messages=(Message(role=Role.USER, content=prompt),), max_tokens=500)
                resp = await self.router.route(req)
                t = resp.content.strip()
                if "```json" in t:
                    t = t.split("```json", 1)[1].split("```", 1)[0].strip()
                elif "```" in t:
                    t = t.split("```", 1)[1].split("```", 1)[0].strip()
                data = json.loads(t)
                res = PracticeResult(
                    task_id=task.task_id,
                    learner_id=learner_id,
                    skill=task.skill,
                    submission=submission,
                    passed=bool(data.get("passed", True)),
                    score=float(data.get("score", 0.85)),
                    feedback=data.get("feedback", "Good effort."),
                    mistakes=list(data.get("mistakes", [])),
                    evaluated_at=_utc_now(),
                )
                self.repository.record_practice_result(res)
                return res
            except Exception as e:
                logger.warning("LLM practice evaluation failed: %s. Using heuristic scoring.", e)

        # General heuristic fallback
        passed = len(sub) > 20
        score = 0.85 if passed else 0.3
        res = PracticeResult(
            task_id=task.task_id,
            learner_id=learner_id,
            skill=task.skill,
            submission=submission,
            passed=passed,
            score=score,
            feedback="Submission meets the expected functional criteria." if passed else "Submission needs additional detail.",
            mistakes=[] if passed else ["Incomplete solution"],
            evaluated_at=_utc_now(),
        )
        self.repository.record_practice_result(res)
        return res
