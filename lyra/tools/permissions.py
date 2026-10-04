"""Permission classification and enforcement for LYRA tools."""

from enum import Enum
from typing import Container

from lyra.core.exceptions import ToolPermissionError


class ToolPermissionLevel(str, Enum):
    """Permission and risk classifications for tools."""

    READ_ONLY = "READ_ONLY"
    LOW_RISK = "LOW_RISK"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    HIGH_RISK = "HIGH_RISK"


class PermissionPolicy:
    """Evaluates whether a tool with a given permission level is authorized to run."""

    DEFAULT_ALLOWED: frozenset[ToolPermissionLevel] = frozenset({
        ToolPermissionLevel.READ_ONLY,
        ToolPermissionLevel.LOW_RISK,
    })

    def __init__(
        self,
        allowed_levels: Container[ToolPermissionLevel] | None = None,
        user_policies: dict[str, Container[ToolPermissionLevel]] | None = None,
    ) -> None:
        self.allowed_levels: frozenset[ToolPermissionLevel] = (
            frozenset(allowed_levels)
            if allowed_levels is not None
            else self.DEFAULT_ALLOWED
        )
        self.user_policies: dict[str, frozenset[ToolPermissionLevel]] = {
            uid: frozenset(lvls) for uid, lvls in (user_policies or {}).items()
        }

    def is_allowed(self, level: ToolPermissionLevel, user_id: str | None = None) -> bool:
        """Check if the given permission level is authorized under this policy, optionally for a user."""
        if user_id and user_id in self.user_policies:
            return level in self.user_policies[user_id]
        return level in self.allowed_levels

    def verify_permission(
        self,
        tool_name: str,
        level: ToolPermissionLevel,
        user_id: str | None = None,
    ) -> None:
        """Verify permission or raise ToolPermissionError."""
        if not self.is_allowed(level, user_id=user_id):
            effective_allowed = (
                self.user_policies[user_id]
                if user_id and user_id in self.user_policies
                else self.allowed_levels
            )
            user_info = f" for user '{user_id}'" if user_id else ""
            raise ToolPermissionError(
                f"Permission denied for tool '{tool_name}'{user_info}. "
                f"Tool requires '{level.value}', but policy only permits: "
                f"{', '.join(sorted(lvl.value for lvl in effective_allowed))}."
            )
