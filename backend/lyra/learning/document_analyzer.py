"""Document and Resume analysis engine for LYRA Adaptive Learning Agent."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from lyra.learning.models import (
    EvidenceSource,
    LearnerProfile,
    SkillEvidence,
    SkillLevel,
)
from lyra.learning.repository import LearningRepository
from lyra.models.messages import AIRequest, Message, Role
from lyra.models.multimodal import FilePart
from lyra.observability.logging import get_logger
from lyra.routing.router import ModelRouter

logger = get_logger("learning.document_analyzer")


class DocumentAnalyzer:
    """Extracts technical skills, projects, and evidence from uploaded resumes and documents."""

    def __init__(
        self,
        repository: LearningRepository,
        router: ModelRouter | None = None,
    ) -> None:
        self.repository = repository
        self.router = router

    def _rule_based_extract(self, text: str) -> dict[str, Any]:
        """Deterministic keyword and structure extractor for offline or fallback analysis."""
        lowered = text.lower()
        extracted_skills: list[str] = []
        known_terms = [
            ("Python", r"\bpython\b"),
            ("JavaScript", r"\bjavascript|js|es6\b"),
            ("TypeScript", r"\btypescript|ts\b"),
            ("Node.js", r"\bnode\.?js|express\b"),
            ("REST APIs", r"\brest|restful|api design\b"),
            ("HTTP Basics", r"\bhttp|https\b"),
            ("SQL Fundamentals", r"\bsql|postgres|mysql|sqlite\b"),
            ("SQL Joins & Relational Queries", r"\bjoins|inner join|relational\b"),
            ("MongoDB & Document Stores", r"\bmongodb|mongoose|nosql\b"),
            ("Git Basics", r"\bgit|github|gitlab\b"),
            ("Docker & Containerization", r"\bdocker|containers\b"),
            ("Machine Learning Fundamentals", r"\bmachine learning|scikit-learn|pandas|numpy\b"),
            ("Deep Learning & Neural Networks", r"\bdeep learning|pytorch|tensorflow\b"),
            ("LLM Application Engineering", r"\bllm|prompting|gemini|openai|langchain\b"),
            ("Automated Testing & TDD", r"\bpytest|unit test|tdd|jest\b"),
        ]
        for name, pattern in known_terms:
            if re.search(pattern, lowered):
                extracted_skills.append(name)

        # Projects extraction
        projects: list[str] = []
        proj_matches = re.findall(r"(?:project|built|developed|created)\s*[:\-]?\s*([^\n\.\;]{10,80})", text, re.IGNORECASE)
        for pm in proj_matches[:3]:
            cl = pm.strip()
            if cl:
                projects.append(cl)

        return {
            "skills": extracted_skills,
            "projects": projects,
            "experience_summary": "Extracted from uploaded document.",
            "education": "Not specified" if "degree" not in lowered else "Degree mentioned",
            "certifications": [],
        }

    async def analyze_document(
        self,
        file_path: str | Path,
        profile: LearnerProfile,
    ) -> dict[str, Any]:
        """Inspect and parse a document file, updating the learner profile with evidence."""
        part = FilePart.from_file(file_path)
        content_text = part.text_content

        extracted: dict[str, Any] = {}
        # 1. Try LLM extraction if router available and online
        if self.router and not getattr(self.router, "offline_mode", False):
            prompt = (
                "You are an expert technical resume and document analyzer for an AI engineering mentor system.\n"
                "Analyze the following resume/document text carefully.\n"
                "Extract:\n"
                "1. 'skills': list of technical skills/languages/technologies actually mentioned or demonstrated.\n"
                "2. 'projects': list of project names and brief technical summaries.\n"
                "3. 'experience_summary': concise summary of work/academic experience.\n"
                "4. 'education': degrees or coursework.\n"
                "5. 'certifications': list of certifications.\n"
                "6. 'evidence_snippets': list of objects with {'skill': string, 'snippet': string, 'demonstrated_level': 'beginner'|'elementary'|'intermediate'|'advanced'}\n"
                "Do NOT inflate skills to expert. Return JSON ONLY matching this structure.\n\n"
                f"DOCUMENT CONTENT:\n{content_text[:6000]}"
            )
            req = AIRequest(
                messages=(Message(role=Role.USER, content=prompt),),
                max_tokens=1000,
            )
            try:
                resp = await self.router.route(req)
                cleaned_json = resp.content.strip()
                if "```json" in cleaned_json:
                    cleaned_json = cleaned_json.split("```json", 1)[1].split("```", 1)[0].strip()
                elif "```" in cleaned_json:
                    cleaned_json = cleaned_json.split("```", 1)[1].split("```", 1)[0].strip()
                extracted = json.loads(cleaned_json)
            except Exception as err:
                logger.warning("LLM document parsing failed or returned invalid JSON: %s. Using rule-based fallback.", err)
                extracted = self._rule_based_extract(content_text)
        else:
            extracted = self._rule_based_extract(content_text)

        # 2. Record evidence and update profile
        skills = extracted.get("skills", [])
        evidence_items = extracted.get("evidence_snippets", [])

        # Process structured evidence snippets if available
        snippet_map = {item.get("skill", "").lower(): item for item in evidence_items if isinstance(item, dict)}

        for s in skills:
            clean_s = str(s).strip()
            if not clean_s:
                continue
            item = snippet_map.get(clean_s.lower(), {})
            snippet = item.get("snippet", f"Mentioned in uploaded document '{part.filename}'")
            lvl_str = item.get("demonstrated_level", "beginner")
            lvl = SkillLevel.from_str(lvl_str)

            # Store evidence
            evidence = SkillEvidence(
                skill=clean_s,
                source=EvidenceSource.DOCUMENT_EVIDENCE,
                evidence=f"Document '{part.filename}': {snippet}",
                confidence=0.70,
            )
            self.repository.add_skill_evidence(profile.learner_id, evidence)

            profile.add_or_update_skill(
                skill=clean_s,
                self_reported=None,
                assessed=lvl,
                confidence=0.70,
                evidence_item=evidence.evidence,
            )

        if extracted.get("projects"):
            for p in extracted["projects"]:
                p_text = str(p).strip()
                if p_text and p_text not in profile.projects_completed:
                    profile.projects_completed.append(p_text)

        if extracted.get("experience_summary"):
            profile.experience = str(extracted["experience_summary"]).strip()
        if extracted.get("education"):
            profile.education = str(extracted["education"]).strip()
        if extracted.get("certifications"):
            profile.certifications.extend([str(c) for c in extracted["certifications"] if str(c) not in profile.certifications])

        profile.resume_summary = f"Analyzed {part.filename}: {len(skills)} skills detected, {len(profile.projects_completed)} projects recorded."
        self.repository.save_learner_profile(profile)

        return {
            "filename": part.filename,
            "skills_detected": skills,
            "projects_detected": extracted.get("projects", []),
            "summary": profile.resume_summary,
        }
