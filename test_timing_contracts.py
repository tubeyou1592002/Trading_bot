"""Block 3 Task 1 — Scheduling Configuration Contract tests.

Direct, small tests for the new ``core/timing_contracts`` module only:
  - valid values are accepted,
  - start after end is rejected,
  - zero / negative interval is rejected,
  - malformed values are rejected fail-closed,
  - DispatchTiming is immutable/frozen.

No scheduler, timer, polling, broker API, or order execution.
No changes to M6-A through M6-E or Block 0/1/2 contracts.
"""

import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from core.timing_contracts import DispatchTiming, TimingValidationError


def test_valid_config_accepted():
    cfg = DispatchTiming(
        start_time=datetime(2026, 9, 11, 9, 0, 0),
        end_time=datetime(2026, 9, 11, 10, 0, 0),
        interval=timedelta(seconds=30),
    )
    assert cfg.start_time == datetime(2026, 9, 11, 9, 0, 0)
    assert cfg.end_time == datetime(2026, 9, 11, 10, 0, 0)
    assert cfg.interval == timedelta(seconds=30)


def test_valid_config_with_milliseconds():
    cfg = DispatchTiming(
        start_time=datetime(2026, 9, 11, 9, 0, 0),
        end_time=datetime(2026, 9, 11, 9, 0, 1),
        interval=timedelta(milliseconds=50),
    )
    assert cfg.interval == timedelta(milliseconds=50)


def test_start_after_end_rejected():
    try:
        DispatchTiming(
            start_time=datetime(2026, 9, 11, 10, 0, 0),
            end_time=datetime(2026, 9, 11, 9, 0, 0),
            interval=timedelta(seconds=30),
        )
    except TimingValidationError:
        return
    raise AssertionError("start after end should raise TimingValidationError")


def test_start_equal_end_accepted():
    """start == end is allowed since spec only rejects 'start after end'."""
    cfg = DispatchTiming(
        start_time=datetime(2026, 9, 11, 9, 0, 0),
        end_time=datetime(2026, 9, 11, 9, 0, 0),
        interval=timedelta(seconds=30),
    )
    assert cfg.start_time == cfg.end_time


def test_interval_zero_rejected():
    try:
        DispatchTiming(
            start_time=datetime(2026, 9, 11, 9, 0, 0),
            end_time=datetime(2026, 9, 11, 10, 0, 0),
            interval=timedelta(0),
        )
    except TimingValidationError:
        return
    raise AssertionError("interval=0 should raise TimingValidationError")


def test_interval_negative_rejected():
    try:
        DispatchTiming(
            start_time=datetime(2026, 9, 11, 9, 0, 0),
            end_time=datetime(2026, 9, 11, 10, 0, 0),
            interval=timedelta(seconds=-10),
        )
    except TimingValidationError:
        return
    raise AssertionError("negative interval should raise TimingValidationError")


def test_start_time_type_rejected():
    try:
        DispatchTiming(
            start_time=None,  # type: ignore
            end_time=datetime(2026, 9, 11, 10, 0, 0),
            interval=timedelta(seconds=30),
        )
    except TimingValidationError:
        return
    raise AssertionError("start_time=None should raise TimingValidationError")


def test_end_time_type_rejected():
    try:
        DispatchTiming(
            start_time=datetime(2026, 9, 11, 9, 0, 0),
            end_time=None,  # type: ignore
            interval=timedelta(seconds=30),
        )
    except TimingValidationError:
        return
    raise AssertionError("end_time=None should raise TimingValidationError")


def test_interval_type_rejected():
    try:
        DispatchTiming(
            start_time=datetime(2026, 9, 11, 9, 0, 0),
            end_time=datetime(2026, 9, 11, 10, 0, 0),
            interval=None,  # type: ignore
        )
    except TimingValidationError:
        return
    raise AssertionError("interval=None should raise TimingValidationError")


def test_immutable_after_construction():
    """DispatchTiming is a frozen dataclass; attributes cannot be set after construction."""
    cfg = DispatchTiming(
        start_time=datetime(2026, 9, 11, 9, 0, 0),
        end_time=datetime(2026, 9, 11, 10, 0, 0),
        interval=timedelta(seconds=30),
    )
    try:
        cfg.start_time = datetime(2026, 9, 11, 9, 30, 0)  # type: ignore
    except Exception as exc:
        if type(exc).__name__ != "FrozenInstanceError":
            raise AssertionError(
                f"Expected FrozenInstanceError, got {type(exc).__name__}: {exc}"
            )
        return
    raise AssertionError("DispatchTiming should be frozen (FrozenInstanceError on attribute set)")


def test_schedule_config_error_is_value_error():
    assert issubclass(TimingValidationError, ValueError)


def main():
    tests = [
        test_valid_config_accepted,
        test_valid_config_with_milliseconds,
        test_start_after_end_rejected,
        test_start_equal_end_accepted,
        test_interval_zero_rejected,
        test_interval_negative_rejected,
        test_start_time_type_rejected,
        test_end_time_type_rejected,
        test_interval_type_rejected,
        test_immutable_after_construction,
        test_schedule_config_error_is_value_error,
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
        except Exception:
            failed += 1
            print(f"  ERROR {test.__name__}")
            import traceback
            traceback.print_exc()

    print()
    print("=" * 50)
    print(f"PASSED: {passed}")
    print(f"FAILED: {failed}")
    print("=" * 50)

    if failed:
        sys.exit(1)

    print(f"\nAll Block 3 Task 1 ScheduleConfig contract tests passed. ({len(tests)} tests)")


if __name__ == "__main__":
    main()