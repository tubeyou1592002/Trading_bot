"""Block UI-4 — Task 6: OrderQueue minimal pending lifecycle tests.

Standalone tests for the new ``OrderQueue.remove`` / ``OrderQueue.is_pending``
operations and for the FIFO / identity guarantees of the queue.

The queue remains a pure pending-entry holder: ``remove`` drops the exact
entry, ``is_pending`` compares order identity (``is``), and the existing
``enqueue`` / ``list_pending`` contract is unchanged.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime, timezone

from models.order import BUY, SELL, Order
from core.order_queue import OrderQueue, QueueEntry


def make_order(
    nsc_id="IRO1TEST0001",
    side=BUY,
    price=150,
    quantity=10,
    creation_date=None,
):
    return Order(
        nsc_id=nsc_id,
        side=side,
        price=price,
        quantity=quantity,
        creation_date=creation_date,
    )


def test_1_is_pending_true_after_enqueue():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")
    assert queue.is_pending(order) is True


def test_2_is_pending_false_for_other_order():
    order = make_order()
    other = make_order("IRO1TEST0002")
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")
    assert queue.is_pending(other) is False


def test_3_remove_drops_the_same_entry():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")
    entry = queue.list_pending()[0]

    queue.remove(entry)

    assert queue.list_pending() == []


def test_4_not_pending_after_remove():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")
    entry = queue.list_pending()[0]

    queue.remove(entry)

    assert queue.is_pending(order) is False


def test_5_removing_wrong_entry_raises_value_error():
    order_a = make_order("IRO1TEST0001")
    order_b = make_order("IRO1TEST0002")
    queue = OrderQueue()
    queue.enqueue(order_a, account_id="ACC-001", broker_name="آگاه")

    foreign_entry = QueueEntry(
        order=order_b,
        account_id="ACC-002",
        broker_name="آگاه",
    )

    try:
        queue.remove(foreign_entry)
    except ValueError:
        pass
    else:
        raise AssertionError("removing a foreign entry must raise ValueError")

    # The real entry is untouched.
    assert queue.list_pending()[0].order is order_a
    assert queue.is_pending(order_a) is True


def test_6_removing_one_entry_preserves_the_rest():
    orders = [
        make_order("IRO1TEST0001"),
        make_order("IRO1TEST0002"),
        make_order("IRO1TEST0003"),
    ]
    queue = OrderQueue()
    for order in orders:
        queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")

    middle = queue.list_pending()[1]
    queue.remove(middle)

    pending = queue.list_pending()
    assert len(pending) == 2
    assert pending[0].order is orders[0]
    assert pending[1].order is orders[2]
    assert queue.is_pending(orders[0]) is True
    assert queue.is_pending(orders[1]) is False
    assert queue.is_pending(orders[2]) is True


def test_7_fifo_remains_pending_order_preserved():
    orders = [
        make_order("IRO1TEST0001"),
        make_order("IRO1TEST0002"),
        make_order("IRO1TEST0003"),
    ]
    queue = OrderQueue()
    for order in orders:
        queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")

    assert [e.order for e in queue.list_pending()] == orders

    # Remove the first entry; the remaining two keep their original order.
    queue.remove(queue.list_pending()[0])
    remaining = queue.list_pending()
    assert len(remaining) == 2
    assert remaining[0].order is orders[1]
    assert remaining[1].order is orders[2]


def test_8_is_pending_uses_object_identity_not_equality():
    # Two distinct Order objects with fully equal field values (explicit
    # creation_date keeps them structurally equal; only identity differs).
    stamp = datetime(2026, 9, 23, 9, 0, 0, tzinfo=timezone.utc)
    order_a = make_order(creation_date=stamp)
    order_b = make_order(creation_date=stamp)
    queue = OrderQueue()
    queue.enqueue(order_a, account_id="ACC-001", broker_name="آگاه")

    assert order_a == order_b  # structural equality holds...
    assert order_a is not order_b
    assert queue.is_pending(order_a) is True
    assert queue.is_pending(order_b) is False


def test_9_enqueue_and_list_pending_unchanged():
    orders = [
        make_order("IRO1TEST0001"),
        make_order("IRO1TEST0002"),
    ]
    queue = OrderQueue()
    queue.enqueue(orders[0], account_id="ACC-001", broker_name="آگاه")
    queue.enqueue(orders[1], account_id="ACC-002", broker_name="آگاه")

    pending = queue.list_pending()
    assert len(pending) == 2
    assert all(
        entry.order is order
        for entry, order in zip(pending, orders)
    )
    assert [entry.account_id for entry in pending] == ["ACC-001", "ACC-002"]
    assert [entry.broker_name for entry in pending] == ["آگاه", "آگاه"]


def main():
    tests = [
        test_1_is_pending_true_after_enqueue,
        test_2_is_pending_false_for_other_order,
        test_3_remove_drops_the_same_entry,
        test_4_not_pending_after_remove,
        test_5_removing_wrong_entry_raises_value_error,
        test_6_removing_one_entry_preserves_the_rest,
        test_7_fifo_remains_pending_order_preserved,
        test_8_is_pending_uses_object_identity_not_equality,
        test_9_enqueue_and_list_pending_unchanged,
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

    print(f"\nAll UI-4 Task 6 queue lifecycle tests passed. ({len(tests)} tests)")


if __name__ == "__main__":
    main()