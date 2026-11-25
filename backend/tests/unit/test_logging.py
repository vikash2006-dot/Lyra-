"""Unit tests for LYRA observability and logging subsystem."""

import io
import logging

from lyra.observability.logging import SecretMaskingFilter, get_logger, setup_logging


def test_setup_logging_level_filtering() -> None:
    """Verify that logger respects configured log level threshold."""
    stream = io.StringIO()
    logger = setup_logging(log_level="WARNING", stream=stream)

    logger.info("This info message should be suppressed.")
    logger.warning("This warning message should be recorded.")

    output = stream.getvalue()
    assert "This info message should be suppressed." not in output
    assert "This warning message should be recorded." in output
    assert "[WARNING]" in output


def test_setup_logging_debug_level() -> None:
    """Verify that DEBUG level outputs debug statements."""
    stream = io.StringIO()
    logger = setup_logging(log_level="DEBUG", stream=stream)

    logger.debug("Testing debug message visibility.")

    output = stream.getvalue()
    assert "Testing debug message visibility." in output
    assert "[DEBUG]" in output


def test_get_logger_hierarchy() -> None:
    """Verify that get_logger creates properly namespaced child loggers."""
    root = get_logger()
    assert root.name == "lyra"

    child = get_logger("core")
    assert child.name == "lyra.core"


def test_secret_masking_filter_scrubs_sensitive_data() -> None:
    """Verify that secret masking prevents API keys and credentials from appearing in logs."""
    stream = io.StringIO()
    logger = setup_logging(log_level="DEBUG", stream=stream)

    # Various secret formats
    logger.info("Connecting with api_key: 'sk-1234567890abcdef1234567890'")
    logger.info("Using Bearer secret_access_token_12345")
    logger.info("User auth token=super_secret_token_12345")
    logger.info("Attempting login password=mySecretPassword123")

    output = stream.getvalue()

    assert "sk-1234567890abcdef1234567890" not in output
    assert "secret_access_token_12345" not in output
    assert "super_secret_token_12345" not in output
    assert "mySecretPassword123" not in output
    assert "***REDACTED***" in output
