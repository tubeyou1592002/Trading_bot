"""Block UI-4 — Task 3: OrderQueue -> OrderQueueAdapter bridge tests.

Standalone tests for ``build_instruction_from_queue`` in
``core.order_queue_adapter``.

The bridge converts the pending entries of an ``OrderQueue`` into one
``LogicalOrderInstruction`` using the existing ``build_logical_instruction``
adapter. This file verifies:
  * explicit account_id / broker_name / plan_id are preserved,
  * the exact Order objects flow through (no clone / reconstruction),
  * sequences stay 0, 1, 2, ...,
  * no grouping / inference across mixed accounts or brokers
    (the adapter contract is one account + one broker per batch),
  * no dispatch or broker activity.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from models.order import BUY, SELL, Order
from core.order_queue import OrderQueue
from core.order_queue_adapter import (
    build_instruction_from_queue,
    build_logical_instruction,
)
from core.execution_planner import (
    LogicalOrderInstruction,
    PlannedOrder,
)


def make_order(nsc_id="IRO1TEST0001", side=BUY, price=150, quantity=10):
    return Order(
        nsc_id=nsc_id,
        side=side,
        price=price,
        quantity=quantity,
    )


def test_empty_queue_yields_instruction_with_empty_orders():
    queue = OrderQueue()
    instruction = build_instruction_from_queue(
        queue,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    assert isinstance(instruction, LogicalOrderInstruction)
    # Real contract: ``__post_init__`` freezes ``orders`` into a tuple.
    assert list(instruction.orders) == []
    assert instruction.plan_id == "plan-001"
    assert instruction.conditions == {}


def test_one_queued_order_yields_one_planned_order():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")

    instruction = build_instruction_from_queue(
        queue,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    assert len(instruction.orders) == 1
    assert isinstance(instruction.orders[0], PlannedOrder)


def test_same_order_object_preserved_through_queue_and_adapter():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")

    instruction = build_instruction_from_queue(
        queue,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    assert instruction.orders[0].order is order


def test_plan_id_preserved_exactly():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")

    instruction = build_instruction_from_queue(
        queue,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-777",
    )
    assert instruction.plan_id == "plan-777"


def test_input_account_id_preserved_exactly():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-ENTRY", broker_name="آگاه")

    instruction = build_instruction_from_queue(
        queue,
        account_id="ACC-INPUT",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    assert instruction.orders[0].account_id == "ACC-INPUT"


def test_input_broker_name_preserved_exactly():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="مبنا")

    instruction = build_instruction_from_queue(
        queue,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    assert instruction.orders[0].broker_name == "آگاه"


def test_sequences_are_0_1_2():
    orders = [
        make_order("IRO1TEST0001"),
        make_order("IRO1TEST0002"),
        make_order("IRO1TEST0003"),
    ]
    queue = OrderQueue()
    for order in orders:
        queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")

    instruction = build_instruction_from_queue(
        queue,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    assert [po.sequence for po in instruction.orders] == [0, 1, 2]


def test_queue_entry_identity_does_not_clone_orders():
    order_a = make_order("IRO1TEST0001")
    order_b = make_order("IRO1TEST0002")
    queue = OrderQueue()
    queue.enqueue(order_a, account_id="ACC-001", broker_name="آگاه")
    queue.enqueue(order_b, account_id="ACC-001", broker_name="آگاه")

    instruction = build_instruction_from_queue(
        queue,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    assert [po.order for po in instruction.orders] == [order_a, order_b]
    assert instruction.orders[0].order is order_a
    assert instruction.orders[1].order is order_b


def test_two_accounts_no_grouping_no_inference():
    """Mixed-account queue: ONE instruction, explicit input account/broker
    wins, no grouping/splitting and no per-entry inference."""
    order_a = make_order("IRO1TEST0001")
    order_b = make_order("IRO1TEST0002")
    queue = OrderQueue()
    queue.enqueue(order_a, account_id="ACC-001", broker_name="آگاه")
    queue.enqueue(order_b, account_id="ACC-002", broker_name="آگاه")

    instruction = build_instruction_from_queue(
        queue,
        account_id="ACC-INPUT",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    # One instruction, never split per account/broker.
    assert isinstance(instruction, LogicalOrderInstruction)
    assert len(instruction.orders) == 2
    # Sequence preserved regardless of mixed bound accounts.
    assert [po.sequence for po in instruction.orders] == [0, 1]
    # Explicit input account/broker is authoritative — no inference from entries.
    assert instruction.orders[0].order is order_a
    assert instruction.orders[1].order is order_b
    assert [po.account_id for po in instruction.orders] == ["ACC-INPUT", "ACC-INPUT"]
    assert [po.broker_name for po in instruction.orders] == ["آگاه", "آگاه"]


def test_two_brokers_no_grouping_no_inference():
    order_a = make_order("IRO1TEST0001")
    order_b = make_order("IRO1TEST0002")
    queue = OrderQueue()
    queue.enqueue(order_a, account_id="ACC-001", broker_name="آگاه")
    queue.enqueue(order_b, account_id="ACC-001", broker_name="مبنا")

    instruction = build_instruction_from_queue(
        queue,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    assert len(instruction.orders) == 2
    assert [po.sequence for po in instruction.orders] == [0, 1]
    assert [po.broker_name for po in instruction.orders] == ["آگاه", "آگاه"]
    assert [po.account_id for po in instruction.orders] == ["ACC-001", "ACC-001"]


class StrictSpy:
    """Raises if ANY attribute is read or any method is called."""

    def __getattribute__(self, name):
        raise AssertionError(f"queue touched order attribute/method: {name}")


def test_bridge_performs_no_dispatch_and_does_not_touch_orders():
    spy = StrictSpy()
    queue = OrderQueue()
    queue.enqueue(spy, account_id="ACC-001", broker_name="آگاه")

    instruction = build_instruction_from_queue(
        queue,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    assert instruction.orders[0].order is spy


def main():
    tests = [
        test_empty_queue_yields_instruction_with_empty_orders,
        test_one_queued_order_yields_one_planned_order,
        test_same_order_object_preserved_through_queue_and_adapter,
        test_plan_id_preserved_exactly,
        test_input_account_id_preserved_exactly,
        test_input_broker_name_preserved_exactly,
        test_sequences_are_0_1_2,
        test_queue_entry_identity_does_not_clone_orders,
        test_two_accounts_no_grouping_no_inference,
        test_two_brokers_no_grouping_no_inference,
        test_bridge_performs_no_dispatch_and_does_not_touch_orders,
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

    print(f"\nAll UI-4 Task 3 bridge tests passed. ({len(tests)} tests)")


if __name__ == "__main__":
    main()