"""Pydantic request models for the LYRA API (responses use the standard envelope)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: str | None = Field(None, max_length=64)


class TaskCreateRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=8000)
    session_id: str | None = Field(None, max_length=64)


class SessionCreateRequest(BaseModel):
    title: str | None = Field(None, max_length=120)


class SessionUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)


class MemoryCreateRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    type: str = Field("fact", max_length=40)
    importance: float = Field(0.6, ge=0.0, le=1.0)
    confidence: float = Field(0.95, ge=0.0, le=1.0)


class MemoryUpdateRequest(BaseModel):
    content: str | None = Field(None, min_length=1, max_length=2000)
    type: str | None = Field(None, max_length=40)
    importance: float | None = Field(None, ge=0.0, le=1.0)
    confidence: float | None = Field(None, ge=0.0, le=1.0)


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    voice: str | None = Field(None, max_length=80)


class SettingsUpdateRequest(BaseModel):
    offline_mode: bool | None = None
    emotional_awareness: bool | None = None
    audio_event_detection: bool | None = None
    cough_detection: bool | None = None
    voice: str | None = Field(None, max_length=80)
    speech_rate: int | None = Field(None, ge=120, le=260)
    screen_awareness: bool | None = None
    vision_cloud_consent: bool | None = None


class DocumentAnalyzeRequest(BaseModel):
    mode: Literal["summary", "resume"] = "summary"
    session_id: str | None = Field(None, max_length=64)
    question: str | None = Field(None, max_length=2000)


class LearningProfileUpdate(BaseModel):
    name: str | None = Field(None, max_length=120)
    target_role: str | None = Field(None, max_length=120)
    career_goal: str | None = Field(None, max_length=500)
    experience: str | None = Field(None, max_length=2000)
    education: str | None = Field(None, max_length=1000)
    preferred_learning_style: str | None = Field(None, max_length=60)
    weekly_learning_hours: float | None = Field(None, ge=0, le=100)
    preferred_languages: list[str] | None = None
    preferred_resources: list[str] | None = None
    weak_topics: list[str] | None = None
    strong_topics: list[str] | None = None


class LearningSkillRequest(BaseModel):
    skill: str = Field(..., min_length=1, max_length=120)
    level: Literal["beginner", "elementary", "intermediate", "advanced", "expert"] | None = None
    evidence: str | None = Field(None, max_length=500)


class LearningPlanRequest(BaseModel):
    duration_weeks: int = Field(8, ge=1, le=52)
    target_role: str | None = Field(None, max_length=120)


class LearningActivityRequest(BaseModel):
    action: Literal["complete_task", "intake"] = "complete_task"
    task_id: str | None = Field(None, max_length=200)
    text: str | None = Field(None, max_length=4000)


class LearningPracticeRequest(BaseModel):
    skill: str | None = Field(None, max_length=120)


class Envelope(BaseModel):
    success: bool
    data: Any = None
    message: str | None = None


class VisionAnalyzeRequest(BaseModel):
    question: str | None = Field(None, max_length=2000)
    session_id: str | None = Field(None, max_length=64)
    target: Literal["screen", "active_window"] = "screen"
    display: int | None = Field(None, ge=1, le=16)
    use_ai: bool = True


class VisionCaptureRequest(BaseModel):
    session_id: str | None = Field(None, max_length=64)
    target: Literal["screen", "active_window"] = "screen"
    display: int | None = Field(None, ge=1, le=16)


class VisionCommandRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = Field(None, max_length=64)


class VisionMonitorRequest(BaseModel):
    interval_seconds: float | None = Field(None, ge=2, le=60)


class VisionSettingsRequest(BaseModel):
    enabled: bool | None = None
    cloud_consent: bool | None = None
