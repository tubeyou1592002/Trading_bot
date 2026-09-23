"""Block UI-4 — Task 8: selected entries -> dispatch -> execution tracking bridge.

Standalone tests for ``dispatch_selected_entries`` in
``core.order_queue_adapter``.

The bridge builds ONE ``ExecutionPlan`` from selected ``QueueEntry``\\ s
(Task 7 adapter), dispatches it through the real ``DispatchIntegration``
against a test-double Dispatch Core (never a real broker), reads the real
``dispatch_integration.last_execution_id`` and returns exactly
``(plan, execution_id, result)``.

Guarantees exercised here:

  * the returned ``execution_id`` is the one the integration really
    registered in its ``ExecutionTracker`` (never ``plan.plan_id``),
  * execution and per-selected-order statuses are visible through the
    existing Tracker contract,
  * the queue and the entries are never mutated,
  * the order of selected entries equals ``plan.orders``,
  * no real broker / network / Core execution call happens (only the
    test-double Dispatch Core is touched),
  * a dispatch with no issued execution fails closed (ValueError).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import patch

from models.order import BUY, SELL, Order
from core.order_queue import OrderQueue
from core.order_queue_adapter import dispatch_selected_entries
from core.dispatch_contracts import DispatchResult, ExecutionPlan
from core.execution_tracker import ExecutionStatus, ExecutionTracker
from core.block5_task3 import StopSignal
from core.block5_task4 import DispatchIntegration


def make_order(nsc_id="IRO1TEST0001", side=BUY, price=150, quantity=10):
    return Order(
        nsc_id=nsc_id,
        side=side,
        price=price,
        quantity=quantity,
    )


def make_queue(orders, account_id="ACC-001", broker_name="آگاه"):
    queue = OrderQueue()
    for order in orders:
        queue.enqueue(order, account_id=account_id, broker_name=broker_name)
    return queue


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
            trace_id="trace-fake-task8",
        )


def make_integration(orders, fake=None, tracker=None, signal=None):
    fake = fake if fake is not None else FakeDispatchCore()
    tracker = tracker if tracker is not None else ExecutionTracker()
    integration = DispatchIntegration(
        dispatch_core=fake, tracker=tracker, stop_signal=signal
    )
    return integration, fake, tracker


def test_1_returns_plan_execution_id_and_result():
    order = make_order()
    queue = make_queue([order])
    entry = queue.list_pending()[0]

    integration, fake, _ = make_integration([order])
    plan, execution_id, result = dispatch_selected_entries(
        [entry],
        dispatch_integration=integration,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-1",
    )

    assert isinstance(plan, ExecutionPlan)
    assert isinstance(execution_id, str) and execution_id
    assert isinstance(result, DispatchResult)
    assert fake.calls == 1
    assert fake.last_plan is plan
    assert result.success is True
    assert plan.plan_id == "plan-1"


def test_2_execution_id_is_the_registered_tracker_execution():
    order = make_order()
    queue = make_queue([order])
    entry = queue.list_pending()[0]

    integration, fake, tracker = make_integration([order])
    plan, execution_id, result = dispatch_selected_entries(
        [entry],
        dispatch_integration=integration,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-1",
    )

    assert execution_id == integration.last_execution_id
    assert tracker.get_status(execution_id) == ExecutionStatus.PENDING


def test_3_selected_order_statuses_visible_in_tracker():
    orders = [
        make_order("IRO1TEST0001"),
        make_order("IRO1TEST0002"),
        make_order("IRO1TEST0003"),
    ]
    queue = make_queue(orders)
    entries = queue.list_pending()

    integration, fake, tracker = make_integration(orders)
    plan, execution_id, result = dispatch_selected_entries(
        entries,
        dispatch_integration=integration,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-1",
    )

    assert plan.execution_order == [0, 1, 2]
    for sequence in plan.execution_order:
        assert tracker.get_order_status(execution_id, sequence) == (
            ExecutionStatus.PENDING
        )
    record = tracker.get_order_record(execution_id, 0)
    assert record.account_id == "ACC-001"


def test_4_queue_unchanged_after_dispatch():
    orders = [
        make_order("IRO1TEST0001"),
        make_order("IRO1TEST0002"),
        make_order("IRO1TEST0003"),
    ]
    queue = make_queue(orders)
    entries = queue.list_pending()

    integration, fake, _ = make_integration(orders)
    dispatch_selected_entries(
        entries,
        dispatch_integration=integration,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-1",
    )

    pending = queue.list_pending()
    assert len(pending) == 3
    assert all(e.order is o for e, o in zip(pending, orders))
    assert all(e.account_id == "ACC-001" for e in pending)
    assert all(e.broker_name == "آگاه" for e in pending)
    assert all(queue.is_pending(order) for order in orders)


def test_5_entries_order_preserved_in_plan_and_sequences():
    orders = [
        make_order("IRO1TEST0001"),
        make_order("IRO1TEST0002"),
        make_order("IRO1TEST0003"),
    ]
    queue = make_queue(orders)
    entries = queue.list_pending()

    subset = [entries[0], entries[2], entries[1]]
    integration, fake, _ = make_integration(orders)
    plan, execution_id, result = dispatch_selected_entries(
        subset,
        dispatch_integration=integration,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-1",
    )

    assert plan.orders == [orders[0], orders[2], orders[1]]
    assert all(
        plan.orders[i] is subset[i].order for i in range(len(subset))
    )
    assert plan.execution_order == [0, 1, 2]


def test_6_execution_id_is_never_plan_id():
    order = make_order()
    queue = make_queue([order])
    entry = queue.list_pending()[0]

    integration, fake, _ = make_integration([order])
    plan, execution_id, result = dispatch_selected_entries(
        [entry],
        dispatch_integration=integration,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-secret",
    )

    assert execution_id != plan.plan_id
    assert execution_id != "plan-secret"
    assert integration.last_execution_id != plan.plan_id


def test_7_no_real_broker_or_core_execution_calls():
    order = make_order()
    queue = make_queue([order])
    entry = queue.list_pending()[0]

    with patch("core.dispatch_core.DispatchCore") as mock_dispatch, \
         patch("core.order_engine.OrderEngine") as mock_engine, \
         patch("brokers.manager.BrokerManager") as mock_broker_manager:
        integration, fake, tracker = make_integration([order])
        plan, execution_id, result = dispatch_selected_entries(
            [entry],
            dispatch_integration=integration,
            account_id="ACC-001",
            broker_name="آگاه",
            plan_id="plan-1",
        )

        assert mock_dispatch.call_count == 0
        assert mock_engine.call_count == 0
        assert mock_broker_manager.call_count == 0

    assert fake.calls == 1
    assert isinstance(plan, ExecutionPlan)
    assert tracker.get_status(execution_id) == ExecutionStatus.PENDING


def test_8_no_issued_execution_fails_closed():
    order = make_order()
    queue = make_queue([order])
    entry = queue.list_pending()[0]

    fake = FakeDispatchCore()
    signal = StopSignal(enabled=True)
    signal.observe(
        DispatchResult(success=True, sent=True, mode="ALL_PROCESSED")
    )
    integration, fake, tracker = make_integration(
        [order], fake=fake, signal=signal
    )

    try:
        dispatch_selected_entries(
            [entry],
            dispatch_integration=integration,
            account_id="ACC-001",
            broker_name="آگاه",
            plan_id="plan-1",
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "a dispatch with no issued execution must raise ValueError "
            "(fail-closed; no execution id may be fabricated)"
        )

    assert integration.last_execution_id is None
    assert fake.calls == 0


def main():
    tests = [
        test_1_returns_plan_execution_id_and_result,
        test_2_execution_id_is_the_registered_tracker_execution,
        test_3_selected_order_statuses_visible_in_tracker,
        test_4_queue_unchanged_after_dispatch,
        test_5_entries_order_preserved_in_plan_and_sequences,
        test_6_execution_id_is_never_plan_id,
        test_7_no_real_broker_or_core_execution_calls,
        test_8_no_issued_execution_fails_closed,
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

    print(f"\nAll UI-4 Task 8 dispatch-bridge tests passed. ({len(tests)} tests)")


if __name__ == "__main__":
    main()