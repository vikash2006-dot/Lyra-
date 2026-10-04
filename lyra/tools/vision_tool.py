"""Safe vision and image inspection tool for LYRA."""

from pathlib import Path
from typing import Any

from lyra.models.multimodal import (
    ALLOWED_IMAGE_EXTENSIONS,
    DEFAULT_MAX_FILE_BYTES,
    ImagePart,
    validate_file_safety,
)
from lyra.models.tools import ToolRequest, ToolResult
from lyra.observability.logging import get_logger
from lyra.tools.base import Tool
from lyra.tools.permissions import ToolPermissionLevel

logger = get_logger("tools.vision")


class VisionTool(Tool):
    """Safely validates and loads local image files for vision analysis."""

    def __init__(self, max_bytes: int = DEFAULT_MAX_FILE_BYTES) -> None:
        self.max_bytes = max_bytes

    @property
    def name(self) -> str:
        return "vision"

    @property
    def description(self) -> str:
        return (
            "Safely inspect and load local images (.png, .jpg, .jpeg, .webp, .gif) "
            "for visual analysis and description."
        )

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "Path to the local image file to inspect.",
                },
                "question": {
                    "type": "string",
                    "description": "Specific question about the image (e.g. 'What does this chart show?').",
                },
            },
            "required": ["image_path"],
            "additionalProperties": False,
        }

    async def execute(self, request: ToolRequest) -> ToolResult:
        """Validate and load local image."""
        raw_path = str(request.arguments.get("image_path", "")).strip()
        question = str(request.arguments.get("question", "Describe what is in this image.")).strip()

        if not raw_path:
            return ToolResult(tool_name=self.name, success=False, error="image_path cannot be empty.")

        try:
            part = ImagePart.from_file(raw_path, max_bytes=self.max_bytes)
            return ToolResult(
                tool_name=self.name,
                success=True,
                output={
                    "image_path": str(part.file_path),
                    "mime_type": part.mime_type,
                    "question": question,
                    "data_base64_sample": part.data_base64[:32] + "...",
                },
                metadata={
                    "image_part": part,
                    "source": "local_filesystem",
                },
            )
        except Exception as err:
            logger.warning("Vision tool failed on '%s': %s", raw_path, err)
            return ToolResult(tool_name=self.name, success=False, error=str(err))

    def can_handle(self, user_input: str) -> dict[str, Any] | None:
        """Detect vision and image inspection intent."""
        import re
        lowered = user_input.lower().strip()
        match = re.search(r"\b(?:inspect image|look at|analyze image|view image|describe image|what is in)\s+([a-zA-Z0-9_\-\./\\]+\.[a-zA-Z0-9]+)", lowered)
        if match:
            path = match.group(1).strip()
            ext = Path(path).suffix.lower()
            if ext in ALLOWED_IMAGE_EXTENSIONS:
                return {"image_path": path, "question": user_input}
        return None

    def format_result(self, result: ToolResult) -> str:
        """Format vision tool result into natural text."""
        if not result.is_success():
            return f"I couldn't load the image: {result.error}"

        out = result.output
        if isinstance(out, dict):
            img = out.get("image_path", "image")
            return f"Successfully loaded image '{img}' ({out.get('mime_type')}) for visual analysis."
        return result.to_text()
