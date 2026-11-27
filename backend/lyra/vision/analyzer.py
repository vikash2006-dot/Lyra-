"""AI visual understanding through LYRA's provider system — vision-capable models only.

Provider classes advertise `supports_vision`, but whether an image is understood depends on
the *model*. Their defaults (e.g. Groq llama-3.3-70b, OpenRouter llama-3.3 instruct, Ollama
llama3.2) are text-only, so screenshots are routed exclusively to explicitly vision-capable
models listed here (overridable with VISION_MODELS="provider:model,..." in backend/.env).
Candidates follow the configured provider priority and fall back on any failure.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import time
from typing import Any
import urllib.request

from lyra.config.settings import _parse_env_file
from lyra.models.messages import AIRequest, Message, Role
from lyra.models.multimodal import ImagePart
from lyra.observability.logging import get_logger, sanitize_text
from lyra.routing.health import ProviderHealthStatus, classify_failure
from lyra.vision.capture import optimize_for_vision
from lyra.vision.models import OCRLine, Screenshot, UIElement

logger = get_logger("vision.analyzer")

# provider -> vision models in preference order (None = the provider's own multimodal default).
# Groq currently offers no vision model, so it is intentionally absent (override with VISION_MODELS).
DEFAULT_VISION_MODELS: dict[str, list[str | None]] = {
    "gemini": [None],  # Gemini 2.x models are natively multimodal
    "openrouter": ["google/gemma-4-31b-it:free", "nvidia/nemotron-3.5-super-vl:free", "google/gemma-4-26b-a4b-it:free"],
    "xai": ["grok-2-vision-latest"],
}
OLLAMA_VISION_HINTS = ("vision", "llava", "bakllava", "moondream", "minicpm-v", "qwen2.5vl", "qwen2-vl", "gemma3", "granite3.2-vision")
SKIP_STATUSES = {ProviderHealthStatus.AUTH_FAILED, ProviderHealthStatus.QUOTA_EXHAUSTED, ProviderHealthStatus.NOT_CONFIGURED}


class VisionUnavailableError(Exception):
    """No vision-capable model could analyze the image."""


def _env(key: str) -> str | None:
    val = os.environ.get(key)
    if val is None:
        val = _parse_env_file(Path(".env")).get(key)
    return val or None


def _extract_json(text: str) -> dict[str, Any]:
    t = (text or "").strip()
    if "```" in t:
        m = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
        if m:
            t = m.group(1)
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in model output")
    return json.loads(t[start : end + 1])


class VisionAnalyzer:
    def __init__(self, router: Any, settings: Any = None) -> None:
        self.router = router
        self.settings = settings
        self._ollama_model: str | None | bool = False  # False = not probed yet
        self.last_used: str | None = None

    # ------------------------------------------------------------------ models
    def _configured_map(self) -> dict[str, list[str | None]]:
        mapping = {k: list(v) for k, v in DEFAULT_VISION_MODELS.items()}
        raw = _env("VISION_MODELS")
        if raw:
            mapping = {}
            for item in raw.split(","):
                if ":" in item:
                    prov, model = item.split(":", 1)
                    mapping.setdefault(prov.strip().lower(), []).append(model.strip() or None)
        return mapping

    def _ollama_vision_model(self) -> str | None:
        if self._ollama_model is not False:
            return self._ollama_model or None
        self._ollama_model = None
        base = (getattr(self.settings, "local_model_url", None) or "http://localhost:11434").rstrip("/")
        try:
            with urllib.request.urlopen(f"{base}/api/tags", timeout=1.5) as r:
                names = [m.get("name", "") for m in json.loads(r.read()).get("models", [])]
            self._ollama_model = next((n for n in names if any(h in n.lower() for h in OLLAMA_VISION_HINTS)), None)
        except Exception:
            self._ollama_model = None
        return self._ollama_model or None

    def candidates(self, local_only: bool = False) -> list[tuple[Any, str | None]]:
        """(provider, model) pairs that can genuinely see images, in priority order."""
        mapping = self._configured_map()
        priority = list(getattr(self.settings, "provider_priority", ()) or mapping.keys())
        names = [p if p != "ollama" else "local" for p in priority] + [n for n in mapping if n not in priority]
        out, seen = [], set()
        for name in names + ["local"]:
            if name in seen:
                continue
            seen.add(name)
            provider = self.router.get_provider(name)
            if provider is None or not provider.is_configured:
                continue
            if self.router.tracker.get_status(provider) in SKIP_STATUSES:
                continue
            if name == "local":
                model = self._ollama_vision_model()
                if model:
                    out.append((provider, model))
                continue
            if local_only or getattr(self.router, "offline_mode", False):
                continue
            for model in mapping.get(name, []):
                out.append((provider, model))
        return out

    def status(self) -> dict[str, Any]:
        cands = self.candidates()
        return {
            "available": bool(cands),
            "models": [f"{p.name}:{m or getattr(p, '_default_model', 'default')}" for p, m in cands],
            "last_used": self.last_used,
        }

    # ---------------------------------------------------------------- requests
    async def _ask_image(self, image: bytes, mime: str, prompt: str, local_only: bool,
                         max_tokens: int = 1500, timeout: float = 45.0) -> tuple[str, str]:
        part = ImagePart.from_bytes(image, mime_type=mime)
        errors = []
        failed_providers: set[str] = set()
        for provider, model in self.candidates(local_only=local_only):
            if provider.name in failed_providers:
                continue
            req = AIRequest(
                messages=(Message(role=Role.USER, content=prompt, parts=(part,)),),
                model=model, temperature=0.1, max_tokens=max_tokens,
            )
            started = time.monotonic()
            try:
                resp = await asyncio.wait_for(provider.generate(req), timeout=timeout)
                self.router.tracker.record_success(provider.name, latency=time.monotonic() - started)
                used = f"{provider.name}/{model or getattr(provider, '_default_model', 'default')}"
                self.last_used = used
                return resp.content, used
            except Exception as err:
                category = classify_failure(err)
                errors.append(f"{provider.name}/{model}: {category.value}")
                if category.value in ("AUTHENTICATION_ERROR", "QUOTA_EXHAUSTED"):
                    failed_providers.add(provider.name)  # account-level: other models would fail too
                # rate limits / missing models are per model (e.g. OpenRouter free tier): try the next one
                logger.warning("Vision request to %s/%s failed (%s): %s", provider.name, model, category.value,
                               sanitize_text(str(err))[:200])
                if category.value in ("AUTHENTICATION_ERROR", "QUOTA_EXHAUSTED"):
                    # account-level problems affect the whole provider; model 404s must not mark it down
                    self.router.tracker.record_failure(
                        provider.name, error=sanitize_text(str(err))[:200], category=category,
                        status=ProviderHealthStatus.AUTH_FAILED if category.value == "AUTHENTICATION_ERROR"
                        else ProviderHealthStatus.QUOTA_EXHAUSTED,
                    )
        raise VisionUnavailableError(
            "No vision-capable AI model is available right now" + (f" ({'; '.join(errors)})" if errors else "") + "."
        )

    async def analyze(
        self,
        shot: Screenshot,
        ocr_lines: list[OCRLine],
        elements: list[UIElement],
        app: dict[str, Any] | None,
        question: str | None = None,
        local_only: bool = False,
    ) -> dict[str, Any]:
        image, mime, factor = await optimize_for_vision(shot.png)
        known = "\n".join(f"[{e.id}] {e.type} '{e.label}'" for e in elements[:120]) or "(none)"
        prompt = (
            "You are LYRA's screen-understanding module. Analyze this screenshot of the user's computer.\n"
            f"Active app: {(app or {}).get('app') or 'unknown'}; window: {(app or {}).get('title') or 'unknown'}.\n"
            "Detected elements from accessibility/OCR (reuse their ids when you refer to them):\n"
            f"{known}\n\n"
            + (f"The user asks: \"{question}\"\n\n" if question else "")
            + "Return ONLY a JSON object with keys:\n"
            '  "summary": 1-3 sentences on what is on screen and what the user is doing,\n'
            '  "page_state": short label of the interface state (e.g. "login form", "code editor with error"),\n'
            '  "elements": up to 25 important UI elements: {"id": existing id or null, "type": button|text_field|link|'
            'menu|checkbox|dropdown|dialog|tab|text, "label": text, "value": current value or null, '
            '"box": [x, y, w, h] in 0-1000 normalized image coordinates, "actionable": bool},\n'
            '  "errors": list of visible error messages, "warnings": list of warnings,\n'
            '  "suggested_next_action": one short sentence or null,\n'
            '  "answer": direct, helpful answer to the user\'s question (or null),\n'
            '  "confidence": 0.0-1.0.\n'
            "Never invent text that is not visible. Do not include passwords or secrets in the output."
        )
        content, used = await self._ask_image(image, mime, prompt, local_only)
        try:
            data = _extract_json(content)
        except Exception:
            data = {"summary": content.strip()[:600], "answer": content.strip(), "elements": [], "confidence": 0.5}
        data["_source"] = used
        data["_factor"] = factor
        return data

    async def decide_action(
        self,
        shot: Screenshot,
        goal: str,
        context_block: str,
        history: list[str],
        local_only: bool = False,
    ) -> dict[str, Any]:
        """Ask the vision model for the single next UI action toward the goal."""
        image, mime, _ = await optimize_for_vision(shot.png)
        prompt = (
            "You control the user's Mac to accomplish a goal, one step at a time.\n"
            f"GOAL: {goal}\n\nCURRENT SCREEN (structured):\n{context_block}\n\n"
            f"ACTIONS TAKEN SO FAR:\n{chr(10).join(history) or '(none)'}\n\n"
            "Decide the ONE next step. Prefer elements by their [id]. Return ONLY JSON:\n"
            '{"action": "click"|"type"|"press"|"scroll"|"done"|"blocked", "element_id": id or null, '
            '"target": label of the element, "text": text to type (for type), "key": key name e.g. "return" '
            '(for press), "direction": "up"|"down" (for scroll), "expected": what should be visible after this step, '
            '"reason": short reason, "sensitive": true if the step deletes data, sends/submits/publishes something, '
            "pays, purchases, signs out, changes security settings or is otherwise irreversible}.\n"
            'Use "done" when the goal is already achieved on screen and "blocked" if it cannot be done '
            "(explain in reason). Never type passwords, card numbers or other secrets."
        )
        content, used = await self._ask_image(image, mime, prompt, local_only, max_tokens=500)
        data = _extract_json(content)
        data["_source"] = used
        return data

    async def verify(self, shot: Screenshot, expectation: str, local_only: bool = False) -> dict[str, Any]:
        image, mime, _ = await optimize_for_vision(shot.png)
        prompt = (
            f"Look at this screenshot. Is the following true? \"{expectation}\"\n"
            'Return ONLY JSON: {"verified": true|false, "evidence": "what on screen supports your answer", '
            '"confidence": 0.0-1.0}. Answer false if you cannot see evidence.'
        )
        content, used = await self._ask_image(image, mime, prompt, local_only, max_tokens=300)
        data = _extract_json(content)
        data["_source"] = used
        return data


def vision_elements(data: dict[str, Any], shot: Screenshot, known: list[UIElement]) -> list[UIElement]:
    """Merge vision-reported elements with known ones; convert normalized boxes to image pixels."""
    by_id = {e.id: e for e in known}
    out: list[UIElement] = []
    for i, raw in enumerate(data.get("elements") or []):
        if not isinstance(raw, dict):
            continue
        eid = raw.get("id")
        if eid and eid in by_id:
            base = by_id[eid]
            out.append(UIElement(id=base.id, type=raw.get("type") or base.type, label=base.label or str(raw.get("label") or ""),
                                 bbox=base.bbox, source=base.source, actionable=bool(raw.get("actionable", base.actionable)),
                                 value=raw.get("value") if raw.get("value") is not None else base.value,
                                 confidence=base.confidence))
            continue
        box = raw.get("box")
        bbox = None
        if isinstance(box, list) and len(box) == 4:
            try:
                x, y, w, h = (float(v) for v in box)
                bbox = [x / 1000 * shot.width, y / 1000 * shot.height, w / 1000 * shot.width, h / 1000 * shot.height]
            except (TypeError, ValueError):
                bbox = None
        out.append(UIElement(id=f"v{i}", type=str(raw.get("type") or "element"), label=str(raw.get("label") or "")[:160],
                             bbox=bbox, source="vision", actionable=bool(raw.get("actionable")),
                             value=None if raw.get("value") is None else str(raw.get("value"))[:200], confidence=0.6))
    return out
