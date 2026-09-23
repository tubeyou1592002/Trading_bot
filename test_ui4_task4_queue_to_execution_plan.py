"""Block UI-4 — Task 4: OrderQueue -> Instruction -> ExecutionPlan tests.

Standalone tests for ``build_execution_plan_from_queue`` in
``core.order_queue_adapter``.

The function crosses the boundary:

    OrderQueue
        -> build_instruction_from_queue()
        -> LogicalOrderInstruction
        -> ExecutionPlanner.build_plan()
        -> ExecutionPlan

These tests verify the real Repository behavior: explicit account_id /
broker_name / plan_id are authoritative (no inference from QueueEntry or
Order), order identity survives to the plan, sequences and order are
preserved, the real planner's empty-queue rejection is honored unchanged,
and no Dispatch/Core/broker machinery is ever invoked.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import patch

from models.order import BUY, SELL, Order
from core.order_queue import OrderQueue
from core.order_queue_adapter import build_execution_plan_from_queue
from core.dispatch_contracts import ExecutionPlan
from core.execution_planner import PlannerValidationError


def make_order(nsc_id="IRO1TEST0001", side=BUY, price=150, quantity=10):
    return Order(
        nsc_id=nsc_id,
        side=side,
        price=price,
        quantity=quantity,
    )


def test_one_order_queue_to_plan():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")

    plan = build_execution_plan_from_queue(
        queue,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    assert isinstance(plan, ExecutionPlan)
    assert len(plan.orders) == 1
    assert plan.execution_order == [0]


def test_plan_id_preserved_in_plan():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")

    plan = build_execution_plan_from_queue(
        queue,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-999",
    )
    assert plan.plan_id == "plan-999"


def test_order_identity_survives_to_plan():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")

    plan = build_execution_plan_from_queue(
        queue,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    assert plan.orders[0] is order


def test_account_identity_preserved_in_plan():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")

    plan = build_execution_plan_from_queue(
        queue,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    # Real planner behavior: plan.accounts holds account_id strings.
    assert plan.accounts == ["ACC-001"]
    assert plan.account_routes == {"ACC-001": "آگاه"}
    assert plan.conditions["binding"][0]["account_id"] == "ACC-001"


def test_broker_identity_preserved_in_plan():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")

    plan = build_execution_plan_from_queue(
        queue,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    assert plan.broker_names == ["آگاه"]
    assert plan.account_routes == {"ACC-001": "آگاه"}
    assert plan.conditions["binding"][0]["broker_name"] == "آگاه"


def test_multiple_orders_order_and_sequence_preserved():
    orders = [
        make_order("IRO1TEST0001"),
        make_order("IRO1TEST0002"),
        make_order("IRO1TEST0003"),
    ]
    queue = OrderQueue()
    for order in orders:
        queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")

    plan = build_execution_plan_from_queue(
        queue,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    assert plan.orders == orders
    assert all(
        o is orders[i]
        for i, o in enumerate(plan.orders)
    )
    assert plan.execution_order == [0, 1, 2]
    # Per-order binding present for every sequence.
    assert [plan.conditions["binding"][s]["account_id"] for s in (0, 1, 2)] == [
        "ACC-001",
        "ACC-001",
        "ACC-001",
    ]


def test_empty_queue_uses_existing_planner_contract():
    """Real planner rejects an instruction with no orders; honor it unchanged."""
    queue = OrderQueue()
    try:
        build_execution_plan_from_queue(
            queue,
            account_id="ACC-001",
            broker_name="آگاه",
            plan_id="plan-001",
        )
    except PlannerValidationError:
        pass
    else:
        raise AssertionError(
            "empty queue must raise PlannerValidationError (real planner contract)"
        )


def test_no_dispatch_or_core_calls():
    """DispatchCore / DispatchIntegration / ExecutionTracker / OrderEngine
    must never be invoked while building the plan."""
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")

    with patch("core.dispatch_core.DispatchCore") as mock_dispatch, \
         patch("core.block5_task4.DispatchIntegration") as mock_integration, \
         patch("core.execution_tracker.ExecutionTracker") as mock_tracker, \
         patch("core.order_engine.OrderEngine") as mock_engine:
        plan = build_execution_plan_from_queue(
            queue,
            account_id="ACC-001",
            broker_name="آگاه",
            plan_id="plan-001",
        )
        assert mock_dispatch.call_count == 0
        assert mock_integration.call_count == 0
        assert mock_tracker.call_count == 0
        assert mock_engine.call_count == 0

    assert isinstance(plan, ExecutionPlan)
    assert len(plan.orders) == 1


def test_no_account_or_broker_inference():
    """Explicit inputs are authoritative; QueueEntry bindings are never used."""
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-ENTRY", broker_name="broker-entry")

    plan = build_execution_plan_from_queue(
        queue,
        account_id="ACC-INPUT",
        broker_name="broker-input",
        plan_id="plan-001",
    )
    assert plan.accounts == ["ACC-INPUT"]
    assert plan.broker_names == ["broker-input"]
    assert plan.account_routes == {"ACC-INPUT": "broker-input"}
    assert plan.conditions["binding"][0]["account_id"] == "ACC-INPUT"
    assert plan.conditions["binding"][0]["broker_name"] == "broker-input"


def test_mixed_queue_entries_produce_single_plan_no_grouping():
    """Two entries bound to different accounts still produce ONE plan with
    the explicit input account/broker; no splitting, no inference."""
    order_a = make_order("IRO1TEST0001")
    order_b = make_order("IRO1TEST0002")
    queue = OrderQueue()
    queue.enqueue(order_a, account_id="ACC-001", broker_name="آگاه")
    queue.enqueue(order_b, account_id="ACC-002", broker_name="مبنا")

    plan = build_execution_plan_from_queue(
        queue,
        account_id="ACC-INPUT",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    assert isinstance(plan, ExecutionPlan)
    assert plan.orders == [order_a, order_b]
    assert plan.execution_order == [0, 1]
    assert plan.accounts == ["ACC-INPUT"]
    assert plan.account_routes == {"ACC-INPUT": "آگاه"}


def main():
    tests = [
        test_one_order_queue_to_plan,
        test_plan_id_preserved_in_plan,
        test_order_identity_survives_to_plan,
        test_account_identity_preserved_in_plan,
        test_broker_identity_preserved_in_plan,
        test_multiple_orders_order_and_sequence_preserved,
        test_empty_queue_uses_existing_planner_contract,
        test_no_dispatch_or_core_calls,
        test_no_account_or_broker_inference,
        test_mixed_queue_entries_produce_single_plan_no_grouping,
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

    print(f"\nAll UI-4 Task 4 planner-boundary tests passed. ({len(tests)} tests)")


if __name__ == "__main__":
    main()