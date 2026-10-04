"""Centralized tool execution harness for LYRA."""

import asyncio
from typing import Any

from lyra.core.exceptions import (
    ToolError,
    ToolLimitExceededError,
    ToolNotFoundError,
    ToolPermissionError,
    ToolTimeoutError,
    ToolValidationError,
)
from lyra.models.tools import ToolRequest, ToolResult
from lyra.observability.logging import get_logger
from lyra.tools.permissions import PermissionPolicy, ToolPermissionLevel
from lyra.tools.registry import ToolRegistry

DEFAULT_TOOL_TIMEOUT_SECONDS: float = 10.0
DEFAULT_MAX_EXECUTIONS_PER_TURN: int = 5


def validate_tool_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    """Validate argument dictionary against a JSON Schema subset."""
    if not isinstance(arguments, dict):
        raise ToolValidationError("Arguments must be a dictionary.")

    properties = schema.get("properties", {})
    required = schema.get("required", [])
    allow_additional = schema.get("additionalProperties", True)

    # Check required properties
    for req_field in required:
        if req_field not in arguments:
            raise ToolValidationError(f"Missing required argument: '{req_field}'.")

    # Check unexpected properties
    if not allow_additional:
        for arg_key in arguments:
            if arg_key not in properties:
                raise ToolValidationError(f"Unexpected argument: '{arg_key}'.")

    # Check types and enum constraints
    type_map = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "object": dict,
        "array": list,
    }

    for key, val in arguments.items():
        if key in properties:
            spec = properties[key]
            expected_type_name = spec.get("type")
            if expected_type_name and expected_type_name in type_map:
                expected_py_type = type_map[expected_type_name]
                # In Python, bool is a subclass of int; disallow booleans when integer/number is expected
                if expected_type_name in ("integer", "number") and isinstance(val, bool):
                    raise ToolValidationError(
                        f"Argument '{key}' expected {expected_type_name}, got bool."
                    )
                if not isinstance(val, expected_py_type):
                    raise ToolValidationError(
                        f"Argument '{key}' expected {expected_type_name}, got {type(val).__name__}."
                    )

            # Check enum choices
            if "enum" in spec and val not in spec["enum"]:
                valid_choices = ", ".join(repr(c) for c in spec["enum"])
                raise ToolValidationError(
                    f"Argument '{key}' has invalid value {val!r}. Allowed choices: [{valid_choices}]."
                )


class ToolExecutor:
    """Executes tools safely with validation, permission enforcement, and loop limits."""

    def __init__(
        self,
        registry: ToolRegistry,
        policy: PermissionPolicy | None = None,
        timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS,
        max_executions_per_turn: int = DEFAULT_MAX_EXECUTIONS_PER_TURN,
        offline_mode: bool | None = None,
    ) -> None:
        from lyra.config.settings import load_settings
        self.registry: ToolRegistry = registry
        self.policy: PermissionPolicy = policy or PermissionPolicy()
        self.timeout_seconds: float = timeout_seconds
        self.max_executions_per_turn: int = max_executions_per_turn
        self.offline_mode: bool = offline_mode if offline_mode is not None else load_settings().offline_mode
        self._logger = get_logger("tools.executor")

    async def execute(
        self,
        request: ToolRequest,
        execution_count: int = 0,
    ) -> ToolResult:
        """Validate, authorize, and execute a tool request.

        Args:
            request: The ToolRequest specifying tool name and arguments.
            execution_count: Current count of tool executions in this turn (loop prevention).

        Returns:
            Structured ToolResult indicating success or failure.
        """
        tool_name = request.tool_name

        # 1. Enforce recursion limit
        if execution_count >= self.max_executions_per_turn:
            error_msg = (
                f"Tool execution limit ({self.max_executions_per_turn}) exceeded in single turn."
            )
            self._logger.error("Recursion limit hit for tool '%s': %s", tool_name, error_msg)
            return ToolResult(tool_name=tool_name, success=False, error=error_msg)

        # 2. Look up tool
        tool = self.registry.get(tool_name)
        if not tool:
            error_msg = f"Tool '{tool_name}' is not registered."
            self._logger.warning("Tool not found: '%s'", tool_name)
            return ToolResult(tool_name=tool_name, success=False, error=error_msg)

        # 2b. Enforce offline mode network isolation
        is_offline = self.offline_mode or bool(request.metadata.get("offline_mode", False))
        if is_offline and getattr(tool, "requires_network", False):
            error_msg = (
                f"Tool '{tool.name}' requires external network access, which is blocked in offline mode."
            )
            self._logger.warning("Offline mode blocked tool '%s'", tool.name)
            return ToolResult(
                tool_name=tool.name,
                success=False,
                error=error_msg,
                metadata={"offline_blocked": True},
            )

        # 2c. Resolve arguments and action-level permission
        args = dict(request.arguments)
        if "." in tool_name:
            sub_action = tool_name.split(".", 1)[1]
            if "action" in tool.input_schema.get("properties", {}) and "action" not in args:
                args["action"] = sub_action

        effective_level = tool.permission_level
        action_arg = args.get("action")
        if action_arg and hasattr(tool, "get_action_permission_level"):
            effective_level = tool.get_action_permission_level(action_arg)

        # 3. Check permissions
        is_confirmed = bool(args.get("confirmed") or request.metadata.get("confirmed"))
        if effective_level == ToolPermissionLevel.CONFIRMATION_REQUIRED and is_confirmed:
            pass  # Explicitly confirmed by user
        else:
            try:
                self.policy.verify_permission(tool.name, effective_level, user_id=request.user_id)
            except ToolPermissionError as perm_err:
                self._logger.warning("Permission denied: %s", perm_err)
                return ToolResult(
                    tool_name=tool.name,
                    success=False,
                    error=str(perm_err),
                    metadata={"requires_confirmation": effective_level == ToolPermissionLevel.CONFIRMATION_REQUIRED},
                )

        # 4. Validate arguments
        try:
            validate_tool_arguments(tool.input_schema, args)
        except ToolValidationError as val_err:
            self._logger.warning("Validation failed for '%s': %s", tool.name, val_err)
            return ToolResult(tool_name=tool.name, success=False, error=str(val_err))

        # 5. Execute with timeout
        self._logger.info(
            "Executing tool '%s' [permission: %s]",
            tool.name,
            effective_level.value,
        )

        exec_request = (
            request
            if args == request.arguments and tool_name == tool.name
            else ToolRequest(
                tool_name=tool.name,
                arguments=args,
                session_id=request.session_id,
                user_id=request.user_id,
                metadata=request.metadata,
            )
        )

        try:
            result = await asyncio.wait_for(
                tool.execute(exec_request),
                timeout=self.timeout_seconds,
            )
            self._logger.info("Tool '%s' executed successfully", tool.name)
            return result
        except asyncio.TimeoutError:
            error_msg = f"Tool '{tool.name}' timed out after {self.timeout_seconds} seconds."
            self._logger.error("Tool timeout: %s", error_msg)
            return ToolResult(tool_name=tool.name, success=False, error=error_msg)
        except ToolError as tool_err:
            error_msg = f"Tool '{tool.name}' error: {tool_err}"
            self._logger.error(error_msg)
            return ToolResult(tool_name=tool.name, success=False, error=error_msg)
        except Exception as err:  # pylint: disable=broad-except
            error_msg = f"Tool '{tool.name}' unexpected execution failure: {err}"
            self._logger.error(error_msg)
            return ToolResult(tool_name=tool.name, success=False, error=error_msg)

    def execute_sync(
        self,
        request: ToolRequest,
        execution_count: int = 0,
    ) -> ToolResult:
        """Synchronously execute a tool request."""
        return asyncio.run(self.execute(request, execution_count))
