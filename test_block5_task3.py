"""Block 5 — Task 3: Conditional Stop Signal tests.

Tests for the StopSignal gate driven by DispatchResult outcomes.

Covered:
  - Disabled rule: success never activates the signal.
  - Enabled rule + success: signal activates on first success.
  - Enabled rule + failure: signal never activates.
  - After activation, state is observable (is_active / should_continue).
  - Activation does not affect previously recorded executions.
  - Fail-closed: invalid result type raises StopSignalError.
  - Fail-closed: invalid enabled type raises StopSignalError.
  - Reset deactivates without changing enabled.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from core.block5_task3 import StopSignal, StopSignalError
from core.dispatch_contracts import DispatchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def ok_result():
    return DispatchResult(success=True, sent=False, mode="DRY_RUN")


def fail_result():
    return DispatchResult(success=False, sent=False, mode="BLOCKED")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_disabled_rule_success_does_not_activate():
    """Disabled rule: a successful result does NOT activate the Stop Signal."""
    signal = StopSignal(enabled=False)
    activated = signal.observe(ok_result())
    assert activated is False
    assert signal.is_active is False
    assert signal.should_continue() is True


def test_disabled_rule_failure_does_not_activate():
    """Disabled rule: a failed result does NOT activate the Stop Signal."""
    signal = StopSignal(enabled=False)
    assert signal.observe(fail_result()) is False
    assert signal.is_active is False
    assert signal.should_continue() is True


def test_enabled_rule_success_activates():
    """Enabled rule + success: Stop Signal activates on the first success."""
    signal = StopSignal(enabled=True)
    activated = signal.observe(ok_result())
    assert activated is True, "first success while enabled must activate"
    assert signal.is_active is True
    assert signal.should_continue() is False
    assert signal.activation_count == 1


def test_enabled_rule_failure_does_not_activate():
    """Enabled rule + failure: Stop Signal does NOT activate."""
    signal = StopSignal(enabled=True)
    activated = signal.observe(fail_result())
    assert activated is False
    assert signal.is_active is False
    assert signal.should_continue() is True
    assert signal.activation_count == 0


def test_enabled_rule_multiple_failures_no_activation():
    """Enabled rule: repeated failures never activate the signal."""
    signal = StopSignal(enabled=True)
    for _ in range(5):
        assert signal.observe(fail_result()) is False
    assert signal.is_active is False
    assert signal.should_continue() is True
    assert signal.activation_count == 0


def test_state_observable_after_activation():
    """After activation, is_active / should_continue reflect the new state."""
    signal = StopSignal(enabled=True)
    assert signal.is_active is False
    assert signal.should_continue() is True

    signal.observe(ok_result())

    assert signal.is_active is True
    assert signal.should_continue() is False


def test_latches_on_first_success_only():
    """Signal latches: subsequent successes are no-ops (not re-activation)."""
    signal = StopSignal(enabled=True)
    assert signal.observe(ok_result()) is True
    # Second success: already active, must NOT re-trigger.
    assert signal.observe(ok_result()) is False
    assert signal.is_active is True
    assert signal.activation_count == 1


def test_activation_does_not_affect_prior_results():
    """Activating the signal does not retroactively change prior outcomes.

    A failure observed before activation stays a failure; a success that
    arrives after activation does not rewrite the past. Per-order results
    remain independent.
    """
    signal = StopSignal(enabled=True)

    # First result is a failure — no activation, order still "failed".
    first = fail_result()
    assert signal.observe(first) is False
    assert signal.is_active is False

    # Second result is a success — activation fires.
    assert signal.observe(ok_result()) is True
    assert signal.is_active is True

    # The original failure is unaffected by the activation.
    assert first.success is False
    assert signal.activation_count == 1


def test_invalid_result_type_fail_closed():
    """Non-DispatchResult input raises StopSignalError."""
    signal = StopSignal(enabled=True)
    for bad in (None, "ok", 123, {"success": True}, object()):
        try:
            signal.observe(bad)
        except StopSignalError:
            continue
        raise AssertionError(f"invalid result {bad!r} must raise StopSignalError")


def test_invalid_enabled_type_fail_closed():
    """Non-bool enabled raises StopSignalError at construction."""
    for bad in (None, "yes", 1, 0, 1.0):
        try:
            StopSignal(enabled=bad)
        except StopSignalError:
            continue
        raise AssertionError(f"invalid enabled {bad!r} must raise StopSignalError")


def test_reset_deactivates_without_changing_enabled():
    """reset() deactivates the signal but keeps enabled unchanged."""
    signal = StopSignal(enabled=True)
    signal.observe(ok_result())
    assert signal.is_active is True

    signal.reset()
    assert signal.is_active is False
    assert signal.should_continue() is True
    assert signal.enabled is True
    assert signal.activation_count == 0

    # After reset, a new success can re-activate.
    assert signal.observe(ok_result()) is True
    assert signal.is_active is True


def test_reset_on_disabled_signal_is_noop():
    """reset() on a disabled signal is a safe no-op."""
    signal = StopSignal(enabled=False)
    signal.reset()
    assert signal.is_active is False
    assert signal.enabled is False


def test_default_enabled_is_false():
    """Default construction has enabled=False (continuous dispatch)."""
    signal = StopSignal()
    assert signal.enabled is False
    assert signal.is_active is False
    assert signal.should_continue() is True


def main():
    tests = [
        test_disabled_rule_success_does_not_activate,
        test_disabled_rule_failure_does_not_activate,
        test_enabled_rule_success_activates,
        test_enabled_rule_failure_does_not_activate,
        test_enabled_rule_multiple_failures_no_activation,
        test_state_observable_after_activation,
        test_latches_on_first_success_only,
        test_activation_does_not_affect_prior_results,
        test_invalid_result_type_fail_closed,
        test_invalid_enabled_type_fail_closed,
        test_reset_deactivates_without_changing_enabled,
        test_reset_on_disabled_signal_is_noop,
        test_default_enabled_is_false,
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

    print(f"\nAll Block 5 Task 3 Stop Signal tests passed. ({len(tests)} tests)")


if __name__ == "__main__":
    main()