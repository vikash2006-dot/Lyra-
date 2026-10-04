"""Emergency stop mechanism for computer control operations."""

from datetime import datetime, timezone
import logging
import threading

from lyra.core.exceptions import ComputerEmergencyStopError

logger = logging.getLogger(__name__)


class EmergencyStop:
    """Thread-safe and async-safe kill switch for all computer interaction."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._is_stopped = False
        self._reason: str | None = None
        self._stopped_at: datetime | None = None

    @property
    def is_stopped(self) -> bool:
        """Check whether emergency stop is currently engaged."""
        with self._lock:
            return self._is_stopped

    @property
    def reason(self) -> str | None:
        """Reason why emergency stop was engaged."""
        with self._lock:
            return self._reason

    @property
    def stopped_at(self) -> datetime | None:
        """Timestamp when emergency stop was triggered."""
        with self._lock:
            return self._stopped_at

    def trigger(self, reason: str = "User triggered emergency stop") -> None:
        """Immediately engage emergency stop, locking out all computer interaction."""
        with self._lock:
            self._is_stopped = True
            self._reason = reason
            self._stopped_at = datetime.now(timezone.utc)
            logger.critical("EMERGENCY STOP ENGAGED: %s", reason)

    def fail_closed(self, reason: str = "Control state became uncertain") -> None:
        """Fail closed immediately when control state is indeterminate."""
        self.trigger(reason=f"Fail-closed lock: {reason}")

    def reset(self) -> None:
        """Reset emergency stop and re-arm computer control upon explicit administrative action."""
        with self._lock:
            self._is_stopped = False
            self._reason = None
            self._stopped_at = None
            logger.warning("Emergency stop has been RESET. Computer control re-armed.")

    def check(self) -> None:
        """Verify emergency stop is not engaged or raise ComputerEmergencyStopError.

        Raises:
            ComputerEmergencyStopError: If emergency stop is engaged.
        """
        with self._lock:
            if self._is_stopped:
                raise ComputerEmergencyStopError(
                    f"Computer interaction aborted: Emergency stop is active ({self._reason})."
                )
