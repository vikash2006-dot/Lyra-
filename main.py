"""Compatibility launcher: ``python main.py`` from the project root still starts the
LYRA terminal assistant (voice mode by default). The code now lives in ``backend/``.

For the web app run the backend API (``cd backend && python main.py``) and the
frontend (``cd frontend && npm run dev``), or ``npm run dev`` from the project root.
"""

from pathlib import Path
import runpy
import sys

CLI = Path(__file__).resolve().parent / "backend" / "cli.py"
sys.argv[0] = str(CLI)
runpy.run_path(str(CLI), run_name="__main__")
