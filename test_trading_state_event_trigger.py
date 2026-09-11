"""Block 4 Task 1 — Trading State Event Trigger tests.

Direct, small tests for the new core/trading_state_event_trigger module:
  - allowed state (VERIFIED_TRADABLE) -> True,
  - blocked state (VERIFIED_BLOCKED) -> False,
  - unverified state (UNVERIFIED) -> False,
  - invalid now input -> False,
  - repeated evaluation is deterministic,
  - inheritance from EventTrigger.

No scheduler, timer, polling, broker API, or order execution.
No changes to M6-A through M6-E or Block 0/1/2 contracts.
"""

import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from core.trading_state_event_trigger import TradingStateEventTrigger
from core.dispatch_contracts import EventTrigger, Trigger
from models.trading_state import (
    UNVERIFIED,
    VERIFIED_BLOCKED,
    VERIFIED_TRADABLE,
    TradingState,
)

NOW = datetime(2026, 9, 11, 9, 0, 0)


def make_trigger(state):
    """Build a TradingStateEventTrigger for the given state."""
    return TradingStateEventTrigger(state=state)


def test_trigger_is_event_trigger_subclass():
    """TradingStateEventTrigger is a concrete EventTrigger (and Trigger)."""
    assert issubclass(TradingStateEventTrigger, EventTrigger)
    assert issubclass(TradingStateEventTrigger, Trigger)


def test_verified_tradable_returns_true():
    """VERIFIED_TRADABLE allows order entry -> True."""
    trigger = make_trigger(VERIFIED_TRADABLE)
    assert trigger.evaluate(NOW) is True


def test_verified_blocked_returns_false():
    """VERIFIED_BLOCKED does not allow order entry -> False."""
    trigger = make_trigger(VERIFIED_BLOCKED)
    assert trigger.evaluate(NOW) is False


def test_unverified_returns_false():
    """UNVERIFIED state -> False (fail-closed)."""
    trigger = make_trigger(UNVERIFIED)
    assert trigger.evaluate(NOW) is False


def test_custom_allowed_state_returns_true():
    """A custom state with both flags True -> True."""
    state = TradingState(
        is_order_entry_allowed=True,
        is_verified=True,
        source="test",
    )
    trigger = make_trigger(state)
    assert trigger.evaluate(NOW) is True


def test_custom_blocked_state_returns_false():
    """A custom state with is_order_entry_allowed=False -> False."""
    state = TradingState(
        is_order_entry_allowed=False,
        is_verified=True,
        source="test",
    )
    trigger = make_trigger(state)
    assert trigger.evaluate(NOW) is False


def test_custom_unverified_state_returns_false():
    """A custom state with is_verified=False -> False."""
    state = TradingState(
        is_order_entry_allowed=True,
        is_verified=False,
        source="test",
    )
    trigger = make_trigger(state)
    assert trigger.evaluate(NOW) is False


def test_invalid_now_returns_false():
    """Non-datetime now -> False (fail-closed)."""
    trigger = make_trigger(VERIFIED_TRADABLE)
    for bad_now in ["2026-09-11", 1_726_048_200, None, 9.5, [], {}]:
        assert trigger.evaluate(bad_now) is False


def test_bool_now_returns_false():
    """bool is not a datetime -> False."""
    trigger = make_trigger(VERIFIED_TRADABLE)
    assert trigger.evaluate(True) is False


def test_repeated_evaluation_is_deterministic():
    """Calling evaluate with the same now always returns the same result."""
    trigger = make_trigger(VERIFIED_TRADABLE)
    for _ in range(5):
        assert trigger.evaluate(NOW) is True

    blocked_trigger = make_trigger(VERIFIED_BLOCKED)
    for _ in range(5):
        assert blocked_trigger.evaluate(NOW) is False


def test_trigger_is_immutable():
    """TradingStateEventTrigger is frozen; attributes cannot be set."""
    trigger = make_trigger(VERIFIED_TRADABLE)
    try:
        trigger.state = UNVERIFIED  # type: ignore
    except Exception as exc:
        if type(exc).__name__ != "FrozenInstanceError":
            raise AssertionError(
                f"Expected FrozenInstanceError, got {type(exc).__name__}: {exc}"
            )
        return
    raise AssertionError("TradingStateEventTrigger should be frozen")


def main():
    tests = [
        test_trigger_is_event_trigger_subclass,
        test_verified_tradable_returns_true,
        test_verified_blocked_returns_false,
        test_unverified_returns_false,
        test_custom_allowed_state_returns_true,
        test_custom_blocked_state_returns_false,
        test_custom_unverified_state_returns_false,
        test_invalid_now_returns_false,
        test_bool_now_returns_false,
        test_repeated_evaluation_is_deterministic,
        test_trigger_is_immutable,
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

    print(
        f"\nAll Block 4 Task 1 TradingStateEventTrigger tests passed. ({len(tests)} tests)"
    )


if __name__ == "__main__":
    main()

