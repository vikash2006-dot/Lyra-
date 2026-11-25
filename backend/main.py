"""LYRA backend API server.

    cd backend
    python main.py                 # http://127.0.0.1:8000  (docs at /docs)
    python main.py --reload        # auto-reload during development

Uses the project virtual environment automatically when present (backend/.venv or
../.venv). Configuration is read from backend/.env (see .env.example).
"""

import os
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent

for _venv in (BACKEND_DIR / ".venv", PROJECT_ROOT / ".venv"):
    _py = _venv / "bin" / "python"
    if _py.exists():
        if Path(sys.prefix).resolve() != _venv.resolve() and not os.environ.get("_LYRA_VENV_BOOTSTRAPPED"):
            os.environ["_LYRA_VENV_BOOTSTRAPPED"] = "1"
            try:
                os.execv(str(_py), [str(_py), str(Path(__file__).resolve())] + sys.argv[1:])
            except OSError:
                pass
        break

os.chdir(BACKEND_DIR)  # lyra.config reads ./.env; keep relative paths inside backend/
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def main() -> int:
    import socket

    import uvicorn

    from app.core.config import load_server_config
    from app.main import configure_logging

    config = load_server_config()
    os.environ.setdefault("LYRA_DATA_DIR", str(config.data_dir))
    configure_logging()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if probe.connect_ex((config.host if config.host != "0.0.0.0" else "127.0.0.1", config.port)) == 0:
            sys.stderr.write(
                f"Port {config.port} is already in use — is the LYRA backend already running?\n"
                f"Check http://{config.host}:{config.port}/api/health or set PORT in backend/.env.\n"
            )
            return 1

    reload = "--reload" in sys.argv
    print(f"LYRA backend starting on http://{config.host}:{config.port}  (API docs: /docs)")
    uvicorn.run(
        "app.asgi:app",
        host=config.host,
        port=config.port,
        reload=reload,
        reload_dirs=[str(BACKEND_DIR / "app"), str(BACKEND_DIR / "lyra")] if reload else None,
        log_level="info",
        ws_ping_interval=20,
        ws_ping_timeout=20,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
