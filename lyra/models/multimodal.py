"""Canonical multimodal domain models for LYRA (Images, Audio, Files) with safe validation."""

from abc import ABC
import base64
from dataclasses import dataclass
import mimetypes
from pathlib import Path

from lyra.core.exceptions import ModelValidationError

# Safe extension and size boundaries
ALLOWED_IMAGE_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
ALLOWED_AUDIO_EXTENSIONS: frozenset[str] = frozenset({".wav", ".mp3", ".ogg", ".m4a"})
ALLOWED_FILE_EXTENSIONS: frozenset[str] = frozenset({
    ".txt", ".md", ".markdown", ".py", ".json", ".csv", ".yaml", ".yml",
    ".html", ".htm", ".xml", ".css", ".js", ".ts", ".rst", ".log", ".pdf",
    ".toml", ".ini",
})
BLOCKED_EXECUTABLE_EXTENSIONS: frozenset[str] = frozenset({
    ".exe", ".bat", ".cmd", ".sh", ".bash", ".zsh", ".bin", ".dll", ".so", ".dylib",
    ".app", ".msi", ".com", ".vbs", ".ps1",
})
DEFAULT_MAX_FILE_BYTES: int = 10 * 1024 * 1024  # 10 MB


def validate_file_safety(
    path: str | Path,
    allowed_extensions: frozenset[str],
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> Path:
    """Validate that a target file exists, is readable, matches permitted media types, and conforms to size limits."""
    file_path = Path(path).resolve()
    if not file_path.exists():
        raise ModelValidationError(f"File not found: {path}")
    if not file_path.is_file():
        raise ModelValidationError(f"Target path is not a regular file: {path}")

    ext = file_path.suffix.lower()
    if ext in BLOCKED_EXECUTABLE_EXTENSIONS:
        raise ModelValidationError(f"Executable or binary script files are strictly blocked for safety: {ext}")

    if ext not in allowed_extensions:
        raise ModelValidationError(
            f"Unsupported file extension '{ext}'. Allowed extensions: {', '.join(sorted(allowed_extensions))}"
        )

    try:
        size = file_path.stat().st_size
    except OSError as err:
        raise ModelValidationError(f"Cannot access file metadata for {path}: {err}") from err

    if size > max_bytes:
        raise ModelValidationError(
            f"File '{file_path.name}' ({size} bytes) exceeds maximum permitted limit of {max_bytes} bytes."
        )

    return file_path


class ContentPart(ABC):
    """Base class for all multimodal content parts within a Message."""


@dataclass(frozen=True)
class TextPart(ContentPart):
    """A segment of plain text."""

    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise ModelValidationError("TextPart text must be a string.")


@dataclass(frozen=True)
class ImagePart(ContentPart):
    """Image data representation supporting inline base64 and filesystem paths."""

    data_base64: str
    mime_type: str = "image/png"
    file_path: str | None = None
    caption: str | None = None

    def __post_init__(self) -> None:
        if not self.data_base64 or not isinstance(self.data_base64, str):
            raise ModelValidationError("ImagePart data_base64 must be a non-empty base64 string.")
        if not self.mime_type.startswith("image/"):
            raise ModelValidationError(f"Invalid image MIME type: {self.mime_type}")

    @classmethod
    def from_bytes(cls, raw_bytes: bytes, mime_type: str = "image/png", caption: str | None = None) -> "ImagePart":
        """Create ImagePart from raw bytes."""
        if not raw_bytes:
            raise ModelValidationError("Cannot create ImagePart from empty bytes.")
        encoded = base64.b64encode(raw_bytes).decode("ascii")
        return cls(data_base64=encoded, mime_type=mime_type, caption=caption)

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        caption: str | None = None,
        max_bytes: int = DEFAULT_MAX_FILE_BYTES,
    ) -> "ImagePart":
        """Safely load an image file from disk and convert to ImagePart."""
        file_path = validate_file_safety(path, allowed_extensions=ALLOWED_IMAGE_EXTENSIONS, max_bytes=max_bytes)

        mime_type, _ = mimetypes.guess_type(str(file_path))
        if not mime_type or not mime_type.startswith("image/"):
            ext = file_path.suffix.lower()
            if ext in (".jpg", ".jpeg"):
                mime_type = "image/jpeg"
            elif ext == ".png":
                mime_type = "image/png"
            elif ext == ".webp":
                mime_type = "image/webp"
            elif ext == ".gif":
                mime_type = "image/gif"
            else:
                mime_type = "image/png"

        try:
            raw_data = file_path.read_bytes()
        except OSError as err:
            raise ModelValidationError(f"Failed to read image file {path}: {err}") from err

        encoded = base64.b64encode(raw_data).decode("ascii")
        return cls(
            data_base64=encoded,
            mime_type=mime_type,
            file_path=str(file_path),
            caption=caption,
        )

    def to_bytes(self) -> bytes:
        """Decode base64 string to raw binary bytes."""
        return base64.b64decode(self.data_base64)


@dataclass(frozen=True)
class AudioPart(ContentPart):
    """Audio data representation supporting speech and audio files."""

    data_base64: str
    mime_type: str = "audio/wav"
    file_path: str | None = None

    def __post_init__(self) -> None:
        if not self.data_base64 or not isinstance(self.data_base64, str):
            raise ModelValidationError("AudioPart data_base64 must be a non-empty base64 string.")
        if not self.mime_type.startswith("audio/"):
            raise ModelValidationError(f"Invalid audio MIME type: {self.mime_type}")

    @classmethod
    def from_bytes(cls, raw_bytes: bytes, mime_type: str = "audio/wav") -> "AudioPart":
        """Create AudioPart from raw audio bytes."""
        if not raw_bytes:
            raise ModelValidationError("Cannot create AudioPart from empty bytes.")
        encoded = base64.b64encode(raw_bytes).decode("ascii")
        return cls(data_base64=encoded, mime_type=mime_type)

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        max_bytes: int = DEFAULT_MAX_FILE_BYTES,
    ) -> "AudioPart":
        """Safely load an audio file from disk into AudioPart."""
        file_path = validate_file_safety(path, allowed_extensions=ALLOWED_AUDIO_EXTENSIONS, max_bytes=max_bytes)

        ext = file_path.suffix.lower()
        if ext in (".wav", ".wave"):
            mime_type = "audio/wav"
        elif ext == ".mp3":
            mime_type = "audio/mp3"
        elif ext == ".ogg":
            mime_type = "audio/ogg"
        elif ext == ".m4a":
            mime_type = "audio/m4a"
        else:
            guessed, _ = mimetypes.guess_type(str(file_path))
            mime_type = guessed if guessed and guessed.startswith("audio/") else "audio/wav"

        try:
            raw_data = file_path.read_bytes()
        except OSError as err:
            raise ModelValidationError(f"Failed to read audio file {path}: {err}") from err

        encoded = base64.b64encode(raw_data).decode("ascii")
        return cls(data_base64=encoded, mime_type=mime_type, file_path=str(file_path))

    def to_bytes(self) -> bytes:
        """Decode base64 string to raw binary bytes."""
        return base64.b64decode(self.data_base64)


@dataclass(frozen=True)
class FilePart(ContentPart):
    """Generic file or document representation (text, markdown, code, pdf)."""

    filename: str
    text_content: str
    data_base64: str | None = None
    mime_type: str = "text/plain"
    file_path: str | None = None

    def __post_init__(self) -> None:
        if not self.filename or not isinstance(self.filename, str):
            raise ModelValidationError("FilePart filename must be a non-empty string.")
        if not isinstance(self.text_content, str):
            raise ModelValidationError("FilePart text_content must be a string.")

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        max_bytes: int = DEFAULT_MAX_FILE_BYTES,
    ) -> "FilePart":
        """Safely load a document or text file from disk into a FilePart."""
        file_path = validate_file_safety(path, allowed_extensions=ALLOWED_FILE_EXTENSIONS, max_bytes=max_bytes)

        mime_type, _ = mimetypes.guess_type(str(file_path))
        mime = mime_type or "text/plain"

        try:
            raw = file_path.read_bytes()
        except OSError as err:
            raise ModelValidationError(f"Failed to read file {path}: {err}") from err

        # Attempt UTF-8 text decode
        try:
            text = raw.decode("utf-8")
            b64 = None
        except UnicodeDecodeError:
            # Fall back to base64 encoding for binary / PDF documents
            text = f"[Binary Document: {file_path.name}, Size: {len(raw)} bytes, MIME: {mime}]"
            b64 = base64.b64encode(raw).decode("ascii")

        return cls(
            filename=file_path.name,
            text_content=text,
            data_base64=b64,
            mime_type=mime,
            file_path=str(file_path),
        )
