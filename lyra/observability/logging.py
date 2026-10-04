"""Observability and logging subsystem for LYRA."""

import logging
import re
import sys
from typing import TextIO

# Patterns that indicate sensitive credentials or tokens
_SECRET_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[a-zA-Z0-9_\-\.]{8,}"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*['\"]?)[a-zA-Z0-9_\-\.]{8,}"),
    re.compile(r"(?i)(token\s*[:=]\s*['\"]?)[a-zA-Z0-9_\-\.]{8,}"),
    re.compile(r"(?i)(secret\s*[:=]\s*['\"]?)[a-zA-Z0-9_\-\.]{8,}"),
    re.compile(r"(?i)(password\s*[:=]\s*['\"]?)[^\s'\"]+"),
    re.compile(r"(?i)(authorization\s*[:=]\s*['\"]?)[^\s'\"]+"),
    re.compile(r"(?i)(cookie\s*[:=]\s*['\"]?)[^\s'\"]+"),
    re.compile(r"(?i)(session[_-]?token\s*[:=]\s*['\"]?)[^\s'\"]+"),
    re.compile(r"(?i)(x-api-key\s*[:=]\s*['\"]?)[a-zA-Z0-9_\-\.]{8,}"),
    re.compile(r"(?i)([?&]key=)[a-zA-Z0-9_\-\.]{8,}"),
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    re.compile(r"gsk_[0-9A-Za-z]{40,}"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]


def sanitize_text(text: str) -> str:
    """Utility function to scrub known secret patterns from any text string."""
    return SecretMaskingFilter._sanitize(text)


class SecretMaskingFilter(logging.Filter):
    """Logging filter that scrubs sensitive patterns from log messages and args."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._sanitize(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: (self._sanitize(v) if isinstance(v, str) else v)
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    self._sanitize(arg) if isinstance(arg, str) else arg
                    for arg in record.args
                )

        return True

    @staticmethod
    def _mask_match(match: re.Match[str]) -> str:
        if match.lastindex and match.lastindex >= 1:
            return f"{match.group(1)}***REDACTED***"
        return "***REDACTED***"

    @classmethod
    def _sanitize(cls, text: str) -> str:
        sanitized = text
        for pattern in _SECRET_PATTERNS:
            sanitized = pattern.sub(cls._mask_match, sanitized)
        return sanitized


def setup_logging(
    log_level: str = "INFO",
    stream: TextIO | None = None,
) -> logging.Logger:
    """Initialize centralized logging for the LYRA application.

    Configures the root 'lyra' logger with standard formatting and secret masking.
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logger = logging.getLogger("lyra")
    logger.setLevel(numeric_level)

    # Avoid duplicate handlers if called multiple times (e.g., during tests)
    logger.handlers.clear()

    target_stream = stream if stream is not None else sys.stderr
    handler = logging.StreamHandler(target_stream)
    handler.setLevel(numeric_level)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    handler.addFilter(SecretMaskingFilter())

    logger.addHandler(handler)
    logger.propagate = False

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Retrieve a namespaced logger under the LYRA hierarchy."""
    if not name or name == "lyra":
        return logging.getLogger("lyra")
    return logging.getLogger(f"lyra.{name}")
