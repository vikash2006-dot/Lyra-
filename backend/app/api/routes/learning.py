"""Adaptive learning APIs — thin HTTP layer over LYRA's LearningService."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from lyra.learning.models import LearnerProfile

from app.api.deps import get_services, rate_limit
from app.core.errors import APIError, ok
from app.schemas import (
    LearningActivityRequest,
    LearningPlanRequest,
    LearningPracticeRequest,
    LearningProfileUpdate,
    LearningSkillRequest,
)
from app.services.serialization import to_jsonable

router = APIRouter(prefix="/learning", tags=["learning"])


def _learning(request: Request):
    services = get_services(request)
    return services, services.runtime.learning_service, services.user_id


@router.get("/profile")
async def get_profile(request: Request) -> dict:
    _, ls, uid = _learning(request)
    profile = ls.get_profile(uid)
    return ok({**to_jsonable(profile), "missing_intake_fields": ls.profile_manager.get_missing_intake_fields(profile)})


@router.put("/profile")
async def update_profile(body: LearningProfileUpdate, request: Request) -> dict:
    _, ls, uid = _learning(request)
    profile = ls.get_profile(uid)
    data = profile.to_dict()
    data.update({k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None})
    updated = LearnerProfile.from_dict(data)
    ls.update_profile(updated)
    return ok(to_jsonable(ls.get_profile(uid)), "Profile updated")


@router.get("/skills")
async def get_skills(request: Request) -> dict:
    _, ls, uid = _learning(request)
    profile = ls.get_profile(uid)
    mastery = {m.skill: to_jsonable(m) for m in ls.repository.list_mastery(uid)}
    skills = []
    for name, rec in profile.skill_levels.items():
        skills.append({**to_jsonable(rec), "mastery": mastery.get(name)})
    return ok({
        "skills": skills,
        "current_skills": profile.current_skills,
        "gaps": to_jsonable(ls.repository.get_skill_gaps(uid)),
        "target_roles": [r.role_name for r in ls.skill_engine.list_target_roles()]
        if hasattr(ls.skill_engine, "list_target_roles") else [],
    })


@router.post("/skills", status_code=201)
async def add_skill(body: LearningSkillRequest, request: Request) -> dict:
    _, ls, uid = _learning(request)
    profile = ls.get_profile(uid)
    profile.add_or_update_skill(body.skill, self_reported=body.level, evidence_item=body.evidence)
    ls.update_profile(profile)
    return ok(to_jsonable(profile.skill_levels.get(body.skill.strip())), "Skill saved")


@router.get("/gaps")
async def get_gaps(request: Request) -> dict:
    _, ls, uid = _learning(request)
    profile = ls.get_profile(uid)
    if not profile.target_role:
        return ok([], "Set a target role to analyse skill gaps")
    return ok(to_jsonable(ls.analyze_gaps(uid)))


@router.get("/plan")
async def get_plan(request: Request) -> dict:
    _, ls, uid = _learning(request)
    plan = ls.get_active_plan(uid)
    return ok({
        "plan": to_jsonable(plan) if plan else None,
        "today": to_jsonable(ls.get_today_tasks(uid)),
    })


@router.post("/plan", status_code=201)
async def create_plan(body: LearningPlanRequest, request: Request) -> dict:
    rate_limit(request, "chat")
    _, ls, uid = _learning(request)
    profile = ls.get_profile(uid)
    if body.target_role:
        profile.target_role = body.target_role.strip()
        ls.update_profile(profile)
    if not profile.target_role:
        raise APIError("TARGET_ROLE_REQUIRED", "Set a target role before generating a learning plan.", 422)
    plan = await ls.create_learning_plan(uid, duration_weeks=body.duration_weeks)
    return ok(to_jsonable(plan), "Learning plan created")


@router.get("/progress")
async def get_progress(request: Request) -> dict:
    _, ls, uid = _learning(request)
    report = ls.get_progress_report(uid)
    activities = ls.repository.list_activities(uid, limit=20)
    return ok({"report": to_jsonable(report), "recent_activities": to_jsonable(activities)})


@router.get("/resources")
async def get_resources(request: Request, skill: str) -> dict:
    _, ls, _ = _learning(request)
    if not skill.strip():
        raise APIError("VALIDATION_ERROR", "skill is required.", 422)
    return ok(to_jsonable(await ls.recommend_resources_for_skill(skill.strip())))


@router.post("/practice", status_code=201)
async def practice(body: LearningPracticeRequest, request: Request) -> dict:
    _, ls, uid = _learning(request)
    return ok(to_jsonable(ls.generate_practice_task(uid, skill=body.skill)))


@router.get("/project")
async def project(request: Request) -> dict:
    _, ls, uid = _learning(request)
    return ok(to_jsonable(ls.generate_project(uid)))


@router.post("/activity")
async def activity(body: LearningActivityRequest, request: Request) -> dict:
    _, ls, uid = _learning(request)
    result: dict[str, Any]
    if body.action == "complete_task":
        if not body.task_id:
            raise APIError("VALIDATION_ERROR", "task_id is required.", 422)
        found = ls.mark_task_complete(uid, body.task_id)
        if not found:
            raise APIError("TASK_NOT_FOUND", "No matching task in the active plan.", 404)
        result = {"completed": body.task_id}
    else:
        if not body.text:
            raise APIError("VALIDATION_ERROR", "text is required for intake.", 422)
        result = {"extracted": to_jsonable(ls.process_intake(uid, body.text))}
    return ok(result, "Activity recorded")
