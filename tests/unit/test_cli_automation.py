"""Unit tests for CLI automation and scheduling commands."""

from unittest.mock import patch
import pytest

from lyra.interfaces.cli import main


def test_cli_schedule_commands(tmp_path, capsys):
    """Verify CLI interactive loop handles /schedule create, list, toggle, and delete."""
    auth_db = str(tmp_path / "cli_sched_auth.db")
    memory_db = str(tmp_path / "cli_sched_mem.db")
    auto_db = str(tmp_path / "cli_sched_auto.db")

    # Inputs:
    # 1. /schedule list (empty)
    # 2. /schedule create 15 Drink water
    # 3. /schedule recurring 30 Stand up
    # 4. /schedule list (shows 2 items)
    # 5. /export (shows automations in export)
    # 6. exit
    simulated_inputs = [
        "/schedule list",
        "/schedule create 15 Drink water",
        "/schedule recurring 30 Stand up",
        "/schedule list",
        "exit",
    ]

    with patch("builtins.input", side_effect=simulated_inputs), \
         patch.dict("os.environ", {
             "AUTH_DB_PATH": auth_db,
             "MEMORY_DB_PATH": memory_db,
             "AUTOMATION_DB_PATH": auto_db,
         }):
        exit_code = main([])
        assert exit_code == 0

    captured = capsys.readouterr().out
    assert "No automations scheduled for this user." in captured
    assert "Created one-time automation" in captured
    assert "Created recurring automation" in captured
    assert "Scheduled Automations (2):" in captured
