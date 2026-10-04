"""Unit tests for LYRA multimodal models and file safety validation."""

from pathlib import Path
import pytest

from lyra.core.exceptions import ModelValidationError
from lyra.models.messages import AIRequest, Message, Role
from lyra.models.multimodal import (
    ALLOWED_AUDIO_EXTENSIONS,
    ALLOWED_FILE_EXTENSIONS,
    ALLOWED_IMAGE_EXTENSIONS,
    AudioPart,
    FilePart,
    ImagePart,
    TextPart,
    validate_file_safety,
)


def test_text_part():
    part = TextPart(text="Hello multimodal world")
    assert part.text == "Hello multimodal world"

    with pytest.raises(ModelValidationError):
        TextPart(text=123)  # type: ignore


def test_image_part_bytes():
    raw = b"fake_png_data_12345"
    img = ImagePart.from_bytes(raw, mime_type="image/png", caption="Test image")
    assert img.mime_type == "image/png"
    assert img.caption == "Test image"
    assert img.to_bytes() == raw


def test_image_part_file(tmp_path: Path):
    img_file = tmp_path / "sample.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\nfakeimage")

    img = ImagePart.from_file(img_file, caption="Saved screenshot")
    assert img.mime_type == "image/png"
    assert img.file_path == str(img_file)
    assert img.to_bytes() == b"\x89PNG\r\n\x1a\nfakeimage"


def test_audio_part_file(tmp_path: Path):
    audio_file = tmp_path / "sample.wav"
    audio_file.write_bytes(b"RIFFfakeaudioWAVE")

    aud = AudioPart.from_file(audio_file)
    assert aud.mime_type == "audio/wav"
    assert aud.to_bytes() == b"RIFFfakeaudioWAVE"


def test_file_part_text(tmp_path: Path):
    doc_file = tmp_path / "notes.md"
    doc_file.write_text("# Project Notes\n- Task 1", encoding="utf-8")

    part = FilePart.from_file(doc_file)
    assert part.filename == "notes.md"
    assert "# Project Notes" in part.text_content
    assert part.data_base64 is None


def test_file_part_binary(tmp_path: Path):
    bin_file = tmp_path / "document.pdf"
    bin_file.write_bytes(b"%PDF-1.4 binary data \xff\xfe")

    part = FilePart.from_file(bin_file)
    assert part.filename == "document.pdf"
    assert "[Binary Document:" in part.text_content
    assert part.data_base64 is not None


def test_file_safety_blocking_executables(tmp_path: Path):
    sh_file = tmp_path / "malicious.sh"
    sh_file.write_text("rm -rf /", encoding="utf-8")

    with pytest.raises(ModelValidationError, match="strictly blocked"):
        validate_file_safety(sh_file, allowed_extensions=ALLOWED_FILE_EXTENSIONS)

    exe_file = tmp_path / "bad.exe"
    exe_file.write_bytes(b"MZ12345")
    with pytest.raises(ModelValidationError, match="strictly blocked"):
        validate_file_safety(exe_file, allowed_extensions=ALLOWED_FILE_EXTENSIONS)


def test_file_safety_missing_file(tmp_path: Path):
    with pytest.raises(ModelValidationError, match="File not found"):
        validate_file_safety(tmp_path / "missing.txt", allowed_extensions=ALLOWED_FILE_EXTENSIONS)


def test_file_safety_unsupported_extension(tmp_path: Path):
    zip_file = tmp_path / "archive.zip"
    zip_file.write_bytes(b"PK00")

    with pytest.raises(ModelValidationError, match="Unsupported file extension"):
        validate_file_safety(zip_file, allowed_extensions=ALLOWED_FILE_EXTENSIONS)


def test_file_safety_oversized_file(tmp_path: Path):
    large_file = tmp_path / "huge.txt"
    large_file.write_bytes(b"a" * 1024)

    with pytest.raises(ModelValidationError, match="exceeds maximum permitted limit"):
        validate_file_safety(large_file, allowed_extensions=ALLOWED_FILE_EXTENSIONS, max_bytes=500)


def test_message_multimodal_helpers(tmp_path: Path):
    img_file = tmp_path / "test.jpg"
    img_file.write_bytes(b"\xff\xd8\xfffakejpg")
    img_part = ImagePart.from_file(img_file)

    txt_file = tmp_path / "code.py"
    txt_file.write_text("print('hello')", encoding="utf-8")
    file_part = FilePart.from_file(txt_file)

    msg = Message(
        role=Role.USER,
        content="Inspect these attachments",
        parts=(img_part, file_part),
    )

    assert msg.has_images() is True
    assert msg.has_files() is True
    assert msg.has_audio() is False
    assert len(msg.get_images()) == 1
    assert len(msg.get_files()) == 1

    req = AIRequest(messages=[msg])
    assert req.has_images() is True
    assert req.has_files() is True
    assert req.requires_multimodal() is True
