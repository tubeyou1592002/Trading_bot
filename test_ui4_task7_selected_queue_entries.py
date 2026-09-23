"""Block UI-4 — Task 7: build an ExecutionPlan from selected QueueEntries.

Standalone tests for ``build_execution_plan_from_selected_entries`` in
``core.order_queue_adapter``.

The function builds ONE ``ExecutionPlan`` from a chosen subset of
``QueueEntry`` objects (only their exact Order objects), bound to the
explicit caller-provided ``account_id`` / ``broker_name``, fail-closed on
any account/broker mismatch. No queue mutation, no dispatch, no tracker or
core execution calls.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import patch

from models.order import BUY, SELL, Order
from core.order_queue import OrderQueue
from core.order_queue_adapter import build_execution_plan_from_selected_entries
from core.dispatch_contracts import ExecutionPlan
from core.execution_planner import PlannerValidationError


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


def test_1_plan_contains_only_selected_orders():
    orders = [
        make_order("IRO1TEST0001"),
        make_order("IRO1TEST0002"),
        make_order("IRO1TEST0003"),
    ]
    queue = make_queue(orders)
    entries = queue.list_pending()

    plan = build_execution_plan_from_selected_entries(
        [entries[0], entries[1]],
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-1",
    )

    assert isinstance(plan, ExecutionPlan)
    assert len(plan.orders) == 2
    assert plan.orders == [orders[0], orders[1]]
    assert plan.execution_order == [0, 1]


def test_2_third_entry_not_in_plan():
    orders = [
        make_order("IRO1TEST0001"),
        make_order("IRO1TEST0002"),
        make_order("IRO1TEST0003"),
    ]
    queue = make_queue(orders)
    entries = queue.list_pending()

    plan = build_execution_plan_from_selected_entries(
        [entries[0], entries[1]],
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-1",
    )
    assert orders[2] not in plan.orders
    assert all(o is not orders[2] for o in plan.orders)


def test_3_order_identity_preserved():
    orders = [
        make_order("IRO1TEST0001"),
        make_order("IRO1TEST0002"),
        make_order("IRO1TEST0003"),
    ]
    queue = make_queue(orders)
    entries = queue.list_pending()

    plan = build_execution_plan_from_selected_entries(
        [entries[0], entries[2]],
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-1",
    )
    assert plan.orders[0] is orders[0]
    assert plan.orders[1] is orders[2]


def test_4_selected_order_sequence_preserved():
    orders = [
        make_order("IRO1TEST0001"),
        make_order("IRO1TEST0002"),
        make_order("IRO1TEST0003"),
    ]
    queue = make_queue(orders)
    entries = queue.list_pending()

    plan = build_execution_plan_from_selected_entries(
        [entries[0], entries[2], entries[1]],
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-1",
    )
    assert all(o is o0 for o, o0 in zip(plan.orders, [orders[0], orders[2], orders[1]]))
    assert plan.execution_order == [0, 1, 2]
    assert plan.orders == [orders[0], orders[2], orders[1]]


def test_5_queue_unchanged_after_building_plan():
    orders = [
        make_order("IRO1TEST0001"),
        make_order("IRO1TEST0002"),
        make_order("IRO1TEST0003"),
    ]
    queue = make_queue(orders)
    entries = queue.list_pending()

    build_execution_plan_from_selected_entries(
        [entries[0], entries[1]],
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-1",
    )

    pending = queue.list_pending()
    assert len(pending) == 3
    assert all(e.order is o for e, o in zip(pending, orders))


def test_6_same_account_and_broker_succeeds():
    order = make_order()
    queue = make_queue([order])
    entry = queue.list_pending()[0]

    plan = build_execution_plan_from_selected_entries(
        [entry],
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-1",
    )
    assert plan.orders[0] is order
    assert plan.accounts == ["ACC-001"]
    assert plan.broker_names == ["آگاه"]


def test_7_different_account_raises_value_error():
    order_a = make_order("IRO1TEST0001")
    order_b = make_order("IRO1TEST0002")
    queue_a = make_queue([order_a], account_id="ACC-001")
    queue_b = make_queue([order_b], account_id="ACC-002")
    entry_a = queue_a.list_pending()[0]
    entry_b = queue_b.list_pending()[0]

    try:
        build_execution_plan_from_selected_entries(
            [entry_a, entry_b],
            account_id="ACC-001",
            broker_name="آگاه",
            plan_id="plan-1",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("mixed accounts must raise ValueError (fail-closed)")


def test_8_different_broker_raises_value_error():
    order_a = make_order("IRO1TEST0001")
    order_b = make_order("IRO1TEST0002")
    queue_a = make_queue([order_a], broker_name="آگاه")
    queue_b = make_queue([order_b], broker_name="مبنا")
    entry_a = queue_a.list_pending()[0]
    entry_b = queue_b.list_pending()[0]

    try:
        build_execution_plan_from_selected_entries(
            [entry_a, entry_b],
            account_id="ACC-001",
            broker_name="آگاه",
            plan_id="plan-1",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("mixed brokers must raise ValueError (fail-closed)")


def test_9_empty_selection_is_fail_closed():
    # Real planner contract: an instruction with no orders raises
    # PlannerValidationError (a ValueError subclass) — unchanged here.
    try:
        build_execution_plan_from_selected_entries(
            [],
            account_id="ACC-001",
            broker_name="آگاه",
            plan_id="plan-1",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("empty selection must fail closed (ValueError)")


def test_10_no_dispatch_tracker_or_core_calls():
    order = make_order()
    queue = make_queue([order])
    entry = queue.list_pending()[0]

    with patch("core.dispatch_core.DispatchCore") as mock_dispatch, \
         patch("core.block5_task4.DispatchIntegration") as mock_integration, \
         patch("core.execution_tracker.ExecutionTracker") as mock_tracker, \
         patch("core.order_engine.OrderEngine") as mock_engine:
        plan = build_execution_plan_from_selected_entries(
            [entry],
            account_id="ACC-001",
            broker_name="آگاه",
            plan_id="plan-1",
        )
        assert mock_dispatch.call_count == 0
        assert mock_integration.call_count == 0
        assert mock_tracker.call_count == 0
        assert mock_engine.call_count == 0

    assert isinstance(plan, ExecutionPlan)
    assert plan.orders[0] is order


def main():
    tests = [
        test_1_plan_contains_only_selected_orders,
        test_2_third_entry_not_in_plan,
        test_3_order_identity_preserved,
        test_4_selected_order_sequence_preserved,
        test_5_queue_unchanged_after_building_plan,
        test_6_same_account_and_broker_succeeds,
        test_7_different_account_raises_value_error,
        test_8_different_broker_raises_value_error,
        test_9_empty_selection_is_fail_closed,
        test_10_no_dispatch_tracker_or_core_calls,
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

    print(f"\nAll UI-4 Task 7 selected-entries tests passed. ({len(tests)} tests)")


if __name__ == "__main__":
    main()