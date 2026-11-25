"""Unit tests for LYRA configuration subsystem."""

from pathlib import Path
import pytest

from lyra.config.settings import Settings, load_settings
from lyra.core.exceptions import ConfigurationError


def test_default_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Ensure default settings are applied when no environment variables or .env exist."""
    # Ensure no environment variables interfere
    monkeypatch.delenv("LYRA_ENV", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    settings = load_settings(env_file=tmp_path / "nonexistent.env")

    assert settings.lyra_env == "development"
    assert settings.log_level == "INFO"
    assert settings.is_development() is True
    assert settings.is_production() is False
    assert settings.is_test() is False


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Ensure environment variables correctly override defaults."""
    monkeypatch.setenv("LYRA_ENV", "production")
    monkeypatch.setenv("LOG_LEVEL", "warning")

    settings = load_settings(env_file=tmp_path / "nonexistent.env")

    assert settings.lyra_env == "production"
    assert settings.log_level == "WARNING"
    assert settings.is_production() is True
    assert settings.is_development() is False


def test_env_file_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure settings are loaded from a valid .env file."""
    monkeypatch.delenv("LYRA_ENV", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "# Comment line\n"
        "LYRA_ENV=test\n"
        "LOG_LEVEL=DEBUG\n",
        encoding="utf-8",
    )

    settings = load_settings(env_file=env_file)

    assert settings.lyra_env == "test"
    assert settings.log_level == "DEBUG"
    assert settings.is_test() is True


def test_env_file_with_quotes_and_whitespace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure quoted and whitespace-padded values in .env are handled correctly."""
    monkeypatch.delenv("LYRA_ENV", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        '  LYRA_ENV = "staging"  \n'
        "  LOG_LEVEL = 'ERROR'  \n",
        encoding="utf-8",
    )

    settings = load_settings(env_file=env_file)

    assert settings.lyra_env == "staging"
    assert settings.log_level == "ERROR"


def test_os_environ_takes_precedence_over_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that os.environ overrides variables defined in .env file."""
    env_file = tmp_path / ".env"
    env_file.write_text("LYRA_ENV=staging\nLOG_LEVEL=DEBUG\n", encoding="utf-8")

    monkeypatch.setenv("LYRA_ENV", "production")
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    settings = load_settings(env_file=env_file)

    assert settings.lyra_env == "production"
    assert settings.log_level == "DEBUG"


def test_explicit_overrides_take_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that explicit overrides dictionary takes top priority."""
    monkeypatch.setenv("LYRA_ENV", "production")

    settings = load_settings(
        env_file=tmp_path / "nonexistent.env",
        overrides={"LYRA_ENV": "test", "LOG_LEVEL": "CRITICAL"},
    )

    assert settings.lyra_env == "test"
    assert settings.log_level == "CRITICAL"


def test_invalid_environment_raises_configuration_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify that unsupported environment values raise ConfigurationError."""
    monkeypatch.delenv("LYRA_ENV", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    with pytest.raises(ConfigurationError, match="Invalid LYRA_ENV"):
        load_settings(
            env_file=tmp_path / "nonexistent.env",
            overrides={"LYRA_ENV": "unsupported_env"},
        )


def test_invalid_log_level_raises_configuration_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify that unsupported log level values raise ConfigurationError."""
    monkeypatch.delenv("LYRA_ENV", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    with pytest.raises(ConfigurationError, match="Invalid LOG_LEVEL"):
        load_settings(
            env_file=tmp_path / "nonexistent.env",
            overrides={"LOG_LEVEL": "TRACE"},
        )


def test_malformed_env_file_raises_configuration_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that malformed .env entries raise ConfigurationError."""
    monkeypatch.delenv("LYRA_ENV", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text("INVALID_LINE_WITHOUT_EQUALS\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="Malformed line"):
        load_settings(env_file=env_file)


def test_provider_keys_and_timeout_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that provider API keys and timeout are loaded and trimmed correctly."""
    monkeypatch.setenv("GEMINI_API_KEY", "  gemini-secret  ")
    monkeypatch.setenv("GROQ_API_KEY", "groq-secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("CEREBRAS_API_KEY", "   ")
    monkeypatch.setenv("REQUEST_TIMEOUT_SECONDS", "15.5")

    settings = load_settings(env_file=tmp_path / "nonexistent.env")

    assert settings.gemini_api_key == "gemini-secret"
    assert settings.groq_api_key == "groq-secret"
    assert settings.openrouter_api_key is None
    assert settings.cerebras_api_key is None
    assert settings.request_timeout_seconds == 15.5


def test_invalid_request_timeout_raises_configuration_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that non-positive or non-numeric timeout values raise ConfigurationError."""
    monkeypatch.setenv("REQUEST_TIMEOUT_SECONDS", "-5.0")

    with pytest.raises(ConfigurationError, match="Invalid REQUEST_TIMEOUT_SECONDS"):
        load_settings(env_file=tmp_path / "nonexistent.env")

    monkeypatch.setenv("REQUEST_TIMEOUT_SECONDS", "abc")
    with pytest.raises(ConfigurationError, match="Invalid REQUEST_TIMEOUT_SECONDS"):
        load_settings(env_file=tmp_path / "nonexistent.env")


def test_phase7_settings_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify loading of Phase 7 settings (Tavily key, Nominatim User-Agent)."""
    monkeypatch.setenv("TAVILY_API_KEY", "  tvly-secret-123  ")
    monkeypatch.setenv("NOMINATIM_USER_AGENT", "Custom-Agent/2.0")

    settings = load_settings(env_file=tmp_path / "nonexistent.env")
    assert settings.tavily_api_key == "tvly-secret-123"
    assert settings.nominatim_user_agent == "Custom-Agent/2.0"


def test_phase8_voice_settings_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify loading of Phase 8 voice settings."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "  el-secret-456  ")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voice-xyz")
    monkeypatch.setenv("VOICE_TIMEOUT_SECONDS", "25.5")

    settings = load_settings(env_file=tmp_path / "nonexistent.env")
    assert settings.elevenlabs_api_key == "el-secret-456"
    assert settings.elevenlabs_voice_id == "voice-xyz"
    assert settings.voice_timeout_seconds == 25.5


def test_phase9_memory_settings_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify loading of Phase 9 memory settings."""
    settings_default = load_settings(env_file=tmp_path / "nonexistent.env")
    assert settings_default.memory_db_path == "lyra_memory.db"

    monkeypatch.setenv("MEMORY_DB_PATH", "custom_memories.sqlite")
    settings_custom = load_settings(env_file=tmp_path / "nonexistent.env")
    assert settings_custom.memory_db_path == "custom_memories.sqlite"

