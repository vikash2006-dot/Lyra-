"""Safe file inspection tool for LYRA."""

from pathlib import Path
from typing import Any

from lyra.core.exceptions import ToolExecutionError, ToolValidationError
from lyra.models.multimodal import (
    ALLOWED_FILE_EXTENSIONS,
    DEFAULT_MAX_FILE_BYTES,
    FilePart,
    validate_file_safety,
)
from lyra.models.tools import ToolRequest, ToolResult
from lyra.observability.logging import get_logger
from lyra.tools.base import Tool
from lyra.tools.permissions import ToolPermissionLevel
from lyra.tools.sanitizer import sanitize_external_text, wrap_untrusted_context

logger = get_logger("tools.file")


class FileTool(Tool):
    """Safely inspects and reads local text and document files within permitted limits."""

    def __init__(self, max_bytes: int = DEFAULT_MAX_FILE_BYTES) -> None:
        self.max_bytes = max_bytes

    @property
    def name(self) -> str:
        return "file"

    @property
    def description(self) -> str:
        return (
            "Safely inspect and read local files (e.g. .txt, .md, .py, .json, .csv, .pdf). "
            "Validates file size, extensions, and prevents arbitrary execution."
        )

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the local file to inspect or read.",
                },
            },
            "required": ["file_path"],
            "additionalProperties": False,
        }

    async def execute(self, request: ToolRequest) -> ToolResult:
        """Read and validate the requested local file."""
        raw_path = str(request.arguments.get("file_path", "")).strip()
        if not raw_path:
            return ToolResult(tool_name=self.name, success=False, error="file_path cannot be empty.")

        try:
            part = FilePart.from_file(raw_path, max_bytes=self.max_bytes)
            clean_text = sanitize_external_text(part.text_content)
            wrapped = wrap_untrusted_context(source=f"file:{part.filename}", content=clean_text)

            return ToolResult(
                tool_name=self.name,
                success=True,
                output={
                    "filename": part.filename,
                    "mime_type": part.mime_type,
                    "content": wrapped,
                    "raw_text": clean_text[:4000],  # bounded excerpt
                    "is_binary": part.data_base64 is not None,
                },
                metadata={"file_path": str(part.file_path)},
            )
        except Exception as err:
            logger.warning("File inspection failed for '%s': %s", raw_path, err)
            return ToolResult(tool_name=self.name, success=False, error=str(err))

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        """Detect file inspection requests."""
        import re
        lowered = user_input.lower().strip()
        match = re.search(r"\b(?:read file|inspect file|open file|view file|cat file|read)\s+([a-zA-Z0-9_\-\./\\]+\.[a-zA-Z0-9]+)", lowered)
        if match:
            path = match.group(1).strip()
            ext = Path(path).suffix.lower()
            if ext in ALLOWED_FILE_EXTENSIONS:
                return {"file_path": path}
        return None

    def format_result(self, result: ToolResult) -> str:
        """Format file inspection output into friendly companion text."""
        if not result.is_success():
            return f"I couldn't read the file: {result.error}"

        out = result.output
        if isinstance(out, dict):
            filename = out.get("filename", "file")
            excerpt = out.get("raw_text", "")
            return f"Here is the content of '{filename}':\n\n{excerpt}"
        return result.to_text()
