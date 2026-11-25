"""SQLite-backed persistence repository for LYRA Adaptive Learning Agent."""

from __future__ import annotations

from abc import ABC, abstractmethod
import json
import sqlite3
import threading
from typing import Any
import uuid

from lyra.core.exceptions import LearningStorageError
from lyra.learning.models import (
    LearnerProfile,
    LearningActivity,
    LearningObjective,
    LearningPlan,
    LearningResource,
    PracticeResult,
    PracticeTask,
    ProgressReport,
    ProjectSpecification,
    Skill,
    SkillEvidence,
    SkillGap,
    SkillMasteryRecord,
    StruggleRecord,
    TargetRole,
    _iso,
    _parse_dt,
    _utc_now,
)
from lyra.observability.logging import get_logger

logger = get_logger("learning.repository")


class LearningRepository(ABC):
    """Abstract interface for storing learning models."""

    @abstractmethod
    def get_learner_profile(self, learner_id: str) -> LearnerProfile | None: ...

    @abstractmethod
    def save_learner_profile(self, profile: LearnerProfile) -> None: ...

    @abstractmethod
    def list_skills(self) -> list[Skill]: ...

    @abstractmethod
    def save_skill(self, skill: Skill) -> None: ...

    @abstractmethod
    def get_skill(self, skill_id: str) -> Skill | None: ...

    @abstractmethod
    def list_target_roles(self) -> list[TargetRole]: ...

    @abstractmethod
    def get_target_role(self, role_name: str) -> TargetRole | None: ...

    @abstractmethod
    def save_target_role(self, role: TargetRole) -> None: ...

    @abstractmethod
    def add_skill_evidence(self, learner_id: str, evidence: SkillEvidence) -> None: ...

    @abstractmethod
    def list_skill_evidence(self, learner_id: str, skill: str | None = None) -> list[SkillEvidence]: ...

    @abstractmethod
    def save_skill_gaps(self, learner_id: str, gaps: list[SkillGap]) -> None: ...

    @abstractmethod
    def get_skill_gaps(self, learner_id: str) -> list[SkillGap]: ...

    @abstractmethod
    def save_learning_plan(self, plan: LearningPlan) -> None: ...

    @abstractmethod
    def get_learning_plan(self, plan_id: str) -> LearningPlan | None: ...

    @abstractmethod
    def get_active_learning_plan(self, learner_id: str) -> LearningPlan | None: ...

    @abstractmethod
    def record_activity(self, activity: LearningActivity) -> None: ...

    @abstractmethod
    def list_activities(self, learner_id: str, limit: int = 50) -> list[LearningActivity]: ...

    @abstractmethod
    def save_mastery(self, record: SkillMasteryRecord) -> None: ...

    @abstractmethod
    def get_mastery(self, learner_id: str, skill: str) -> SkillMasteryRecord | None: ...

    @abstractmethod
    def list_mastery(self, learner_id: str) -> list[SkillMasteryRecord]: ...

    @abstractmethod
    def save_struggle(self, struggle: StruggleRecord) -> None: ...

    @abstractmethod
    def get_active_struggles(self, learner_id: str) -> list[StruggleRecord]: ...

    @abstractmethod
    def record_practice_result(self, result: PracticeResult) -> None: ...

    @abstractmethod
    def list_practice_results(self, learner_id: str, skill: str | None = None) -> list[PracticeResult]: ...

    @abstractmethod
    def save_progress_report(self, report: ProgressReport) -> None: ...

    @abstractmethod
    def get_latest_progress_report(self, learner_id: str) -> ProgressReport | None: ...


class SQLiteLearningRepository(LearningRepository):
    """Thread-safe SQLite repository implementing LearningRepository."""

    def __init__(self, db_path: str = "lyra_learning.db") -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            try:
                self._conn = sqlite3.connect(self.db_path, check_same_thread=False, autocommit=False)
                self._conn.row_factory = sqlite3.Row
            except sqlite3.Error as e:
                raise LearningStorageError(f"Failed to connect to SQLite learning DB: {e}") from e
        return self._conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_conn()
            try:
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS learners (
                            learner_id TEXT PRIMARY KEY,
                            profile_json TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS skills (
                            id TEXT PRIMARY KEY,
                            name TEXT NOT NULL UNIQUE,
                            category TEXT NOT NULL,
                            data_json TEXT NOT NULL
                        )
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS target_roles (
                            role_name TEXT PRIMARY KEY,
                            data_json TEXT NOT NULL
                        )
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS skill_evidence (
                            id TEXT PRIMARY KEY,
                            learner_id TEXT NOT NULL,
                            skill TEXT NOT NULL,
                            source TEXT NOT NULL,
                            evidence TEXT NOT NULL,
                            confidence REAL NOT NULL,
                            created_at TEXT NOT NULL
                        )
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS skill_gaps (
                            id TEXT PRIMARY KEY,
                            learner_id TEXT NOT NULL,
                            skill TEXT NOT NULL,
                            gap_json TEXT NOT NULL,
                            priority INTEGER NOT NULL
                        )
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS learning_objectives (
                            id TEXT PRIMARY KEY,
                            learner_id TEXT NOT NULL,
                            skill TEXT NOT NULL,
                            data_json TEXT NOT NULL,
                            status TEXT NOT NULL
                        )
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS learning_resources (
                            id TEXT PRIMARY KEY,
                            skill TEXT NOT NULL,
                            topic TEXT NOT NULL,
                            data_json TEXT NOT NULL
                        )
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS learning_plans (
                            plan_id TEXT PRIMARY KEY,
                            learner_id TEXT NOT NULL,
                            status TEXT NOT NULL,
                            data_json TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS learning_activities (
                            activity_id TEXT PRIMARY KEY,
                            learner_id TEXT NOT NULL,
                            type TEXT NOT NULL,
                            skill TEXT NOT NULL,
                            data_json TEXT NOT NULL,
                            created_at TEXT NOT NULL
                        )
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS practice_tasks (
                            task_id TEXT PRIMARY KEY,
                            skill TEXT NOT NULL,
                            level TEXT NOT NULL,
                            data_json TEXT NOT NULL
                        )
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS practice_results (
                            id TEXT PRIMARY KEY,
                            task_id TEXT NOT NULL,
                            learner_id TEXT NOT NULL,
                            skill TEXT NOT NULL,
                            passed INTEGER NOT NULL,
                            score REAL NOT NULL,
                            data_json TEXT NOT NULL,
                            evaluated_at TEXT NOT NULL
                        )
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS project_specifications (
                            project_id TEXT PRIMARY KEY,
                            difficulty TEXT NOT NULL,
                            data_json TEXT NOT NULL
                        )
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS mastery_records (
                            learner_id TEXT NOT NULL,
                            skill TEXT NOT NULL,
                            mastery_score REAL NOT NULL,
                            confidence REAL NOT NULL,
                            status TEXT NOT NULL,
                            data_json TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            PRIMARY KEY (learner_id, skill)
                        )
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS struggle_records (
                            struggle_id TEXT PRIMARY KEY,
                            learner_id TEXT NOT NULL,
                            skill TEXT NOT NULL,
                            resolved INTEGER NOT NULL,
                            data_json TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                    """)
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS progress_reports (
                            id TEXT PRIMARY KEY,
                            learner_id TEXT NOT NULL,
                            data_json TEXT NOT NULL,
                            generated_at TEXT NOT NULL
                        )
                    """)

                    # Indices
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_learner ON skill_evidence(learner_id, skill)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_gaps_learner ON skill_gaps(learner_id, priority)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_plans_learner ON learning_plans(learner_id, status)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_activities_learner ON learning_activities(learner_id, created_at DESC)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_practice_results ON practice_results(learner_id, skill)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_struggles_learner ON struggle_records(learner_id, resolved)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_learner ON progress_reports(learner_id, generated_at DESC)")
            except sqlite3.Error as e:
                raise LearningStorageError(f"Failed to initialize learning database schema: {e}") from e

    # Learner Profile CRUD
    def get_learner_profile(self, learner_id: str) -> LearnerProfile | None:
        with self._lock:
            conn = self._get_conn()
            row = conn.execute("SELECT profile_json FROM learners WHERE learner_id = ?", (learner_id,)).fetchone()
            if not row:
                return None
            data = json.loads(row["profile_json"])
            return LearnerProfile.from_dict(data)

    def save_learner_profile(self, profile: LearnerProfile) -> None:
        with self._lock:
            conn = self._get_conn()
            payload = json.dumps(profile.to_dict())
            now_iso = _iso(_utc_now())
            with conn:
                conn.execute("""
                    INSERT INTO learners (learner_id, profile_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(learner_id) DO UPDATE SET
                        profile_json = excluded.profile_json,
                        updated_at = excluded.updated_at
                """, (profile.learner_id, payload, now_iso))

    # Skills Taxonomy CRUD
    def list_skills(self) -> list[Skill]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute("SELECT data_json FROM skills").fetchall()
            return [Skill.from_dict(json.loads(r["data_json"])) for r in rows]

    def save_skill(self, skill: Skill) -> None:
        with self._lock:
            conn = self._get_conn()
            payload = json.dumps(skill.to_dict())
            with conn:
                conn.execute("""
                    INSERT INTO skills (id, name, category, data_json)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        category = excluded.category,
                        data_json = excluded.data_json
                """, (skill.id, skill.name, skill.category, payload))

    def get_skill(self, skill_id: str) -> Skill | None:
        with self._lock:
            conn = self._get_conn()
            row = conn.execute("SELECT data_json FROM skills WHERE id = ? OR name = ?", (skill_id, skill_id)).fetchone()
            if not row:
                return None
            return Skill.from_dict(json.loads(row["data_json"]))

    # Target Roles CRUD
    def list_target_roles(self) -> list[TargetRole]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute("SELECT data_json FROM target_roles").fetchall()
            return [TargetRole.from_dict(json.loads(r["data_json"])) for r in rows]

    def get_target_role(self, role_name: str) -> TargetRole | None:
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT data_json FROM target_roles WHERE LOWER(role_name) = LOWER(?)",
                (role_name.strip(),),
            ).fetchone()
            if not row:
                return None
            return TargetRole.from_dict(json.loads(row["data_json"]))

    def save_target_role(self, role: TargetRole) -> None:
        with self._lock:
            conn = self._get_conn()
            payload = json.dumps(role.to_dict())
            with conn:
                conn.execute("""
                    INSERT INTO target_roles (role_name, data_json)
                    VALUES (?, ?)
                    ON CONFLICT(role_name) DO UPDATE SET
                        data_json = excluded.data_json
                """, (role.role_name, payload))

    # Skill Evidence CRUD
    def add_skill_evidence(self, learner_id: str, evidence: SkillEvidence) -> None:
        with self._lock:
            conn = self._get_conn()
            ev_id = str(uuid.uuid4())
            with conn:
                conn.execute("""
                    INSERT INTO skill_evidence (id, learner_id, skill, source, evidence, confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    ev_id,
                    learner_id,
                    evidence.skill,
                    evidence.source.value if hasattr(evidence.source, "value") else str(evidence.source),
                    evidence.evidence,
                    evidence.confidence,
                    _iso(evidence.created_at),
                ))

    def list_skill_evidence(self, learner_id: str, skill: str | None = None) -> list[SkillEvidence]:
        with self._lock:
            conn = self._get_conn()
            if skill:
                rows = conn.execute(
                    "SELECT skill, source, evidence, confidence, created_at FROM skill_evidence WHERE learner_id = ? AND LOWER(skill) = LOWER(?) ORDER BY created_at DESC",
                    (learner_id, skill.strip()),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT skill, source, evidence, confidence, created_at FROM skill_evidence WHERE learner_id = ? ORDER BY created_at DESC",
                    (learner_id,),
                ).fetchall()
            return [
                SkillEvidence(
                    skill=r["skill"],
                    source=r["source"],
                    evidence=r["evidence"],
                    confidence=float(r["confidence"]),
                    created_at=_parse_dt(r["created_at"]),
                )
                for r in rows
            ]

    # Skill Gaps CRUD
    def save_skill_gaps(self, learner_id: str, gaps: list[SkillGap]) -> None:
        with self._lock:
            conn = self._get_conn()
            with conn:
                conn.execute("DELETE FROM skill_gaps WHERE learner_id = ?", (learner_id,))
                for gap in gaps:
                    gap_id = str(uuid.uuid4())
                    payload = json.dumps(gap.to_dict())
                    conn.execute("""
                        INSERT INTO skill_gaps (id, learner_id, skill, gap_json, priority)
                        VALUES (?, ?, ?, ?, ?)
                    """, (gap_id, learner_id, gap.skill, payload, gap.priority))

    def get_skill_gaps(self, learner_id: str) -> list[SkillGap]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT gap_json FROM skill_gaps WHERE learner_id = ? ORDER BY priority ASC",
                (learner_id,),
            ).fetchall()
            return [SkillGap.from_dict(json.loads(r["gap_json"])) for r in rows]

    # Learning Plan CRUD
    def save_learning_plan(self, plan: LearningPlan) -> None:
        with self._lock:
            conn = self._get_conn()
            payload = json.dumps(plan.to_dict())
            now_iso = _iso(_utc_now())
            with conn:
                conn.execute("""
                    INSERT INTO learning_plans (plan_id, learner_id, status, data_json, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(plan_id) DO UPDATE SET
                        status = excluded.status,
                        data_json = excluded.data_json,
                        updated_at = excluded.updated_at
                """, (plan.plan_id, plan.learner_id, plan.status, payload, now_iso))

    def get_learning_plan(self, plan_id: str) -> LearningPlan | None:
        with self._lock:
            conn = self._get_conn()
            row = conn.execute("SELECT data_json FROM learning_plans WHERE plan_id = ?", (plan_id,)).fetchone()
            if not row:
                return None
            return LearningPlan.from_dict(json.loads(row["data_json"]))

    def get_active_learning_plan(self, learner_id: str) -> LearningPlan | None:
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT data_json FROM learning_plans WHERE learner_id = ? AND status = 'active' ORDER BY updated_at DESC LIMIT 1",
                (learner_id,),
            ).fetchone()
            if not row:
                return None
            return LearningPlan.from_dict(json.loads(row["data_json"]))

    # Learning Activities CRUD
    def record_activity(self, activity: LearningActivity) -> None:
        with self._lock:
            conn = self._get_conn()
            payload = json.dumps(activity.to_dict())
            with conn:
                conn.execute("""
                    INSERT INTO learning_activities (activity_id, learner_id, type, skill, data_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(activity_id) DO UPDATE SET
                        data_json = excluded.data_json
                """, (
                    activity.activity_id,
                    activity.learner_id,
                    activity.type.value if hasattr(activity.type, "value") else str(activity.type),
                    activity.skill,
                    payload,
                    _iso(activity.started_at),
                ))

    def list_activities(self, learner_id: str, limit: int = 50) -> list[LearningActivity]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT data_json FROM learning_activities WHERE learner_id = ? ORDER BY created_at DESC LIMIT ?",
                (learner_id, limit),
            ).fetchall()
            return [LearningActivity.from_dict(json.loads(r["data_json"])) for r in rows]

    # Skill Mastery CRUD
    def save_mastery(self, record: SkillMasteryRecord) -> None:
        with self._lock:
            conn = self._get_conn()
            payload = json.dumps(record.to_dict())
            now_iso = _iso(_utc_now())
            with conn:
                conn.execute("""
                    INSERT INTO mastery_records (learner_id, skill, mastery_score, confidence, status, data_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(learner_id, skill) DO UPDATE SET
                        mastery_score = excluded.mastery_score,
                        confidence = excluded.confidence,
                        status = excluded.status,
                        data_json = excluded.data_json,
                        updated_at = excluded.updated_at
                """, (
                    record.learner_id,
                    record.skill,
                    record.mastery_score,
                    record.confidence,
                    record.status.value if hasattr(record.status, "value") else str(record.status),
                    payload,
                    now_iso,
                ))

    def get_mastery(self, learner_id: str, skill: str) -> SkillMasteryRecord | None:
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT data_json FROM mastery_records WHERE learner_id = ? AND LOWER(skill) = LOWER(?)",
                (learner_id, skill.strip()),
            ).fetchone()
            if not row:
                return None
            return SkillMasteryRecord.from_dict(json.loads(row["data_json"]))

    def list_mastery(self, learner_id: str) -> list[SkillMasteryRecord]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute("SELECT data_json FROM mastery_records WHERE learner_id = ?", (learner_id,)).fetchall()
            return [SkillMasteryRecord.from_dict(json.loads(r["data_json"])) for r in rows]

    # Struggles CRUD
    def save_struggle(self, struggle: StruggleRecord) -> None:
        with self._lock:
            conn = self._get_conn()
            payload = json.dumps(struggle.to_dict())
            now_iso = _iso(_utc_now())
            with conn:
                conn.execute("""
                    INSERT INTO struggle_records (struggle_id, learner_id, skill, resolved, data_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(struggle_id) DO UPDATE SET
                        resolved = excluded.resolved,
                        data_json = excluded.data_json,
                        updated_at = excluded.updated_at
                """, (
                    struggle.struggle_id,
                    struggle.learner_id,
                    struggle.skill,
                    1 if struggle.resolved else 0,
                    payload,
                    now_iso,
                ))

    def get_active_struggles(self, learner_id: str) -> list[StruggleRecord]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT data_json FROM struggle_records WHERE learner_id = ? AND resolved = 0 ORDER BY updated_at DESC",
                (learner_id,),
            ).fetchall()
            return [StruggleRecord.from_dict(json.loads(r["data_json"])) for r in rows]

    # Practice Results CRUD
    def record_practice_result(self, result: PracticeResult) -> None:
        with self._lock:
            conn = self._get_conn()
            res_id = str(uuid.uuid4())
            payload = json.dumps(result.to_dict())
            with conn:
                conn.execute("""
                    INSERT INTO practice_results (id, task_id, learner_id, skill, passed, score, data_json, evaluated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    res_id,
                    result.task_id,
                    result.learner_id,
                    result.skill,
                    1 if result.passed else 0,
                    result.score,
                    payload,
                    _iso(result.evaluated_at),
                ))

    def list_practice_results(self, learner_id: str, skill: str | None = None) -> list[PracticeResult]:
        with self._lock:
            conn = self._get_conn()
            if skill:
                rows = conn.execute(
                    "SELECT data_json FROM practice_results WHERE learner_id = ? AND LOWER(skill) = LOWER(?) ORDER BY evaluated_at DESC",
                    (learner_id, skill.strip()),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT data_json FROM practice_results WHERE learner_id = ? ORDER BY evaluated_at DESC",
                    (learner_id,),
                ).fetchall()
            return [PracticeResult.from_dict(json.loads(r["data_json"])) for r in rows]

    # Progress Reports CRUD
    def save_progress_report(self, report: ProgressReport) -> None:
        with self._lock:
            conn = self._get_conn()
            rep_id = str(uuid.uuid4())
            payload = json.dumps(report.to_dict())
            with conn:
                conn.execute("""
                    INSERT INTO progress_reports (id, learner_id, data_json, generated_at)
                    VALUES (?, ?, ?, ?)
                """, (rep_id, report.learner_id, payload, _iso(report.generated_at)))

    def get_latest_progress_report(self, learner_id: str) -> ProgressReport | None:
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT data_json FROM progress_reports WHERE learner_id = ? ORDER BY generated_at DESC LIMIT 1",
                (learner_id,),
            ).fetchone()
            if not row:
                return None
            return ProgressReport.from_dict(json.loads(row["data_json"]))
