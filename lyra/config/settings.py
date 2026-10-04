"""Centralized configuration system for LYRA."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Mapping

from lyra.core.exceptions import ConfigurationError

VALID_ENVIRONMENTS: frozenset[str] = frozenset({"development", "production", "test", "staging"})
VALID_LOG_LEVELS: frozenset[str] = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

DEFAULT_ENV: str = "development"
DEFAULT_LOG_LEVEL: str = "INFO"
DEFAULT_REQUEST_TIMEOUT: float = 30.0
DEFAULT_GEMINI_MODEL: str = "gemini-2.5-flash"
DEFAULT_GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_XAI_MODEL: str = "grok-2-latest"
DEFAULT_PROVIDER_PRIORITY: tuple[str, ...] = ("gemini", "xai", "groq", "cerebras", "openrouter", "anakin", "ollama")
DEFAULT_RATE_LIMIT_COOLDOWN: float = 300.0
DEFAULT_ANAKIN_API_VERSION: str = "2024-05-06"
DEFAULT_ANAKIN_BASE_URL: str = "https://api.anakin.ai"
DEFAULT_ANAKIN_APP_TYPE: str = "quickapp"
DEFAULT_LOCAL_PROVIDER_ENABLED: bool = False
DEFAULT_STT_PROVIDER: str = "free"
DEFAULT_TTS_PROVIDER: str = "system"
DEFAULT_VOICE_SILENCE_DURATION: float = 1.2
DEFAULT_VOICE_INPUT_TIMEOUT: float = 15.0
DEFAULT_AUTH_DB_PATH: str = "lyra_auth.db"
DEFAULT_LEARNING_DB_PATH: str = "lyra_learning.db"
DEFAULT_AUTH_TOKEN_TTL: float = 86400.0
DEFAULT_AUTH_MAX_FAILED_ATTEMPTS: int = 5
DEFAULT_AUTH_LOCKOUT_DURATION: float = 900.0
DEFAULT_AUTOMATION_DB_PATH: str = "lyra_automation.db"
DEFAULT_AUTOMATION_POLL_INTERVAL: float = 1.0
DEFAULT_AUTOMATION_MAX_RETRIES: int = 3
DEFAULT_BROWSER_HEADLESS: bool = True
DEFAULT_BROWSER_DOWNLOAD_DIR: str = "downloads"
DEFAULT_BROWSER_MAX_DOWNLOAD_SIZE: int = 10_485_760  # 10 MB
DEFAULT_BROWSER_BLOCKED_DOMAINS: tuple[str, ...] = ("169.254.169.254", "metadata.google.internal")
DEFAULT_BROWSER_TIMEOUT: float = 30.0
DEFAULT_BROWSER_DRIVER_TYPE: str = "auto"
DEFAULT_COMPUTER_ENABLED: bool = False
DEFAULT_COMPUTER_ALLOW_APPS: tuple[str, ...] = (
    "Calculator",
    "TextEdit",
    "Notes",
    "Finder",
    "Visual Studio Code",
    "VS Code",
    "Code",
    "Google Chrome",
    "Chrome",
    "Safari",
    "Terminal",
)
DEFAULT_COMPUTER_BLOCKED_APPS: tuple[str, ...] = (
    "Terminal",
    "iTerm",
    "Console",
    "System Settings",
    "System Preferences",
    "Disk Utility",
)
DEFAULT_COMPUTER_SCREENSHOT_DIR: str = "screenshots"
DEFAULT_COMPUTER_REQUIRE_CONFIRMATION: bool = True
DEFAULT_OFFLINE_MODE: bool = False
DEFAULT_LOCAL_MODEL_URL: str = "http://localhost:11434"
DEFAULT_LOCAL_MODEL_NAME: str = "llama3.2"
DEFAULT_LOCAL_MODEL_TIMEOUT: float = 60.0
DEFAULT_LOCAL_MODEL_AUTO_DISCOVER: bool = True


@dataclass(frozen=True)
class Settings:
    """Immutable application settings for LYRA."""

    lyra_env: str = DEFAULT_ENV
    log_level: str = DEFAULT_LOG_LEVEL

    # Phase 3: AI Provider credentials (optional, None if unconfigured)
    gemini_api_key: str | None = None
    gemini_model: str = DEFAULT_GEMINI_MODEL
    gemini_base_url: str = DEFAULT_GEMINI_BASE_URL
    xai_api_key: str | None = None
    xai_model: str = DEFAULT_XAI_MODEL
    groq_api_key: str | None = None
    openrouter_api_key: str | None = None
    cerebras_api_key: str | None = None
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT

    # Phase 4: Model Router settings
    provider_priority: tuple[str, ...] = DEFAULT_PROVIDER_PRIORITY
    rate_limit_cooldown_seconds: float = DEFAULT_RATE_LIMIT_COOLDOWN

    # Phase 5: Anakin AI Provider & Workflow settings
    anakin_api_key: str | None = None
    anakin_app_id: str | None = None
    anakin_api_version: str = DEFAULT_ANAKIN_API_VERSION
    anakin_base_url: str = DEFAULT_ANAKIN_BASE_URL
    anakin_app_type: str = DEFAULT_ANAKIN_APP_TYPE
    anakin_workflows: tuple[dict[str, Any], ...] = ()

    # Phase 7: Real-world external tool settings
    tavily_api_key: str | None = None
    nominatim_user_agent: str = "LYRA-Personal-AI-OS/1.0"

    # Phase 8: Voice settings
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    voice_timeout_seconds: float = 15.0
    stt_provider: str = DEFAULT_STT_PROVIDER
    tts_provider: str = DEFAULT_TTS_PROVIDER
    voice_silence_duration_seconds: float = DEFAULT_VOICE_SILENCE_DURATION
    voice_input_timeout_seconds: float = DEFAULT_VOICE_INPUT_TIMEOUT

    # Phase 9: Memory settings
    memory_db_path: str = "lyra_memory.db"

    # Phase 11: Authentication & User Identity settings
    auth_db_path: str = DEFAULT_AUTH_DB_PATH
    learning_db_path: str = DEFAULT_LEARNING_DB_PATH
    auth_token_ttl_seconds: float = DEFAULT_AUTH_TOKEN_TTL
    auth_max_failed_attempts: int = DEFAULT_AUTH_MAX_FAILED_ATTEMPTS
    auth_lockout_duration_seconds: float = DEFAULT_AUTH_LOCKOUT_DURATION

    # Phase 12: Automation & Scheduling settings
    automation_db_path: str = DEFAULT_AUTOMATION_DB_PATH
    automation_poll_interval_seconds: float = DEFAULT_AUTOMATION_POLL_INTERVAL
    automation_max_retries: int = DEFAULT_AUTOMATION_MAX_RETRIES

    # Phase 13: Safe Browser Automation settings
    browser_headless: bool = DEFAULT_BROWSER_HEADLESS
    browser_download_dir: str = DEFAULT_BROWSER_DOWNLOAD_DIR
    browser_max_download_size_bytes: int = DEFAULT_BROWSER_MAX_DOWNLOAD_SIZE
    browser_allowed_domains: tuple[str, ...] = ()
    browser_blocked_domains: tuple[str, ...] = DEFAULT_BROWSER_BLOCKED_DOMAINS
    browser_timeout_seconds: float = DEFAULT_BROWSER_TIMEOUT
    browser_driver_type: str = DEFAULT_BROWSER_DRIVER_TYPE

    # Phase 14: Controlled Computer Interaction settings
    computer_enabled: bool = DEFAULT_COMPUTER_ENABLED
    computer_allow_apps: tuple[str, ...] = DEFAULT_COMPUTER_ALLOW_APPS
    computer_blocked_apps: tuple[str, ...] = DEFAULT_COMPUTER_BLOCKED_APPS
    computer_screenshot_dir: str = DEFAULT_COMPUTER_SCREENSHOT_DIR
    computer_require_confirmation: bool = DEFAULT_COMPUTER_REQUIRE_CONFIRMATION

    # Phase 15: Offline & Local AI Mode settings
    offline_mode: bool = DEFAULT_OFFLINE_MODE
    local_provider_enabled: bool = DEFAULT_LOCAL_PROVIDER_ENABLED
    local_model_url: str = DEFAULT_LOCAL_MODEL_URL
    local_model_name: str = DEFAULT_LOCAL_MODEL_NAME
    local_model_timeout_seconds: float = DEFAULT_LOCAL_MODEL_TIMEOUT
    local_model_auto_discover: bool = DEFAULT_LOCAL_MODEL_AUTO_DISCOVER

    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.lyra_env == "development"

    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.lyra_env == "production"

    def is_test(self) -> bool:
        """Check if running in test environment."""
        return self.lyra_env == "test"


def _parse_env_file(filepath: Path) -> dict[str, str]:
    """Parse a simple .env file into key-value pairs without third-party dependencies."""
    env_vars: dict[str, str] = {}
    if not filepath.is_file():
        return env_vars

    try:
        content = filepath.read_text(encoding="utf-8")
    except OSError as err:
        raise ConfigurationError(f"Failed to read environment file '{filepath}': {err}") from err

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            raise ConfigurationError(
                f"Malformed line {line_number} in '{filepath}': expected KEY=VALUE"
            )

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        if not key:
            raise ConfigurationError(
                f"Empty variable name at line {line_number} in '{filepath}'"
            )

        # Strip matching surrounding quotes if present
        if len(value) >= 2 and (
            (value.startswith('"') and value.endswith('"'))
            or (value.startswith("'") and value.endswith("'"))
        ):
            value = value[1:-1]

        env_vars[key] = value

    return env_vars


def _parse_anakin_workflows(raw_val: Any) -> tuple[dict[str, Any], ...]:
    """Parse configured Anakin workflows from JSON string or list/tuple."""
    if not raw_val:
        return ()
    if isinstance(raw_val, (list, tuple)):
        return tuple(dict(w) for w in raw_val if isinstance(w, dict))
    if isinstance(raw_val, str) and raw_val.strip():
        try:
            parsed = json.loads(raw_val.strip())
            if isinstance(parsed, list):
                return tuple(dict(w) for w in parsed if isinstance(w, dict))
            if isinstance(parsed, dict):
                return (parsed,)
        except Exception:
            return ()
    return ()


def load_settings(
    env_file: str | Path | None = None,
    overrides: Mapping[str, str] | None = None,
) -> Settings:
    """Load and validate settings from .env file and environment variables.

    Precedence order (highest to lowest):
    1. Explicit overrides dictionary
    2. System environment variables (os.environ)
    3. .env file variables
    4. Built-in defaults
    """
    merged: dict[str, str] = {}

    # 1. Load from .env file if path given or default .env exists in current working directory
    target_file = Path(env_file) if env_file is not None else Path(".env")
    if target_file.exists():
        merged.update(_parse_env_file(target_file))

    # 2. Overlay system environment variables
    recognized_keys = (
        "LYRA_ENV",
        "LOG_LEVEL",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "CEREBRAS_API_KEY",
        "REQUEST_TIMEOUT_SECONDS",
        "PROVIDER_PRIORITY",
        "RATE_LIMIT_COOLDOWN_SECONDS",
        "TAVILY_API_KEY",
        "NOMINATIM_USER_AGENT",
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_VOICE_ID",
        "VOICE_TIMEOUT_SECONDS",
        "STT_PROVIDER",
        "TTS_PROVIDER",
        "VOICE_SILENCE_DURATION_SECONDS",
        "VOICE_INPUT_TIMEOUT_SECONDS",
        "MEMORY_DB_PATH",
        "AUTH_DB_PATH",
        "AUTH_TOKEN_TTL_SECONDS",
        "AUTH_MAX_FAILED_ATTEMPTS",
        "AUTH_LOCKOUT_DURATION_SECONDS",
        "AUTOMATION_DB_PATH",
        "AUTOMATION_POLL_INTERVAL_SECONDS",
        "AUTOMATION_MAX_RETRIES",
        "BROWSER_HEADLESS",
        "BROWSER_DOWNLOAD_DIR",
        "BROWSER_MAX_DOWNLOAD_SIZE_BYTES",
        "BROWSER_ALLOWED_DOMAINS",
        "BROWSER_BLOCKED_DOMAINS",
        "BROWSER_TIMEOUT_SECONDS",
        "BROWSER_DRIVER_TYPE",
        "COMPUTER_ENABLED",
        "COMPUTER_ALLOW_APPS",
        "COMPUTER_BLOCKED_APPS",
        "COMPUTER_SCREENSHOT_DIR",
        "COMPUTER_REQUIRE_CONFIRMATION",
        "GEMINI_MODEL",
        "GEMINI_BASE_URL",
        "XAI_API_KEY",
        "GROK_API_KEY",
        "XAI_MODEL",
        "LYRA_PROVIDER_ORDER",
        "LYRA_PROVIDER_COOLDOWN_SECONDS",
        "OLLAMA_BASE_URL",
        "LYRA_OFFLINE_MODE",
        "OFFLINE_MODE",
        "LOCAL_PROVIDER_ENABLED",
        "LOCAL_MODEL_URL",
        "OLLAMA_HOST",
        "LOCAL_MODEL_NAME",
        "LOCAL_MODEL_TIMEOUT_SECONDS",
        "LOCAL_MODEL_AUTO_DISCOVER",
        "ANAKIN_API_KEY",
        "ANAKIN_APP_ID",
        "ANAKIN_API_VERSION",
        "ANAKIN_BASE_URL",
        "ANAKIN_APP_TYPE",
        "ANAKIN_WORKFLOWS",
    )
    for key in recognized_keys:
        if key in os.environ:
            merged[key] = os.environ[key]

    # 3. Overlay explicit overrides
    if overrides:
        merged.update(overrides)

    # Resolve and validate LYRA_ENV
    raw_env = merged.get("LYRA_ENV", DEFAULT_ENV).strip().lower()
    if not raw_env:
        raise ConfigurationError("LYRA_ENV cannot be empty.")
    if raw_env not in VALID_ENVIRONMENTS:
        valid_options = ", ".join(sorted(VALID_ENVIRONMENTS))
        raise ConfigurationError(
            f"Invalid LYRA_ENV '{raw_env}'. Valid options are: {valid_options}."
        )

    # Resolve and validate LOG_LEVEL
    raw_log_level = merged.get("LOG_LEVEL", DEFAULT_LOG_LEVEL).strip().upper()
    if not raw_log_level:
        raise ConfigurationError("LOG_LEVEL cannot be empty.")
    if raw_log_level not in VALID_LOG_LEVELS:
        valid_levels = ", ".join(sorted(VALID_LOG_LEVELS))
        raise ConfigurationError(
            f"Invalid LOG_LEVEL '{raw_log_level}'. Valid options are: {valid_levels}."
        )

    # Resolve and validate REQUEST_TIMEOUT_SECONDS
    raw_timeout = merged.get("REQUEST_TIMEOUT_SECONDS")
    timeout_seconds = DEFAULT_REQUEST_TIMEOUT
    if raw_timeout is not None and str(raw_timeout).strip():
        try:
            timeout_seconds = float(raw_timeout)
            if timeout_seconds <= 0:
                raise ValueError
        except ValueError as err:
            raise ConfigurationError(
                f"Invalid REQUEST_TIMEOUT_SECONDS '{raw_timeout}': must be a positive number."
            ) from err

    # Resolve and validate RATE_LIMIT_COOLDOWN_SECONDS (supports LYRA_PROVIDER_COOLDOWN_SECONDS)
    raw_cooldown = merged.get("LYRA_PROVIDER_COOLDOWN_SECONDS") or merged.get("RATE_LIMIT_COOLDOWN_SECONDS")
    cooldown_seconds = DEFAULT_RATE_LIMIT_COOLDOWN
    if raw_cooldown is not None and str(raw_cooldown).strip():
        try:
            cooldown_seconds = float(raw_cooldown)
            if cooldown_seconds <= 0:
                raise ValueError
        except ValueError as err:
            raise ConfigurationError(
                f"Invalid RATE_LIMIT_COOLDOWN_SECONDS '{raw_cooldown}': must be a positive number."
            ) from err

    # Resolve PROVIDER_PRIORITY (supports LYRA_PROVIDER_ORDER)
    raw_priority = merged.get("LYRA_PROVIDER_ORDER") or merged.get("PROVIDER_PRIORITY")
    if raw_priority is not None and str(raw_priority).strip():
        parsed_priority = tuple(
            item.strip().lower()
            for item in str(raw_priority).split(",")
            if item.strip()
        )
        provider_priority = parsed_priority if parsed_priority else DEFAULT_PROVIDER_PRIORITY
    else:
        provider_priority = DEFAULT_PROVIDER_PRIORITY

    # Provider API keys: treat empty/whitespace strings as None
    def _clean_key(var_name: str) -> str | None:
        val = merged.get(var_name)
        if val is not None:
            stripped = val.strip()
            return stripped if stripped else None
        return None

    # Voice timeout
    raw_voice_timeout = merged.get("VOICE_TIMEOUT_SECONDS")
    voice_timeout = 15.0
    if raw_voice_timeout is not None and str(raw_voice_timeout).strip():
        try:
            voice_timeout = float(raw_voice_timeout)
            if voice_timeout <= 0:
                raise ValueError
        except ValueError as err:
            raise ConfigurationError(
                f"Invalid VOICE_TIMEOUT_SECONDS '{raw_voice_timeout}': must be a positive number."
            ) from err

    stt_provider = (merged.get("STT_PROVIDER") or DEFAULT_STT_PROVIDER).strip().lower() or DEFAULT_STT_PROVIDER
    tts_provider = (merged.get("TTS_PROVIDER") or DEFAULT_TTS_PROVIDER).strip().lower() or DEFAULT_TTS_PROVIDER

    raw_silence = merged.get("VOICE_SILENCE_DURATION_SECONDS")
    voice_silence_dur = DEFAULT_VOICE_SILENCE_DURATION
    if raw_silence is not None and str(raw_silence).strip():
        try:
            voice_silence_dur = float(raw_silence)
            if voice_silence_dur <= 0:
                raise ValueError
        except ValueError as err:
            raise ConfigurationError(
                f"Invalid VOICE_SILENCE_DURATION_SECONDS '{raw_silence}': must be a positive number."
            ) from err

    raw_input_timeout = merged.get("VOICE_INPUT_TIMEOUT_SECONDS")
    voice_input_timeout = DEFAULT_VOICE_INPUT_TIMEOUT
    if raw_input_timeout is not None and str(raw_input_timeout).strip():
        try:
            voice_input_timeout = float(raw_input_timeout)
            if voice_input_timeout <= 0:
                raise ValueError
        except ValueError as err:
            raise ConfigurationError(
                f"Invalid VOICE_INPUT_TIMEOUT_SECONDS '{raw_input_timeout}': must be a positive number."
            ) from err

    # Auth token TTL
    raw_auth_ttl = merged.get("AUTH_TOKEN_TTL_SECONDS")
    auth_token_ttl = DEFAULT_AUTH_TOKEN_TTL
    if raw_auth_ttl is not None and str(raw_auth_ttl).strip():
        try:
            auth_token_ttl = float(raw_auth_ttl)
            if auth_token_ttl <= 0:
                raise ValueError
        except ValueError as err:
            raise ConfigurationError(
                f"Invalid AUTH_TOKEN_TTL_SECONDS '{raw_auth_ttl}': must be a positive number."
            ) from err

    # Auth max failed attempts
    raw_max_attempts = merged.get("AUTH_MAX_FAILED_ATTEMPTS")
    auth_max_failed_attempts = DEFAULT_AUTH_MAX_FAILED_ATTEMPTS
    if raw_max_attempts is not None and str(raw_max_attempts).strip():
        try:
            auth_max_failed_attempts = int(raw_max_attempts)
            if auth_max_failed_attempts <= 0:
                raise ValueError
        except ValueError as err:
            raise ConfigurationError(
                f"Invalid AUTH_MAX_FAILED_ATTEMPTS '{raw_max_attempts}': must be a positive integer."
            ) from err

    # Auth lockout duration
    raw_lockout_dur = merged.get("AUTH_LOCKOUT_DURATION_SECONDS")
    auth_lockout_dur = DEFAULT_AUTH_LOCKOUT_DURATION
    if raw_lockout_dur is not None and str(raw_lockout_dur).strip():
        try:
            auth_lockout_dur = float(raw_lockout_dur)
            if auth_lockout_dur <= 0:
                raise ValueError
        except ValueError as err:
            raise ConfigurationError(
                f"Invalid AUTH_LOCKOUT_DURATION_SECONDS '{raw_lockout_dur}': must be a positive number."
            ) from err

    # Automation poll interval
    raw_poll = merged.get("AUTOMATION_POLL_INTERVAL_SECONDS")
    automation_poll = DEFAULT_AUTOMATION_POLL_INTERVAL
    if raw_poll is not None and str(raw_poll).strip():
        try:
            automation_poll = float(raw_poll)
            if automation_poll <= 0:
                raise ValueError
        except ValueError as err:
            raise ConfigurationError(
                f"Invalid AUTOMATION_POLL_INTERVAL_SECONDS '{raw_poll}': must be a positive number."
            ) from err

    # Automation max retries
    raw_retries = merged.get("AUTOMATION_MAX_RETRIES")
    automation_retries = DEFAULT_AUTOMATION_MAX_RETRIES
    if raw_retries is not None and str(raw_retries).strip():
        try:
            automation_retries = int(raw_retries)
            if automation_retries < 0:
                raise ValueError
        except ValueError as err:
            raise ConfigurationError(
                f"Invalid AUTOMATION_MAX_RETRIES '{raw_retries}': must be a non-negative integer."
            ) from err

    # Phase 13: Browser settings
    raw_browser_headless = merged.get("BROWSER_HEADLESS")
    browser_headless = DEFAULT_BROWSER_HEADLESS
    if raw_browser_headless is not None and str(raw_browser_headless).strip():
        val = str(raw_browser_headless).strip().lower()
        browser_headless = val in ("1", "true", "yes", "on")

    browser_download_dir = (
        merged.get("BROWSER_DOWNLOAD_DIR", DEFAULT_BROWSER_DOWNLOAD_DIR).strip()
        or DEFAULT_BROWSER_DOWNLOAD_DIR
    )

    raw_browser_max_size = merged.get("BROWSER_MAX_DOWNLOAD_SIZE_BYTES")
    browser_max_size = DEFAULT_BROWSER_MAX_DOWNLOAD_SIZE
    if raw_browser_max_size is not None and str(raw_browser_max_size).strip():
        try:
            browser_max_size = int(raw_browser_max_size)
            if browser_max_size <= 0:
                raise ValueError
        except ValueError as err:
            raise ConfigurationError(
                f"Invalid BROWSER_MAX_DOWNLOAD_SIZE_BYTES '{raw_browser_max_size}': must be a positive integer."
            ) from err

    raw_allowed = merged.get("BROWSER_ALLOWED_DOMAINS")
    browser_allowed: tuple[str, ...] = ()
    if raw_allowed is not None and str(raw_allowed).strip():
        browser_allowed = tuple(d.strip().lower() for d in str(raw_allowed).split(",") if d.strip())

    raw_blocked = merged.get("BROWSER_BLOCKED_DOMAINS")
    browser_blocked = DEFAULT_BROWSER_BLOCKED_DOMAINS
    if raw_blocked is not None and str(raw_blocked).strip():
        parsed_blocked = tuple(d.strip().lower() for d in str(raw_blocked).split(",") if d.strip())
        browser_blocked = parsed_blocked if parsed_blocked else DEFAULT_BROWSER_BLOCKED_DOMAINS

    raw_browser_timeout = merged.get("BROWSER_TIMEOUT_SECONDS")
    browser_timeout = DEFAULT_BROWSER_TIMEOUT
    if raw_browser_timeout is not None and str(raw_browser_timeout).strip():
        try:
            browser_timeout = float(raw_browser_timeout)
            if browser_timeout <= 0:
                raise ValueError
        except ValueError as err:
            raise ConfigurationError(
                f"Invalid BROWSER_TIMEOUT_SECONDS '{raw_browser_timeout}': must be a positive number."
            ) from err

    raw_driver_type = (
        merged.get("BROWSER_DRIVER_TYPE", DEFAULT_BROWSER_DRIVER_TYPE).strip().lower()
        or DEFAULT_BROWSER_DRIVER_TYPE
    )
    if raw_driver_type not in ("auto", "playwright", "mock"):
        raise ConfigurationError(
            f"Invalid BROWSER_DRIVER_TYPE '{raw_driver_type}': valid options are auto, playwright, mock."
        )

    # Phase 14: Computer settings
    raw_computer_enabled = merged.get("COMPUTER_ENABLED")
    computer_enabled = DEFAULT_COMPUTER_ENABLED
    if raw_computer_enabled is not None and str(raw_computer_enabled).strip():
        val = str(raw_computer_enabled).strip().lower()
        computer_enabled = val in ("1", "true", "yes", "on")

    raw_comp_allow = merged.get("COMPUTER_ALLOW_APPS")
    computer_allow_apps = DEFAULT_COMPUTER_ALLOW_APPS
    if raw_comp_allow is not None and str(raw_comp_allow).strip():
        parsed_comp_allow = tuple(a.strip() for a in str(raw_comp_allow).split(",") if a.strip())
        computer_allow_apps = parsed_comp_allow if parsed_comp_allow else DEFAULT_COMPUTER_ALLOW_APPS

    raw_comp_block = merged.get("COMPUTER_BLOCKED_APPS")
    computer_blocked_apps = DEFAULT_COMPUTER_BLOCKED_APPS
    if raw_comp_block is not None and str(raw_comp_block).strip():
        parsed_comp_block = tuple(a.strip() for a in str(raw_comp_block).split(",") if a.strip())
        computer_blocked_apps = parsed_comp_block if parsed_comp_block else DEFAULT_COMPUTER_BLOCKED_APPS

    computer_screenshot_dir = (
        merged.get("COMPUTER_SCREENSHOT_DIR", DEFAULT_COMPUTER_SCREENSHOT_DIR).strip()
        or DEFAULT_COMPUTER_SCREENSHOT_DIR
    )

    raw_comp_conf = merged.get("COMPUTER_REQUIRE_CONFIRMATION")
    computer_require_conf = DEFAULT_COMPUTER_REQUIRE_CONFIRMATION
    if raw_comp_conf is not None and str(raw_comp_conf).strip():
        val = str(raw_comp_conf).strip().lower()
        computer_require_conf = val in ("1", "true", "yes", "on")

    # Phase 15: Offline & Local Model settings
    raw_offline = merged.get("LYRA_OFFLINE_MODE") or merged.get("OFFLINE_MODE")
    offline_mode = DEFAULT_OFFLINE_MODE
    if raw_offline is not None and str(raw_offline).strip():
        offline_mode = str(raw_offline).strip().lower() in ("1", "true", "yes", "on")

    local_model_url = (
        merged.get("OLLAMA_BASE_URL")
        or merged.get("LOCAL_MODEL_URL")
        or merged.get("OLLAMA_HOST")
        or DEFAULT_LOCAL_MODEL_URL
    ).strip() or DEFAULT_LOCAL_MODEL_URL

    local_model_name = (
        merged.get("LOCAL_MODEL_NAME")
        or DEFAULT_LOCAL_MODEL_NAME
    ).strip() or DEFAULT_LOCAL_MODEL_NAME

    raw_local_timeout = merged.get("LOCAL_MODEL_TIMEOUT_SECONDS")
    local_model_timeout = DEFAULT_LOCAL_MODEL_TIMEOUT
    if raw_local_timeout is not None and str(raw_local_timeout).strip():
        try:
            local_model_timeout = float(raw_local_timeout)
            if local_model_timeout <= 0:
                raise ValueError()
        except ValueError as err:
            raise ConfigurationError(
                f"Invalid LOCAL_MODEL_TIMEOUT_SECONDS: '{raw_local_timeout}'. Must be a positive number."
            ) from err

    raw_auto_disc = merged.get("LOCAL_MODEL_AUTO_DISCOVER")
    local_model_auto_discover = DEFAULT_LOCAL_MODEL_AUTO_DISCOVER
    if raw_auto_disc is not None and str(raw_auto_disc).strip():
        local_model_auto_discover = str(raw_auto_disc).strip().lower() in ("1", "true", "yes", "on")

    raw_local_enabled = merged.get("LOCAL_PROVIDER_ENABLED")
    if raw_local_enabled is not None and str(raw_local_enabled).strip():
        local_provider_enabled = str(raw_local_enabled).strip().lower() in ("1", "true", "yes", "on")
    else:
        has_explicit_url = bool(merged.get("OLLAMA_BASE_URL") or merged.get("LOCAL_MODEL_URL") or merged.get("OLLAMA_HOST"))
        local_provider_enabled = has_explicit_url or offline_mode

    gemini_model = (
        merged.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
    ).strip() or DEFAULT_GEMINI_MODEL

    gemini_base_url = (
        merged.get("GEMINI_BASE_URL") or DEFAULT_GEMINI_BASE_URL
    ).strip() or DEFAULT_GEMINI_BASE_URL

    xai_model = (
        merged.get("XAI_MODEL") or DEFAULT_XAI_MODEL
    ).strip() or DEFAULT_XAI_MODEL

    return Settings(
        lyra_env=raw_env,
        log_level=raw_log_level,
        gemini_api_key=_clean_key("GEMINI_API_KEY"),
        gemini_model=gemini_model,
        gemini_base_url=gemini_base_url,
        xai_api_key=_clean_key("XAI_API_KEY") or _clean_key("GROK_API_KEY"),
        xai_model=xai_model,
        groq_api_key=_clean_key("GROQ_API_KEY"),
        openrouter_api_key=_clean_key("OPENROUTER_API_KEY"),
        cerebras_api_key=_clean_key("CEREBRAS_API_KEY"),
        request_timeout_seconds=timeout_seconds,
        provider_priority=provider_priority,
        rate_limit_cooldown_seconds=cooldown_seconds,
        tavily_api_key=_clean_key("TAVILY_API_KEY"),
        nominatim_user_agent=merged.get("NOMINATIM_USER_AGENT", "LYRA-Personal-AI-OS/1.0").strip()
        or "LYRA-Personal-AI-OS/1.0",
        elevenlabs_api_key=_clean_key("ELEVENLABS_API_KEY"),
        elevenlabs_voice_id=merged.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM").strip()
        or "21m00Tcm4TlvDq8ikWAM",
        voice_timeout_seconds=voice_timeout,
        stt_provider=stt_provider,
        tts_provider=tts_provider,
        voice_silence_duration_seconds=voice_silence_dur,
        voice_input_timeout_seconds=voice_input_timeout,
        memory_db_path=merged.get("MEMORY_DB_PATH", "lyra_memory.db").strip() or "lyra_memory.db",
        learning_db_path=merged.get("LEARNING_DB_PATH", DEFAULT_LEARNING_DB_PATH).strip() or DEFAULT_LEARNING_DB_PATH,
        auth_db_path=merged.get("AUTH_DB_PATH", DEFAULT_AUTH_DB_PATH).strip() or DEFAULT_AUTH_DB_PATH,
        auth_token_ttl_seconds=auth_token_ttl,
        auth_max_failed_attempts=auth_max_failed_attempts,
        auth_lockout_duration_seconds=auth_lockout_dur,
        automation_db_path=merged.get("AUTOMATION_DB_PATH", DEFAULT_AUTOMATION_DB_PATH).strip()
        or DEFAULT_AUTOMATION_DB_PATH,
        automation_poll_interval_seconds=automation_poll,
        automation_max_retries=automation_retries,
        browser_headless=browser_headless,
        browser_download_dir=browser_download_dir,
        browser_max_download_size_bytes=browser_max_size,
        browser_allowed_domains=browser_allowed,
        browser_blocked_domains=browser_blocked,
        browser_timeout_seconds=browser_timeout,
        browser_driver_type=raw_driver_type,
        computer_enabled=computer_enabled,
        computer_allow_apps=computer_allow_apps,
        computer_blocked_apps=computer_blocked_apps,
        computer_screenshot_dir=computer_screenshot_dir,
        computer_require_confirmation=computer_require_conf,
        offline_mode=offline_mode,
        local_provider_enabled=local_provider_enabled,
        local_model_url=local_model_url,
        local_model_name=local_model_name,
        local_model_timeout_seconds=local_model_timeout,
        local_model_auto_discover=local_model_auto_discover,
        anakin_api_key=_clean_key("ANAKIN_API_KEY"),
        anakin_app_id=_clean_key("ANAKIN_APP_ID"),
        anakin_api_version=(merged.get("ANAKIN_API_VERSION") or DEFAULT_ANAKIN_API_VERSION).strip() or DEFAULT_ANAKIN_API_VERSION,
        anakin_base_url=(merged.get("ANAKIN_BASE_URL") or DEFAULT_ANAKIN_BASE_URL).strip().rstrip("/") or DEFAULT_ANAKIN_BASE_URL,
        anakin_app_type=(merged.get("ANAKIN_APP_TYPE") or DEFAULT_ANAKIN_APP_TYPE).strip().lower() or DEFAULT_ANAKIN_APP_TYPE,
        anakin_workflows=_parse_anakin_workflows(merged.get("ANAKIN_WORKFLOWS")),
    )
