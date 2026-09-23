"""Block UI-4 — Task 2: OrderQueue tests.

Standalone tests for ``core.order_queue.OrderQueue``.

The queue is a pure FIFO holder for pre-dispatch orders with explicit
per-entry Account -> Broker bindings. These tests verify emptiness,
preservation of order identity and bindings, insertion order, no mixing
across accounts/brokers, and that the queue performs no dispatch or broker
work of any kind.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from models.order import BUY, SELL, Order
from core.order_queue import OrderQueue, QueueEntry


def make_order(nsc_id="IRO1TEST0001", side=BUY, price=150, quantity=10):
    return Order(
        nsc_id=nsc_id,
        side=side,
        price=price,
        quantity=quantity,
    )


def test_queue_is_empty_initially():
    queue = OrderQueue()
    assert queue.list_pending() == []


def test_one_order_is_enqueued():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")
    pending = queue.list_pending()
    assert len(pending) == 1


def test_list_pending_returns_the_same_order():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")
    assert queue.list_pending()[0].order == order


def test_order_object_identity_preserved():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")
    assert queue.list_pending()[0].order is order


def test_account_id_preserved_exactly():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-007", broker_name="آگاه")
    assert queue.list_pending()[0].account_id == "ACC-007"


def test_broker_name_preserved_exactly():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="مبنا")
    assert queue.list_pending()[0].broker_name == "مبنا"


def test_insertion_order_preserved():
    orders = [
        make_order("IRO1TEST0001"),
        make_order("IRO1TEST0002"),
        make_order("IRO1TEST0003"),
    ]
    queue = OrderQueue()
    for order in orders:
        queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")
    pending = queue.list_pending()
    assert all(
        entry.order is order
        for entry, order in zip(pending, orders)
    )
    assert [pending[i].account_id for i in range(3)] == ["ACC-001"] * 3


def test_orders_with_different_accounts_do_not_mix():
    order_a = make_order("IRO1TEST0001")
    order_b = make_order("IRO1TEST0002")
    queue = OrderQueue()
    queue.enqueue(order_a, account_id="ACC-001", broker_name="آگاه")
    queue.enqueue(order_b, account_id="ACC-002", broker_name="آگاه")
    pending = queue.list_pending()
    assert pending[0].order is order_a
    assert pending[0].account_id == "ACC-001"
    assert pending[1].order is order_b
    assert pending[1].account_id == "ACC-002"


def test_orders_with_different_brokers_do_not_mix():
    order_a = make_order("IRO1TEST0001")
    order_b = make_order("IRO1TEST0002")
    queue = OrderQueue()
    queue.enqueue(order_a, account_id="ACC-001", broker_name="آگاه")
    queue.enqueue(order_b, account_id="ACC-001", broker_name="مبنا")
    pending = queue.list_pending()
    assert pending[0].order is order_a
    assert pending[0].broker_name == "آگاه"
    assert pending[1].order is order_b
    assert pending[1].broker_name == "مبنا"


def test_entry_exposes_only_order_account_broker():
    order = make_order()
    queue = OrderQueue()
    queue.enqueue(order, account_id="ACC-001", broker_name="آگاه")
    entry = queue.list_pending()[0]
    assert isinstance(entry, QueueEntry)
    assert set(vars(entry)) == {"order", "account_id", "broker_name"}


class StrictSpy:
    """Raises if ANY attribute is read or any method is called."""

    def __getattribute__(self, name):
        raise AssertionError(f"queue touched order attribute/method: {name}")


def test_queue_performs_no_dispatch_or_broker_call():
    """The queue is pure storage: it must not read, clone, mutate, or call anything."""
    spy = StrictSpy()
    queue = OrderQueue()
    queue.enqueue(spy, account_id="ACC-001", broker_name="آگاه")
    pending = queue.list_pending()
    assert pending[0].order is spy
    assert pending[0].account_id == "ACC-001"
    assert pending[0].broker_name == "آگاه"


def main():
    tests = [
        test_queue_is_empty_initially,
        test_one_order_is_enqueued,
        test_list_pending_returns_the_same_order,
        test_order_object_identity_preserved,
        test_account_id_preserved_exactly,
        test_broker_name_preserved_exactly,
        test_insertion_order_preserved,
        test_orders_with_different_accounts_do_not_mix,
        test_orders_with_different_brokers_do_not_mix,
        test_entry_exposes_only_order_account_broker,
        test_queue_performs_no_dispatch_or_broker_call,
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

    print(f"\nAll UI-4 Task 2 queue tests passed. ({len(tests)} tests)")


if __name__ == "__main__":
    main()