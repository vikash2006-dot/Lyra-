"""HTTP server configuration for the LYRA backend API.

LYRA's own settings (providers, voice, memory, tools...) still come from
``lyra.config.settings``. This module only covers what the API server adds:
bind address, CORS, optional access token, storage locations and upload limits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

from lyra.config.settings import _parse_env_file

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_STORAGE_DIR = BACKEND_DIR / "storage"

DEFAULT_CORS_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class ServerConfig:
    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    api_token: str | None = None
    storage_dir: Path = DEFAULT_STORAGE_DIR
    data_dir: Path = field(default_factory=lambda: DEFAULT_STORAGE_DIR / "data")
    upload_dir: Path = field(default_factory=lambda: DEFAULT_STORAGE_DIR / "uploads")
    log_dir: Path = field(default_factory=lambda: DEFAULT_STORAGE_DIR / "logs")
    max_upload_bytes: int = 10 * 1024 * 1024
    max_audio_bytes: int = 15 * 1024 * 1024
    rate_limit_per_minute: int = 60
    auto_migrate: bool = True
    user_id: str = "default_user"

    @property
    def api_db_path(self) -> Path:
        return self.data_dir / "lyra_api.db"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


def load_server_config(env_file: str | Path | None = None) -> ServerConfig:
    """Load server configuration from backend/.env and the process environment."""
    file_vars = _parse_env_file(Path(env_file) if env_file else BACKEND_DIR / ".env")

    def get(key: str, default: str | None = None) -> str | None:
        val = os.environ.get(key)
        if val is None:
            val = file_vars.get(key)
        return default if val is None or val == "" else val

    storage_dir = Path(get("LYRA_STORAGE_DIR", str(DEFAULT_STORAGE_DIR))).expanduser().resolve()
    data_dir = Path(get("LYRA_DATA_DIR", str(storage_dir / "data"))).expanduser().resolve()
    origins_raw = get("CORS_ORIGINS")
    origins = (
        tuple(o.strip().rstrip("/") for o in origins_raw.split(",") if o.strip())
        if origins_raw
        else DEFAULT_CORS_ORIGINS
    )
    app_env = (get("APP_ENV") or get("LYRA_ENV") or "development").lower()
    if "*" in origins and app_env == "production":
        origins = tuple(o for o in origins if o != "*")

    return ServerConfig(
        app_env=app_env,
        host=get("HOST", "127.0.0.1") or "127.0.0.1",
        port=int(get("PORT", "8000") or 8000),
        cors_origins=origins,
        api_token=get("LYRA_API_TOKEN"),
        storage_dir=storage_dir,
        data_dir=data_dir,
        upload_dir=Path(get("LYRA_UPLOAD_DIR", str(storage_dir / "uploads"))).expanduser().resolve(),
        log_dir=storage_dir / "logs",
        max_upload_bytes=int(get("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)) or 0),
        rate_limit_per_minute=int(get("API_RATE_LIMIT_PER_MINUTE", "60") or 60),
        auto_migrate=_as_bool(get("LYRA_AUTO_MIGRATE"), True),
        user_id=get("LYRA_USER_ID", "default_user") or "default_user",
    )
