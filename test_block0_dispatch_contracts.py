"""
Block 0 — Dispatch Architecture Foundation tests.

Direct, small tests for the new contracts only:
  - Trigger abstraction (abstract, cannot instantiate).
  - TimeTrigger / EventTrigger are Trigger subclasses (contract only).
  - ExecutionPlan is a pure data container.
  - BrokerDispatchRequest / BrokerDispatchResponse are data containers.
  - DispatchResult is a simple, explicit status.

No execution behavior. No broker implementation. No scheduler.
No changes to M6-A through M6-E.
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from core.dispatch_contracts import (
    BrokerDispatchRequest,
    BrokerDispatchResponse,
    DispatchResult,
    EventTrigger,
    ExecutionPlan,
    TimeTrigger,
    Trigger,
)


def test_trigger_is_abstract():
    """Trigger is an ABC; it cannot be instantiated directly."""
    try:
        Trigger()
    except TypeError:
        return
    raise AssertionError("Trigger() should raise TypeError (abstract)")


def test_time_trigger_is_trigger():
    """TimeTrigger is a Trigger subclass (contract only)."""
    assert issubclass(TimeTrigger, Trigger)


def test_event_trigger_is_trigger():
    """EventTrigger is a Trigger subclass (contract only)."""
    assert issubclass(EventTrigger, Trigger)


def test_trigger_evaluate_is_abstract():
    """Trigger.evaluate must be implemented by concrete triggers."""
    try:
        TimeTrigger()
    except TypeError:
        return
    raise AssertionError(
        "TimeTrigger() should raise TypeError (still abstract)"
    )


def test_execution_plan_is_pure_data():
    """ExecutionPlan is a data container with sensible defaults."""
    plan = ExecutionPlan()
    assert plan.orders == []
    assert plan.accounts == []
    assert plan.broker_names == []
    assert plan.execution_order == []
    assert plan.conditions == {}
    assert plan.plan_id is None
    assert plan.created_at is None


def test_execution_plan_accepts_data():
    """ExecutionPlan stores provided data without behavior."""
    plan = ExecutionPlan(
        orders=["o1"],
        accounts=["a1"],
        broker_names=["broker-x"],
        execution_order=[0],
        conditions={"gate": True},
        plan_id="plan-1",
        created_at=datetime(2026, 1, 1),
    )
    assert plan.orders == ["o1"]
    assert plan.accounts == ["a1"]
    assert plan.broker_names == ["broker-x"]
    assert plan.execution_order == [0]
    assert plan.conditions == {"gate": True}
    assert plan.plan_id == "plan-1"
    assert plan.created_at == datetime(2026, 1, 1)


def test_broker_dispatch_request_is_data():
    """BrokerDispatchRequest is a data envelope."""
    req = BrokerDispatchRequest(
        broker_name="broker-x",
        order="o",
        account="a",
        instrument="i",
        live=False,
        trace_id="t-1",
    )
    assert req.broker_name == "broker-x"
    assert req.order == "o"
    assert req.account == "a"
    assert req.instrument == "i"
    assert req.live is False
    assert req.trace_id == "t-1"


def test_broker_dispatch_request_defaults():
    """BrokerDispatchRequest defaults to dry-run, no trace."""
    req = BrokerDispatchRequest(
        broker_name="broker-x",
        order="o",
        account="a",
        instrument="i",
    )
    assert req.live is False
    assert req.trace_id is None


def test_broker_dispatch_response_is_data():
    """BrokerDispatchResponse is a data envelope."""
    resp = BrokerDispatchResponse(
        success=True,
        mode="DRY_RUN",
        message="ok",
        broker_order_id="ord-1",
        raw={"x": 1},
    )
    assert resp.success is True
    assert resp.mode == "DRY_RUN"
    assert resp.message == "ok"
    assert resp.broker_order_id == "ord-1"
    assert resp.raw == {"x": 1}


def test_dispatch_result_is_simple_status():
    """DispatchResult is a simple, explicit status."""
    result = DispatchResult(
        success=True,
        sent=False,
        mode="READY",
        message="ok",
        broker_name="broker-x",
        order_count=1,
        trace_id="t-1",
    )
    assert result.success is True
    assert result.sent is False
    assert result.mode == "READY"
    assert result.message == "ok"
    assert result.broker_name == "broker-x"
    assert result.order_count == 1
    assert result.trace_id == "t-1"


def test_dispatch_result_defaults():
    """DispatchResult defaults are zero/None."""
    result = DispatchResult(
        success=False,
        sent=False,
        mode="BLOCKED",
    )
    assert result.success is False
    assert result.sent is False
    assert result.mode == "BLOCKED"
    assert result.message is None
    assert result.broker_name is None
    assert result.order_count == 0
    assert result.trace_id is None


def main():
    tests = [
        test_trigger_is_abstract,
        test_time_trigger_is_trigger,
        test_event_trigger_is_trigger,
        test_trigger_evaluate_is_abstract,
        test_execution_plan_is_pure_data,
        test_execution_plan_accepts_data,
        test_broker_dispatch_request_is_data,
        test_broker_dispatch_request_defaults,
        test_broker_dispatch_response_is_data,
        test_dispatch_result_is_simple_status,
        test_dispatch_result_defaults,
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

    print(f"\nAll Block 0 contract tests passed. ({len(tests)} tests)")


if __name__ == "__main__":
    main()