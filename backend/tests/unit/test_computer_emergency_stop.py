"""Unit tests for EmergencyStop kill switch and fail-closed safety behavior."""

import concurrent.futures
import pytest

from lyra.computer.emergency_stop import EmergencyStop
from lyra.core.exceptions import ComputerEmergencyStopError


def test_emergency_stop_lifecycle():
    estop = EmergencyStop()

    # Initially disarmed
    assert not estop.is_stopped
    assert estop.reason is None
    assert estop.stopped_at is None
    estop.check()  # Does not raise

    # Trigger emergency stop
    estop.trigger(reason="Test kill switch trigger")
    assert estop.is_stopped
    assert estop.reason == "Test kill switch trigger"
    assert estop.stopped_at is not None

    with pytest.raises(ComputerEmergencyStopError, match="Emergency stop is active"):
        estop.check()

    # Reset
    estop.reset()
    assert not estop.is_stopped
    assert estop.reason is None
    assert estop.stopped_at is None
    estop.check()  # Pass again


def test_emergency_stop_fail_closed():
    estop = EmergencyStop()
    estop.fail_closed("Indeterminate cursor coordinates")

    assert estop.is_stopped
    assert "Fail-closed lock" in estop.reason
    with pytest.raises(ComputerEmergencyStopError, match="Fail-closed lock"):
        estop.check()


def test_emergency_stop_thread_safety():
    estop = EmergencyStop()

    def worker(idx: int):
        if idx == 5:
            estop.trigger(reason=f"Worker {idx} stopped")
        return estop.is_stopped

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in futures]

    assert estop.is_stopped
    assert any(results)
