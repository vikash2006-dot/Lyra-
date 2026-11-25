"""Document upload, storage and analysis (resume analysis + AI summaries)."""

from __future__ import annotations

from datetime import datetime, timezone
import mimetypes
from pathlib import Path
import re
import shutil
from typing import Any
import uuid

from lyra.learning.service import LearningService
from lyra.models.multimodal import (
    ALLOWED_FILE_EXTENSIONS,
    BLOCKED_EXECUTABLE_EXTENSIONS,
    FilePart,
)
from lyra.observability.logging import get_logger, sanitize_text

from app.core.errors import APIError
from app.services.chat_service import ChatService
from app.services.serialization import to_jsonable
from app.services.store import APIStore

logger = get_logger("api.documents")

ANALYSIS_MODES = ("summary", "resume")


def sanitize_filename(name: str) -> str:
    base = Path(name or "").name  # strips any directory components / traversal
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .")
    return base[:120] or "document.txt"


class DocumentService:
    def __init__(
        self,
        store: APIStore,
        upload_dir: Path,
        max_bytes: int,
        user_id: str,
        learning: LearningService,
        chat: ChatService,
    ) -> None:
        self.store = store
        self.upload_dir = upload_dir
        self.max_bytes = max_bytes
        self.user_id = user_id
        self.learning = learning
        self.chat = chat
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def supported_extensions() -> list[str]:
        return sorted(ALLOWED_FILE_EXTENSIONS)

    def _public(self, doc: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in doc.items() if k not in ("stored_path", "user_id")}

    def save_upload(self, filename: str, data: bytes) -> dict[str, Any]:
        safe_name = sanitize_filename(filename)
        ext = Path(safe_name).suffix.lower()
        if ext in BLOCKED_EXECUTABLE_EXTENSIONS:
            raise APIError("UNSUPPORTED_FILE_TYPE", "Executable files are not allowed.", 415)
        if ext not in ALLOWED_FILE_EXTENSIONS:
            raise APIError(
                "UNSUPPORTED_FILE_TYPE",
                f"Unsupported file type '{ext or 'none'}'. Allowed: {', '.join(self.supported_extensions())}",
                415,
            )
        if not data:
            raise APIError("EMPTY_FILE", "The uploaded file is empty.", 422)
        if len(data) > self.max_bytes:
            raise APIError("PAYLOAD_TOO_LARGE", f"File exceeds the {self.max_bytes // (1024 * 1024)} MB limit.", 413)

        doc_id = f"doc_{uuid.uuid4().hex[:12]}"
        folder = (self.upload_dir / doc_id).resolve()
        if self.upload_dir.resolve() not in folder.parents:
            raise APIError("BAD_REQUEST", "Invalid upload path.", 400)
        folder.mkdir(parents=True, exist_ok=False)
        path = folder / safe_name
        path.write_bytes(data)
        path.chmod(0o600)  # stored as data only, never executable

        try:
            FilePart.from_file(path, max_bytes=self.max_bytes)  # LYRA's own safety validation
        except Exception as err:
            shutil.rmtree(folder, ignore_errors=True)
            raise APIError("INVALID_FILE", sanitize_text(str(err)), 422) from err

        doc = {
            "id": doc_id,
            "user_id": self.user_id,
            "filename": safe_name,
            "stored_path": str(path),
            "mime_type": mimetypes.guess_type(safe_name)[0] or "text/plain",
            "size_bytes": len(data),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.store.add_document(doc)
        return self._public({**doc, "analysis": None})

    def _get(self, doc_id: str) -> dict[str, Any]:
        doc = self.store.get_document(doc_id)
        if not doc or doc["user_id"] != self.user_id:
            raise APIError("DOCUMENT_NOT_FOUND", "Document not found.", 404)
        return doc

    def get(self, doc_id: str) -> dict[str, Any]:
        return self._public(self._get(doc_id))

    def list(self) -> list[dict[str, Any]]:
        return [self._public(d) for d in self.store.list_documents(self.user_id)]

    def delete(self, doc_id: str) -> None:
        doc = self._get(doc_id)
        folder = Path(doc["stored_path"]).parent
        if self.upload_dir.resolve() in folder.resolve().parents:
            shutil.rmtree(folder, ignore_errors=True)
        self.store.delete_document(doc_id)

    async def analyze(self, doc_id: str, mode: str, session_id: str | None = None,
                      question: str | None = None) -> dict[str, Any]:
        if mode not in ANALYSIS_MODES:
            raise APIError("VALIDATION_ERROR", f"mode must be one of {', '.join(ANALYSIS_MODES)}.", 422)
        doc = self._get(doc_id)
        path = Path(doc["stored_path"])
        if not path.exists():
            raise APIError("DOCUMENT_MISSING", "The stored file is missing.", 410)

        if mode == "resume":
            raw = await self.learning.analyze_document(self.user_id, path)
            analysis = {"mode": "resume", "result": to_jsonable(raw)}
        else:
            part = FilePart.from_file(path, max_bytes=self.max_bytes)
            prompt = (question or "").strip() or f"Please inspect and summarize the attached document '{doc['filename']}'."
            turn = await self.chat.run_turn(prompt, session_id, parts=[part], source="document")
            analysis = {"mode": "summary", "summary": turn["response"], "session_id": turn["session_id"]}

        analysis["analyzed_at"] = datetime.now(timezone.utc).isoformat()
        self.store.set_document_analysis(doc_id, analysis)
        return {**self._public(doc), "analysis": analysis}
