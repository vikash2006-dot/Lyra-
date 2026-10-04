"""Progress Report Generator compiling evidence-based achievements and next steps."""

from __future__ import annotations

from typing import Any

from lyra.learning.models import (
    ObjectiveStatus,
    ProgressReport,
    _utc_now,
)
from lyra.learning.repository import LearningRepository
from lyra.observability.logging import get_logger

logger = get_logger("learning.progress")


class ProgressReportGenerator:
    """Generates structured, verifiable progress reports grounded in actual learner telemetry."""

    def __init__(self, repository: LearningRepository) -> None:
        self.repository = repository

    def generate_report(self, learner_id: str) -> ProgressReport:
        """Compile stored skills, gaps, practice outcomes, and struggles into a comprehensive report."""
        profile = self.repository.get_learner_profile(learner_id)
        target_role = (profile.target_role if profile else "") or "Backend Developer"

        mastery_list = self.repository.list_mastery(learner_id)
        struggles = self.repository.get_active_struggles(learner_id)
        gaps = self.repository.get_skill_gaps(learner_id)
        results = self.repository.list_practice_results(learner_id)
        activities = self.repository.list_activities(learner_id, limit=50)

        # 1. Categorize Skills
        acquired: list[str] = []
        in_progress: list[str] = []
        weak_areas: list[str] = []

        for m in mastery_list:
            if m.status == ObjectiveStatus.COMPLETED or m.mastery_score >= 0.85:
                acquired.append(f"{m.skill} ({int(m.mastery_score * 100)}% mastery)")
            elif m.status == ObjectiveStatus.NEEDS_REVIEW or m.mastery_score < 0.6:
                weak_areas.append(f"{m.skill} ({int(m.mastery_score * 100)}% - needs review)")
            else:
                in_progress.append(f"{m.skill} ({int(m.mastery_score * 100)}% in progress)")

        # Include profile weak topics
        if profile:
            for wt in profile.weak_topics:
                if not any(wt.lower() in w.lower() for w in weak_areas):
                    weak_areas.append(wt)

        # Include active struggles
        for st in struggles:
            label = f"{st.skill}: {st.concept_or_topic}"
            if not any(st.skill.lower() in w.lower() for w in weak_areas):
                weak_areas.append(label)

        # 2. Remaining Gaps
        remaining_gaps = [f"{g.skill} (Priority {g.priority}, required: {g.required_level.value})" for g in gaps[:5]]

        # 3. Practice Performance Summary
        if results:
            pass_count = sum(1 for r in results if r.passed)
            avg_score = sum(r.score for r in results) / len(results)
            perf_summary = f"{len(results)} practice tasks evaluated ({pass_count} passed, {int(avg_score * 100)}% average score)."
        else:
            perf_summary = "No practice tasks completed yet."

        # 4. Learning Consistency
        study_activities = [a for a in activities if a.type.value in ("study", "practice", "project")]
        consistency = f"{len(study_activities)} learning sessions logged across active curriculum."

        # 5. Recommended Next Steps
        next_steps: list[str] = []
        if weak_areas:
            first_weak = weak_areas[0].split("(")[0].strip()
            next_steps.append(f"Focus on targeted remedial exercises for: {first_weak}")
        if in_progress:
            first_prog = in_progress[0].split("(")[0].strip()
            next_steps.append(f"Continue active practice and tasks for: {first_prog}")
        elif gaps:
            next_steps.append(f"Begin next priority competency: {gaps[0].skill}")
        else:
            next_steps.append("Consolidate competencies with a capstone milestone project.")

        report = ProgressReport(
            learner_id=learner_id,
            target_role=target_role,
            skills_acquired=acquired,
            skills_in_progress=in_progress,
            remaining_gaps=remaining_gaps,
            weak_areas=weak_areas,
            completed_objectives=[f"Completed {len(acquired)} core skills"],
            projects_completed=list(profile.projects_completed if profile else []),
            practice_performance_summary=perf_summary,
            learning_consistency=consistency,
            recommended_next_steps=next_steps,
            generated_at=_utc_now(),
        )

        self.repository.save_progress_report(report)
        return report
