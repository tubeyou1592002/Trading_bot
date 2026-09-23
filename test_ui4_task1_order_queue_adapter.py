"""Block UI-4 — Task 1: Order -> LogicalOrderInstruction Adapter tests.

Standalone tests for ``core.order_queue_adapter.build_logical_instruction``.

The adapter converts existing Order objects into the immutable Block 1
``LogicalOrderInstruction`` contract without cloning/mutating orders,
without guessing account/broker bindings, and without performing any
login, brokerage, dispatch, or tracking work.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from core.order_queue_adapter import build_logical_instruction
from core.execution_planner import (
    LogicalOrderInstruction,
    PlannerValidationError,
    PlannedOrder,
)
from models.order import BUY, SELL, Order


def make_order(nsc_id="IRO1TEST0001", side=BUY, price=150, quantity=10):
    return Order(
        nsc_id=nsc_id,
        side=side,
        price=price,
        quantity=quantity,
    )


def test_one_order_yields_one_planned_order():
    order = make_order()
    instruction = build_logical_instruction(
        queued_orders=[order],
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    assert isinstance(instruction, LogicalOrderInstruction)
    assert len(instruction.orders) == 1


def test_plan_id_preserved():
    order = make_order()
    instruction = build_logical_instruction(
        queued_orders=[order],
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-XYZ",
    )
    assert instruction.plan_id == "plan-XYZ"


def test_account_id_preserved_exactly():
    order = make_order()
    instruction = build_logical_instruction(
        queued_orders=[order],
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    assert instruction.orders[0].account_id == "ACC-001"


def test_broker_name_preserved_exactly():
    order = make_order()
    instruction = build_logical_instruction(
        queued_orders=[order],
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    assert instruction.orders[0].broker_name == "آگاه"


def test_sequence_is_0_1_2_for_multiple_orders():
    orders = [make_order("IRO1TEST0001"), make_order("IRO1TEST0002"), make_order("IRO1TEST0003")]
    instruction = build_logical_instruction(
        queued_orders=orders,
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    assert [po.sequence for po in instruction.orders] == [0, 1, 2]


def test_same_order_object_is_used_no_clone():
    order_a = make_order("IRO1TEST0001")
    order_b = make_order("IRO1TEST0002")
    instruction = build_logical_instruction(
        queued_orders=[order_a, order_b],
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    assert instruction.orders[0].order is order_a
    assert instruction.orders[1].order is order_b


def test_conditions_match_real_contract_defaults():
    order = make_order()
    instruction = build_logical_instruction(
        queued_orders=[order],
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-001",
    )
    # Real contract: per-order and instruction conditions are plain dicts,
    # empty by default (``PlannedOrder.conditions`` / ``LogicalOrderInstruction.conditions``).
    assert isinstance(instruction.conditions, dict)
    assert instruction.conditions == {}
    assert isinstance(instruction.orders[0].conditions, dict)
    assert instruction.orders[0].conditions == {}


def test_account_ids_not_mixed_between_batches():
    """Each batch binds its own single account_id; batches never mix."""
    order_x = make_order("IRO1TEST0001")
    order_y = make_order("IRO1TEST0002")

    batch_acc1 = build_logical_instruction(
        queued_orders=[order_x],
        account_id="ACC-001",
        broker_name="آگاه",
        plan_id="plan-1",
    )
    batch_acc2 = build_logical_instruction(
        queued_orders=[order_y],
        account_id="ACC-002",
        broker_name="آگاه",
        plan_id="plan-2",
    )

    assert batch_acc1.orders[0].account_id == "ACC-001"
    assert batch_acc2.orders[0].account_id == "ACC-002"
    assert batch_acc1.orders[0].account_id != batch_acc2.orders[0].account_id


def test_invalid_account_id_uses_existing_model_validation():
    order = make_order()
    try:
        build_logical_instruction(
            queued_orders=[order],
            account_id="   ",
            broker_name="آگاه",
            plan_id="plan-001",
        )
    except PlannerValidationError:
        pass
    else:
        raise AssertionError("blank account_id must raise PlannerValidationError")


def test_invalid_plan_id_uses_existing_model_validation():
    order = make_order()
    try:
        build_logical_instruction(
            queued_orders=[order],
            account_id="ACC-001",
            broker_name="آگاه",
            plan_id="",
        )
    except PlannerValidationError:
        pass
    else:
        raise AssertionError("blank plan_id must raise PlannerValidationError")


def main():
    tests = [
        test_one_order_yields_one_planned_order,
        test_plan_id_preserved,
        test_account_id_preserved_exactly,
        test_broker_name_preserved_exactly,
        test_sequence_is_0_1_2_for_multiple_orders,
        test_same_order_object_is_used_no_clone,
        test_conditions_match_real_contract_defaults,
        test_account_ids_not_mixed_between_batches,
        test_invalid_account_id_uses_existing_model_validation,
        test_invalid_plan_id_uses_existing_model_validation,
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
        f"\nAll UI-4 Task 1 adapter tests passed. ({len(tests)} tests)"
    )


if __name__ == "__main__":
    main()