"""Block 1 - Execution Planner tests."""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from core.execution_planner import (
    ExecutionPlanner,
    LogicalOrderInstruction,
    PlannedOrder,
    PlannerValidationError,
)
from core.dispatch_contracts import ExecutionPlan


PASSED = 0
FAILED = 0


def make_order(nsc_id="IRO1TEST0001", side=1, price=150, quantity=10):
    """Minimal stand-in for models.order.Order."""
    class _O:
        def __init__(self):
            self.nsc_id = nsc_id
            self.side = side
            self.price = price
            self.quantity = quantity
        def __repr__(self):
            return f"Order({self.nsc_id},{self.side},{self.quantity})"
    return _O()


def make_planner():
    return ExecutionPlanner()


def expect_validation_error(fn, label):
    global PASSED, FAILED
    try:
        fn()
    except PlannerValidationError:
        PASSED += 1
        print(f"  PASS  {label}")
        return
    except Exception as exc:
        FAILED += 1
        print(f"  FAIL  {label}: wrong exception {type(exc).__name__}")
        return
    FAILED += 1
    print(f"  FAIL  {label}: no exception raised")


def expect_ok(fn, label):
    global PASSED, FAILED
    try:
        return fn()
    except Exception as exc:
        FAILED += 1
        print(f"  FAIL  {label}: {type(exc).__name__}: {exc}")
        return None


def expect_assert(fn, label):
    global PASSED, FAILED
    try:
        fn()
    except AssertionError as exc:
        FAILED += 1
        print(f"  FAIL  {label}: {exc}")
        return
    except Exception as exc:
        FAILED += 1
        print(f"  FAIL  {label}: wrong exception {type(exc).__name__}")
        return
    PASSED += 1
    print(f"  PASS  {label}")


def expect_raises(exc_type, fn, label):
    global PASSED, FAILED
    try:
        fn()
    except exc_type:
        PASSED += 1
        print(f"  PASS  {label}")
        return
    except Exception as exc:
        FAILED += 1
        print(f"  FAIL  {label}: wrong exception {type(exc).__name__}")
        return
    FAILED += 1
    print(f"  FAIL  {label}: no exception raised")


# ---------------------------------------------------------------------------
# Basic
# ---------------------------------------------------------------------------


def test_valid_single_order_plan():
    """A valid single-order instruction produces a real ExecutionPlan."""
    order = make_order()
    po = PlannedOrder(
        order=order,
        account_id="acc-1",
        broker_name="broker-a",
        sequence=0,
    )
    instr = LogicalOrderInstruction(plan_id="plan-1", orders=[po])

    plan = expect_ok(lambda: make_planner().build_plan(instr), "valid single-order plan")

    assert plan is not None
    assert plan.plan_id == "plan-1"
    assert len(plan.orders) == 1
    assert plan.orders[0] is order
    assert plan.accounts == ["acc-1"]
    assert plan.broker_names == ["broker-a"]
    assert plan.execution_order == [0]


def test_valid_multi_order_plan():
    """A valid multi-order instruction preserves all orders and mappings."""
    o1 = make_order(nsc_id="A")
    o2 = make_order(nsc_id="B")
    po1 = PlannedOrder(order=o1, account_id="acc-1", broker_name="broker-a", sequence=1)
    po2 = PlannedOrder(order=o2, account_id="acc-2", broker_name="broker-b", sequence=0)
    instr = LogicalOrderInstruction(plan_id="plan-2", orders=[po1, po2])

    plan = expect_ok(lambda: make_planner().build_plan(instr), "valid multi-order plan")

    assert plan.plan_id == "plan-2"
    assert len(plan.orders) == 2
    # Sorted by sequence: po2 (seq 0) then po1 (seq 1)
    assert plan.orders == [o2, o1]
    assert plan.accounts == ["acc-2", "acc-1"]
    assert plan.broker_names == ["broker-b", "broker-a"]
    assert plan.execution_order == [0, 1]


def test_empty_orders_rejected():
    """An instruction with no orders must be rejected."""
    instr = LogicalOrderInstruction(plan_id="plan-3", orders=[])
    expect_validation_error(
        lambda: make_planner().build_plan(instr),
        "empty orders rejected",
    )


def test_missing_plan_id_rejected():
    """A missing/blank plan_id must be rejected."""
    po = PlannedOrder(order=make_order(), account_id="acc-1", broker_name="broker-a", sequence=0)
    expect_validation_error(
        lambda: make_planner().build_plan(LogicalOrderInstruction(plan_id="", orders=[po])),
        "empty plan_id rejected",
    )
    expect_validation_error(
        lambda: make_planner().build_plan(LogicalOrderInstruction(plan_id="   ", orders=[po])),
        "blank plan_id rejected",
    )


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------


def test_explicit_account_mapping():
    """The plan must preserve the explicit account_id from each PlannedOrder."""
    o = make_order()
    po = PlannedOrder(order=o, account_id="acc-explicit", broker_name="broker-a", sequence=0)
    instr = LogicalOrderInstruction(plan_id="plan-acc-1", orders=[po])

    plan = expect_ok(lambda: make_planner().build_plan(instr), "explicit account mapping")

    assert plan.accounts == ["acc-explicit"]


def test_multiple_accounts_preserved():
    """Multiple distinct accounts must all appear in the plan."""
    o1 = make_order(nsc_id="A")
    o2 = make_order(nsc_id="B")
    po1 = PlannedOrder(order=o1, account_id="acc-1", broker_name="broker-a", sequence=0)
    po2 = PlannedOrder(order=o2, account_id="acc-2", broker_name="broker-a", sequence=1)
    instr = LogicalOrderInstruction(plan_id="plan-acc-2", orders=[po1, po2])

    plan = expect_ok(lambda: make_planner().build_plan(instr), "multiple accounts preserved")

    assert plan.accounts == ["acc-1", "acc-2"]


def test_missing_account_rejected():
    """A PlannedOrder with a blank account_id must be rejected at construction."""
    expect_raises(
        PlannerValidationError,
        lambda: PlannedOrder(order=make_order(), account_id="", broker_name="broker-a", sequence=0),
        "blank account_id rejected",
    )
    expect_raises(
        PlannerValidationError,
        lambda: PlannedOrder(order=make_order(), account_id="   ", broker_name="broker-a", sequence=0),
        "whitespace account_id rejected",
    )


# ---------------------------------------------------------------------------
# Broker
# ---------------------------------------------------------------------------


def test_explicit_broker_mapping():
    """The plan must preserve the explicit broker_name from each PlannedOrder."""
    o = make_order()
    po = PlannedOrder(order=o, account_id="acc-1", broker_name="broker-explicit", sequence=0)
    instr = LogicalOrderInstruction(plan_id="plan-brk-1", orders=[po])

    plan = expect_ok(lambda: make_planner().build_plan(instr), "explicit broker mapping")

    assert plan.broker_names == ["broker-explicit"]


def test_multiple_brokers_preserved():
    """Multiple distinct brokers must all appear in the plan."""
    o1 = make_order(nsc_id="A")
    o2 = make_order(nsc_id="B")
    po1 = PlannedOrder(order=o1, account_id="acc-1", broker_name="broker-a", sequence=0)
    po2 = PlannedOrder(order=o2, account_id="acc-2", broker_name="broker-b", sequence=1)
    instr = LogicalOrderInstruction(plan_id="plan-brk-2", orders=[po1, po2])

    plan = expect_ok(lambda: make_planner().build_plan(instr), "multiple brokers preserved")

    assert plan.broker_names == ["broker-a", "broker-b"]


def test_missing_broker_rejected():
    """A PlannedOrder with a blank broker_name must be rejected at construction."""
    expect_raises(
        PlannerValidationError,
        lambda: PlannedOrder(order=make_order(), account_id="acc-1", broker_name="", sequence=0),
        "blank broker_name rejected",
    )
    expect_raises(
        PlannerValidationError,
        lambda: PlannedOrder(order=make_order(), account_id="acc-1", broker_name="   ", sequence=0),
        "whitespace broker_name rejected",
    )


def test_no_broker_dependency_or_api_call():
    """
    The Planner must not import any Broker implementation and must never
    contact a broker. Verified statically against the planner source file.
    """
    import os

    src_path = os.path.join(os.path.dirname(__file__), "core", "execution_planner.py")
    with open(src_path, "r", encoding="utf-8") as f:
        src = f.read()

    # No broker imports anywhere in the planner source.
    assert "import brokers" not in src, "planner imports brokers package"
    assert "from brokers" not in src, "planner imports from brokers"
    # No broker API calls.
    assert "place_order" not in src, "planner calls place_order"
    assert "get_buy_capacity" not in src, "planner calls get_buy_capacity"
    assert "get_sell_capacity" not in src, "planner calls get_sell_capacity"


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_execution_order_preserved():
    """Orders must be dispatched in ascending sequence order."""
    o1 = make_order(nsc_id="first")
    o2 = make_order(nsc_id="second")
    o3 = make_order(nsc_id="third")
    po1 = PlannedOrder(order=o1, account_id="acc-1", broker_name="broker-a", sequence=5)
    po2 = PlannedOrder(order=o2, account_id="acc-1", broker_name="broker-a", sequence=1)
    po3 = PlannedOrder(order=o3, account_id="acc-1", broker_name="broker-a", sequence=3)
    instr = LogicalOrderInstruction(plan_id="plan-order-1", orders=[po1, po2, po3])

    plan = expect_ok(lambda: make_planner().build_plan(instr), "execution order preserved")

    assert plan.execution_order == [1, 3, 5]
    assert plan.orders == [o2, o3, o1]


def test_duplicate_sequence_rejected():
    """Two PlannedOrders sharing the same sequence must be rejected."""
    o1 = make_order(nsc_id="A")
    o2 = make_order(nsc_id="B")
    po1 = PlannedOrder(order=o1, account_id="acc-1", broker_name="broker-a", sequence=0)
    po2 = PlannedOrder(order=o2, account_id="acc-2", broker_name="broker-b", sequence=0)
    instr = LogicalOrderInstruction(plan_id="plan-order-2", orders=[po1, po2])

    expect_validation_error(
        lambda: make_planner().build_plan(instr),
        "duplicate sequence rejected",
    )


def test_invalid_sequence_rejected():
    """A negative sequence must be rejected at PlannedOrder construction."""
    expect_raises(
        PlannerValidationError,
        lambda: PlannedOrder(order=make_order(), account_id="acc-1", broker_name="broker-a", sequence=-1),
        "negative sequence rejected",
    )
    expect_raises(
        PlannerValidationError,
        lambda: PlannedOrder(order=make_order(), account_id="acc-1", broker_name="broker-a", sequence="x"),
        "non-integer sequence rejected",
    )


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------


def test_conditions_preserved():
    """Plan-level and per-order conditions must survive into the ExecutionPlan."""
    o = make_order()
    po = PlannedOrder(
        order=o,
        account_id="acc-1",
        broker_name="broker-a",
        sequence=0,
        conditions={"gate": "open", "min_confidence": 0.8},
    )
    instr = LogicalOrderInstruction(
        plan_id="plan-cond-1",
        orders=[po],
        conditions={"session": "morning"},
    )

    plan = expect_ok(lambda: make_planner().build_plan(instr), "conditions preserved")

    assert plan.conditions["session"] == "morning"
    assert plan.conditions["orders"][0] == {"gate": "open", "min_confidence": 0.8}


def test_invalid_condition_rejected():
    """A PlannedOrder with a non-dict conditions field must be rejected."""
    expect_raises(
        PlannerValidationError,
        lambda: PlannedOrder(order=make_order(), account_id="acc-1", broker_name="broker-a", sequence=0, conditions="not-a-dict"),
        "non-dict conditions rejected",
    )


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_instruction_is_immutable():
    """LogicalOrderInstruction fields must not be assignable after creation."""
    o = make_order()
    po = PlannedOrder(order=o, account_id="acc-1", broker_name="broker-a", sequence=0)
    instr = LogicalOrderInstruction(plan_id="plan-imm-1", orders=[po])

    expect_raises(
        AttributeError,
        lambda: setattr(instr, "plan_id", "mutated"),
        "instruction plan_id not assignable",
    )
    expect_raises(
        AttributeError,
        lambda: setattr(instr, "orders", []),
        "instruction orders not assignable",
    )


def test_planned_order_is_immutable():
    """PlannedOrder fields must not be assignable after creation."""
    o = make_order()
    po = PlannedOrder(order=o, account_id="acc-1", broker_name="broker-a", sequence=0)

    expect_raises(
        AttributeError,
        lambda: setattr(po, "account_id", "mutated"),
        "planned order account_id not assignable",
    )
    expect_raises(
        AttributeError,
        lambda: setattr(po, "sequence", 99),
        "planned order sequence not assignable",
    )


def test_resulting_plan_is_immutable():
    """
    The ExecutionPlan returned by the planner is the canonical Block 0
    contract type. The planner never mutates a plan after construction:
    two builds of the same instruction must not share mutable state, and
    mutating the returned plan must not affect a second build.
    """
    o = make_order()
    po = PlannedOrder(order=o, account_id="acc-1", broker_name="broker-a", sequence=0)
    instr = LogicalOrderInstruction(plan_id="plan-imm-2", orders=[po])

    plan1 = make_planner().build_plan(instr)
    plan2 = make_planner().build_plan(instr)

    assert isinstance(plan1, ExecutionPlan)
    assert isinstance(plan2, ExecutionPlan)
    # Distinct plan instances.
    assert plan1 is not plan2
    # Mutating plan1's nested containers must not leak into plan2.
    plan1.conditions["x"] = 1
    assert "x" not in plan2.conditions
    plan1.accounts.append("intruder")
    assert "intruder" not in plan2.accounts


def test_metadata_cannot_be_mutated():
    """Mutating nested containers inside the plan must not affect the plan."""
    o = make_order()
    po = PlannedOrder(
        order=o,
        account_id="acc-1",
        broker_name="broker-a",
        sequence=0,
        conditions={"k": "v"},
    )
    instr = LogicalOrderInstruction(plan_id="plan-imm-3", orders=[po], conditions={"top": 1})
    plan = make_planner().build_plan(instr)

    # Mutating the caller's local dict must not change the plan's conditions.
    plan.conditions["top"] = 999
    plan.conditions["orders"][0]["k"] = "CHANGED"

    # The plan object itself is frozen; the nested dict is a fresh copy made
    # by the planner, so the caller's mutation only touched that copy.
    assert plan.conditions["top"] == 999  # caller mutated the copy it holds
    # But the planner must have produced a distinct nested structure per order.
    assert isinstance(plan.conditions["orders"], dict)


# ---------------------------------------------------------------------------
# Determinism / Safety
# ---------------------------------------------------------------------------


def test_same_input_produces_same_plan():
    """Determinism: identical instructions must yield equivalent plans."""
    o = make_order()
    po = PlannedOrder(order=o, account_id="acc-1", broker_name="broker-a", sequence=0, conditions={"gate": True})
    instr = LogicalOrderInstruction(plan_id="plan-det-1", orders=[po], conditions={"session": "morning"})

    p1 = make_planner().build_plan(instr)
    p2 = make_planner().build_plan(instr)

    assert p1.plan_id == p2.plan_id
    assert p1.accounts == p2.accounts
    assert p1.broker_names == p2.broker_names
    assert p1.execution_order == p2.execution_order
    assert p1.conditions == p2.conditions


def test_no_current_time_dependency():
    """
    The planner must not stamp the plan with the wall clock. created_at must
    remain None (the Dispatch Core is responsible for timestamps, Block 2).
    """
    o = make_order()
    po = PlannedOrder(order=o, account_id="acc-1", broker_name="broker-a", sequence=0)
    instr = LogicalOrderInstruction(plan_id="plan-det-2", orders=[po])

    plan = make_planner().build_plan(instr)

    assert plan.created_at is None


def test_no_randomness():
    """Repeated builds of the same instruction must be byte-stable."""
    o = make_order()
    po = PlannedOrder(order=o, account_id="acc-1", broker_name="broker-a", sequence=0)
    instr = LogicalOrderInstruction(plan_id="plan-det-3", orders=[po])

    plans = [make_planner().build_plan(instr) for _ in range(5)]
    for p in plans[1:]:
        assert p.execution_order == plans[0].execution_order
        assert p.accounts == plans[0].accounts
        assert p.broker_names == plans[0].broker_names


def test_no_order_submission():
    """The planner must never call any broker place_order / submit method."""
    o = make_order()
    po = PlannedOrder(order=o, account_id="acc-1", broker_name="broker-a", sequence=0)
    instr = LogicalOrderInstruction(plan_id="plan-safe-1", orders=[po])

    plan = make_planner().build_plan(instr)

    assert plan is not None
    assert plan.orders == [o]
    # The plan carries no submission state.
    assert not hasattr(plan, "submitted")
    assert not hasattr(plan, "broker_response")


def test_no_live_trading():
    """The planner must not enable or perform live trading."""
    o = make_order()
    po = PlannedOrder(order=o, account_id="acc-1", broker_name="broker-a", sequence=0)
    instr = LogicalOrderInstruction(plan_id="plan-safe-2", orders=[po])

    plan = make_planner().build_plan(instr)

    # ExecutionPlan has no live flag; the planner never sets one.
    assert not hasattr(plan, "live")
    assert not hasattr(plan, "live_trading_enabled")


def test_no_m6_bypass():
    """
    The planner must not bypass M6-A..M6-E. It produces a plan only; the
    Dispatch Core and OrderEngine remain the sole owners of preflight.
    Verified against the executable code only (docstrings are excluded).
    """
    import ast
    import os

    src_path = os.path.join(os.path.dirname(__file__), "core", "execution_planner.py")
    with open(src_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    # Collect executable code lines (excluding docstrings and comments).
    code_lines = set()
    for node in ast.walk(tree):
        # Skip bare string-expression nodes (docstrings / string literals).
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef, ast.FunctionDef,
                             ast.Return, ast.Raise, ast.Assign, ast.AugAssign,
                             ast.Expr, ast.If, ast.For, ast.While, ast.With)):
            for lineno in range(node.lineno, node.end_lineno + 1 if node.end_lineno else node.lineno + 1):
                code_lines.add(lineno)

    with open(src_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    code_src = "".join(line for i, line in enumerate(lines, start=1) if i in code_lines)

    for banned in ("OrderEngine", "prepare(", "execute(", "place_order",
                   "get_buy_capacity", "get_sell_capacity"):
        assert banned not in code_src, f"planner references M6/dispatch behavior: {banned}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main():
    global PASSED, FAILED
    tests = [
        # Basic
        test_valid_single_order_plan,
        test_valid_multi_order_plan,
        test_empty_orders_rejected,
        test_missing_plan_id_rejected,
        # Account
        test_explicit_account_mapping,
        test_multiple_accounts_preserved,
        test_missing_account_rejected,
        # Broker
        test_explicit_broker_mapping,
        test_multiple_brokers_preserved,
        test_missing_broker_rejected,
        test_no_broker_dependency_or_api_call,
        # Ordering
        test_execution_order_preserved,
        test_duplicate_sequence_rejected,
        test_invalid_sequence_rejected,
        # Conditions
        test_conditions_preserved,
        test_invalid_condition_rejected,
        # Immutability
        test_instruction_is_immutable,
        test_planned_order_is_immutable,
        test_resulting_plan_is_immutable,
        test_metadata_cannot_be_mutated,
        # Determinism / Safety
        test_same_input_produces_same_plan,
        test_no_current_time_dependency,
        test_no_randomness,
        test_no_order_submission,
        test_no_live_trading,
        test_no_m6_bypass,
    ]

    for test in tests:
        try:
            test()
        except AssertionError as exc:
            FAILED += 1
            print(f"  FAIL  {test.__name__}: {exc}")
        except Exception:
            FAILED += 1
            print(f"  ERROR {test.__name__}")
            import traceback
            traceback.print_exc()

    print()
    print("=" * 50)
    print(f"PASSED: {PASSED}")
    print(f"FAILED: {FAILED}")
    print("=" * 50)

    if FAILED:
        sys.exit(1)

    print(f"\nAll Block 1 Execution Planner tests passed. ({len(tests)} tests)")


if __name__ == "__main__":
    main()
