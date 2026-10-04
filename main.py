"""LYRA — Personal AI Operating System

Single-command entry point to bootstrap and run LYRA via `python main.py`.
Automatically detects and uses the local virtual environment (.venv) if available,
and defaults to the continuous voice-controlled personal assistant mode.
"""

import os
from pathlib import Path
import sys

# 1. Automatic virtual environment bootstrapping
PROJECT_ROOT = Path(__file__).resolve().parent
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"

if (
    VENV_PYTHON.exists()
    and sys.executable != str(VENV_PYTHON)
    and not os.environ.get("_LYRA_VENV_BOOTSTRAPPED")
):
    os.environ["_LYRA_VENV_BOOTSTRAPPED"] = "1"
    try:
        os.execv(str(VENV_PYTHON), [str(VENV_PYTHON)] + sys.argv)
    except OSError:
        pass  # Fall back to current interpreter if execv fails

# 2. Ensure project root is in sys.path
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lyra.interfaces.cli import main

if __name__ == "__main__":
    # If invoked without arguments, default directly to continuous voice mode
    cli_args = ["voice"] if len(sys.argv) == 1 else sys.argv[1:]
    sys.exit(main(cli_args))
