"""Unit tests for BrowserTool integration with LYRA tool system, executor, and permissions."""

import asyncio
from pathlib import Path
import pytest

from lyra.browser.manager import BrowserManager
from lyra.browser.mock_driver import MockBrowserDriver
from lyra.browser.policy import BrowserPolicy
from lyra.models.tools import ToolRequest, ToolResult
from lyra.tools.browser_tool import BrowserTool
from lyra.tools.executor import ToolExecutor
from lyra.tools.permissions import PermissionPolicy, ToolPermissionLevel
from lyra.tools.registry import ToolRegistry


def test_browser_tool_metadata():
    tool = BrowserTool()
    assert tool.name == "browser"
    assert "open websites" in tool.description.lower()
    assert tool.permission_level == ToolPermissionLevel.LOW_RISK

    schema = tool.input_schema
    assert schema["type"] == "object"
    assert "action" in schema["required"]
    assert "navigate" in schema["properties"]["action"]["enum"]
    assert "download" in schema["properties"]["action"]["enum"]


def test_browser_tool_can_handle():
    tool = BrowserTool()

    # URL navigation queries
    res = tool.can_handle("Please open website https://news.ycombinator.com")
    assert res is not None
    assert res["action"] == "navigate"
    assert res["url"] == "https://news.ycombinator.com"

    res_url = tool.can_handle("https://example.com")
    assert res_url is not None
    assert res_url["action"] == "navigate"

    # Download query
    res_dl = tool.can_handle("Please download https://example.com/dataset.csv")
    assert res_dl is not None
    assert res_dl["action"] == "download"
    assert res_dl["url"] == "https://example.com/dataset.csv"

    # Extraction query
    res_ext = tool.can_handle("Read the current webpage")
    assert res_ext is not None
    assert res_ext["action"] == "extract"

    # Unrelated queries
    assert tool.can_handle("What is the weather in Tokyo?") is None
    assert tool.can_handle("Hello, how are you?") is None


def test_browser_tool_navigate_and_extract_flow():
    async def _test():
        driver = MockBrowserDriver()
        driver.register_page(
            "https://docs.local/guide",
            "Documentation Guide",
            "<html><head><title>Documentation Guide</title></head><body><h1>Guide</h1><p>Step 1: Install.</p></body></html>",
        )
        manager = BrowserManager(driver=driver)
        tool = BrowserTool(manager=manager)

        # 1. Extract before navigate fails
        req_extract_empty = ToolRequest(
            tool_name="browser",
            arguments={"action": "extract", "session_id": "test_sess"},
        )
        res_extract_empty = await tool.execute(req_extract_empty)
        assert not res_extract_empty.success
        assert "No active webpage" in res_extract_empty.error

        # 2. Navigate to page
        req_nav = ToolRequest(
            tool_name="browser",
            arguments={"action": "navigate", "url": "https://docs.local/guide", "session_id": "test_sess"},
        )
        res_nav = await tool.execute(req_nav)
        assert res_nav.success
        assert res_nav.output["url"] == "https://docs.local/guide"
        assert res_nav.output["title"] == "Documentation Guide"
        assert "<untrusted_external_content source=\"browser\">" in res_nav.output["content"]
        assert "Step 1: Install." in res_nav.output["content"]

        # 3. Extract active page
        req_extract = ToolRequest(
            tool_name="browser",
            arguments={"action": "extract", "session_id": "test_sess"},
        )
        res_extract = await tool.execute(req_extract)
        assert res_extract.success
        assert res_extract.output["title"] == "Documentation Guide"
        assert "Step 1: Install." in res_extract.output["content"]

        await manager.close()

    asyncio.run(_test())


def test_browser_tool_confirmation_enforcement_for_clicks_and_fills():
    async def _test():
        driver = MockBrowserDriver()
        manager = BrowserManager(driver=driver)
        tool = BrowserTool(manager=manager)

        # Navigate first
        await tool.execute(ToolRequest(
            tool_name="browser",
            arguments={"action": "navigate", "url": "https://store.local/account", "session_id": "user_sess"},
        ))

        # 1. Destructive click without confirmed=True fails with confirmation notice
        req_click_unconfirmed = ToolRequest(
            tool_name="browser",
            arguments={
                "action": "click",
                "selector": "button.btn-delete-account",
                "session_id": "user_sess",
                "confirmed": False,
            },
        )
        res_click_unconfirmed = await tool.execute(req_click_unconfirmed)
        assert not res_click_unconfirmed.success
        assert res_click_unconfirmed.metadata.get("requires_confirmation") is True
        assert "confirmation required" in res_click_unconfirmed.error.lower()

        # 2. Destructive click with confirmed=True succeeds
        req_click_confirmed = ToolRequest(
            tool_name="browser",
            arguments={
                "action": "click",
                "selector": "button.btn-delete-account",
                "session_id": "user_sess",
                "confirmed": True,
            },
        )
        res_click_confirmed = await tool.execute(req_click_confirmed)
        assert res_click_confirmed.success
        assert res_click_confirmed.output["selector"] == "button.btn-delete-account"

        # 3. Password fill without confirmed=True fails with confirmation notice
        req_fill_unconfirmed = ToolRequest(
            tool_name="browser",
            arguments={
                "action": "fill",
                "selector": "input#password",
                "value": "secret123",
                "session_id": "user_sess",
                "confirmed": False,
            },
        )
        res_fill_unconfirmed = await tool.execute(req_fill_unconfirmed)
        assert not res_fill_unconfirmed.success
        assert res_fill_unconfirmed.metadata.get("requires_confirmation") is True

        # 4. Password fill with confirmed=True succeeds
        req_fill_confirmed = ToolRequest(
            tool_name="browser",
            arguments={
                "action": "fill",
                "selector": "input#password",
                "value": "secret123",
                "session_id": "user_sess",
                "confirmed": True,
            },
        )
        res_fill_confirmed = await tool.execute(req_fill_confirmed)
        assert res_fill_confirmed.success

        await manager.close()

    asyncio.run(_test())


def test_browser_tool_download_lifecycle(tmp_path: Path):
    async def _test():
        driver = MockBrowserDriver()
        download_dir = tmp_path / "browser_downloads"
        policy = BrowserPolicy(download_dir=download_dir, max_download_size_bytes=5000)
        manager = BrowserManager(driver=driver, policy=policy)
        tool = BrowserTool(manager=manager, policy=policy)

        # 1. Download without confirmation fails
        req_dl_unconfirmed = ToolRequest(
            tool_name="browser",
            arguments={
                "action": "download",
                "url": "https://example.local/report.pdf",
                "confirmed": False,
            },
        )
        res_dl_unconfirmed = await tool.execute(req_dl_unconfirmed)
        assert not res_dl_unconfirmed.success
        assert res_dl_unconfirmed.metadata.get("requires_confirmation") is True

        # 2. Confirmed download succeeds
        req_dl_confirmed = ToolRequest(
            tool_name="browser",
            arguments={
                "action": "download",
                "url": "https://example.local/report.pdf",
                "confirmed": True,
            },
        )
        res_dl_confirmed = await tool.execute(req_dl_confirmed)
        assert res_dl_confirmed.success
        assert "report.pdf" in res_dl_confirmed.output["downloaded_path"]
        assert Path(res_dl_confirmed.output["downloaded_path"]).exists()

        # 3. Download exceeding size limit
        big_session = await manager.get_or_create_session("big_download")
        big_session._driver.mock_download_data["https://example.local/huge.iso"] = b"X" * 10000

        req_dl_huge = ToolRequest(
            tool_name="browser",
            arguments={
                "action": "download",
                "url": "https://example.local/huge.iso",
                "confirmed": True,
                "session_id": "big_download",
            },
        )
        res_dl_huge = await tool.execute(req_dl_huge)
        assert not res_dl_huge.success
        assert "exceeds maximum limit" in res_dl_huge.error

        await manager.close()

    asyncio.run(_test())


def test_browser_tool_executor_integration():
    async def _test():
        driver = MockBrowserDriver()
        manager = BrowserManager(driver=driver)
        tool = BrowserTool(manager=manager)

        registry = ToolRegistry()
        registry.register(tool)

        # Policy permitting LOW_RISK (default)
        executor = ToolExecutor(registry=registry, policy=PermissionPolicy())

        req = ToolRequest(
            tool_name="browser",
            arguments={"action": "navigate", "url": "https://example.com"},
        )
        res = await executor.execute(req)
        assert res.success
        assert res.output["url"] == "https://example.com"

        # Policy denying LOW_RISK (READ_ONLY only)
        restricted_policy = PermissionPolicy(allowed_levels=[ToolPermissionLevel.READ_ONLY])
        restricted_executor = ToolExecutor(registry=registry, policy=restricted_policy)

        res_blocked = await restricted_executor.execute(req)
        assert not res_blocked.success
        assert "Permission denied" in res_blocked.error

        await manager.close()

    asyncio.run(_test())
