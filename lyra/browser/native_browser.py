"""Native macOS Browser Controller for LYRA.

Controls real desktop browsers (Google Chrome and Safari) on macOS via AppleScript
and System Events for tab management, navigation, search, media control, and result selection.
"""

import asyncio
import logging
import os
import re
import subprocess
import sys
from typing import Any, Optional
import urllib.parse
import urllib.request

logger = logging.getLogger("browser.native")


class NativeBrowserController:
    """Controls real macOS desktop browser sessions with tab, search, and media management."""

    def __init__(self, use_mock: bool = False) -> None:
        self._is_mac = sys.platform == "darwin"
        self._use_mock = use_mock or not self._is_mac
        self._mock_tabs: list[dict[str, Any]] = [
            {"index": 1, "title": "New Tab", "url": "about:blank"}
        ]
        self._mock_active_tab: int = 1

    def detect_active_browser(self) -> str:
        """Detect which supported browser is currently running or preferred."""
        if self._use_mock or not self._is_mac:
            return "mock"

        # Check Google Chrome
        try:
            res = subprocess.run(
                ["osascript", "-e", 'application "Google Chrome" is running'],
                capture_output=True,
                text=True,
                check=False,
                timeout=2,
            )
            if res.stdout.strip().lower() == "true":
                return "Google Chrome"
        except Exception:
            pass

        # Check Safari
        try:
            res = subprocess.run(
                ["osascript", "-e", 'application "Safari" is running'],
                capture_output=True,
                text=True,
                check=False,
                timeout=2,
            )
            if res.stdout.strip().lower() == "true":
                return "Safari"
        except Exception:
            pass

        return "Google Chrome"

    def focus_browser(self, browser_name: Optional[str] = None) -> bool:
        """Bring browser to front."""
        if self._use_mock or not self._is_mac:
            return True
        browser = browser_name or self.detect_active_browser()
        try:
            subprocess.run(
                ["osascript", "-e", f'tell application "{browser}" to activate'],
                check=False,
                timeout=3,
            )
            return True
        except Exception as err:
            logger.error("Failed to focus browser '%s': %s", browser, err)
            return False

    def list_tabs(self, browser_name: Optional[str] = None) -> list[dict[str, Any]]:
        """List all open tabs in the front browser window."""
        if self._use_mock or not self._is_mac:
            return list(self._mock_tabs)

        browser = browser_name or self.detect_active_browser()
        tabs: list[dict[str, Any]] = []

        if browser == "Google Chrome":
            script = """
            tell application "Google Chrome"
                if (count of windows) = 0 then return ""
                set out to ""
                set idx to 1
                repeat with t in tabs of front window
                    set out to out & (idx as string) & "|||" & (title of t) & "|||" & (URL of t) & "\\n"
                    set idx to idx + 1
                end repeat
                return out
            end tell
            """
            try:
                res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False, timeout=4)
                for line in res.stdout.strip().split("\n"):
                    parts = line.split("|||")
                    if len(parts) >= 3:
                        tabs.append({
                            "index": int(parts[0]),
                            "title": parts[1].strip(),
                            "url": parts[2].strip(),
                        })
            except Exception as err:
                logger.error("Failed to list Chrome tabs: %s", err)

        elif browser == "Safari":
            script = """
            tell application "Safari"
                if (count of windows) = 0 then return ""
                set out to ""
                set idx to 1
                repeat with t in tabs of front window
                    set out to out & (idx as string) & "|||" & (name of t) & "|||" & (URL of t) & "\\n"
                    set idx to idx + 1
                end repeat
                return out
            end tell
            """
            try:
                res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False, timeout=4)
                for line in res.stdout.strip().split("\n"):
                    parts = line.split("|||")
                    if len(parts) >= 3:
                        tabs.append({
                            "index": int(parts[0]),
                            "title": parts[1].strip(),
                            "url": parts[2].strip(),
                        })
            except Exception as err:
                logger.error("Failed to list Safari tabs: %s", err)

        return tabs

    def new_tab(self, url: str = "about:blank", browser_name: Optional[str] = None) -> dict[str, Any]:
        """Create a new tab and navigate to url."""
        if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("about:"):
            url = f"https://{url}"

        if self._use_mock or not self._is_mac:
            new_idx = len(self._mock_tabs) + 1
            entry = {"index": new_idx, "title": url, "url": url}
            self._mock_tabs.append(entry)
            self._mock_active_tab = new_idx
            return {"success": True, "action": "new_tab", "index": new_idx, "url": url}

        browser = browser_name or self.detect_active_browser()
        self.focus_browser(browser)

        if browser == "Google Chrome":
            script = f'''
            tell application "Google Chrome"
                if (count of windows) = 0 then
                    make new window
                    set URL of active tab of front window to "{url}"
                else
                    tell front window
                        set newTab to make new tab with properties {{URL:"{url}"}}
                        set active tab index to (count of tabs)
                    end tell
                end if
            end tell
            '''
            try:
                subprocess.run(["osascript", "-e", script], check=False, timeout=5)
                # Verify tab created
                tabs = self.list_tabs(browser)
                return {
                    "success": True,
                    "action": "new_tab",
                    "url": url,
                    "tabs_count": len(tabs),
                    "active_tab": tabs[-1] if tabs else {"url": url},
                }
            except Exception as err:
                logger.error("Failed to create Chrome new tab: %s", err)
                return {"success": False, "error": str(err)}

        elif browser == "Safari":
            script = f'''
            tell application "Safari"
                if (count of windows) = 0 then
                    make new document with properties {{URL:"{url}"}}
                else
                    tell front window
                        make new tab with properties {{URL:"{url}"}}
                        set current tab to tab (count of tabs)
                    end tell
                end if
            end tell
            '''
            try:
                subprocess.run(["osascript", "-e", script], check=False, timeout=5)
                tabs = self.list_tabs(browser)
                return {
                    "success": True,
                    "action": "new_tab",
                    "url": url,
                    "tabs_count": len(tabs),
                    "active_tab": tabs[-1] if tabs else {"url": url},
                }
            except Exception as err:
                logger.error("Failed to create Safari new tab: %s", err)
                return {"success": False, "error": str(err)}

        # Fallback system open
        subprocess.run(["open", url], check=False)
        return {"success": True, "action": "new_tab", "url": url}

    def close_tab(self, index: Optional[int] = None, browser_name: Optional[str] = None) -> dict[str, Any]:
        """Close the active tab or tab at index."""
        if self._use_mock or not self._is_mac:
            if self._mock_tabs:
                removed = self._mock_tabs.pop()
                return {"success": True, "action": "close_tab", "closed": removed}
            return {"success": False, "error": "No tabs open to close"}

        browser = browser_name or self.detect_active_browser()
        self.focus_browser(browser)

        if browser == "Google Chrome":
            if index is not None:
                script = f'''
                tell application "Google Chrome"
                    if (count of windows) > 0 and (count of tabs of front window) >= {index} then
                        close tab {index} of front window
                        return "closed"
                    end if
                end tell
                '''
            else:
                script = '''
                tell application "Google Chrome"
                    if (count of windows) > 0 then
                        close active tab of front window
                        return "closed"
                    end if
                end tell
                '''
            try:
                res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False, timeout=4)
                return {"success": True, "action": "close_tab"}
            except Exception as err:
                return {"success": False, "error": str(err)}

        elif browser == "Safari":
            script = '''
            tell application "Safari"
                if (count of windows) > 0 then
                    close current tab of front window
                    return "closed"
                end if
            end tell
            '''
            try:
                subprocess.run(["osascript", "-e", script], check=False, timeout=4)
                return {"success": True, "action": "close_tab"}
            except Exception as err:
                return {"success": False, "error": str(err)}

        return {"success": True, "action": "close_tab"}

    def switch_tab(self, target: Any, browser_name: Optional[str] = None) -> dict[str, Any]:
        """Switch to tab index (1-based) or 'next'/'previous'."""
        if self._use_mock or not self._is_mac:
            return {"success": True, "action": "switch_tab", "target": str(target)}

        browser = browser_name or self.detect_active_browser()
        self.focus_browser(browser)

        if str(target).lower() in ("next", "forward"):
            # Command + Option + Right Arrow or Ctrl + Tab
            cmd = 'tell application "System Events" to key code 124 using {command down, option down}'
            subprocess.run(["osascript", "-e", cmd], check=False, timeout=3)
            return {"success": True, "action": "switch_tab", "direction": "next"}

        if str(target).lower() in ("previous", "prev", "back"):
            cmd = 'tell application "System Events" to key code 123 using {command down, option down}'
            subprocess.run(["osascript", "-e", cmd], check=False, timeout=3)
            return {"success": True, "action": "switch_tab", "direction": "previous"}

        try:
            idx = int(target)
            if browser == "Google Chrome":
                script = f'tell application "Google Chrome" to set active tab index of front window to {idx}'
                subprocess.run(["osascript", "-e", script], check=False, timeout=3)
            elif browser == "Safari":
                script = f'tell application "Safari" to set current tab of front window to tab {idx} of front window'
                subprocess.run(["osascript", "-e", script], check=False, timeout=3)
            return {"success": True, "action": "switch_tab", "index": idx}
        except Exception as err:
            return {"success": False, "error": str(err)}

    def navigate(self, url: str, browser_name: Optional[str] = None) -> dict[str, Any]:
        """Navigate active tab to url."""
        if not url.startswith("http://") and not url.startswith("https://"):
            url = f"https://{url}"

        if self._use_mock or not self._is_mac:
            if self._mock_tabs:
                self._mock_tabs[self._mock_active_tab - 1]["url"] = url
            return {"success": True, "action": "navigate", "url": url}

        browser = browser_name or self.detect_active_browser()
        self.focus_browser(browser)

        if browser == "Google Chrome":
            script = f'''
            tell application "Google Chrome"
                if (count of windows) = 0 then
                    make new window
                end if
                set URL of active tab of front window to "{url}"
            end tell
            '''
            try:
                subprocess.run(["osascript", "-e", script], check=False, timeout=5)
                return {"success": True, "action": "navigate", "url": url}
            except Exception as err:
                logger.error("Chrome navigate error: %s", err)

        elif browser == "Safari":
            script = f'''
            tell application "Safari"
                if (count of windows) = 0 then
                    make new document with properties {{URL:"{url}"}}
                else
                    set URL of current tab of front window to "{url}"
                end if
            end tell
            '''
            try:
                subprocess.run(["osascript", "-e", script], check=False, timeout=5)
                return {"success": True, "action": "navigate", "url": url}
            except Exception as err:
                logger.error("Safari navigate error: %s", err)

        subprocess.run(["open", url], check=False)
        return {"success": True, "action": "navigate", "url": url}

    def find_tab(self, match_str: str, browser_name: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Find an existing open tab whose URL or title contains match_str."""
        tabs = self.list_tabs(browser_name)
        target = match_str.lower()
        for t in tabs:
            if target in t.get("url", "").lower() or target in t.get("title", "").lower():
                return t
        return None

    def open_or_reuse_tab(
        self,
        url: str,
        domain_pattern: Optional[str] = None,
        force_new_tab: bool = False,
        browser_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """Navigate to URL, strictly reusing an existing tab if available unless force_new_tab is True."""
        if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("about:"):
            url = f"https://{url}"

        if self._use_mock or not self._is_mac:
            if force_new_tab:
                return self.new_tab(url)
            if domain_pattern and self._mock_tabs:
                for t in self._mock_tabs:
                    if domain_pattern.lower() in t.get("url", "").lower():
                        t["url"] = url
                        return {"success": True, "action": "reuse_tab", "reused": True, "url": url}
            return self.navigate(url)

        browser = browser_name or self.detect_active_browser()
        self.focus_browser(browser)

        # Tab reuse policy: check if domain already open in any tab
        if not force_new_tab and domain_pattern:
            existing = self.find_tab(domain_pattern, browser)
            if existing:
                idx = existing.get("index", 1)
                self.switch_tab(idx, browser)
                if existing.get("url", "") != url:
                    res = self.navigate(url, browser)
                    res["reused"] = True
                    return res
                return {
                    "success": True,
                    "action": "reuse_tab",
                    "reused": True,
                    "index": idx,
                    "url": existing.get("url", url),
                    "title": existing.get("title", ""),
                }

        # If user explicitly requested a new tab
        if force_new_tab:
            return self.new_tab(url, browser)

        # Check if active tab is blank or new tab
        tabs = self.list_tabs(browser)
        if not tabs:
            return self.new_tab(url, browser)

        return self.navigate(url, browser)

    def search_google(self, query: str, in_new_tab: bool = False) -> dict[str, Any]:
        """Perform a Google search with tab reuse unless in_new_tab is explicitly requested."""
        encoded = urllib.parse.quote_plus(query)
        url = f"https://www.google.com/search?q={encoded}"
        res = self.open_or_reuse_tab(url, domain_pattern="google.com", force_new_tab=in_new_tab)
        res["query"] = query
        res["search_engine"] = "google"
        return res

    def search_youtube(self, query: str, in_new_tab: bool = False) -> dict[str, Any]:
        """Perform a YouTube search with tab reuse unless in_new_tab is explicitly requested."""
        encoded = urllib.parse.quote_plus(query)
        url = f"https://www.youtube.com/results?search_query={encoded}"
        res = self.open_or_reuse_tab(url, domain_pattern="youtube.com", force_new_tab=in_new_tab)
        res["query"] = query
        res["service"] = "youtube"
        return res

    def resolve_youtube_top_video(self, query: str) -> Optional[str]:
        """Extract top video ID from YouTube search for instant playback using dual JSON/HTML scraping."""
        encoded = urllib.parse.quote_plus(query)
        search_url = f"https://www.youtube.com/results?search_query={encoded}"
        req = urllib.request.Request(
            search_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                html_text = resp.read().decode("utf-8", errors="ignore")
                # 1. Primary: match JSON videoId inside ytInitialData
                json_vids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html_text)
                if json_vids:
                    return json_vids[0]
                # 2. Secondary: match href /watch?v=
                vids = re.findall(r'/watch\?v=([a-zA-Z0-9_-]{11})', html_text)
                if vids:
                    return vids[0]
        except Exception as err:
            logger.debug("Failed to scrape top YouTube video: %s", err)
        return None

    def play_youtube(self, query: str, in_new_tab: bool = False) -> dict[str, Any]:
        """Search YouTube, resolve the top video, and navigate directly to play it with tab reuse."""
        video_id = self.resolve_youtube_top_video(query)
        if video_id:
            watch_url = f"https://www.youtube.com/watch?v={video_id}"
            res = self.open_or_reuse_tab(watch_url, domain_pattern="youtube.com", force_new_tab=in_new_tab)
            res["video_id"] = video_id
            res["query"] = query
            res["status"] = "playing"
            return res

        # Fallback to search results page
        return self.search_youtube(query, in_new_tab=in_new_tab)

    def toggle_playback(self, command: str = "pause") -> dict[str, Any]:
        """Toggle or control playback in active window/browser."""
        if self._use_mock or not self._is_mac:
            return {"success": True, "action": command}

        # Focus frontmost browser or media player
        browser = self.detect_active_browser()
        self.focus_browser(browser)

        # Space bar toggles playback on YouTube / HTML5 video
        try:
            subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to key code 49'],
                check=False,
                timeout=2,
            )
            return {"success": True, "action": command, "target": browser}
        except Exception as err:
            return {"success": False, "error": str(err)}

    def scroll(self, direction: str = "down", amount: int = 3) -> dict[str, Any]:
        """Scroll active browser page."""
        if self._use_mock or not self._is_mac:
            return {"success": True, "action": "scroll", "direction": direction}

        browser = self.detect_active_browser()
        self.focus_browser(browser)

        # 125 = down arrow, 126 = up arrow, 121 = pagedown, 116 = pageup
        code = 125 if direction.lower() in ("down", "bottom") else 126
        try:
            for _ in range(amount):
                subprocess.run(
                    ["osascript", "-e", f'tell application "System Events" to key code {code}'],
                    check=False,
                    timeout=2,
                )
            return {"success": True, "action": "scroll", "direction": direction}
        except Exception as err:
            return {"success": False, "error": str(err)}

    def click_first_result(self, last_query: Optional[str] = None, last_domain: Optional[str] = None) -> dict[str, Any]:
        """Click or navigate to the first search result on YouTube or Google using semantic DOM inspection."""
        if self._use_mock or not self._is_mac:
            target_url = f"https://www.youtube.com/watch?v=mock_video" if last_domain == "youtube.com" else "https://example.com/first_result"
            if self._mock_tabs:
                self._mock_tabs[self._mock_active_tab - 1]["url"] = target_url
            return {"success": True, "action": "open_search_result", "index": 1, "url": target_url}

        browser = self.detect_active_browser()
        self.focus_browser(browser)

        # YouTube specific handling
        if last_domain == "youtube.com" or (last_query and "youtube" in (last_query or "").lower()):
            if last_query:
                # Direct top video resolution
                return self.play_youtube(last_query)

            # Click top video on existing YouTube results page
            if browser == "Google Chrome":
                script = '''
                tell application "Google Chrome"
                    if (count of windows) > 0 then
                        tell active tab of front window
                            execute javascript "(() => { const v = document.querySelector('ytd-video-renderer a#video-title'); if (v) { const u = v.href; window.location.href = u; return u; } return ''; })()"
                        end tell
                    end if
                end tell
                '''
                try:
                    subprocess.run(["osascript", "-e", script], check=False, timeout=4)
                    return {"success": True, "action": "open_search_result", "index": 1, "service": "youtube"}
                except Exception as err:
                    logger.debug("Chrome YouTube click failed: %s", err)

            elif browser == "Safari":
                script = '''
                tell application "Safari"
                    if (count of windows) > 0 then
                        tell current tab of front window
                            do JavaScript "(() => { const v = document.querySelector('ytd-video-renderer a#video-title'); if (v) { const u = v.href; window.location.href = u; return u; } return ''; })()"
                        end tell
                    end if
                end tell
                '''
                try:
                    subprocess.run(["osascript", "-e", script], check=False, timeout=4)
                    return {"success": True, "action": "open_search_result", "index": 1, "service": "youtube"}
                except Exception as err:
                    logger.debug("Safari YouTube click failed: %s", err)

        # Google / General Web Search handling
        if browser == "Google Chrome":
            script = '''
            tell application "Google Chrome"
                if (count of windows) > 0 then
                    tell active tab of front window
                        execute javascript "(() => { const a = document.querySelector('div#search a h3')?.closest('a') || document.querySelector('h3')?.closest('a'); if (a) { const u = a.href; window.location.href = u; return u; } return ''; })()"
                    end tell
                end if
            end tell
            '''
            try:
                subprocess.run(["osascript", "-e", script], check=False, timeout=4)
                return {"success": True, "action": "open_search_result", "index": 1, "service": "google"}
            except Exception as err:
                logger.debug("Chrome Google click failed: %s", err)

        elif browser == "Safari":
            script = '''
            tell application "Safari"
                if (count of windows) > 0 then
                    tell current tab of front window
                        do JavaScript "(() => { const a = document.querySelector('div#search a h3')?.closest('a') || document.querySelector('h3')?.closest('a'); if (a) { const u = a.href; window.location.href = u; return u; } return ''; })()"
                    end tell
                end if
            end tell
            '''
            try:
                subprocess.run(["osascript", "-e", script], check=False, timeout=4)
                return {"success": True, "action": "open_search_result", "index": 1, "service": "google"}
            except Exception as err:
                logger.debug("Safari Google click failed: %s", err)

        # Final fallback: press Return key to activate focused result
        try:
            subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to key code 36'],
                check=False,
                timeout=2,
            )
            return {"success": True, "action": "open_search_result", "index": 1}
        except Exception:
            pass

        return {"success": True, "action": "open_search_result", "index": 1}
