"""Block 3 Task 3 - Timed dispatch scheduler tests.

Direct, small tests for the new core/timed_dispatch_scheduler module only:
  - one valid window, multiple intervals, exact end boundary,
  - interval that does not land exactly on end_time,
  - start == end, interval larger than the window,
  - invalid inputs rejected (via DispatchTiming),
  - repeated deterministic generation.

No scheduler loop, timer, polling, broker API, or order execution.
No changes to M6-A through M6-E or Block 0/1/2 contracts.
"""

import sys, os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from core.timed_dispatch_scheduler import TimedDispatchScheduler
from core.timing_contracts import DispatchTiming, TimingValidationError


def make_scheduler(start, end, interval):
    timing = DispatchTiming(start_time=start, end_time=end, interval=interval)
    return TimedDispatchScheduler(timing=timing)


def test_one_valid_window():
    start = datetime(2026, 9, 11, 9, 0, 0)
    end = datetime(2026, 9, 11, 9, 0, 30)
    s = make_scheduler(start, end, timedelta(seconds=30))
    assert s.generate() == [start, end]


def test_multiple_intervals():
    start = datetime(2026, 9, 11, 9, 0, 0)
    end = datetime(2026, 9, 11, 10, 0, 0)
    s = make_scheduler(start, end, timedelta(minutes=15))
    exp = [
        datetime(2026, 9, 11, 9, 0, 0),
        datetime(2026, 9, 11, 9, 15, 0),
        datetime(2026, 9, 11, 9, 30, 0),
        datetime(2026, 9, 11, 9, 45, 0),
        datetime(2026, 9, 11, 10, 0, 0),
    ]
    assert s.generate() == exp


def test_exact_end_boundary():
    start = datetime(2026, 9, 11, 9, 0, 0)
    end = datetime(2026, 9, 11, 10, 0, 0)
    s = make_scheduler(start, end, timedelta(minutes=20))
    exp = [
        datetime(2026, 9, 11, 9, 0, 0),
        datetime(2026, 9, 11, 9, 20, 0),
        datetime(2026, 9, 11, 9, 40, 0),
        datetime(2026, 9, 11, 10, 0, 0),
    ]
    assert s.generate() == exp


def test_interval_does_not_land_exactly_on_end():
    start = datetime(2026, 9, 11, 9, 0, 0)
    end = datetime(2026, 9, 11, 10, 0, 0)
    s = make_scheduler(start, end, timedelta(minutes=25))
    exp = [
        datetime(2026, 9, 11, 9, 0, 0),
        datetime(2026, 9, 11, 9, 25, 0),
        datetime(2026, 9, 11, 9, 50, 0),
    ]
    assert s.generate() == exp


def test_start_equals_end():
    start = datetime(2026, 9, 11, 9, 0, 0)
    end = datetime(2026, 9, 11, 9, 0, 0)
    s = make_scheduler(start, end, timedelta(minutes=30))
    assert s.generate() == [start]


def test_interval_larger_than_window():
    start = datetime(2026, 9, 11, 9, 0, 0)
    end = datetime(2026, 9, 11, 9, 10, 0)
    s = make_scheduler(start, end, timedelta(minutes=30))
    assert s.generate() == [start]


def test_invalid_timing_rejected():
    invalid_cases = [
        (datetime(2026, 9, 11, 10, 0, 0), datetime(2026, 9, 11, 9, 0, 0), timedelta(seconds=30)),
        (datetime(2026, 9, 11, 9, 0, 0), datetime(2026, 9, 11, 10, 0, 0), timedelta(0)),
        (datetime(2026, 9, 11, 9, 0, 0), datetime(2026, 9, 11, 10, 0, 0), timedelta(seconds=-10)),
        (None, datetime(2026, 9, 11, 10, 0, 0), timedelta(seconds=30)),
        (datetime(2026, 9, 11, 9, 0, 0), "not-a-datetime", timedelta(seconds=30)),
    ]
    for start, end, interval in invalid_cases:
        try:
            make_scheduler(start, end, interval)
        except TimingValidationError:
            continue
        raise AssertionError(f"Expected TimingValidationError for start={start!r}, end={end!r}")


def test_repeated_deterministic_generation():
    start = datetime(2026, 9, 11, 9, 0, 0)
    end = datetime(2026, 9, 11, 10, 0, 0)
    s = make_scheduler(start, end, timedelta(minutes=10))
    first = s.generate()
    for _ in range(5):
        assert s.generate() == first, "generate() is not deterministic"


def test_scheduler_is_immutable():
    s = make_scheduler(datetime(2026, 9, 11, 9, 0, 0), datetime(2026, 9, 11, 10, 0, 0), timedelta(minutes=15))
    try:
        s.timing = DispatchTiming(start_time=datetime(2026, 9, 11, 9, 0, 0), end_time=datetime(2026, 9, 11, 10, 0, 0), interval=timedelta(minutes=15))
    except Exception as exc:
        if type(exc).__name__ != "FrozenInstanceError":
            raise AssertionError(f"Expected FrozenInstanceError, got {type(exc).__name__}: {exc}")
        return
    raise AssertionError("TimedDispatchScheduler should be frozen")


def test_result_is_new_list_each_call():
    s = make_scheduler(datetime(2026, 9, 11, 9, 0, 0), datetime(2026, 9, 11, 9, 10, 0), timedelta(minutes=5))
    a_list = s.generate()
    b_list = s.generate()
    assert a_list == b_list
    assert a_list is not b_list, "generate() should return a new list each call"


def main():
    tests = [
        test_one_valid_window,
        test_multiple_intervals,
        test_exact_end_boundary,
        test_interval_does_not_land_exactly_on_end,
        test_start_equals_end,
        test_interval_larger_than_window,
        test_invalid_timing_rejected,
        test_repeated_deterministic_generation,
        test_scheduler_is_immutable,
        test_result_is_new_list_each_call,
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

    print(f"All Block 3 Task 3 TimedDispatchScheduler tests passed. ({len(tests)} tests)")


if __name__ == "__main__":
    main()
