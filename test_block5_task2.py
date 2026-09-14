"""Block 5 — Task 2: Result Collection tests.

Tests for the connector that records an existing DispatchResult into the
ExecutionTracker (Block 5 Task 1).

Covered:
  - DispatchResult(success=True)  -> REGISTERED
  - DispatchResult(success=False) -> FAILED
  - Unknown execution_id -> fail-closed (ExecutionTrackerError)
  - Invalid result type -> fail-closed
  - No broker, API, IO, clock, or persistence involvement.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from core.block5_task2 import collect_result, collect_result_safe
from core.dispatch_contracts import DispatchResult
from core.execution_tracker import (
    ExecutionStatus,
    ExecutionTracker,
    ExecutionTrackerError,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_success_maps_to_registered():
    """DispatchResult(success=True) -> ExecutionStatus.REGISTERED."""
    tracker = ExecutionTracker()
    tracker.register("exec-001")

    status = collect_result(
        tracker, "exec-001", DispatchResult(success=True, sent=False, mode="DRY_RUN")
    )

    assert status == ExecutionStatus.REGISTERED
    assert tracker.get_status("exec-001") == ExecutionStatus.REGISTERED


def test_failure_maps_to_failed():
    """DispatchResult(success=False) -> ExecutionStatus.FAILED."""
    tracker = ExecutionTracker()
    tracker.register("exec-002")

    status = collect_result(
        tracker,
        "exec-002",
        DispatchResult(success=False, sent=False, mode="BLOCKED", message="denied"),
    )

    assert status == ExecutionStatus.FAILED
    assert tracker.get_status("exec-002") == ExecutionStatus.FAILED


def test_unknown_execution_id_fail_closed():
    """Unknown execution_id -> ExecutionTrackerError (fail-closed).

    Verifies the tracker state is genuinely unchanged: no record is
    created and the registry remains empty after the failed call.
    """
    tracker = ExecutionTracker()
    result = DispatchResult(success=True, sent=False, mode="DRY_RUN")

    # Snapshot the tracker's internal records before the call.
    records_before = dict(tracker._records)

    try:
        collect_result(tracker, "missing", result)
    except ExecutionTrackerError:
        # Verify the tracker was NOT modified by the failed call.
        assert tracker._records == records_before, (
            "tracker _records must be unchanged after a fail-closed call"
        )
        assert "missing" not in tracker._records, (
            "no record must be created for an unknown execution_id"
        )
        assert len(tracker._records) == 0, (
            "tracker registry must remain empty after failed collect"
        )
        return
    raise AssertionError("unknown execution_id must raise ExecutionTrackerError")


def test_unknown_execution_id_safe_returns_none():
    """collect_result_safe returns None for unknown execution_id."""
    tracker = ExecutionTracker()
    result = DispatchResult(success=True, sent=False, mode="DRY_RUN")

    status = collect_result_safe(tracker, "missing", result)
    assert status is None


def test_invalid_result_type_fail_closed():
    """Non-DispatchResult input -> ExecutionTrackerError."""
    tracker = ExecutionTracker()
    tracker.register("exec-003")

    for bad in (None, "ok", 123, {"success": True}, object()):
        try:
            collect_result(tracker, "exec-003", bad)
        except ExecutionTrackerError:
            continue
        raise AssertionError(f"invalid result {bad!r} must raise ExecutionTrackerError")


def test_blank_execution_id_fail_closed():
    """Blank execution_id -> ExecutionTrackerError."""
    tracker = ExecutionTracker()
    result = DispatchResult(success=True, sent=False, mode="DRY_RUN")

    for bad_id in ("", "   ", None, 123):
        try:
            collect_result(tracker, bad_id, result)
        except ExecutionTrackerError:
            continue
        raise AssertionError(f"bad execution_id {bad_id!r} must raise")


def test_idempotent_status_after_collection():
    """After collection, get_status reflects the recorded status."""
    tracker = ExecutionTracker()
    tracker.register("exec-004")

    collect_result(
        tracker, "exec-004", DispatchResult(success=True, sent=False, mode="DRY_RUN")
    )
    assert tracker.get_status("exec-004") == ExecutionStatus.REGISTERED

    collect_result(
        tracker,
        "exec-004",
        DispatchResult(success=False, sent=False, mode="BLOCKED"),
    )
    assert tracker.get_status("exec-004") == ExecutionStatus.FAILED


def test_records_are_independent():
    """Two executions record their own results independently."""
    tracker = ExecutionTracker()
    tracker.register("exec-a")
    tracker.register("exec-b")

    collect_result(
        tracker, "exec-a", DispatchResult(success=True, sent=False, mode="DRY_RUN")
    )
    collect_result(
        tracker,
        "exec-b",
        DispatchResult(success=False, sent=False, mode="BLOCKED"),
    )

    assert tracker.get_status("exec-a") == ExecutionStatus.REGISTERED
    assert tracker.get_status("exec-b") == ExecutionStatus.FAILED


def test_safe_returns_status_on_success():
    """collect_result_safe returns the status on success."""
    tracker = ExecutionTracker()
    tracker.register("exec-005")

    status = collect_result_safe(
        tracker, "exec-005", DispatchResult(success=True, sent=False, mode="DRY_RUN")
    )
    assert status == ExecutionStatus.REGISTERED


def main():
    tests = [
        test_success_maps_to_registered,
        test_failure_maps_to_failed,
        test_unknown_execution_id_fail_closed,
        test_unknown_execution_id_safe_returns_none,
        test_invalid_result_type_fail_closed,
        test_blank_execution_id_fail_closed,
        test_idempotent_status_after_collection,
        test_records_are_independent,
        test_safe_returns_status_on_success,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print(f"  PASS  {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {test.__name__}: {exc}")
        except Exception as exc:
            failed += 1
            print(f"  ERROR {test.__name__}: {exc}")
            import traceback
            traceback.print_exc()

    print()
    print("=" * 50)
    print(f"PASSED: {passed}")
    print(f"FAILED: {failed}")
    print("=" * 50)

    if failed:
        sys.exit(1)

    print(f"\nAll Block 5 Task 2 result collection tests passed. ({len(tests)} tests)")


if __name__ == "__main__":
    main()