"""Block UI-4 — Task 5: Queue -> Plan -> DispatchIntegration -> Tracker.

Integration/contract tests of the real existing path:

    OrderQueue
        -> build_execution_plan_from_queue()
        -> ExecutionPlan
        -> DispatchIntegration.dispatch()
        -> ExecutionTracker (PENDING)
    result path:
        DispatchIntegration.record_result()
            -> collect_result(...)
            -> ExecutionTracker (REGISTERED)

Only the broker boundary is faked (a minimal fake Dispatch Core — the test
double holding the ``dispatch(plan)`` entry point); every other component is
the real Repository implementation. No order is submitted to any real
broker, no credentials are used, and the queue is never mutated (no
dequeue/remove/mark_dispatched exists or is exercised).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from models.order import BUY, Order
from core.order_queue import OrderQueue
from core.order_queue_adapter import build_execution_plan_from_queue
from core.dispatch_contracts import DispatchResult, ExecutionPlan
from core.execution_tracker import ExecutionStatus, ExecutionTracker
from core.block5_task4 import DispatchIntegration


def make_order(nsc_id="IRO1TEST0001", side=BUY, price=150, quantity=10):
    return Order(
        nsc_id=nsc_id,
        side=side,
        price=price,
        quantity=quantity,
    )


class FakeDispatchCore:
    """Test double for the Block 2 dispatch entry point.

    Exposes ``dispatch(plan)`` (the only thing ``DispatchIntegration``
    requires) and returns a realistic successful ``DispatchResult``. No
    broker/order is ever touched.
    """

    def __init__(self):
        self.calls = 0
        self.last_plan = None

    def dispatch(self, plan: ExecutionPlan) -> DispatchResult:
        self.calls += 1
        self.last_plan = plan
        return DispatchResult(
            success=True,
            sent=True,
            mode="ALL_PROCESSED",
            message="fake dispatch: all processed",
            broker_name="آگاه",
            order_count=len(plan.orders),
            trace_id="trace-fake-1",
        )


def build_plan(queue):
    return build_execution_plan_from_queue(
        queue,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-1",
    )


def test_1_queue_unchanged_after_building_plan():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")

    plan = build_execution_plan_from_queue(
        queue,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-1",
    )
    assert isinstance(plan, ExecutionPlan)

    pending = queue.list_pending()
    assert len(pending) == 1
    assert pending[0].order is order
    assert pending[0].account_id == "ACC-001"
    assert pending[0].broker_name == "آگاه"


def test_2_plan_is_built_from_queue():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")

    plan = build_execution_plan_from_queue(
        queue,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-1",
    )
    assert plan.plan_id == "plan-1"
    assert plan.orders == [order]
    assert all(o is order for o in plan.orders)
    assert plan.accounts == ["ACC-001"]
    assert plan.broker_names == ["آگاه"]


def test_3_dispatch_registers_pending():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")
    plan = build_plan(queue)

    fake = FakeDispatchCore()
    tracker = ExecutionTracker()
    integration = DispatchIntegration(dispatch_core=fake, tracker=tracker)

    result = integration.dispatch(plan)

    # The real fake-boundary result is returned unchanged.
    assert result.success is True
    assert result.mode == "ALL_PROCESSED"
    assert fake.calls == 1

    # Dispatch registered the execution in PENDING (real tracker).
    execution_id = integration.last_execution_id
    assert execution_id is not None
    assert tracker.get_status(execution_id) == ExecutionStatus.PENDING

    # The account-aware order record was registered as PENDING too.
    assert tracker.get_order_status(execution_id, 0) == ExecutionStatus.PENDING


def test_4_result_path_reaches_registered():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")
    plan = build_plan(queue)

    fake = FakeDispatchCore()
    tracker = ExecutionTracker()
    integration = DispatchIntegration(dispatch_core=fake, tracker=tracker)

    result = integration.dispatch(plan)
    execution_id = integration.last_execution_id

    # Result path: record_result -> collect_result -> ExecutionTracker.
    status = integration.record_result(execution_id, result)
    assert status == ExecutionStatus.REGISTERED
    assert tracker.get_status(execution_id) == ExecutionStatus.REGISTERED


def test_5_queue_still_has_entry_after_dispatch():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")
    plan = build_plan(queue)

    fake = FakeDispatchCore()
    tracker = ExecutionTracker()
    integration = DispatchIntegration(dispatch_core=fake, tracker=tracker)
    integration.dispatch(plan)

    # Intentionally unchanged: no dequeue/remove/mark_dispatched exists here.
    pending = queue.list_pending()
    assert len(pending) == 1
    assert pending[0].order is order
    assert pending[0].account_id == "ACC-001"
    assert pending[0].broker_name == "آگاه"


def main():
    tests = [
        test_1_queue_unchanged_after_building_plan,
        test_2_plan_is_built_from_queue,
        test_3_dispatch_registers_pending,
        test_4_result_path_reaches_registered,
        test_5_queue_still_has_entry_after_dispatch,
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

    print(f"\nAll UI-4 Task 5 integration tests passed. ({len(tests)} tests)")


if __name__ == "__main__":
    main()