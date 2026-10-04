"""Unit tests for NativeBrowserController tabs, MediaTool, KeyboardTool, and MouseTool."""

import pytest
from lyra.browser.native_browser import NativeBrowserController
from lyra.computer.media import MediaController
from lyra.models.tools import ToolRequest
from lyra.tools.browser_tool import BrowserTool
from lyra.tools.keyboard_mouse_tool import KeyboardTool, MouseTool
from lyra.tools.media_tool import MediaTool


def test_native_browser_controller_mock_tab_lifecycle():
    nb = NativeBrowserController(use_mock=True)
    initial_tabs = nb.list_tabs()
    assert len(initial_tabs) == 1

    # New tab
    res_new = nb.new_tab("https://github.com")
    assert res_new["success"]
    assert len(nb.list_tabs()) == 2

    # Switch tab
    res_switch = nb.switch_tab(1)
    assert res_switch["success"]

    # Close tab
    res_close = nb.close_tab()
    assert res_close["success"]
    assert len(nb.list_tabs()) == 1


def test_browser_tool_tab_actions():
    import asyncio

    async def _test():
        nb = NativeBrowserController(use_mock=True)
        tool = BrowserTool(native_controller=nb)

        # 1. new_tab
        req_new = ToolRequest(tool_name="browser", arguments={"action": "new_tab", "url": "https://www.google.com"})
        res_new = await tool.execute(req_new)
        assert res_new.success
        assert res_new.output["action"] == "new_tab"
        assert "https://www.google.com" in res_new.output["url"]

        # 2. list_tabs
        req_list = ToolRequest(tool_name="browser", arguments={"action": "list_tabs"})
        res_list = await tool.execute(req_list)
        assert res_list.success
        assert res_list.output["count"] >= 1

        # 3. switch_tab
        req_switch = ToolRequest(tool_name="browser", arguments={"action": "switch_tab", "direction": "previous"})
        res_switch = await tool.execute(req_switch)
        assert res_switch.success

        # 4. close_tab
        req_close = ToolRequest(tool_name="browser", arguments={"action": "close_tab"})
        res_close = await tool.execute(req_close)
        assert res_close.success

    asyncio.run(_test())


def test_media_tool_actions():
    import asyncio

    async def _test():
        m_ctrl = MediaController(use_mock=True)
        tool = MediaTool(controller=m_ctrl)

        req_pause = ToolRequest(tool_name="media", arguments={"action": "pause"})
        res_pause = await tool.execute(req_pause)
        assert res_pause.success
        assert "Paused" in tool.format_result(res_pause)

        req_play = ToolRequest(tool_name="media", arguments={"action": "play"})
        res_play = await tool.execute(req_play)
        assert res_play.success

        req_next = ToolRequest(tool_name="media", arguments={"action": "next"})
        res_next = await tool.execute(req_next)
        assert res_next.success

    asyncio.run(_test())


def test_keyboard_and_mouse_tools():
    import asyncio

    async def _test():
        kb_tool = KeyboardTool()
        req_key = ToolRequest(tool_name="keyboard", arguments={"action": "press", "key": "enter"})
        res_key = await kb_tool.execute(req_key)
        assert res_key.success

        req_hotkey = ToolRequest(tool_name="keyboard", arguments={"action": "hotkey", "keys": ["command", "l"]})
        res_hotkey = await kb_tool.execute(req_hotkey)
        assert res_hotkey.success

        mouse_tool = MouseTool()
        req_move = ToolRequest(tool_name="mouse", arguments={"action": "move", "x": 100, "y": 200})
        res_move = await mouse_tool.execute(req_move)
        assert res_move.success
        assert res_move.output["x"] == 100

    asyncio.run(_test())
