"""Unit tests for CLI authentication and identity interactive commands."""

from unittest.mock import patch
import pytest

from lyra.auth.local import LocalAuthProvider
from lyra.auth.manager import AuthManager
from lyra.companion.orchestrator import CompanionOrchestrator
from lyra.companion.session import Session
from lyra.interfaces.cli import main
from lyra.memory.manager import MemoryManager
from lyra.memory.policy import MemoryPolicy
from lyra.memory.sqlite_repository import SQLiteMemoryRepository
from lyra.models.identity import AuthenticationState, User


def test_cli_whoami_and_auth_flow(tmp_path, capsys):
    """Verify CLI interactive loop handles /register, /whoami, /export, and /logout."""
    auth_db = str(tmp_path / "cli_auth.db")
    memory_db = str(tmp_path / "cli_memory.db")

    # Inputs:
    # 1. /whoami (anonymous)
    # 2. /register testuser
    #    password: MyPassword123
    #    display name: Tester
    # 3. /whoami (authenticated)
    # 4. /export
    # 5. /logout
    # 6. /whoami (anonymous again)
    # 7. exit
    simulated_inputs = [
        "/whoami",
        "/register testuser",
        "MyPassword123",
        "Tester",
        "/whoami",
        "/export",
        "/logout",
        "/whoami",
        "exit",
    ]

    with patch("builtins.input", side_effect=simulated_inputs), \
         patch("getpass.getpass", return_value="MyPassword123"), \
         patch.dict("os.environ", {"AUTH_DB_PATH": auth_db, "MEMORY_DB_PATH": memory_db}):
        exit_code = main([])
        assert exit_code == 0

    captured = capsys.readouterr().out
    assert "Current state: Anonymous" in captured
    assert "Successfully registered and logged in as 'testuser'" in captured
    assert "Authenticated as: testuser" in captured
    assert '"username": "testuser"' in captured  # Export JSON
    assert "Logged out. Session reverted to anonymous." in captured
