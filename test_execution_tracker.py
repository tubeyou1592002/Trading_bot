"""Block 5 Task 1 — Execution Tracker Core tests.

Covers register / update_status / get_status only.
No broker, dispatch, strategy, or UI involvement.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from core.execution_tracker import (
    ExecutionRecord,
    ExecutionStatus,
    ExecutionTracker,
    ExecutionTrackerError,
)


def test_register_starts_pending():
    tracker = ExecutionTracker()
    record = tracker.register("exec-001")
    assert isinstance(record, ExecutionRecord)
    assert record.execution_id == "exec-001"
    assert record.status == ExecutionStatus.PENDING


def test_get_status_returns_current_status():
    tracker = ExecutionTracker()
    tracker.register("exec-001")
    assert tracker.get_status("exec-001") == ExecutionStatus.PENDING


def test_update_status_all_supported_states():
    tracker = ExecutionTracker()
    tracker.register("exec-001")
    for status in (
        ExecutionStatus.SUBMITTED,
        ExecutionStatus.REGISTERED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
    ):
        record = tracker.update_status("exec-001", status)
        assert record.status == status
        assert tracker.get_status("exec-001") == status


def test_register_duplicate_raises():
    tracker = ExecutionTracker()
    tracker.register("exec-001")
    try:
        tracker.register("exec-001")
    except ExecutionTrackerError:
        return
    raise AssertionError("duplicate execution_id must raise")


def test_register_blank_id_raises():
    tracker = ExecutionTracker()
    for bad_id in ("", "   ", None, 123):
        try:
            tracker.register(bad_id)
        except ExecutionTrackerError:
            continue
        raise AssertionError(f"bad execution_id {bad_id!r} must raise")


def test_update_unknown_id_raises():
    tracker = ExecutionTracker()
    try:
        tracker.update_status("missing", ExecutionStatus.SUBMITTED)
    except ExecutionTrackerError:
        return
    raise AssertionError("unknown execution_id must raise")


def test_get_unknown_id_raises():
    tracker = ExecutionTracker()
    try:
        tracker.get_status("missing")
    except ExecutionTrackerError:
        return
    raise AssertionError("unknown execution_id must raise")


def test_update_invalid_status_raises():
    tracker = ExecutionTracker()
    tracker.register("exec-001")
    try:
        tracker.update_status("exec-001", "FILLED")
    except ExecutionTrackerError:
        return
    raise AssertionError("non-ExecutionStatus must raise")


def test_records_are_independent():
    tracker = ExecutionTracker()
    tracker.register("exec-001")
    tracker.register("exec-002")
    tracker.update_status("exec-001", ExecutionStatus.REGISTERED)
    assert tracker.get_status("exec-001") == ExecutionStatus.REGISTERED
    assert tracker.get_status("exec-002") == ExecutionStatus.PENDING
