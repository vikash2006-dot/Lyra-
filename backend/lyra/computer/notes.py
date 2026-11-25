"""Native Apple Notes controller for macOS.

Uses the native AppleScript dictionary of Apple Notes to create, focus,
write to, and verify notes on real macOS systems, with safe mock fallback for non-macOS/test environments.
"""

import asyncio
import html
import logging
import re
import subprocess
import sys
from typing import Any, Optional

logger = logging.getLogger("computer.notes")


class NotesController:
    """Controls real macOS Apple Notes application via native AppleScript dictionary."""

    def __init__(self, use_mock: bool = False) -> None:
        self._is_mac = sys.platform == "darwin"
        self._use_mock = use_mock or not self._is_mac
        self._mock_notes: list[dict[str, Any]] = []

    def is_available(self) -> bool:
        """Check if Notes application is available on this system."""
        if self._use_mock or not self._is_mac:
            return True
        try:
            res = subprocess.run(
                ["osascript", "-e", 'tell application "Notes" to return name'],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
            return res.returncode == 0 and "Notes" in res.stdout
        except Exception:
            return False

    def is_running(self) -> bool:
        """Check if Notes application is currently running."""
        if self._use_mock or not self._is_mac:
            return True
        try:
            res = subprocess.run(
                ["osascript", "-e", 'application "Notes" is running'],
                capture_output=True,
                text=True,
                check=False,
                timeout=2,
            )
            return res.stdout.strip().lower() == "true"
        except Exception:
            return False

    def open_notes(self) -> dict[str, Any]:
        """Activate and bring real macOS Notes to the front."""
        if self._use_mock or not self._is_mac:
            return {"success": True, "action": "open_notes", "status": "active"}

        try:
            script = 'tell application "Notes" to activate'
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False, timeout=5)
            if res.returncode != 0:
                return {
                    "success": False,
                    "action": "open_notes",
                    "error": f"Failed to activate Notes: {res.stderr.strip()}",
                }
            return {"success": True, "action": "open_notes", "status": "active"}
        except Exception as err:
            logger.error("Error activating Notes: %s", err)
            return {"success": False, "action": "open_notes", "error": str(err)}

    def create_note(
        self,
        body_text: str,
        title: Optional[str] = None,
        folder: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new note in Apple Notes and bring it into view."""
        if not body_text and not title:
            return {"success": False, "error": "Cannot create note without content or title"}

        if self._use_mock or not self._is_mac:
            note_entry = {
                "id": f"mock_note_{len(self._mock_notes) + 1}",
                "title": title or (body_text[:30] if body_text else "New Note"),
                "body": body_text,
                "folder": folder or "Notes",
            }
            self._mock_notes.append(note_entry)
            return {
                "success": True,
                "action": "create_note",
                "note_id": note_entry["id"],
                "title": note_entry["title"],
                "text": body_text,
                "verified": True,
            }

        # Build clean HTML body for Notes
        escaped_title = html.escape(title) if title else ""
        escaped_body = html.escape(body_text).replace("\n", "<br>")

        if escaped_title:
            html_content = f"<div><h1>{escaped_title}</h1></div><div>{escaped_body}</div>"
        else:
            html_content = f"<div>{escaped_body}</div>"

        # Sanitize for AppleScript string literal
        as_body = html_content.replace("\\", "\\\\").replace('"', '\\"')

        # Folder targeting if specified
        target_folder_clause = f'folder "{folder}"' if folder else 'default account'

        script = f'''
        tell application "Notes"
            activate
            try
                set targetLocation to {target_folder_clause}
                set newNote to make new note at targetLocation with properties {{body:"{as_body}"}}
                show newNote
                set noteBody to body of newNote
                return (id of newNote) & "|||" & noteBody
            on error errMsg
                -- Fallback to making note directly at default account
                set newNote to make new note with properties {{body:"{as_body}"}}
                show newNote
                set noteBody to body of newNote
                return (id of newNote) & "|||" & noteBody
            end try
        end tell
        '''

        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False, timeout=8)
            if res.returncode != 0:
                err_msg = res.stderr.strip()
                logger.error("AppleScript error creating note: %s", err_msg)
                return {
                    "success": False,
                    "action": "create_note",
                    "error": f"Notes is open, but I couldn't write the message: {err_msg}",
                }

            out = res.stdout.strip()
            parts = out.split("|||", 1)
            note_id = parts[0] if len(parts) > 0 else "unknown"
            returned_body = parts[1] if len(parts) > 1 else ""

            # Verification: ensure requested text is present in the note body
            verified = self._verify_text_in_html(body_text, returned_body)

            return {
                "success": True,
                "action": "create_note",
                "note_id": note_id,
                "title": title or "Note",
                "text": body_text,
                "verified": verified,
            }
        except Exception as err:
            logger.error("Failed to execute AppleScript note creation: %s", err)
            return {
                "success": False,
                "action": "create_note",
                "error": f"Notes is open, but I couldn't type the message: {err}",
            }

    def write_note(self, text: str, title: Optional[str] = None) -> dict[str, Any]:
        """High-level operation: Activate Notes, create note with content, and verify."""
        self.open_notes()
        return self.create_note(body_text=text, title=title)

    def get_front_note_content(self) -> dict[str, Any]:
        """Read back the body and title of the currently focused note."""
        if self._use_mock or not self._is_mac:
            if self._mock_notes:
                latest = self._mock_notes[-1]
                return {"success": True, "title": latest["title"], "body": latest["body"]}
            return {"success": False, "error": "No notes found in mock store"}

        script = '''
        tell application "Notes"
            if (count of windows) = 0 then return "NO_WINDOW"
            try
                -- Try to get body of note in front window
                set frontNote to note of front window
                return (name of frontNote) & "|||" & (body of frontNote)
            on error
                -- Fallback to first note in default account
                set firstNote to first note of default account
                return (name of firstNote) & "|||" & (body of firstNote)
            end try
        end tell
        '''
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False, timeout=5)
            if res.returncode != 0 or not res.stdout.strip():
                return {"success": False, "error": "Could not inspect active note"}
            out = res.stdout.strip()
            if out == "NO_WINDOW":
                return {"success": False, "error": "No Notes window open"}
            parts = out.split("|||", 1)
            return {
                "success": True,
                "title": parts[0] if len(parts) > 0 else "",
                "body": parts[1] if len(parts) > 1 else "",
            }
        except Exception as err:
            return {"success": False, "error": str(err)}

    def verify_note_content(self, expected_text: str) -> bool:
        """Verify that expected text exists in the front/most recent note."""
        info = self.get_front_note_content()
        if not info.get("success"):
            return False
        body = info.get("body", "")
        return self._verify_text_in_html(expected_text, body)

    @staticmethod
    def _verify_text_in_html(expected: str, raw_html: str) -> bool:
        """Strip HTML tags and check if expected text matches stripped text."""
        if not expected:
            return True
        clean_html = re.sub(r"<[^>]+>", " ", raw_html)
        clean_html = html.unescape(clean_html)
        # Normalize whitespace
        norm_expected = " ".join(expected.split()).lower()
        norm_actual = " ".join(clean_html.split()).lower()
        return norm_expected in norm_actual
