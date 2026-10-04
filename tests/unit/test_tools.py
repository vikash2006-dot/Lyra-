"""Unit tests for LYRA tool calling models, registry, and permissions."""

import pytest

from lyra.core.exceptions import (
    ModelValidationError,
    ToolError,
    ToolPermissionError,
    ToolValidationError,
)
from lyra.models.tools import ToolRequest, ToolResult
from lyra.tools.base import Tool
from lyra.tools.decider import ToolDecider
from lyra.tools.executor import validate_tool_arguments
from lyra.tools.permissions import PermissionPolicy, ToolPermissionLevel
from lyra.tools.registry import ToolRegistry


class DummyTool(Tool):
    """Dummy tool for testing registration and execution."""

    def __init__(self, name: str = "dummy", level: ToolPermissionLevel = ToolPermissionLevel.READ_ONLY) -> None:
        self._name = name
        self._level = level

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Dummy tool description."

    @property
    def permission_level(self) -> ToolPermissionLevel:
        return self._level

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "count": {"type": "integer"},
                "mode": {"type": "string", "enum": ["fast", "slow"]},
            },
            "required": ["text"],
            "additionalProperties": False,
        }

    def can_handle(self, user_input: str) -> dict | None:
        if "dummy" in user_input.lower():
            return {"text": "hello"}
        return None

    async def execute(self, request: ToolRequest) -> ToolResult:
        return ToolResult(tool_name=self.name, success=True, output=f"dummy: {request.arguments.get('text')}")


def test_tool_request_models():
    """Verify ToolRequest validation and fields."""
    req = ToolRequest(tool_name="test_tool", arguments={"key": "val"})
    assert req.tool_name == "test_tool"
    assert req.arguments == {"key": "val"}

    with pytest.raises(ModelValidationError):
        ToolRequest(tool_name="")

    with pytest.raises(ModelValidationError):
        ToolRequest(tool_name="tool", arguments="invalid")  # type: ignore


def test_tool_result_models():
    """Verify ToolResult success, failure, and serialization."""
    res_success = ToolResult(tool_name="calc", success=True, output={"result": 42})
    assert res_success.is_success() is True
    assert res_success.is_failure() is False
    assert "42" in res_success.to_text()

    res_fail = ToolResult(tool_name="calc", success=False, error="division by zero")
    assert res_fail.is_success() is False
    assert res_fail.is_failure() is True
    assert "division by zero" in res_fail.to_text()

    with pytest.raises(ModelValidationError):
        ToolResult(tool_name="", success=True)


def test_tool_registry():
    """Verify registry add, get, list, duplicate prevention, and schema export."""
    registry = ToolRegistry()
    assert len(registry.list_tools()) == 0

    tool = DummyTool(name="test_calc")
    registry.register(tool)
    assert registry.has("test_calc") is True
    assert registry.has("TEST_CALC") is True
    assert registry.get("test_calc") is tool
    assert registry.get("nonexistent") is None
    assert len(registry.list_tools()) == 1

    # Duplicate registration should raise ToolError
    with pytest.raises(ToolError, match="already registered"):
        registry.register(DummyTool(name="test_calc"))

    # Registering non-tool should raise ToolError
    with pytest.raises(ToolError, match="non-Tool object"):
        registry.register("not_a_tool")  # type: ignore

    # Tool with empty name
    with pytest.raises(ToolError, match="cannot be empty"):
        registry.register(DummyTool(name="   "))

    # Schemas export
    schemas = registry.get_schemas()
    assert len(schemas) == 1
    assert schemas[0]["name"] == "test_calc"
    assert schemas[0]["permission_level"] == "READ_ONLY"
    assert "parameters" in schemas[0]


def test_permission_policy():
    """Verify default and custom permission policy enforcement."""
    policy = PermissionPolicy()
    assert policy.is_allowed(ToolPermissionLevel.READ_ONLY) is True
    assert policy.is_allowed(ToolPermissionLevel.LOW_RISK) is True
    assert policy.is_allowed(ToolPermissionLevel.CONFIRMATION_REQUIRED) is False
    assert policy.is_allowed(ToolPermissionLevel.HIGH_RISK) is False

    # Should not raise for allowed
    policy.verify_permission("safe_tool", ToolPermissionLevel.READ_ONLY)

    # Should raise for disallowed
    with pytest.raises(ToolPermissionError, match="Permission denied"):
        policy.verify_permission("risky_tool", ToolPermissionLevel.HIGH_RISK)

    # Custom policy
    elevated_policy = PermissionPolicy(allowed_levels=[ToolPermissionLevel.HIGH_RISK])
    assert elevated_policy.is_allowed(ToolPermissionLevel.HIGH_RISK) is True
    assert elevated_policy.is_allowed(ToolPermissionLevel.READ_ONLY) is False


def test_validate_tool_arguments():
    """Verify JSON schema subset argument validator."""
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "count": {"type": "integer"},
            "ratio": {"type": "number"},
            "flag": {"type": "boolean"},
            "mode": {"type": "string", "enum": ["a", "b"]},
        },
        "required": ["name"],
        "additionalProperties": False,
    }

    # Valid args
    validate_tool_arguments(schema, {"name": "test", "count": 5, "ratio": 1.5, "flag": True, "mode": "a"})

    # Non-dict arguments
    with pytest.raises(ToolValidationError, match="must be a dictionary"):
        validate_tool_arguments(schema, "string")  # type: ignore

    # Missing required
    with pytest.raises(ToolValidationError, match="Missing required argument"):
        validate_tool_arguments(schema, {"count": 1})

    # Unexpected argument
    with pytest.raises(ToolValidationError, match="Unexpected argument"):
        validate_tool_arguments(schema, {"name": "ok", "unknown_field": 123})

    # Type mismatch: string expected
    with pytest.raises(ToolValidationError, match="expected string"):
        validate_tool_arguments(schema, {"name": 123})

    # Type mismatch: integer expected, got bool (bool is subclass of int)
    with pytest.raises(ToolValidationError, match="expected integer, got bool"):
        validate_tool_arguments(schema, {"name": "ok", "count": True})

    # Enum mismatch
    with pytest.raises(ToolValidationError, match="Allowed choices"):
        validate_tool_arguments(schema, {"name": "ok", "mode": "invalid_choice"})


def test_tool_decider():
    """Verify ToolDecider routes queries to matching tools."""
    tool = DummyTool(name="dummy")
    registry = ToolRegistry(tools=[tool])
    decider = ToolDecider(registry)

    # Matching query
    req = decider.decide("Can you run the dummy tool?")
    assert req is not None
    assert req.tool_name == "dummy"
    assert req.arguments == {"text": "hello"}

    # Non-matching query
    assert decider.decide("What is the weather?") is None
