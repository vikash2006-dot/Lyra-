"""UI element detection and target location.

Sources, most reliable first:
  1. Accessibility API (exact roles, labels, values, positions) — needs Accessibility permission.
  2. Vision-model elements (semantic, approximate boxes).
  3. OCR text (exact text, precise boxes, inferred role).
Locating a target ("the Login button") searches them in that order.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from lyra.vision.models import OCRLine, Screenshot, UIElement

_AX_ROLE_MAP = {
    "AXButton": "button", "AXMenuButton": "button", "AXPopUpButton": "dropdown", "AXComboBox": "dropdown",
    "AXTextField": "text_field", "AXTextArea": "text_field", "AXSearchField": "text_field",
    "AXSecureTextField": "password_field", "AXCheckBox": "checkbox", "AXRadioButton": "radio",
    "AXLink": "link", "AXMenuItem": "menu_item", "AXMenuBarItem": "menu", "AXTab": "tab",
    "AXSheet": "dialog", "AXDialog": "dialog", "AXSlider": "slider", "AXStaticText": "text",
    "AXHeading": "heading", "AXImage": "image", "AXCell": "cell", "AXRow": "row",
}
_ACTIONABLE = {"button", "dropdown", "text_field", "password_field", "checkbox", "radio", "link", "menu_item",
               "menu", "tab", "slider"}
_BUTTON_WORDS = re.compile(
    r"^(?:ok|okay|cancel|submit|save|send|sign ?in|log ?in|login|sign ?up|register|next|back|continue|done|close|"
    r"apply|yes|no|allow|deny|open|delete|remove|search|go|run|start|stop|retry|confirm|accept|agree|install|"
    r"update|download|upload|create|add|edit|share|reply|post|buy|pay|checkout)\b",
    re.IGNORECASE,
)


def accessibility_elements(pid: int, shot: Screenshot, limit: int = 250, max_depth: int = 25) -> list[UIElement]:
    """Walk the frontmost app's accessibility tree (bounded) and convert to image-pixel boxes."""
    try:
        import ApplicationServices as AX  # type: ignore
    except Exception:
        return []
    if not AX.AXIsProcessTrusted():
        return []

    def attr(el: Any, name: str) -> Any:
        err, val = AX.AXUIElementCopyAttributeValue(el, name, None)
        return None if err else val

    app = AX.AXUIElementCreateApplication(pid)
    root = attr(app, "AXFocusedWindow") or app
    out: list[UIElement] = []
    stack: list[tuple[Any, int]] = [(root, 0)]
    while stack and len(out) < limit:
        el, depth = stack.pop()
        role = str(attr(el, "AXRole") or "")
        kind = _AX_ROLE_MAP.get(role)
        if kind:
            label = attr(el, "AXTitle") or attr(el, "AXDescription") or attr(el, "AXPlaceholderValue") or ""
            value = attr(el, "AXValue")
            if kind == "text" and not label:
                label, value = value or "", None
            if kind == "password_field":
                value = "••••" if value else None  # never read secrets
            pos, size = attr(el, "AXPosition"), attr(el, "AXSize")
            bbox = None
            try:
                ok_p, p = AX.AXValueGetValue(pos, AX.kAXValueCGPointType, None)
                ok_s, s = AX.AXValueGetValue(size, AX.kAXValueCGSizeType, None)
                if ok_p and ok_s and s.width > 0 and s.height > 0:
                    bbox = [(p.x - shot.origin_x) * shot.scale, (p.y - shot.origin_y) * shot.scale,
                            s.width * shot.scale, s.height * shot.scale]
            except Exception:
                bbox = None
            label = str(label).strip()
            if (label or kind in _ACTIONABLE) and bbox and bbox[0] >= -5 and bbox[1] >= -5 \
                    and bbox[0] < shot.width and bbox[1] < shot.height:
                out.append(UIElement(
                    id=f"ax{len(out)}", type=kind, label=label[:120],
                    value=None if value is None else str(value)[:200], bbox=bbox, source="accessibility",
                    actionable=kind in _ACTIONABLE, confidence=0.95,
                ))
        if depth < max_depth:
            for child in (attr(el, "AXChildren") or [])[:80]:
                stack.append((child, depth + 1))
    return out


def ocr_elements(lines: list[OCRLine], start: int = 0) -> list[UIElement]:
    els = []
    for i, line in enumerate(lines):
        text = line.text.strip()
        if not text:
            continue
        is_button = len(text) <= 24 and bool(_BUTTON_WORDS.match(text))
        els.append(UIElement(
            id=f"t{start + i}", type="button" if is_button else "text", label=text[:160], bbox=line.bbox,
            source="ocr", actionable=is_button, confidence=round(line.confidence, 2),
        ))
    return els


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


_TYPE_WORDS = {
    "button": "button", "link": "link", "field": "text_field", "box": "text_field", "input": "text_field",
    "checkbox": "checkbox", "dropdown": "dropdown", "menu": "menu", "tab": "tab",
}


def locate(target: str, elements: list[UIElement], element_id: str | None = None) -> UIElement | None:
    """Find the element a user/LLM refers to: by id, exact label, then fuzzy label (+ type hint)."""
    if element_id:
        hit = next((e for e in elements if e.id == element_id and e.bbox), None)
        if hit:
            return hit
    t = _norm(target)
    if not t:
        return None
    want_type = next((v for k, v in _TYPE_WORDS.items() if re.search(rf"\b{k}\b", t)), None)
    words = [w for w in t.split() if w not in _TYPE_WORDS and w not in ("the", "a", "an", "on", "that", "this")]
    core = " ".join(words) or t
    source_rank = {"accessibility": 0, "vision": 1, "ocr": 2}

    def score(e: UIElement) -> float:
        label = _norm(e.label)
        if not label or not e.bbox:
            return 0.0
        if label == core:
            s = 1.0
        elif core in label or label in core:
            s = 0.85 * min(len(core), len(label)) / max(len(core), len(label)) + 0.1
        else:
            s = SequenceMatcher(None, core, label).ratio() * 0.8
        if want_type and e.type == want_type:
            s += 0.15
        if e.actionable:
            s += 0.05
        return s - source_rank.get(e.source, 3) * 0.02

    best = max(elements, key=score, default=None)
    return best if best is not None and score(best) >= 0.55 else None


def center(e: UIElement) -> tuple[float, float]:
    x, y, w, h = e.bbox or (0, 0, 0, 0)
    return x + w / 2, y + h / 2
