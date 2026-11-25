"""Media Controller for LYRA.

Controls media playback across running players (Spotify, Apple Music, QuickTime)
and active web browser sessions.
"""

import logging
import subprocess
import sys
from typing import Any

logger = logging.getLogger("computer.media")


class MediaController:
    """Controls media playback (play, pause, resume, next, previous, stop)."""

    def __init__(self, use_mock: bool = False) -> None:
        self._is_mac = sys.platform == "darwin"
        self._use_mock = use_mock or not self._is_mac
        self._mock_state: str = "paused"

    def _is_app_running(self, app_name: str) -> bool:
        if self._use_mock or not self._is_mac:
            return False
        try:
            res = subprocess.run(
                ["osascript", "-e", f'application "{app_name}" is running'],
                capture_output=True,
                text=True,
                check=False,
                timeout=2,
            )
            return res.stdout.strip().lower() == "true"
        except Exception:
            return False

    def play(self) -> dict[str, Any]:
        """Start or resume playback on active player or browser."""
        if self._use_mock:
            self._mock_state = "playing"
            return {"status": "playing", "target": "mock"}

        # 1. Check Spotify
        if self._is_app_running("Spotify"):
            try:
                subprocess.run(["osascript", "-e", 'tell application "Spotify" to play'], check=False, timeout=3)
                return {"status": "playing", "target": "Spotify"}
            except Exception:
                pass

        # 2. Check Apple Music
        if self._is_app_running("Music"):
            try:
                subprocess.run(["osascript", "-e", 'tell application "Music" to play'], check=False, timeout=3)
                return {"status": "playing", "target": "Music"}
            except Exception:
                pass

        # 3. Check Google Chrome YouTube tab
        if self._is_app_running("Google Chrome"):
            try:
                script = '''
                tell application "Google Chrome"
                    set found to false
                    repeat with w in windows
                        repeat with t in tabs of w
                            if (URL of t) contains "youtube.com" then
                                tell t to execute javascript "const v = document.querySelector('video'); if (v) v.play();"
                                set found to true
                                exit repeat
                            end if
                        end repeat
                        if found then exit repeat
                    end repeat
                end tell
                '''
                subprocess.run(["osascript", "-e", script], check=False, timeout=3)
                return {"status": "playing", "target": "YouTube (Chrome)"}
            except Exception:
                pass

        # 4. Fallback: space bar on active window
        try:
            subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to key code 49'],
                check=False,
                timeout=2,
            )
            return {"status": "playing", "target": "active window"}
        except Exception:
            pass

        self._mock_state = "playing"
        return {"status": "playing", "target": "system"}

    def pause(self) -> dict[str, Any]:
        """Pause playback on active player or browser."""
        if self._use_mock:
            self._mock_state = "paused"
            return {"status": "paused", "target": "mock"}

        # 1. Check Spotify
        if self._is_app_running("Spotify"):
            try:
                subprocess.run(["osascript", "-e", 'tell application "Spotify" to pause'], check=False, timeout=3)
                return {"status": "paused", "target": "Spotify"}
            except Exception:
                pass

        # 2. Check Apple Music
        if self._is_app_running("Music"):
            try:
                subprocess.run(["osascript", "-e", 'tell application "Music" to pause'], check=False, timeout=3)
                return {"status": "paused", "target": "Music"}
            except Exception:
                pass

        # 3. Check Google Chrome YouTube tab
        if self._is_app_running("Google Chrome"):
            try:
                script = '''
                tell application "Google Chrome"
                    set found to false
                    repeat with w in windows
                        repeat with t in tabs of w
                            if (URL of t) contains "youtube.com" then
                                tell t to execute javascript "const v = document.querySelector('video'); if (v) v.pause();"
                                set found to true
                                exit repeat
                            end if
                        end repeat
                        if found then exit repeat
                    end repeat
                end tell
                '''
                subprocess.run(["osascript", "-e", script], check=False, timeout=3)
                return {"status": "paused", "target": "YouTube (Chrome)"}
            except Exception:
                pass

        # 4. Fallback: space bar on active window
        try:
            subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to key code 49'],
                check=False,
                timeout=2,
            )
            return {"status": "paused", "target": "active window"}
        except Exception:
            pass

        self._mock_state = "paused"
        return {"status": "paused", "target": "system"}

    def resume(self) -> dict[str, Any]:
        """Resume playback."""
        return self.play()

    def next_track(self) -> dict[str, Any]:
        """Skip to next track."""
        if self._use_mock:
            return {"status": "next", "target": "mock"}

        if self._is_app_running("Spotify"):
            try:
                subprocess.run(["osascript", "-e", 'tell application "Spotify" to next track'], check=False, timeout=3)
                return {"status": "next", "target": "Spotify"}
            except Exception:
                pass

        if self._is_app_running("Music"):
            try:
                subprocess.run(["osascript", "-e", 'tell application "Music" to next track'], check=False, timeout=3)
                return {"status": "next", "target": "Music"}
            except Exception:
                pass

        # YouTube next video (Shift + N)
        if self._is_app_running("Google Chrome"):
            try:
                script = '''
                tell application "Google Chrome"
                    repeat with w in windows
                        repeat with t in tabs of w
                            if (URL of t) contains "youtube.com" then
                                tell t to execute javascript "const btn = document.querySelector('.ytp-next-button'); if (btn) btn.click();"
                                return "clicked"
                            end if
                        end repeat
                    end repeat
                end tell
                '''
                subprocess.run(["osascript", "-e", script], check=False, timeout=3)
                return {"status": "next", "target": "YouTube (Chrome)"}
            except Exception:
                pass

        return {"status": "next", "target": "system"}

    def previous_track(self) -> dict[str, Any]:
        """Go back to previous track."""
        if self._use_mock:
            return {"status": "previous", "target": "mock"}

        if self._is_app_running("Spotify"):
            try:
                subprocess.run(["osascript", "-e", 'tell application "Spotify" to previous track'], check=False, timeout=3)
                return {"status": "previous", "target": "Spotify"}
            except Exception:
                pass

        if self._is_app_running("Music"):
            try:
                subprocess.run(["osascript", "-e", 'tell application "Music" to previous track'], check=False, timeout=3)
                return {"status": "previous", "target": "Music"}
            except Exception:
                pass

        return {"status": "previous", "target": "system"}

    def stop(self) -> dict[str, Any]:
        """Stop playback."""
        return self.pause()
