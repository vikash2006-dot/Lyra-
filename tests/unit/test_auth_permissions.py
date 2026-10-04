"""Unit tests verifying that identity and authentication respect tool permissions."""

import pytest

from lyra.companion.session import Session
from lyra.models.identity import AuthenticationState, User
from lyra.models.tools import ToolRequest, ToolResult
from lyra.tools.base import Tool
from lyra.tools.executor import ToolExecutor
from lyra.tools.permissions import PermissionPolicy, ToolPermissionLevel
from lyra.tools.registry import ToolRegistry


class SafeTool(Tool):
    """Read-only safe dummy tool."""

    @property
    def name(self) -> str:
        return "safe_tool"

    @property
    def description(self) -> str:
        return "A safe read-only tool."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.READ_ONLY

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, request: ToolRequest) -> ToolResult:
        return ToolResult(tool_name=self.name, success=True, output="safe_executed")


class DangerousTool(Tool):
    """High-risk dangerous dummy tool."""

    @property
    def name(self) -> str:
        return "dangerous_tool"

    @property
    def description(self) -> str:
        return "A high risk tool."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return ToolPermissionLevel.HIGH_RISK

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, request: ToolRequest) -> ToolResult:
        return ToolResult(tool_name=self.name, success=True, output="dangerous_executed")


@pytest.fixture
def tool_env():
    """Setup registry and tools."""
    registry = ToolRegistry()
    registry.register(SafeTool())
    registry.register(DangerousTool())
    return registry


import asyncio


def test_authenticated_user_cannot_bypass_default_permission_policy(tool_env):
    """Verify that logging in does NOT grant access to dangerous tools under default policy."""
    policy = PermissionPolicy()  # Defaults to READ_ONLY and LOW_RISK
    executor = ToolExecutor(registry=tool_env, policy=policy)

    user = User(id="user-standard", username="john_doe", display_name="John Doe")
    session = Session()
    session.bind_user(user)
    assert session.is_authenticated is True

    # Safe tool succeeds
    req_safe = ToolRequest(tool_name="safe_tool", user_id=session.user_id)
    res_safe = asyncio.run(executor.execute(req_safe))
    assert res_safe.success is True
    assert res_safe.output == "safe_executed"

    # Dangerous tool fails permission check even though user is authenticated!
    req_dangerous = ToolRequest(tool_name="dangerous_tool", user_id=session.user_id)
    res_dangerous = asyncio.run(executor.execute(req_dangerous))
    assert res_dangerous.success is False
    assert "Permission denied" in res_dangerous.error
    assert "HIGH_RISK" in res_dangerous.error


def test_user_specific_permission_policies(tool_env):
    """Verify that user-specific policy overrides only affect the designated user."""
    admin_id = "user-admin-123"
    regular_id = "user-regular-456"

    # Policy grants HIGH_RISK only to admin_id
    policy = PermissionPolicy(
        allowed_levels=[ToolPermissionLevel.READ_ONLY],
        user_policies={
            admin_id: [ToolPermissionLevel.READ_ONLY, ToolPermissionLevel.HIGH_RISK],
        },
    )
    executor = ToolExecutor(registry=tool_env, policy=policy)

    # Admin user can execute dangerous tool
    admin_req = ToolRequest(tool_name="dangerous_tool", user_id=admin_id)
    admin_res = asyncio.run(executor.execute(admin_req))
    assert admin_res.success is True
    assert admin_res.output == "dangerous_executed"

    # Regular user is denied dangerous tool
    regular_req = ToolRequest(tool_name="dangerous_tool", user_id=regular_id)
    regular_res = asyncio.run(executor.execute(regular_req))
    assert regular_res.success is False
    assert "Permission denied" in regular_res.error

    # Anonymous user is denied dangerous tool
    anon_req = ToolRequest(tool_name="dangerous_tool", user_id=None)
    anon_res = asyncio.run(executor.execute(anon_req))
    assert anon_res.success is False
    assert "Permission denied" in anon_res.error
