"""Canonical domain models and data structures for the LYRA Adaptive Learning Agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import uuid

from lyra.core.exceptions import ModelValidationError


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _parse_dt(val: Any) -> datetime:
    if isinstance(val, datetime):
        return val if val.tzinfo is not None else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str) and val.strip():
        try:
            parsed = datetime.fromisoformat(val)
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return _utc_now()


class SkillLevel(str, Enum):
    """Standardized competency and difficulty tiers."""

    BEGINNER = "beginner"
    ELEMENTARY = "elementary"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"

    @property
    def rank(self) -> int:
        """Numeric rank for distance/gap calculation."""
        ranks = {
            SkillLevel.BEGINNER: 1,
            SkillLevel.ELEMENTARY: 2,
            SkillLevel.INTERMEDIATE: 3,
            SkillLevel.ADVANCED: 4,
            SkillLevel.EXPERT: 5,
        }
        return ranks[self]

    @classmethod
    def from_rank(cls, rank: int) -> SkillLevel:
        clamped = max(1, min(5, rank))
        mapping = {
            1: cls.BEGINNER,
            2: cls.ELEMENTARY,
            3: cls.INTERMEDIATE,
            4: cls.ADVANCED,
            5: cls.EXPERT,
        }
        return mapping[clamped]

    @classmethod
    def from_str(cls, val: str | SkillLevel) -> SkillLevel:
        if isinstance(val, SkillLevel):
            return val
        norm = str(val).strip().lower()
        aliases = {
            "basic": cls.BEGINNER,
            "novice": cls.BEGINNER,
            "started": cls.BEGINNER,
            "beginner": cls.BEGINNER,
            "elementary": cls.ELEMENTARY,
            "foundational": cls.ELEMENTARY,
            "medium": cls.INTERMEDIATE,
            "intermediate": cls.INTERMEDIATE,
            "proficient": cls.ADVANCED,
            "advanced": cls.ADVANCED,
            "master": cls.EXPERT,
            "expert": cls.EXPERT,
        }
        if norm in aliases:
            return aliases[norm]
        for member in cls:
            if member.value == norm:
                return member
        return cls.BEGINNER


class EvidenceSource(str, Enum):
    """Origin category of learning and skill evidence."""

    SELF_REPORTED = "self_reported"
    DOCUMENT_EVIDENCE = "document_evidence"
    ASSESSED = "assessed"
    INFERRED = "inferred"


class ObjectiveStatus(str, Enum):
    """Progression state of learning objectives and topics."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"


class ResourceType(str, Enum):
    """Catalog types for learning materials."""

    DOCUMENTATION = "documentation"
    TUTORIAL = "tutorial"
    COURSE = "course"
    VIDEO = "video"
    ARTICLE = "article"
    BOOK = "book"
    INTERACTIVE_EXERCISE = "interactive_exercise"
    PRACTICE_PLATFORM = "practice_platform"
    PROJECT = "project"


class TaskType(str, Enum):
    """Categorization of practice and assessment tasks."""

    MCQ = "mcq"
    CODING_PROBLEM = "coding_problem"
    DEBUGGING_PROBLEM = "debugging_problem"
    CONCEPTUAL_QUESTION = "conceptual_question"
    IMPLEMENTATION_TASK = "implementation_task"
    MINI_PROJECT = "mini_project"
    SYSTEM_DESIGN_TASK = "system_design_task"
    REAL_WORLD_SCENARIO = "real_world_scenario"
    INTERVIEW_QUESTION = "interview_question"


class ActivityType(str, Enum):
    """Learning activity types for granular telemetry."""

    STUDY = "study"
    PRACTICE = "practice"
    PROJECT = "project"
    QUIZ = "quiz"
    REVISION = "revision"
    QUESTION = "question"
    ASSESSMENT = "assessment"


@dataclass
class SkillEvidence:
    """Concrete evidence entry grounding learner skill assessment."""

    skill: str
    source: EvidenceSource | str
    evidence: str
    confidence: float = 0.70
    created_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if isinstance(self.source, str):
            self.source = EvidenceSource(self.source)
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "source": self.source.value if isinstance(self.source, EvidenceSource) else str(self.source),
            "evidence": self.evidence,
            "confidence": self.confidence,
            "created_at": _iso(self.created_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillEvidence:
        return cls(
            skill=data["skill"],
            source=EvidenceSource(data.get("source", EvidenceSource.INFERRED.value)),
            evidence=data.get("evidence", ""),
            confidence=float(data.get("confidence", 0.7)),
            created_at=_parse_dt(data.get("created_at")),
        )


@dataclass
class SkillLevelRecord:
    """Granular skill representation distinguishing self-reported from demonstrated level."""

    skill: str
    self_reported_level: SkillLevel | None = None
    assessed_level: SkillLevel = SkillLevel.BEGINNER
    confidence: float = 0.5
    evidence: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if isinstance(self.self_reported_level, str):
            self.self_reported_level = SkillLevel.from_str(self.self_reported_level)
        if isinstance(self.assessed_level, str):
            self.assessed_level = SkillLevel.from_str(self.assessed_level)
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "self_reported_level": self.self_reported_level.value if self.self_reported_level else None,
            "assessed_level": self.assessed_level.value,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "updated_at": _iso(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillLevelRecord:
        sr = data.get("self_reported_level")
        return cls(
            skill=data["skill"],
            self_reported_level=SkillLevel.from_str(sr) if sr else None,
            assessed_level=SkillLevel.from_str(data.get("assessed_level", SkillLevel.BEGINNER)),
            confidence=float(data.get("confidence", 0.5)),
            evidence=list(data.get("evidence", [])),
            updated_at=_parse_dt(data.get("updated_at")),
        )


@dataclass
class Skill:
    """Standardized entry in the global or domain skill taxonomy."""

    id: str
    name: str
    category: str
    prerequisites: list[str] = field(default_factory=list)
    related_skills: list[str] = field(default_factory=list)
    difficulty: SkillLevel = SkillLevel.BEGINNER
    description: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.difficulty, str):
            self.difficulty = SkillLevel.from_str(self.difficulty)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "prerequisites": list(self.prerequisites),
            "related_skills": list(self.related_skills),
            "difficulty": self.difficulty.value,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Skill:
        return cls(
            id=data["id"],
            name=data["name"],
            category=data.get("category", "General"),
            prerequisites=list(data.get("prerequisites", [])),
            related_skills=list(data.get("related_skills", [])),
            difficulty=SkillLevel.from_str(data.get("difficulty", SkillLevel.BEGINNER)),
            description=data.get("description", ""),
        )


@dataclass
class TargetRole:
    """Target career role requirements and progression blueprint."""

    role_name: str
    required_skills: dict[str, SkillLevel] = field(default_factory=dict)
    preferred_skills: dict[str, SkillLevel] = field(default_factory=dict)
    typical_tasks: list[str] = field(default_factory=list)
    learning_dependencies: dict[str, list[str]] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "role_name": self.role_name,
            "required_skills": {k: v.value for k, v in self.required_skills.items()},
            "preferred_skills": {k: v.value for k, v in self.preferred_skills.items()},
            "typical_tasks": list(self.typical_tasks),
            "learning_dependencies": {k: list(v) for k, v in self.learning_dependencies.items()},
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TargetRole:
        req = {k: SkillLevel.from_str(v) for k, v in data.get("required_skills", {}).items()}
        pref = {k: SkillLevel.from_str(v) for k, v in data.get("preferred_skills", {}).items()}
        return cls(
            role_name=data["role_name"],
            required_skills=req,
            preferred_skills=pref,
            typical_tasks=list(data.get("typical_tasks", [])),
            learning_dependencies=dict(data.get("learning_dependencies", {})),
            description=data.get("description", ""),
        )


@dataclass
class SkillGap:
    """Difference between current assessed competency and target role expectation."""

    skill: str
    current_level: SkillLevel | None
    required_level: SkillLevel
    gap_size: int  # required_rank - current_rank
    priority: int  # 1 (highest) to 5 (lowest)
    evidence: list[str] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)
    recommended_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "current_level": self.current_level.value if self.current_level else None,
            "required_level": self.required_level.value,
            "gap_size": self.gap_size,
            "priority": self.priority,
            "evidence": list(self.evidence),
            "prerequisites": list(self.prerequisites),
            "recommended_action": self.recommended_action,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillGap:
        cur = data.get("current_level")
        return cls(
            skill=data["skill"],
            current_level=SkillLevel.from_str(cur) if cur else None,
            required_level=SkillLevel.from_str(data.get("required_level", SkillLevel.BEGINNER)),
            gap_size=int(data.get("gap_size", 1)),
            priority=int(data.get("priority", 3)),
            evidence=list(data.get("evidence", [])),
            prerequisites=list(data.get("prerequisites", [])),
            recommended_action=data.get("recommended_action", ""),
        )


@dataclass
class LearningObjective:
    """Atomic, measurable learning step addressing a skill gap."""

    id: str
    skill: str
    title: str
    description: str
    prerequisites: list[str] = field(default_factory=list)
    difficulty: SkillLevel = SkillLevel.BEGINNER
    estimated_time_minutes: int = 60
    status: ObjectiveStatus = ObjectiveStatus.NOT_STARTED
    mastery_level: float = 0.0

    def __post_init__(self) -> None:
        if isinstance(self.difficulty, str):
            self.difficulty = SkillLevel.from_str(self.difficulty)
        if isinstance(self.status, str):
            self.status = ObjectiveStatus(self.status)
        self.mastery_level = max(0.0, min(1.0, float(self.mastery_level)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "skill": self.skill,
            "title": self.title,
            "description": self.description,
            "prerequisites": list(self.prerequisites),
            "difficulty": self.difficulty.value,
            "estimated_time_minutes": self.estimated_time_minutes,
            "status": self.status.value,
            "mastery_level": self.mastery_level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LearningObjective:
        return cls(
            id=data["id"],
            skill=data["skill"],
            title=data.get("title", ""),
            description=data.get("description", ""),
            prerequisites=list(data.get("prerequisites", [])),
            difficulty=SkillLevel.from_str(data.get("difficulty", SkillLevel.BEGINNER)),
            estimated_time_minutes=int(data.get("estimated_time_minutes", 60)),
            status=ObjectiveStatus(data.get("status", ObjectiveStatus.NOT_STARTED.value)),
            mastery_level=float(data.get("mastery_level", 0.0)),
        )


@dataclass
class LearningResource:
    """Curated or verified educational material."""

    title: str
    type: ResourceType = ResourceType.DOCUMENTATION
    url: str = ""
    provider: str = ""
    difficulty: SkillLevel = SkillLevel.BEGINNER
    estimated_time_minutes: int = 45
    topic: str = ""
    reason: str = ""
    quality_score: float = 0.9

    def __post_init__(self) -> None:
        if isinstance(self.type, str):
            self.type = ResourceType(self.type)
        if isinstance(self.difficulty, str):
            self.difficulty = SkillLevel.from_str(self.difficulty)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "type": self.type.value,
            "url": self.url,
            "provider": self.provider,
            "difficulty": self.difficulty.value,
            "estimated_time_minutes": self.estimated_time_minutes,
            "topic": self.topic,
            "reason": self.reason,
            "quality_score": self.quality_score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LearningResource:
        return cls(
            title=data["title"],
            type=ResourceType(data.get("type", ResourceType.DOCUMENTATION.value)),
            url=data.get("url", ""),
            provider=data.get("provider", ""),
            difficulty=SkillLevel.from_str(data.get("difficulty", SkillLevel.BEGINNER)),
            estimated_time_minutes=int(data.get("estimated_time_minutes", 45)),
            topic=data.get("topic", ""),
            reason=data.get("reason", ""),
            quality_score=float(data.get("quality_score", 0.9)),
        )


@dataclass
class PracticeTask:
    """Targeted exercise generated to assess and reinforce a specific skill."""

    task_id: str
    skill: str
    level: SkillLevel
    task_type: TaskType
    title: str
    prompt: str
    starter_code: str | None = None
    expected_criteria: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    solution_explanation: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.level, str):
            self.level = SkillLevel.from_str(self.level)
        if isinstance(self.task_type, str):
            self.task_type = TaskType(self.task_type)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "skill": self.skill,
            "level": self.level.value,
            "task_type": self.task_type.value,
            "title": self.title,
            "prompt": self.prompt,
            "starter_code": self.starter_code,
            "expected_criteria": list(self.expected_criteria),
            "hints": list(self.hints),
            "solution_explanation": self.solution_explanation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PracticeTask:
        return cls(
            task_id=data["task_id"],
            skill=data["skill"],
            level=SkillLevel.from_str(data.get("level", SkillLevel.BEGINNER)),
            task_type=TaskType(data.get("task_type", TaskType.CODING_PROBLEM.value)),
            title=data.get("title", ""),
            prompt=data.get("prompt", ""),
            starter_code=data.get("starter_code"),
            expected_criteria=list(data.get("expected_criteria", [])),
            hints=list(data.get("hints", [])),
            solution_explanation=data.get("solution_explanation", ""),
        )


@dataclass
class PracticeResult:
    """Outcome of an evaluated practice task submission."""

    task_id: str
    learner_id: str
    skill: str
    submission: str
    passed: bool
    score: float  # 0.0 - 1.0
    feedback: str
    mistakes: list[str] = field(default_factory=list)
    evaluated_at: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "learner_id": self.learner_id,
            "skill": self.skill,
            "submission": self.submission,
            "passed": self.passed,
            "score": self.score,
            "feedback": self.feedback,
            "mistakes": list(self.mistakes),
            "evaluated_at": _iso(self.evaluated_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PracticeResult:
        return cls(
            task_id=data["task_id"],
            learner_id=data["learner_id"],
            skill=data["skill"],
            submission=data.get("submission", ""),
            passed=bool(data.get("passed", False)),
            score=float(data.get("score", 0.0)),
            feedback=data.get("feedback", ""),
            mistakes=list(data.get("mistakes", [])),
            evaluated_at=_parse_dt(data.get("evaluated_at")),
        )


@dataclass
class ProjectSpecification:
    """Progressive milestone project to consolidate acquired competencies."""

    project_id: str
    title: str
    difficulty: SkillLevel
    objective: str
    requirements: list[str] = field(default_factory=list)
    technologies: list[str] = field(default_factory=list)
    expected_features: list[str] = field(default_factory=list)
    milestones: list[str] = field(default_factory=list)
    evaluation_criteria: list[str] = field(default_factory=list)
    skills_practiced: list[str] = field(default_factory=list)
    extension_ideas: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.difficulty, str):
            self.difficulty = SkillLevel.from_str(self.difficulty)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "title": self.title,
            "difficulty": self.difficulty.value,
            "objective": self.objective,
            "requirements": list(self.requirements),
            "technologies": list(self.technologies),
            "expected_features": list(self.expected_features),
            "milestones": list(self.milestones),
            "evaluation_criteria": list(self.evaluation_criteria),
            "skills_practiced": list(self.skills_practiced),
            "extension_ideas": list(self.extension_ideas),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectSpecification:
        return cls(
            project_id=data["project_id"],
            title=data.get("title", ""),
            difficulty=SkillLevel.from_str(data.get("difficulty", SkillLevel.BEGINNER)),
            objective=data.get("objective", ""),
            requirements=list(data.get("requirements", [])),
            technologies=list(data.get("technologies", [])),
            expected_features=list(data.get("expected_features", [])),
            milestones=list(data.get("milestones", [])),
            evaluation_criteria=list(data.get("evaluation_criteria", [])),
            skills_practiced=list(data.get("skills_practiced", [])),
            extension_ideas=list(data.get("extension_ideas", [])),
        )


@dataclass
class LearningActivity:
    """Historical telemetry record for a completed or attempted study action."""

    activity_id: str
    learner_id: str
    type: ActivityType
    skill: str
    objective_id: str | None = None
    started_at: datetime = field(default_factory=_utc_now)
    completed_at: datetime | None = None
    duration_minutes: int = 0
    score: float | None = None
    difficulty: SkillLevel = SkillLevel.BEGINNER
    result: str = ""
    mistakes: list[str] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.type, str):
            self.type = ActivityType(self.type)
        if isinstance(self.difficulty, str):
            self.difficulty = SkillLevel.from_str(self.difficulty)

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "learner_id": self.learner_id,
            "type": self.type.value,
            "skill": self.skill,
            "objective_id": self.objective_id,
            "started_at": _iso(self.started_at),
            "completed_at": _iso(self.completed_at),
            "duration_minutes": self.duration_minutes,
            "score": self.score,
            "difficulty": self.difficulty.value,
            "result": self.result,
            "mistakes": list(self.mistakes),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LearningActivity:
        return cls(
            activity_id=data["activity_id"],
            learner_id=data["learner_id"],
            type=ActivityType(data.get("type", ActivityType.STUDY.value)),
            skill=data.get("skill", ""),
            objective_id=data.get("objective_id"),
            started_at=_parse_dt(data.get("started_at")),
            completed_at=_parse_dt(data.get("completed_at")) if data.get("completed_at") else None,
            duration_minutes=int(data.get("duration_minutes", 0)),
            score=float(data["score"]) if data.get("score") is not None else None,
            difficulty=SkillLevel.from_str(data.get("difficulty", SkillLevel.BEGINNER)),
            result=data.get("result", ""),
            mistakes=list(data.get("mistakes", [])),
            notes=data.get("notes", ""),
        )


@dataclass
class SkillMasteryRecord:
    """Estimated mastery assessment grounded in multiple evidence types."""

    learner_id: str
    skill: str
    mastery_score: float = 0.0  # 0.0 to 1.0
    confidence: float = 0.5     # 0.0 to 1.0
    evidence_count: int = 0
    last_assessed: datetime = field(default_factory=_utc_now)
    weaknesses: list[str] = field(default_factory=list)
    status: ObjectiveStatus = ObjectiveStatus.NOT_STARTED

    def __post_init__(self) -> None:
        self.mastery_score = max(0.0, min(1.0, float(self.mastery_score)))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        if isinstance(self.status, str):
            self.status = ObjectiveStatus(self.status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "learner_id": self.learner_id,
            "skill": self.skill,
            "mastery_score": self.mastery_score,
            "confidence": self.confidence,
            "evidence_count": self.evidence_count,
            "last_assessed": _iso(self.last_assessed),
            "weaknesses": list(self.weaknesses),
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillMasteryRecord:
        return cls(
            learner_id=data["learner_id"],
            skill=data["skill"],
            mastery_score=float(data.get("mastery_score", 0.0)),
            confidence=float(data.get("confidence", 0.5)),
            evidence_count=int(data.get("evidence_count", 0)),
            last_assessed=_parse_dt(data.get("last_assessed")),
            weaknesses=list(data.get("weaknesses", [])),
            status=ObjectiveStatus(data.get("status", ObjectiveStatus.NOT_STARTED.value)),
        )


@dataclass
class StruggleRecord:
    """Detected persistent difficulty, recurring mistake, or misconception."""

    struggle_id: str
    learner_id: str
    skill: str
    concept_or_topic: str
    signals: list[str] = field(default_factory=list)
    failure_count: int = 1
    consecutive_failures: int = 1
    first_detected: datetime = field(default_factory=_utc_now)
    last_detected: datetime = field(default_factory=_utc_now)
    resolved: bool = False
    remedial_actions_taken: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "struggle_id": self.struggle_id,
            "learner_id": self.learner_id,
            "skill": self.skill,
            "concept_or_topic": self.concept_or_topic,
            "signals": list(self.signals),
            "failure_count": self.failure_count,
            "consecutive_failures": self.consecutive_failures,
            "first_detected": _iso(self.first_detected),
            "last_detected": _iso(self.last_detected),
            "resolved": self.resolved,
            "remedial_actions_taken": list(self.remedial_actions_taken),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StruggleRecord:
        return cls(
            struggle_id=data["struggle_id"],
            learner_id=data["learner_id"],
            skill=data["skill"],
            concept_or_topic=data.get("concept_or_topic", ""),
            signals=list(data.get("signals", [])),
            failure_count=int(data.get("failure_count", 1)),
            consecutive_failures=int(data.get("consecutive_failures", 1)),
            first_detected=_parse_dt(data.get("first_detected")),
            last_detected=_parse_dt(data.get("last_detected")),
            resolved=bool(data.get("resolved", False)),
            remedial_actions_taken=list(data.get("remedial_actions_taken", [])),
        )


@dataclass
class DailyPlan:
    """A day's structured learning schedule strictly bounded by time."""

    day: str  # e.g., "Monday", "Day 1"
    objectives: list[str] = field(default_factory=list)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    total_minutes: int = 0
    date_str: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "objectives": list(self.objectives),
            "tasks": list(self.tasks),
            "total_minutes": self.total_minutes,
            "date_str": self.date_str,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DailyPlan:
        return cls(
            day=data.get("day", "Day"),
            objectives=list(data.get("objectives", [])),
            tasks=list(data.get("tasks", [])),
            total_minutes=int(data.get("total_minutes", 0)),
            date_str=data.get("date_str"),
        )


@dataclass
class WeekPlan:
    """Weekly sprint with daily allocations and target milestone."""

    week_number: int
    theme: str
    days: list[DailyPlan] = field(default_factory=list)
    target_weekly_minutes: int = 480
    milestone: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "week_number": self.week_number,
            "theme": self.theme,
            "days": [d.to_dict() for d in self.days],
            "target_weekly_minutes": self.target_weekly_minutes,
            "milestone": self.milestone,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WeekPlan:
        days = [DailyPlan.from_dict(d) for d in data.get("days", [])]
        return cls(
            week_number=int(data.get("week_number", 1)),
            theme=data.get("theme", ""),
            days=days,
            target_weekly_minutes=int(data.get("target_weekly_minutes", 480)),
            milestone=data.get("milestone", ""),
        )


@dataclass
class LearningPlan:
    """Full personalized, multi-week adaptive learning curriculum."""

    plan_id: str
    learner_id: str
    target_role: str
    duration_weeks: int = 8
    weekly_hours: float = 8.0
    weeks: list[WeekPlan] = field(default_factory=list)
    objectives: list[str] = field(default_factory=list)
    milestones: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    status: str = "active"

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "learner_id": self.learner_id,
            "target_role": self.target_role,
            "duration_weeks": self.duration_weeks,
            "weekly_hours": self.weekly_hours,
            "weeks": [w.to_dict() for w in self.weeks],
            "objectives": list(self.objectives),
            "milestones": list(self.milestones),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LearningPlan:
        weeks = [WeekPlan.from_dict(w) for w in data.get("weeks", [])]
        return cls(
            plan_id=data["plan_id"],
            learner_id=data["learner_id"],
            target_role=data.get("target_role", "Software Engineer"),
            duration_weeks=int(data.get("duration_weeks", 8)),
            weekly_hours=float(data.get("weekly_hours", 8.0)),
            weeks=weeks,
            objectives=list(data.get("objectives", [])),
            milestones=list(data.get("milestones", [])),
            created_at=_parse_dt(data.get("created_at")),
            updated_at=_parse_dt(data.get("updated_at")),
            status=data.get("status", "active"),
        )


@dataclass
class ProgressReport:
    """Comprehensive progress evaluation summarizing skills, gaps, and next actions."""

    learner_id: str
    target_role: str
    skills_acquired: list[str] = field(default_factory=list)
    skills_in_progress: list[str] = field(default_factory=list)
    remaining_gaps: list[str] = field(default_factory=list)
    weak_areas: list[str] = field(default_factory=list)
    completed_objectives: list[str] = field(default_factory=list)
    projects_completed: list[str] = field(default_factory=list)
    practice_performance_summary: str = ""
    learning_consistency: str = ""
    recommended_next_steps: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "learner_id": self.learner_id,
            "target_role": self.target_role,
            "skills_acquired": list(self.skills_acquired),
            "skills_in_progress": list(self.skills_in_progress),
            "remaining_gaps": list(self.remaining_gaps),
            "weak_areas": list(self.weak_areas),
            "completed_objectives": list(self.completed_objectives),
            "projects_completed": list(self.projects_completed),
            "practice_performance_summary": self.practice_performance_summary,
            "learning_consistency": self.learning_consistency,
            "recommended_next_steps": list(self.recommended_next_steps),
            "generated_at": _iso(self.generated_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProgressReport:
        return cls(
            learner_id=data["learner_id"],
            target_role=data.get("target_role", ""),
            skills_acquired=list(data.get("skills_acquired", [])),
            skills_in_progress=list(data.get("skills_in_progress", [])),
            remaining_gaps=list(data.get("remaining_gaps", [])),
            weak_areas=list(data.get("weak_areas", [])),
            completed_objectives=list(data.get("completed_objectives", [])),
            projects_completed=list(data.get("projects_completed", [])),
            practice_performance_summary=data.get("practice_performance_summary", ""),
            learning_consistency=data.get("learning_consistency", ""),
            recommended_next_steps=list(data.get("recommended_next_steps", [])),
            generated_at=_parse_dt(data.get("generated_at")),
        )


@dataclass
class LearnerProfile:
    """Core domain model representing a learner's abilities, goals, and history."""

    learner_id: str
    name: str = "Learner"
    current_skills: list[str] = field(default_factory=list)
    skill_levels: dict[str, SkillLevelRecord] = field(default_factory=dict)
    experience: str = ""
    education: str = ""
    target_role: str = ""
    career_goal: str = ""
    preferred_learning_style: str = "hands-on"
    weekly_learning_hours: float = 8.0
    preferred_languages: list[str] = field(default_factory=list)
    preferred_resources: list[str] = field(default_factory=list)
    completed_topics: list[str] = field(default_factory=list)
    topics_in_progress: list[str] = field(default_factory=list)
    weak_topics: list[str] = field(default_factory=list)
    strong_topics: list[str] = field(default_factory=list)
    projects_completed: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    resume_summary: str = ""
    portfolio_summary: str = ""
    current_learning_plan_id: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def get_effective_level(self, skill: str) -> SkillLevel | None:
        """Retrieve the assessed skill level, or beginner if only self-reported, or None if unknown."""
        norm = skill.strip().lower()
        for k, record in self.skill_levels.items():
            if k.strip().lower() == norm:
                return record.assessed_level
        if any(s.strip().lower() == norm for s in self.current_skills):
            return SkillLevel.BEGINNER
        return None

    def add_or_update_skill(
        self,
        skill: str,
        self_reported: SkillLevel | str | None = None,
        assessed: SkillLevel | str | None = None,
        confidence: float = 0.5,
        evidence_item: str | None = None,
    ) -> None:
        """Safely register or update skill record without blindly trusting claims."""
        clean_skill = skill.strip()
        sr = SkillLevel.from_str(self_reported) if self_reported else None
        as_lvl = SkillLevel.from_str(assessed) if assessed else (sr or SkillLevel.BEGINNER)

        if clean_skill not in self.skill_levels:
            ev_list = [evidence_item] if evidence_item else []
            self.skill_levels[clean_skill] = SkillLevelRecord(
                skill=clean_skill,
                self_reported_level=sr,
                assessed_level=as_lvl,
                confidence=confidence,
                evidence=ev_list,
                updated_at=_utc_now(),
            )
        else:
            rec = self.skill_levels[clean_skill]
            if sr is not None:
                rec.self_reported_level = sr
            if assessed is not None:
                rec.assessed_level = as_lvl
                rec.confidence = confidence
            if evidence_item and evidence_item not in rec.evidence:
                rec.evidence.append(evidence_item)
            rec.updated_at = _utc_now()

        if clean_skill not in self.current_skills:
            self.current_skills.append(clean_skill)
        self.updated_at = _utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "learner_id": self.learner_id,
            "name": self.name,
            "current_skills": list(self.current_skills),
            "skill_levels": {k: v.to_dict() for k, v in self.skill_levels.items()},
            "experience": self.experience,
            "education": self.education,
            "target_role": self.target_role,
            "career_goal": self.career_goal,
            "preferred_learning_style": self.preferred_learning_style,
            "weekly_learning_hours": self.weekly_learning_hours,
            "preferred_languages": list(self.preferred_languages),
            "preferred_resources": list(self.preferred_resources),
            "completed_topics": list(self.completed_topics),
            "topics_in_progress": list(self.topics_in_progress),
            "weak_topics": list(self.weak_topics),
            "strong_topics": list(self.strong_topics),
            "projects_completed": list(self.projects_completed),
            "certifications": list(self.certifications),
            "resume_summary": self.resume_summary,
            "portfolio_summary": self.portfolio_summary,
            "current_learning_plan_id": self.current_learning_plan_id,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LearnerProfile:
        sl_raw = data.get("skill_levels", {})
        skill_levels = {k: SkillLevelRecord.from_dict(v) for k, v in sl_raw.items()}
        return cls(
            learner_id=data["learner_id"],
            name=data.get("name", "Learner"),
            current_skills=list(data.get("current_skills", [])),
            skill_levels=skill_levels,
            experience=data.get("experience", ""),
            education=data.get("education", ""),
            target_role=data.get("target_role", ""),
            career_goal=data.get("career_goal", ""),
            preferred_learning_style=data.get("preferred_learning_style", "hands-on"),
            weekly_learning_hours=float(data.get("weekly_learning_hours", 8.0)),
            preferred_languages=list(data.get("preferred_languages", [])),
            preferred_resources=list(data.get("preferred_resources", [])),
            completed_topics=list(data.get("completed_topics", [])),
            topics_in_progress=list(data.get("topics_in_progress", [])),
            weak_topics=list(data.get("weak_topics", [])),
            strong_topics=list(data.get("strong_topics", [])),
            projects_completed=list(data.get("projects_completed", [])),
            certifications=list(data.get("certifications", [])),
            resume_summary=data.get("resume_summary", ""),
            portfolio_summary=data.get("portfolio_summary", ""),
            current_learning_plan_id=data.get("current_learning_plan_id"),
            created_at=_parse_dt(data.get("created_at")),
            updated_at=_parse_dt(data.get("updated_at")),
        )
