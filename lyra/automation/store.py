"""Abstract base interface for automation storage."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Sequence

from lyra.models.automation import Automation


class AutomationStore(ABC):
    """Abstract persistence repository for automations."""

    @abstractmethod
    def save(self, automation: Automation) -> None:
        """Insert or update an automation task in storage."""

    @abstractmethod
    def get(self, automation_id: str, user_id: str | None = None) -> Automation | None:
        """Retrieve an automation by ID, optionally validating user ownership."""

    @abstractmethod
    def list_automations(
        self,
        user_id: str | None = None,
        enabled_only: bool = False,
    ) -> list[Automation]:
        """List stored automations, optionally filtered by user and enabled state."""

    @abstractmethod
    def delete(self, automation_id: str, user_id: str | None = None) -> bool:
        """Delete an automation from storage. Returns True if deleted."""

    @abstractmethod
    def get_due_automations(self, as_of: datetime | None = None) -> list[Automation]:
        """Retrieve all enabled automations whose next_run is on or before as_of."""

    @abstractmethod
    def purge_user(self, user_id: str) -> int:
        """Delete all automations belonging to a specific user (for data privacy)."""
