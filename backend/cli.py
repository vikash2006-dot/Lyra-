"""LYRA — terminal interface (text chat and continuous voice mode).

Usage (from the backend directory):
    python cli.py            # continuous voice conversation (mic -> LYRA -> speakers)
    python cli.py chat       # interactive text chat
    python cli.py "prompt"   # single-shot query
    python cli.py --help

The web UI talks to the API server instead (``python main.py``). Both share the same
LYRA core, configuration (backend/.env) and data directory (backend/storage/data).
"""

import os
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent

# Re-exec inside the project virtual environment when available.
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

os.chdir(BACKEND_DIR)  # .env and relative paths resolve against backend/
os.environ.setdefault("LYRA_DATA_DIR", str(BACKEND_DIR / "storage" / "data"))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from lyra.interfaces.cli import main  # noqa: E402

if __name__ == "__main__":
    argv = sys.argv[1:]
    if not argv:
        argv = ["voice"]  # historical default: continuous voice mode
    elif argv == ["chat"]:
        argv = []  # interactive text chat
    sys.exit(main(argv))
