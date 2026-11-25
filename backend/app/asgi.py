"""ASGI entry point: ``uvicorn app.asgi:app`` (run from the backend directory)."""

import os

from app.core.config import load_server_config
from app.main import configure_logging, create_app

_config = load_server_config()
os.environ.setdefault("LYRA_DATA_DIR", str(_config.data_dir))
configure_logging()
app = create_app(_config)
