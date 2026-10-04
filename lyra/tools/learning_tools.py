"""LYRA Tool interfaces for the Adaptive Learning Agent."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from lyra.learning.models import SkillLevel
from lyra.learning.service import LearningService
from lyra.models.tools import ToolRequest, ToolResult
from lyra.observability.logging import get_logger
from lyra.tools.base import Tool
from lyra.tools.permissions import ToolPermissionLevel

logger = get_logger("tools.learning")


class GetLearnerProfileTool(Tool):
    """Retrieves the current learner profile and assessed skill inventory."""

    def __init__(self, service: LearningService) -> None:
        self.service = service

    @property
    def name(self) -> str:
        return "get_learner_profile"

    @property
    def description(self) -> str:
        return "Retrieve the learner's profile, including target role, verified skills, and learning goals."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "learner_id": {"type": "string", "description": "Unique identifier of the learner."},
            },
            "required": [],
            "additionalProperties": False,
        }

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        lowered = user_input.lower().strip()
        if any(p in lowered for p in ("show my profile", "view my profile", "my learner profile", "what are my skills", "what skills do i have")):
            return {}
        return None

    async def execute(self, request: ToolRequest) -> ToolResult:
        lid = request.user_id or str(request.arguments.get("learner_id", "default_user"))
        profile = self.service.get_profile(lid)
        return ToolResult(tool_name=self.name, success=True, output=profile.to_dict())

    def format_result(self, result: ToolResult) -> str:
        if not result.is_success() or not isinstance(result.output, dict):
            return "Could not retrieve learner profile."
        p = result.output
        role = p.get("target_role") or "Undecided"
        skills = ", ".join(p.get("current_skills", [])) or "None recorded"
        hours = p.get("weekly_learning_hours", 8.0)
        return f"Learner Profile:\n- Target Role: {role}\n- Skills: {skills}\n- Commitment: {hours} hrs/week"


class UpdateLearnerProfileTool(Tool):
    """Updates learner target role, goals, or weekly hours and bootstraps curriculum."""

    def __init__(self, service: LearningService) -> None:
        self.service = service

    @property
    def name(self) -> str:
        return "update_learner_profile"

    @property
    def description(self) -> str:
        return "Update learner parameters such as target role, career goal, known skills, or weekly hours."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.LOW_RISK

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "user_input": {"type": "string"},
                "target_role": {"type": "string"},
                "weekly_hours": {"type": "number"},
                "career_goal": {"type": "string"},
            },
            "additionalProperties": True,
        }

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        lowered = user_input.lower().strip()
        if any(p in lowered for p in ("i want to become", "change my goal to", "target role to", "switch goal to", "my goal is to become")):
            return {"user_input": user_input}
        return None

    async def execute(self, request: ToolRequest) -> ToolResult:
        lid = request.user_id or "default_user"
        profile = self.service.get_profile(lid)
        u_input = request.arguments.get("user_input")
        if u_input:
            self.service.process_intake(lid, str(u_input))
            profile = self.service.get_profile(lid)

        if "target_role" in request.arguments:
            profile.target_role = str(request.arguments["target_role"])
            profile.career_goal = f"Become a {profile.target_role}"
        if "weekly_hours" in request.arguments:
            profile.weekly_learning_hours = float(request.arguments["weekly_hours"])
        self.service.update_profile(profile)

        # Analyze gaps and bootstrap plan if target role is set
        gaps = self.service.analyze_gaps(lid)
        plan = self.service.get_active_plan(lid)
        if not plan and profile.target_role:
            plan = await self.service.create_learning_plan(lid, duration_weeks=8)

        today = self.service.get_today_tasks(lid)
        practice = self.service.generate_practice_task(lid)

        return ToolResult(
            tool_name=self.name,
            success=True,
            output={
                "profile": profile.to_dict(),
                "gaps": [g.to_dict() for g in gaps],
                "plan_created": plan is not None,
                "plan_id": plan.plan_id if plan else None,
                "today": today,
                "practice": practice.to_dict() if practice else None,
            },
        )

    def format_result(self, result: ToolResult) -> str:
        if not result.is_success() or not isinstance(result.output, dict):
            return "Could not update learner profile."
        data = result.output
        p = data.get("profile", {})
        role = p.get("target_role", "Software Engineer")
        hours = p.get("weekly_learning_hours", 8.0)
        gaps = data.get("gaps", [])
        today = data.get("today", {})
        practice = data.get("practice", {})

        lines = [
            f"Profile Updated: Target Role -> {role} ({hours} hrs/week).",
            f"\nIdentified {len(gaps)} prioritized skill gaps:",
        ]
        for g in gaps[:4]:
            lines.append(f"  • {g.get('skill')} (Target: {g.get('required_level')})")

        if today and today.get("has_plan"):
            lines.append(f"\nToday's Focus ({today.get('day')}):")
            for t in today.get("tasks", [])[:2]:
                lines.append(f"  - {t.get('title')} ({t.get('duration_minutes')} min)")

        if practice:
            lines.append(f"\nToday's Practice Task:")
            lines.append(f"  {practice.get('title')}: {practice.get('prompt')}")

        return "\n".join(lines)


class AnalyzeLearningDocumentTool(Tool):
    """Analyzes uploaded resumes, certificates, and portfolio documents."""

    def __init__(self, service: LearningService) -> None:
        self.service = service

    @property
    def name(self) -> str:
        return "analyze_learning_document"

    @property
    def description(self) -> str:
        return "Inspect and extract technical skills and evidence from an uploaded resume or document file."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Local path to document or resume file."},
            },
            "required": ["file_path"],
            "additionalProperties": False,
        }

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        lowered = user_input.lower().strip()
        m = re.search(r"(?:analyze my resume|here is my resume|parse resume|analyze document)[:\s]+([a-zA-Z0-9_\-\./\\]+)", lowered)
        if m:
            return {"file_path": m.group(1).strip()}
        return None

    async def execute(self, request: ToolRequest) -> ToolResult:
        lid = request.user_id or "default_user"
        fp = request.arguments.get("file_path", "")
        if not fp:
            return ToolResult(tool_name=self.name, success=False, error="file_path cannot be empty.")
        try:
            res = await self.service.analyze_document(lid, fp)
            return ToolResult(tool_name=self.name, success=True, output=res)
        except Exception as err:
            return ToolResult(tool_name=self.name, success=False, error=str(err))


class AnalyzeSkillGapsTool(Tool):
    """Performs prerequisite-aware skill gap analysis against target role."""

    def __init__(self, service: LearningService) -> None:
        self.service = service

    @property
    def name(self) -> str:
        return "analyze_skill_gaps"

    @property
    def description(self) -> str:
        return "Analyze missing or unmastered skills required for the learner's target career role."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target_role": {"type": "string"},
            },
            "additionalProperties": False,
        }

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        lowered = user_input.lower().strip()
        if any(p in lowered for p in ("what am i missing", "what skills am i missing", "skill gaps", "analyze my skills", "gap analysis")):
            m = re.search(r"(?:for|to become a?)\s+([a-zA-Z0-9\s]+?)(?:role|\?|$)", lowered)
            role = m.group(1).strip().title() if m else None
            return {"target_role": role} if role else {}
        return None

    async def execute(self, request: ToolRequest) -> ToolResult:
        lid = request.user_id or "default_user"
        role = request.arguments.get("target_role")
        gaps = self.service.analyze_gaps(lid, target_role_name=role)
        return ToolResult(tool_name=self.name, success=True, output=[g.to_dict() for g in gaps])

    def format_result(self, result: ToolResult) -> str:
        if not result.is_success() or not isinstance(result.output, list):
            return "Could not perform gap analysis."
        gaps = result.output
        if not gaps:
            return "No critical skill gaps identified for your target role!"
        lines = [f"Identified {len(gaps)} Skill Gaps (Prioritized):"]
        for g in gaps[:5]:
            lines.append(f"- {g['skill']} (Current: {g.get('current_level') or 'None'}, Target: {g['required_level']})")
        return "\n".join(lines)


class GenerateLearningPlanTool(Tool):
    """Generates an 8-week structured learning plan bounded by hours."""

    def __init__(self, service: LearningService) -> None:
        self.service = service

    @property
    def name(self) -> str:
        return "generate_learning_plan"

    @property
    def description(self) -> str:
        return "Generate a personalized weekly learning plan customized to the learner's time budget."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.LOW_RISK

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "duration_weeks": {"type": "integer"},
            },
            "additionalProperties": False,
        }

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        lowered = user_input.lower().strip()
        if any(p in lowered for p in ("make me a learning plan", "create a learning plan", "generate learning plan", "create my weekly plan")):
            m = re.search(r"(\d+)\s*weeks?", lowered)
            weeks = int(m.group(1)) if m else 8
            return {"duration_weeks": weeks}
        return None

    async def execute(self, request: ToolRequest) -> ToolResult:
        lid = request.user_id or "default_user"
        weeks = int(request.arguments.get("duration_weeks", 8))
        plan = await self.service.create_learning_plan(lid, duration_weeks=weeks)
        return ToolResult(tool_name=self.name, success=True, output=plan.to_dict())

    def format_result(self, result: ToolResult) -> str:
        if not result.is_success() or not isinstance(result.output, dict):
            return "Could not generate learning plan."
        p = result.output
        return (
            f"Created {p.get('duration_weeks')}-week learning plan for {p.get('target_role')} "
            f"({p.get('weekly_hours')} hrs/week) with {len(p.get('weeks', []))} structured weekly milestones."
        )


class GetTodayLearningTasksTool(Tool):
    """Fast-path retrieval of today's study and practice tasks."""

    def __init__(self, service: LearningService) -> None:
        self.service = service

    @property
    def name(self) -> str:
        return "get_today_learning_tasks"

    @property
    def description(self) -> str:
        return "Retrieve the scheduled study sessions and coding tasks for today."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        lowered = user_input.lower().strip()
        if any(p in lowered for p in ("what should i study today", "what to learn today", "today's task", "today's learning", "what should i do today")):
            return {}
        return None

    async def execute(self, request: ToolRequest) -> ToolResult:
        lid = request.user_id or "default_user"
        tasks_data = self.service.get_today_tasks(lid)
        return ToolResult(tool_name=self.name, success=True, output=tasks_data)

    def format_result(self, result: ToolResult) -> str:
        if not result.is_success() or not isinstance(result.output, dict):
            return "Could not fetch today's learning tasks."
        data = result.output
        if not data.get("has_plan"):
            return data.get("message", "No active plan found.")
        lines = [f"Today ({data.get('day')}, Week {data.get('week_number')}):"]
        for idx, t in enumerate(data.get("tasks", []), 1):
            status = " [DONE]" if t.get("completed") else ""
            lines.append(f"{idx}. {t.get('title')} — {t.get('duration_minutes')} min{status}")
        return "\n".join(lines)


class GeneratePracticeTaskTool(Tool):
    """Generates targeted exercises, coding problems, or debugging drills."""

    def __init__(self, service: LearningService) -> None:
        self.service = service

    @property
    def name(self) -> str:
        return "generate_practice_task"

    @property
    def description(self) -> str:
        return "Generate a targeted coding exercise or practice problem focused on a specific skill or weakness."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill": {"type": "string"},
            },
            "additionalProperties": False,
        }

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        lowered = user_input.lower().strip()
        if any(p in lowered for p in ("give me a practice task", "give me a practice problem", "give me a coding problem", "give me a harder problem")):
            m = re.search(r"(?:for|on|with)\s+([a-zA-Z0-9\s]+)", lowered)
            skill = m.group(1).strip().title() if m else None
            return {"skill": skill} if skill else {}
        return None

    async def execute(self, request: ToolRequest) -> ToolResult:
        lid = request.user_id or "default_user"
        skill = request.arguments.get("skill")
        task = self.service.generate_practice_task(lid, skill=skill)
        return ToolResult(tool_name=self.name, success=True, output=task.to_dict())

    def format_result(self, result: ToolResult) -> str:
        if not result.is_success() or not isinstance(result.output, dict):
            return "Could not generate practice task."
        t = result.output
        out = f"Practice Problem: {t.get('title')} ({t.get('skill')})\n\n{t.get('prompt')}"
        if t.get("starter_code"):
            out += f"\n\nStarter Code:\n{t.get('starter_code')}"
        return out


class EvaluatePracticeResultTool(Tool):
    """Evaluates learner code submissions, scores them, and adapts trajectory."""

    def __init__(self, service: LearningService) -> None:
        self.service = service

    @property
    def name(self) -> str:
        return "evaluate_practice_result"

    @property
    def description(self) -> str:
        return "Evaluate a code submission or answer for a practice task."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.LOW_RISK

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill": {"type": "string"},
                "submission": {"type": "string"},
            },
            "required": ["submission"],
            "additionalProperties": True,
        }

    async def execute(self, request: ToolRequest) -> ToolResult:
        lid = request.user_id or "default_user"
        skill = request.arguments.get("skill", "REST APIs")
        sub = request.arguments.get("submission", "")
        task = self.service.generate_practice_task(lid, skill=skill)
        eval_res = await self.service.submit_practice(lid, task, sub)
        pr = eval_res["result"]
        return ToolResult(
            tool_name=self.name,
            success=True,
            output={
                "passed": pr.passed,
                "score": pr.score,
                "feedback": pr.feedback,
                "mistakes": pr.mistakes,
                "adaptation": eval_res["adaptation_message"],
            },
        )


class GenerateProjectTool(Tool):
    """Generates a structured real-world capstone or milestone project."""

    def __init__(self, service: LearningService) -> None:
        self.service = service

    @property
    def name(self) -> str:
        return "generate_project"

    @property
    def description(self) -> str:
        return "Generate a progressive, real-world portfolio project specification."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "difficulty": {"type": "string"},
            },
            "additionalProperties": False,
        }

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        lowered = user_input.lower().strip()
        if any(p in lowered for p in ("give me a project", "create a project", "generate a project", "portfolio project")):
            return {}
        return None

    async def execute(self, request: ToolRequest) -> ToolResult:
        lid = request.user_id or "default_user"
        diff_str = request.arguments.get("difficulty")
        diff = SkillLevel.from_str(diff_str) if diff_str else None
        proj = self.service.generate_project(lid, difficulty=diff)
        return ToolResult(tool_name=self.name, success=True, output=proj.to_dict())


class GetLearningProgressTool(Tool):
    """Generates an evidence-backed progress report."""

    def __init__(self, service: LearningService) -> None:
        self.service = service

    @property
    def name(self) -> str:
        return "get_learning_progress"

    @property
    def description(self) -> str:
        return "Retrieve the comprehensive progress report including acquired skills, remaining gaps, and struggles."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        lowered = user_input.lower().strip()
        if any(p in lowered for p in ("how am i progressing", "show my progress", "learning progress", "what did i learn", "progress report")):
            return {}
        return None

    async def execute(self, request: ToolRequest) -> ToolResult:
        lid = request.user_id or "default_user"
        report = self.service.get_progress_report(lid)
        return ToolResult(tool_name=self.name, success=True, output=report.to_dict())

    def format_result(self, result: ToolResult) -> str:
        if not result.is_success() or not isinstance(result.output, dict):
            return "Could not retrieve progress report."
        r = result.output
        lines = [
            f"LYRA Progress Report — Target: {r.get('target_role')}",
            f"\nAcquired Skills ({len(r.get('skills_acquired', []))}):",
        ]
        for s in r.get("skills_acquired", []):
            lines.append(f"  ✓ {s}")
        if not r.get("skills_acquired"):
            lines.append("  (None fully completed yet)")

        if r.get("weak_areas"):
            lines.append(f"\nNeeds Improvement ({len(r.get('weak_areas'))}):")
            for w in r.get("weak_areas"):
                lines.append(f"  ⚠ {w}")

        lines.append(f"\nRemaining Gaps ({len(r.get('remaining_gaps', []))}):")
        for g in r.get("remaining_gaps", [])[:4]:
            lines.append(f"  • {g}")

        lines.append(f"\nRecommended Next Steps:")
        for idx, ns in enumerate(r.get("recommended_next_steps", []), 1):
            lines.append(f"  {idx}. {ns}")

        return "\n".join(lines)


class DetectLearningStrugglesTool(Tool):
    """Summarizes identified learning struggles and misconceptions."""

    def __init__(self, service: LearningService) -> None:
        self.service = service

    @property
    def name(self) -> str:
        return "detect_learning_struggles"

    @property
    def description(self) -> str:
        return "Inspect recorded misconceptions, struggle areas, and recommended remedial actions."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        lowered = user_input.lower().strip()
        if any(p in lowered for p in ("what am i weak at", "what do i struggle with", "my weak areas", "where am i struggling")):
            return {}
        return None

    async def execute(self, request: ToolRequest) -> ToolResult:
        lid = request.user_id or "default_user"
        struggles = self.service.repository.get_active_struggles(lid)
        return ToolResult(tool_name=self.name, success=True, output=[s.to_dict() for s in struggles])

    def format_result(self, result: ToolResult) -> str:
        if not result.is_success() or not isinstance(result.output, list):
            return "Could not inspect struggles."
        st = result.output
        if not st:
            return "No persistent struggles detected. You are keeping up well with your curriculum!"
        lines = ["Detected Areas of Struggle:"]
        for item in st:
            lines.append(f"- {item.get('skill')}: {item.get('concept_or_topic')}")
            for rem in item.get("remedial_actions_taken", [])[:1]:
                lines.append(f"  Action: {rem}")
        return "\n".join(lines)


class RecommendLearningResourcesTool(Tool):
    """Provides verified documentation and tutorial resources."""

    def __init__(self, service: LearningService) -> None:
        self.service = service

    @property
    def name(self) -> str:
        return "recommend_learning_resources"

    @property
    def description(self) -> str:
        return "Recommend verified, high-quality documentation and resources for a skill."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill": {"type": "string"},
            },
            "required": ["skill"],
            "additionalProperties": False,
        }

    async def execute(self, request: ToolRequest) -> ToolResult:
        skill = str(request.arguments.get("skill", "REST APIs"))
        res = await self.service.recommend_resources_for_skill(skill)
        return ToolResult(tool_name=self.name, success=True, output=[r.to_dict() for r in res])


class RecordLearningActivityTool(Tool):
    """Records completed learning tasks, study sessions, or assessments."""

    def __init__(self, service: LearningService) -> None:
        self.service = service

    @property
    def name(self) -> str:
        return "record_learning_activity"

    @property
    def description(self) -> str:
        return "Mark a learning task complete or record a study session."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.LOW_RISK

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
            },
            "additionalProperties": True,
        }

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        lowered = user_input.lower().strip()
        if any(p in lowered for p in ("i completed today's task", "completed task", "mark task complete", "finished task", "i finished today's task", "mark this task complete")):
            m = re.search(r"(?:task|finished)\s+([a-zA-Z0-9_\-]+)", lowered)
            task_id = m.group(1).strip() if m else "today_task"
            return {"task_id": task_id}
        return None

    async def execute(self, request: ToolRequest) -> ToolResult:
        lid = request.user_id or "default_user"
        tid = request.arguments.get("task_id", "today_task")
        success = self.service.mark_task_complete(lid, tid)
        return ToolResult(
            tool_name=self.name,
            success=True,
            output={"task_id": tid, "recorded": True, "plan_updated": success},
        )

    def format_result(self, result: ToolResult) -> str:
        return "Great job! I have recorded your completed learning task and updated your active plan."


class UpdateLearningPlanTool(Tool):
    """Adapts, resets, or updates the active learning plan."""

    def __init__(self, service: LearningService) -> None:
        self.service = service

    @property
    def name(self) -> str:
        return "update_learning_plan"

    @property
    def description(self) -> str:
        return "Update or adapt the learning plan based on recent progress or schedule changes."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.LOW_RISK

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
            },
            "additionalProperties": False,
        }

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        lowered = user_input.lower().strip()
        if any(p in lowered for p in ("update my learning plan", "adapt my plan", "recalculate plan", "update my plan", "regenerate plan", "reset plan")):
            return {"reason": user_input}
        return None

    async def execute(self, request: ToolRequest) -> ToolResult:
        lid = request.user_id or "default_user"
        reason = request.arguments.get("reason", "Manual user update")
        plan, explanation = self.service.adaptation_engine.adapt_plan(lid, trigger_reason=reason)
        return ToolResult(
            tool_name=self.name,
            success=True,
            output={"plan": plan.to_dict() if plan else None, "explanation": explanation},
        )

    def format_result(self, result: ToolResult) -> str:
        out = result.output if isinstance(result.output, dict) else {}
        return out.get("explanation", "Learning plan updated successfully.")


class UpdateSkillMasteryTool(Tool):
    """Updates assessed skill mastery and confidence."""

    def __init__(self, service: LearningService) -> None:
        self.service = service

    @property
    def name(self) -> str:
        return "update_skill_mastery"

    @property
    def description(self) -> str:
        return "Update or recalculate mastery scores for a specific skill."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.LOW_RISK

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill": {"type": "string"},
            },
            "required": ["skill"],
            "additionalProperties": False,
        }

    async def execute(self, request: ToolRequest) -> ToolResult:
        lid = request.user_id or "default_user"
        skill = str(request.arguments.get("skill", "REST APIs"))
        record = self.service.mastery_engine.calculate_mastery(lid, skill)
        return ToolResult(tool_name=self.name, success=True, output=record.to_dict())


class GenerateLearningObjectivesTool(Tool):
    """Generates structured learning objectives from skill gaps."""

    def __init__(self, service: LearningService) -> None:
        self.service = service

    @property
    def name(self) -> str:
        return "generate_learning_objectives"

    @property
    def description(self) -> str:
        return "Generate granular, structured learning objectives for current skill gaps."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def execute(self, request: ToolRequest) -> ToolResult:
        lid = request.user_id or "default_user"
        objs = await self.service.generate_objectives(lid)
        return ToolResult(tool_name=self.name, success=True, output=[o.to_dict() for o in objs])


class AnswerLearningQuestionTool(Tool):
    """Answers learner questions about topics, misconceptions, or progression."""

    def __init__(self, service: LearningService) -> None:
        self.service = service

    @property
    def name(self) -> str:
        return "answer_learning_question"

    @property
    def description(self) -> str:
        return "Provide pedagogical mentorship answers, clarifying concepts or explaining learning trajectory."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
            },
            "required": ["question"],
            "additionalProperties": False,
        }

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        lowered = user_input.lower().strip()
        triggers = (
            "what should i learn next",
            "why am i learning this",
            "how far am i from",
            "i don't understand",
            "i keep making mistakes with",
            "why do i keep struggling with",
            "am i ready for interviews",
            "explain this again",
        )
        if any(t in lowered for t in triggers):
            return {"question": user_input}
        return None

    async def execute(self, request: ToolRequest) -> ToolResult:
        lid = request.user_id or "default_user"
        q = str(request.arguments.get("question", "")).strip()
        lowered = q.lower()

        # Check for struggle detection trigger
        self.service.struggle_detector.detect_conceptual_confusion(lid, q)

        # Fast path answers
        if "what should i learn next" in lowered:
            gaps = self.service.analyze_gaps(lid)
            next_topic = gaps[0].skill if gaps else "Capstone Project"
            return ToolResult(
                tool_name=self.name,
                success=True,
                output={
                    "answer": f"Based on your current progress and target role, you should learn {next_topic} next.",
                    "topic": next_topic,
                },
            )

        if "why do i keep struggling with" in lowered or "keep making mistakes with" in lowered:
            struggles = self.service.repository.get_active_struggles(lid)
            reason = "You are working through a common misconception. Let's break it down step-by-step with intuitive examples."
            if struggles:
                reason = f"You are encountering difficulty with {struggles[0].concept_or_topic}. This is a frequent stumbling block, so I've adapted your plan to focus on foundational practice before moving forward."
            return ToolResult(
                tool_name=self.name,
                success=True,
                output={"answer": reason},
            )

        if "how far am i from" in lowered:
            rep = self.service.get_progress_report(lid)
            acq_len = len(rep.skills_acquired)
            gaps_len = len(rep.remaining_gaps)
            total = max(1, acq_len + gaps_len)
            pct = int((acq_len / total) * 100)
            return ToolResult(
                tool_name=self.name,
                success=True,
                output={"answer": f"You are approximately {pct}% towards your {rep.target_role} baseline ({acq_len} competencies verified, {gaps_len} remaining)."},
            )

        return ToolResult(
            tool_name=self.name,
            success=True,
            output={"answer": f"To master {q}, we focus on hands-on application, deliberate practice, and continuous feedback."},
        )

    def format_result(self, result: ToolResult) -> str:
        if isinstance(result.output, dict) and "answer" in result.output:
            return str(result.output["answer"])
        return result.to_text()


def create_learning_tools(service: LearningService) -> list[Tool]:
    """Factory creating the complete suite of LYRA learning tools."""
    return [
        GetLearnerProfileTool(service),
        UpdateLearnerProfileTool(service),
        AnalyzeLearningDocumentTool(service),
        AnalyzeSkillGapsTool(service),
        GenerateLearningObjectivesTool(service),
        RecommendLearningResourcesTool(service),
        GenerateLearningPlanTool(service),
        GetTodayLearningTasksTool(service),
        GeneratePracticeTaskTool(service),
        EvaluatePracticeResultTool(service),
        GenerateProjectTool(service),
        RecordLearningActivityTool(service),
        UpdateSkillMasteryTool(service),
        DetectLearningStrugglesTool(service),
        UpdateLearningPlanTool(service),
        GetLearningProgressTool(service),
        AnswerLearningQuestionTool(service),
    ]

