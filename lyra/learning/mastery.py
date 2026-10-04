"""Multi-evidence Mastery Engine calculating grounded skill progression."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from lyra.learning.models import (
    ObjectiveStatus,
    PracticeResult,
    SkillMasteryRecord,
    _utc_now,
)
from lyra.learning.repository import LearningRepository
from lyra.observability.logging import get_logger

logger = get_logger("learning.mastery")


class MasteryEngine:
    """Calculates robust, multi-sourced skill mastery scores and confidence ratings."""

    def __init__(self, repository: LearningRepository) -> None:
        self.repository = repository

    def calculate_mastery(
        self,
        learner_id: str,
        skill: str,
    ) -> SkillMasteryRecord:
        """Evaluate all recorded evidence, practice scores, and mistake patterns for a skill."""
        clean_skill = skill.strip()
        evidence_items = self.repository.list_skill_evidence(learner_id, clean_skill)
        practice_results = self.repository.list_practice_results(learner_id, clean_skill)
        struggles = [s for s in self.repository.get_active_struggles(learner_id) if s.skill.lower() == clean_skill.lower()]

        evidence_count = len(evidence_items) + len(practice_results)
        if evidence_count == 0:
            return SkillMasteryRecord(
                learner_id=learner_id,
                skill=clean_skill,
                mastery_score=0.0,
                confidence=0.1,
                evidence_count=0,
                last_assessed=_utc_now(),
                weaknesses=[],
                status=ObjectiveStatus.NOT_STARTED,
            )

        # 1. Gather scores
        scores: list[float] = []
        weaknesses: list[str] = []

        for pr in practice_results:
            scores.append(pr.score)
            for m in pr.mistakes:
                if m not in weaknesses:
                    weaknesses.append(m)

        for ev in evidence_items:
            # Baseline evidence weight
            scores.append(ev.confidence)

        avg_score = sum(scores) / len(scores) if scores else 0.0

        # 2. Confidence scaling based on volume and diversity of evidence
        # 1 item -> 0.40 confidence; 3 items -> 0.70 confidence; 5+ items -> 0.90+ confidence
        confidence = min(0.95, 0.35 + (evidence_count * 0.12))

        # Penalty if active struggles exist
        if struggles:
            avg_score = max(0.2, avg_score * 0.75)
            confidence = max(0.5, confidence)

        # Determine status: NEVER declare completed on a single task!
        if evidence_count >= 3 and avg_score >= 0.85 and not struggles:
            status = ObjectiveStatus.COMPLETED
        elif struggles or any(pr.score < 0.6 for pr in practice_results[-2:]):
            status = ObjectiveStatus.NEEDS_REVIEW
        else:
            status = ObjectiveStatus.IN_PROGRESS

        record = SkillMasteryRecord(
            learner_id=learner_id,
            skill=clean_skill,
            mastery_score=round(avg_score, 2),
            confidence=round(confidence, 2),
            evidence_count=evidence_count,
            last_assessed=_utc_now(),
            weaknesses=weaknesses,
            status=status,
        )

        self.repository.save_mastery(record)
        return record

    def update_from_practice_result(
        self,
        result: PracticeResult,
    ) -> SkillMasteryRecord:
        """Immediately ingest a new practice outcome and recalculate skill mastery."""
        return self.calculate_mastery(result.learner_id, result.skill)
