"""Data models for LYRA's visual awareness."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Screenshot:
    """A captured image plus the geometry needed to map image pixels to screen points."""

    png: bytes
    width: int                    # image pixels
    height: int
    origin_x: float = 0.0         # top-left of the captured region in global screen points
    origin_y: float = 0.0
    scale: float = 1.0            # image pixels per screen point (2.0 on Retina)
    display_id: int | None = None
    window: dict[str, Any] | None = None
    kind: str = "display"         # display | window | active_window
    captured_at: str = field(default_factory=utc_now)

    def to_screen_point(self, x_px: float, y_px: float) -> tuple[int, int]:
        return int(round(self.origin_x + x_px / self.scale)), int(round(self.origin_y + y_px / self.scale))

    def meta(self) -> dict[str, Any]:
        return {
            "width": self.width, "height": self.height, "scale": self.scale, "kind": self.kind,
            "display_id": self.display_id, "origin": [self.origin_x, self.origin_y],
            "window": self.window, "captured_at": self.captured_at, "bytes": len(self.png),
        }


@dataclass
class OCRLine:
    text: str
    confidence: float
    bbox: list[float]  # [x, y, w, h] in image pixels, top-left origin

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "confidence": round(self.confidence, 2), "bbox": [round(v, 1) for v in self.bbox]}


@dataclass
class UIElement:
    id: str
    type: str                     # button, text_field, link, menu, checkbox, dropdown, dialog, text, ...
    label: str
    bbox: list[float] | None      # [x, y, w, h] in image pixels
    source: str                   # accessibility | ocr | vision
    actionable: bool = False
    value: str | None = None
    confidence: float = 0.8

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.bbox:
            d["bbox"] = [round(v, 1) for v in self.bbox]
        return d


@dataclass
class ScreenContext:
    """Structured understanding of what is on screen at one moment."""

    captured_at: str
    active_app: str | None
    window_title: str | None
    summary: str
    visible_text: str
    elements: list[UIElement]
    errors: list[str]
    warnings: list[str]
    page_state: str | None
    suggested_next_action: str | None
    confidence: float
    analysis_source: str          # vision:<provider>/<model> | local
    screenshot: dict[str, Any] | None = None
    ocr_lines: int = 0
    question: str | None = None
    answer: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "captured_at": self.captured_at,
            "active_app": self.active_app,
            "window_title": self.window_title,
            "summary": self.summary,
            "visible_text": self.visible_text,
            "elements": [e.to_dict() for e in self.elements],
            "errors": self.errors,
            "warnings": self.warnings,
            "page_state": self.page_state,
            "suggested_next_action": self.suggested_next_action,
            "confidence": self.confidence,
            "analysis_source": self.analysis_source,
            "screenshot": self.screenshot,
            "ocr_lines": self.ocr_lines,
            "question": self.question,
            "answer": self.answer,
        }

    def prompt_block(self, max_text: int = 2500, max_elements: int = 40) -> str:
        """Compact text form for LLM reasoning (follow-up questions, planning)."""
        els = "\n".join(
            f"  [{e.id}] {e.type} '{e.label}'" + (f" = '{e.value}'" if e.value else "") for e in self.elements[:max_elements]
        )
        return (
            f"Active app: {self.active_app or 'unknown'} | Window: {self.window_title or 'unknown'}\n"
            f"Summary: {self.summary}\n"
            f"Errors: {'; '.join(self.errors) or 'none'} | Warnings: {'; '.join(self.warnings) or 'none'}\n"
            f"Elements:\n{els or '  (none detected)'}\n"
            f"Visible text:\n{self.visible_text[:max_text]}"
        )
