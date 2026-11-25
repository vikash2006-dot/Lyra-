"""Unit tests for browser tab reuse policy and YouTube playback resolution."""

import pytest

from lyra.browser.native_browser import NativeBrowserController
from lyra.models.tools import ToolRequest
from lyra.tools.browser_tool import BrowserTool


def test_native_browser_tab_reuse():
    controller = NativeBrowserController(use_mock=True)

    # Initial mock state has index 1: about:blank
    # 1. Search YouTube
    res1 = controller.search_youtube("Believer")
    assert res1["success"] is True
    assert "youtube.com" in res1["url"]

    # 2. Search again: should reuse the existing tab rather than creating a new one
    tabs_before = len(controller.list_tabs())
    res2 = controller.search_youtube("Arijit Singh")
    tabs_after = len(controller.list_tabs())
    assert tabs_after == tabs_before  # Reused!
    assert res2.get("reused") is True

    # 3. Explicitly request new tab
    res3 = controller.search_youtube("Coldplay", in_new_tab=True)
    tabs_new = len(controller.list_tabs())
    assert tabs_new == tabs_before + 1


def test_native_browser_google_tab_reuse():
    controller = NativeBrowserController(use_mock=True)

    # 1. Google search
    res1 = controller.search_google("Python tutorials")
    assert res1["success"] is True
    assert "google.com" in res1["url"]

    # 2. Subsequent Google search reuses tab
    tabs_before = len(controller.list_tabs())
    res2 = controller.search_google("React authentication")
    tabs_after = len(controller.list_tabs())
    assert tabs_after == tabs_before
    assert res2.get("reused") is True

    # 3. Explicitly request new tab
    res3 = controller.search_google("Rust tutorial", in_new_tab=True)
    assert len(controller.list_tabs()) == tabs_before + 1


def test_youtube_top_video_dual_resolution(monkeypatch):
    controller = NativeBrowserController(use_mock=True)

    # Test JSON videoId extraction
    fake_html = '{"videoId":"W0DM5lcj6mw","title":{"runs":[{"text":"Imagine Dragons - Believer"}]}}'

    class FakeResponse:
        def __init__(self, data):
            self._data = data.encode("utf-8")

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: FakeResponse(fake_html))

    vid = controller.resolve_youtube_top_video("Believer")
    assert vid == "W0DM5lcj6mw"


def test_browser_tool_no_duplicate_launch(monkeypatch):
    import asyncio

    async def _run():
        controller = NativeBrowserController(use_mock=True)
        tool = BrowserTool(native_controller=controller)

        # Verify navigate does not fail and uses native controller
        req = ToolRequest(tool_name="browser", arguments={"action": "navigate", "url": "https://example.com"})
        res = await tool.execute(req)
        assert res.success is True
        assert res.output["url"] == "https://example.com"

    asyncio.run(_run())
