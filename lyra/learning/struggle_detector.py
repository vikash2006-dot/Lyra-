"""Persistent struggle and misconception detection engine."""

from __future__ import annotations

import re
from typing import Any
import uuid

from lyra.learning.models import (
    LearnerProfile,
    PracticeResult,
    StruggleRecord,
    _utc_now,
)
from lyra.learning.repository import LearningRepository
from lyra.observability.logging import get_logger

logger = get_logger("learning.struggle_detector")


class StruggleDetector:
    """Detects recurring mistakes, misconceptions, and learning bottlenecks."""

    def __init__(self, repository: LearningRepository) -> None:
        self.repository = repository

    def analyze_practice_performance(
        self,
        learner_id: str,
        skill: str,
    ) -> StruggleRecord | None:
        """Inspect recent practice outcomes to identify persistent patterns of failure."""
        history = self.repository.list_practice_results(learner_id, skill)
        if len(history) < 2:
            return None

        # Check for consecutive failures
        recent_failures = []
        for r in history[:5]:
            if not r.passed or r.score < 0.6:
                recent_failures.append(r)
            else:
                break

        if len(recent_failures) >= 2:
            # Persistent struggle detected!
            all_mistakes: list[str] = []
            for f in recent_failures:
                all_mistakes.extend(f.mistakes)

            # Identify common concept or topic
            concept = skill
            if any("join" in m.lower() for m in all_mistakes):
                concept = "SQL Joins (INNER vs LEFT JOIN semantics)"
            elif any("auth" in m.lower() for m in all_mistakes):
                concept = "Authentication vs Authorization"
            elif any("async" in m.lower() for m in all_mistakes):
                concept = "Asynchronous execution and Promises"

            signals = [
                f"{len(recent_failures)} consecutive failed practice exercises in {skill}",
            ] + list(set(all_mistakes))

            struggle_id = f"struggle_{skill.lower().replace(' ', '_')}_{uuid.uuid4().hex[:6]}"
            remedials = [
                f"Deconstruct {concept} with intuitive visual diagrams and step-by-step contrast examples.",
                f"Insert focused remedial practice specifically contrasting the failure cases in {skill}.",
                "Slow down pacing and pause progression to downstream topics until confirmed mastery.",
            ]

            struggle = StruggleRecord(
                struggle_id=struggle_id,
                learner_id=learner_id,
                skill=skill,
                concept_or_topic=concept,
                signals=signals,
                failure_count=len(recent_failures),
                consecutive_failures=len(recent_failures),
                first_detected=_utc_now(),
                last_detected=_utc_now(),
                resolved=False,
                remedial_actions_taken=remedials,
            )

            self.repository.save_struggle(struggle)

            # Update learner profile weak topics
            profile = self.repository.get_learner_profile(learner_id)
            if profile and skill not in profile.weak_topics:
                profile.weak_topics.append(skill)
                self.repository.save_learner_profile(profile)

            logger.info("Persistent struggle identified for learner '%s' on '%s'", learner_id, concept)
            return struggle

        return None

    def detect_conceptual_confusion(
        self,
        learner_id: str,
        user_message: str,
    ) -> StruggleRecord | None:
        """Detect explicit signals of repeated struggle from conversational questions."""
        lowered = user_message.lower()
        struggle_phrases = [
            r"i keep making mistakes with\s+([a-zA-Z0-9\s\-]+)",
            r"i struggle with\s+([a-zA-Z0-9\s\-]+)",
            r"i don't understand\s+([a-zA-Z0-9\s\-]+)",
            r"why do i keep failing\s+([a-zA-Z0-9\s\-]+)",
            r"confused between\s+([a-zA-Z0-9\s\-]+)",
        ]
        for pat in struggle_phrases:
            m = re.search(pat, lowered)
            if m:
                topic = m.group(1).strip().title()
                struggle_id = f"struggle_conv_{uuid.uuid4().hex[:6]}"
                struggle = StruggleRecord(
                    struggle_id=struggle_id,
                    learner_id=learner_id,
                    skill=topic,
                    concept_or_topic=topic,
                    signals=[f"Explicit user report: '{user_message.strip()}'"],
                    failure_count=1,
                    consecutive_failures=1,
                    first_detected=_utc_now(),
                    last_detected=_utc_now(),
                    resolved=False,
                    remedial_actions_taken=[
                        f"Provide targeted conceptual explanation of {topic} with simplified analogies.",
                        f"Generate targeted micro-drills on {topic}.",
                    ],
                )
                self.repository.save_struggle(struggle)

                profile = self.repository.get_learner_profile(learner_id)
                if profile and topic not in profile.weak_topics:
                    profile.weak_topics.append(topic)
                    self.repository.save_learner_profile(profile)

                return struggle
        return None
