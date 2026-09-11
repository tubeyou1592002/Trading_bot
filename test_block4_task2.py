"""Block 4 — Task 2: Connect TradingStateEventTrigger to ExecutionPlanner tests.

Tests for the connection between TradingStateEventTrigger and ExecutionPlanner.build_plan()
using a spy around the actual ExecutionPlanner instance.
No modification to TradingStateEventTrigger, ExecutionPlanner, or DispatchCore.
No scheduler, timer, polling, or broker API involvement.
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from core.block4_task2 import connect_trigger_to_planner
from core.trading_state_event_trigger import TradingStateEventTrigger
from core.execution_planner import ExecutionPlanner, LogicalOrderInstruction, PlannedOrder
from models.trading_state import TradingState, VERIFIED_TRADABLE, VERIFIED_BLOCKED, UNVERIFIED
from core.dispatch_contracts import ExecutionPlan

NOW = datetime(2026, 9, 11, 9, 0, 0)


def make_instruction():
    """Build a basic LogicalOrderInstruction for testing."""
    order = object()  # concrete order object not needed for connection logic
    planned_order = PlannedOrder(
        order=order,
        account_id="ACC-001",
        broker_name="آگاه",
        sequence=1,
    )
    return LogicalOrderInstruction(
        plan_id="plan-001",
        orders=[planned_order],
    )


def test_trigger_true_planner_called_with_exact_instruction():
    """Trigger=True: the provided Planner instance is used, build_plan() called once with exact instruction."""
    planner = ExecutionPlanner()
    # Track calls and save the original build_plan
    build_plan_calls = []
    original_build_plan = planner.build_plan

    def tracking_build_plan(inst):
        build_plan_calls.append(inst)  # track the instruction object
        # Call the original build_plan and return its result
        return original_build_plan(inst)

    # Replace build_plan with tracking version that calls original
    planner.build_plan = tracking_build_plan  # type: ignore

    trigger = TradingStateEventTrigger(state=VERIFIED_TRADABLE)
    instruction = make_instruction()
    result = connect_trigger_to_planner(trigger, planner, instruction, NOW)

    assert result["fired"] is True
    assert result["execution_plan"] is not None
    assert result["trigger_result"] is True
    assert result["planner_called"] is True
    # Verify the exact Planner instance was used (we track calls on it)
    assert len(build_plan_calls) == 1, f"Expected exactly 1 call, got {len(build_plan_calls)}"
    # Verify the exact same LogicalOrderInstruction object was passed
    assert build_plan_calls[0] is instruction, "Expected the exact same Instruction object"
    # Verify the plan has expected structure (from ExecutionPlanner.build_plan)
    plan = result["execution_plan"]
    assert plan.plan_id == "plan-001"
    assert len(plan.orders) == 1
    assert "binding" in plan.conditions


def test_trigger_false_planner_not_called():
    """Trigger=False: the provided Planner's build_plan() is NOT called."""
    planner = ExecutionPlanner()
    instruction = make_instruction()
    result = connect_trigger_to_planner(TradingStateEventTrigger(state=VERIFIED_BLOCKED), planner, instruction, NOW)

    assert result["fired"] is False
    assert result["execution_plan"] is None
    assert result["trigger_result"] is False
    assert result["planner_called"] is False


def test_trigger_unverified_planner_not_called():
    """Trigger=False (UNVERIFIED): Planner is not called, result fail-closed."""
    planner = ExecutionPlanner()
    instruction = make_instruction()
    result = connect_trigger_to_planner(TradingStateEventTrigger(state=UNVERIFIED), planner, instruction, NOW)

    assert result["fired"] is False
    assert result["execution_plan"] is None
    assert result["planner_called"] is False


def test_trigger_verified_blocked_planner_not_called():
    """Trigger=False (VERIFIED_BLOCKED): Planner is not called, result fail-closed."""
    planner = ExecutionPlanner()
    instruction = make_instruction()
    result = connect_trigger_to_planner(TradingStateEventTrigger(state=VERIFIED_BLOCKED), planner, instruction, NOW)

    assert result["fired"] is False
    assert result["execution_plan"] is None
    assert result["planner_called"] is False


def test_invalid_uncertain_trigger_fail_closed():
    """Invalid/uncertain trigger states -> fail-closed, Planner NOT called.

    Tests multiple states that are not VERIFIED_TRADABLE to ensure the
    connector always takes the fail-closed path when the trigger does not
    explicitly fire. The provided Planner's build_plan() must not be called.
    """
    planner = ExecutionPlanner()
    uncertain_states = [
        VERIFIED_BLOCKED,
        UNVERIFIED,
    ]
    for state in uncertain_states:
        instruction = make_instruction()
        result = connect_trigger_to_planner(TradingStateEventTrigger(state=state), planner, instruction, NOW)
        assert result["fired"] is False, f"State {state} should not fire"
        assert result["execution_plan"] is None, f"State {state} should not produce a plan"
        assert result["trigger_result"] is False, f"State {state} should return False"
        assert result["planner_called"] is False, f"State {state} should not call build_plan"


def main():
    tests = [
        test_trigger_true_planner_called_with_exact_instruction,
        test_trigger_false_planner_not_called,
        test_trigger_unverified_planner_not_called,
        test_trigger_verified_blocked_planner_not_called,
        test_invalid_uncertain_trigger_fail_closed,
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

    print(
        f"\nAll Block 4 Task 2 connection tests passed. ({len(tests)} tests)"
    )


if __name__ == "__main__":
    main()