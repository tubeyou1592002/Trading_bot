"""Block 3 Task 2 — Timed dispatch trigger tests.

Direct, small tests for the new ``core/timed_dispatch_trigger`` module only:
  - before start -> False,
  - at start -> True (inclusive),
  - inside window -> True,
  - at end -> True (inclusive),
  - after end -> False,
  - invalid type for ``now`` -> TypeError,
  - trigger is immutable (frozen),
  - repeated evaluation is deterministic.

No scheduler, timer, polling, broker API, or order execution.
No changes to M6-A through M6-E or Block 0/1/2 contracts.
"""

import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from core.timed_dispatch_trigger import TimedDispatchTrigger
from core.timing_contracts import DispatchTiming
from core.dispatch_contracts import TimeTrigger, Trigger


START = datetime(2026, 9, 11, 9, 0, 0)
END = datetime(2026, 9, 11, 10, 0, 0)
INTERVAL = timedelta(seconds=30)


def make_trigger(start=START, end=END, interval=INTERVAL):
    """Build a TimedDispatchTrigger with a validated DispatchTiming."""
    timing = DispatchTiming(start_time=start, end_time=end, interval=interval)
    return TimedDispatchTrigger(timing=timing)


def test_trigger_is_time_trigger_subclass():
    """TimedDispatchTrigger is a concrete TimeTrigger (and thus a Trigger)."""
    assert issubclass(TimedDispatchTrigger, TimeTrigger)
    assert issubclass(TimedDispatchTrigger, Trigger)


def test_before_start_returns_false():
    """A moment strictly before the window opens must not fire."""
    trigger = make_trigger()
    now = START - timedelta(seconds=1)
    assert trigger.evaluate(now) is False


def test_at_start_returns_true():
    """The exact start moment fires (window is inclusive on the left)."""
    trigger = make_trigger()
    assert trigger.evaluate(START) is True


def test_inside_window_returns_true():
    """Any moment strictly inside the window fires."""
    trigger = make_trigger()
    now = START + timedelta(minutes=30)
    assert trigger.evaluate(now) is True


def test_at_end_returns_true():
    """The exact end moment fires (window is inclusive on the right)."""
    trigger = make_trigger()
    assert trigger.evaluate(END) is True


def test_after_end_returns_false():
    """A moment strictly after the window closes must not fire."""
    trigger = make_trigger()
    now = END + timedelta(seconds=1)
    assert trigger.evaluate(now) is False


def test_invalid_now_type_raises_type_error():
    """Non-datetime ``now`` must raise TypeError, not a silent wrong result."""
    trigger = make_trigger()
    for bad_now in ["2026-09-11 09:30:00", 1_726_048_200, None, 9.5, [], {}]:
        try:
            trigger.evaluate(bad_now)
        except TypeError:
            continue
        raise AssertionError(
            f"evaluate({bad_now!r}) should raise TypeError but did not"
        )


def test_bool_now_raises_type_error():
    """bool is a subclass of int but not a datetime; must be rejected."""
    trigger = make_trigger()
    try:
        trigger.evaluate(True)
    except TypeError:
        return
    raise AssertionError("evaluate(True) should raise TypeError")


def test_trigger_is_immutable():
    """TimedDispatchTrigger is frozen; attributes cannot be set after construction."""
    trigger = make_trigger()
    try:
        trigger.timing = DispatchTiming(  # type: ignore
            start_time=START, end_time=END, interval=INTERVAL
        )
    except Exception as exc:
        if type(exc).__name__ != "FrozenInstanceError":
            raise AssertionError(
                f"Expected FrozenInstanceError, got {type(exc).__name__}: {exc}"
            )
        return
    raise AssertionError("TimedDispatchTrigger should be frozen")


def test_repeated_evaluation_is_deterministic():
    """Calling evaluate with the same ``now`` always returns the same result."""
    trigger = make_trigger()
    inside = START + timedelta(minutes=15)
    outside = END + timedelta(hours=1)

    for _ in range(5):
        assert trigger.evaluate(inside) is True
        assert trigger.evaluate(outside) is False


def test_instantiation_and_evaluate_work():
    """End-to-end: build trigger and evaluate without error."""
    trigger = make_trigger()
    assert isinstance(trigger, TimedDispatchTrigger)
    assert trigger.evaluate(START) is True


def main():
    tests = [
        test_trigger_is_time_trigger_subclass,
        test_before_start_returns_false,
        test_at_start_returns_true,
        test_inside_window_returns_true,
        test_at_end_returns_true,
        test_after_end_returns_false,
        test_invalid_now_type_raises_type_error,
        test_bool_now_raises_type_error,
        test_trigger_is_immutable,
        test_repeated_evaluation_is_deterministic,
        test_instantiation_and_evaluate_work,
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

    print(f"\nAll Block 3 Task 2 TimedDispatchTrigger tests passed. ({len(tests)} tests)")


if __name__ == "__main__":
    main()


