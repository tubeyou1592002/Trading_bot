"""
Block 2 — Dispatch Core unit tests (real ExecutionPlanner path).

Every plan in this file is built through the actual Block 1 planner
(``ExecutionPlanner.build_plan``), which produces ``ExecutionPlan.accounts``
as account_id strings and preserves the per-order Account -> Broker binding
under ``plan.conditions["binding"]``. Tests mock only the broker/provider
boundary and the OrderEngine so no network or broker lifecycle code is
touched.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import Mock, patch

from core.dispatch_core import DispatchCore, DispatchTrace, LowLatencyDispatchCore
from core.dispatch_contracts import ExecutionPlan
from core.execution_planner import (
    ExecutionPlanner,
    LogicalOrderInstruction,
    PlannedOrder,
)
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import BUY, Order


PASSED = 0
FAILED = 0


def make_order(nsc_id="IRO1TEST0001", side=BUY, price=150, quantity=10):
    return Order(
        nsc_id=nsc_id,
        side=side,
        price=price,
        quantity=quantity,
    )


def make_account(account_id="acc-1"):
    acc = Account(
        last_balance=0,
        adjusted_balance_t2=0,
        tradable_balance_t1=1_000_000,
        tradable_balance_t2=1_000_000,
        payable_balance_with_agah_credit_t0=0,
        payable_balance_with_agah_credit_t1=0,
        payable_balance_with_agah_credit_t2=0,
        payable_balance_without_agah_credit_t0=0,
        block=0,
        credit=0,
        settlement_date_t0=None,
        settlement_date_t1=None,
        settlement_date_t2=None,
    )
    acc.account_id = account_id
    return acc


def build_plan(orders, account_ids, broker_names, execution_order=None, plan_id="test-plan"):
    """
    Build an ExecutionPlan through the REAL Block 1 planner so every test
    exercises the actual ExecutionPlanner -> ExecutionPlan -> DispatchCore
    path. The planner produces ``plan.accounts`` as account_id strings and
    preserves the per-order binding under ``plan.conditions["binding"]``.
    """
    if execution_order is None:
        execution_order = list(range(len(orders)))
    pos = [
        PlannedOrder(
            order=order,
            account_id=account_ids[i],
            broker_name=broker_names[i],
            sequence=execution_order[i],
        )
        for i, order in enumerate(orders)
    ]
    return ExecutionPlanner().build_plan(
        LogicalOrderInstruction(plan_id=plan_id, orders=pos)
    )


def attach_accounts(plan, accounts_by_id):
    """
    Attach the bound Account objects to the plan exactly as a caller that
    has resolved them (integration layer / Block 6) would do, preserving the
    dedup order the Planner used (first appearance along execution_order).

    Returns the modified plan.
    """
    seen = []
    for seq in plan.execution_order:
        acc_id = plan.conditions["binding"][seq]["account_id"]
        if acc_id not in seen:
            seen.append(acc_id)
    plan.accounts = [accounts_by_id[a] for a in seen]
    return plan


def make_mock_broker(name="\u0622\u06af\u0627\u0647"):
    broker = Mock()
    broker.name = name
    return broker


def make_mock_provider():
    provider = Mock()
    provider.get_instrument.return_value = (
        Mock(),
        BrokerInstrument(nsc_id="IRO1TEST0001"),
    )
    return provider


def make_broker_manager(broker_names):
    """Return (manager_mock) wired to return unique broker/provider mocks."""
    available = {name: make_mock_broker(name) for name in broker_names}
    providers = {name: make_mock_provider() for name in broker_names}

    manager = Mock()
    manager.get.side_effect = lambda name, _a=available: _a[name]
    manager.get_instrument_provider.side_effect = lambda name, _p=providers: _p[name]
    return manager


def expect(cond, label):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  PASS  {label}")
    else:
        FAILED += 1
        print(f"  FAIL  {label}")


def expect_result(result, success, mode, label):
    expect(
        result.success is success and result.mode == mode,
        f"{label} (success={result.success}, mode={result.mode})",
    )


def ok_result():
    res = Mock()
    res.success = True
    res.sent = False
    res.mode = "READY"
    return res
# ---------------------------------------------------------------------------
# Initialization / empty plan
# ---------------------------------------------------------------------------


def test_dispatch_core_initialization():
    core = DispatchCore()
    expect(core.broker_manager is not None, "broker_manager present")
    expect(core.order_engine is not None, "order_engine present")
    expect(core.live_trading_enabled is False, "live trading stays disabled")


def test_low_latency_alias():
    core = LowLatencyDispatchCore()
    expect(isinstance(core, DispatchCore), "alias subclasses DispatchCore")


def test_dispatch_with_empty_plan():
    core = DispatchCore()
    result = core.dispatch(ExecutionPlan())
    expect_result(result, True, "NO_ORDERS", "empty plan returns NO_ORDERS")
    expect(result.sent is False, "empty plan never sent")
    expect(result.order_count == 0, "empty plan order_count 0")


def test_planner_accounts_are_strings():
    """Actual Block 1 contract: plan.accounts is a list of account_id strings."""
    plan = build_plan(
        [make_order("A"), make_order("B")],
        ["acc-1", "acc-2"],
        ["broker-a", "broker-b"],
    )
    expect(plan.accounts == ["acc-1", "acc-2"], f"accounts={plan.accounts} (strings)")
    expect(all(isinstance(a, str) for a in plan.accounts), "every account entry is a str")


def test_real_planner_preserves_exact_binding():
    """
    The real ExecutionPlanner preserves the per-order account/broker binding
    (Block 2 contract: "derive or preserve the binding from the planning
    stage"), even when execution_order differs from the input order.
    """
    plan = build_plan(
        [make_order("A"), make_order("B")],
        ["acc-1", "acc-2"],
        ["broker-a", "broker-b"],
        execution_order=[1, 0],  # B first
    )
    # Sorted by sequence: seq 0 -> B (acc-2/broker-b), seq 1 -> A (acc-1/broker-a)
    expect(
        plan.conditions["binding"][0]
        == {"account_id": "acc-2", "broker_name": "broker-b"},
        "binding for sequence 0",
    )
    expect(
        plan.conditions["binding"][1]
        == {"account_id": "acc-1", "broker_name": "broker-a"},
        "binding for sequence 1",
    )
    # User conditions (empty here) must remain an independent key.
    expect(plan.conditions["orders"][0] == {}, "user conditions untouched")


# ---------------------------------------------------------------------------
# Single order
# ---------------------------------------------------------------------------


def test_single_order_valid_binding():
    """Real planner plan + resolved Account object -> full dry-run success."""
    core = DispatchCore()
    core.broker_manager = make_broker_manager(["\u0622\u06af\u0627\u0647"])

    order = make_order()
    acc = make_account("acc-1")
    plan = attach_accounts(
        build_plan([order], ["acc-1"], ["\u0622\u06af\u0627\u0647"]),
        {"acc-1": acc},
    )

    calls = []

    def fake_execute(broker, provider, ins_code, order, account, live):
        calls.append((broker.name, ins_code, account, live))
        return ok_result()

    core.order_engine.execute_by_ins_code = Mock(side_effect=fake_execute)

    result = core.dispatch(plan)

    expect_result(result, True, "ALL_PROCESSED", "single order dry-run processed")
    expect(result.order_count == 1, "one order dispatched")
    expect(len(calls) == 1, "execute_by_ins_code called once")
    expect(calls[0][0] == "\u0622\u06af\u0627\u0647", "plan broker used")
    expect(calls[0][1] == "IRO1TEST0001", "ins_code is order.nsc_id")
    expect(calls[0][2] is acc, "plan account object preserved")
    expect(calls[0][3] is False, "live=False forwarded")


def test_single_order_nsc_resolution_used():
    """The instrument is resolved through the provider path per bound broker."""
    core = DispatchCore()
    manager = make_broker_manager(["\u0622\u06af\u0627\u0647"])
    core.broker_manager = manager

    order = make_order()
    acc = make_account("acc-1")
    plan = attach_accounts(
        build_plan([order], ["acc-1"], ["\u0622\u06af\u0627\u0647"]),
        {"acc-1": acc},
    )

    def fake_execute(broker, provider, ins_code, order, account, live):
        return ok_result()

    core.order_engine.execute_by_ins_code = Mock(side_effect=fake_execute)

    core.dispatch(plan)
    manager.get_instrument_provider.assert_called_once_with("\u0622\u06af\u0627\u0647")
# ---------------------------------------------------------------------------
# Multi-order dispatch (multi-account / multi-broker plan)
# ---------------------------------------------------------------------------


def test_dispatch_processes_orders_multi_account_multi_broker():
    """
    Orders bound to different accounts and brokers through the REAL planner
    are dispatched to the exact (order, account, broker) triple.
    """
    core = DispatchCore()
    core.broker_manager = make_broker_manager(["broker-a", "broker-b"])

    o0 = make_order("IRO1TEST0001")
    o1 = make_order("IRO1TEST0002")
    o2 = make_order("IRO1TEST0003")
    acc1 = make_account("acc-1")
    acc2 = make_account("acc-2")

    plan = build_plan(
        [o0, o1, o2],
        ["acc-1", "acc-2", "acc-1"],
        ["broker-a", "broker-b", "broker-b"],
    )
    attach_accounts(plan, {"acc-1": acc1, "acc-2": acc2})

    dispatched = []

    def fake_execute(broker, provider, ins_code, order, account, live):
        dispatched.append((order.nsc_id, account.account_id, broker.name))
        return ok_result()

    core.order_engine.execute_by_ins_code = Mock(side_effect=fake_execute)

    result = core.dispatch(plan)

    expect_result(result, True, "ALL_PROCESSED", "all orders processed (dry-run)")
    expect(result.order_count == 3, "three orders dispatched")
    expect(
        dispatched == [
            ("IRO1TEST0001", "acc-1", "broker-a"),
            ("IRO1TEST0002", "acc-2", "broker-b"),
            ("IRO1TEST0003", "acc-1", "broker-b"),
        ],
        f"exact per-order binding preserved {dispatched}",
    )


def test_execution_order_respected():
    """Orders execute in plan.execution_order, not input order."""
    core = DispatchCore()
    core.broker_manager = make_broker_manager(["\u0622\u06af\u0627\u0647"])

    o1 = make_order("A")
    o2 = make_order("B")
    acc = make_account("acc-1")
    plan = attach_accounts(
        build_plan(
            [o1, o2],
            ["acc-1", "acc-1"],
            ["\u0622\u06af\u0627\u0647", "\u0622\u06af\u0627\u0647"],
            execution_order=[1, 0],  # B first
        ),
        {"acc-1": acc},
    )

    seen = []

    def fake_execute(broker, provider, ins_code, order, account, live):
        seen.append(order.nsc_id)
        return ok_result()

    core.order_engine.execute_by_ins_code = Mock(side_effect=fake_execute)

    result = core.dispatch(plan)
    expect_result(result, True, "ALL_PROCESSED", "orders processed")
    expect(seen == ["B", "A"], f"execution_order respected (got {seen})")


def test_string_only_accounts_fail_closed():
    """
    Real planner output may carry only account_id strings (no Account object).
    The Dispatch Core preserves the binding, invents nothing, and reports a
    fail-closed BLOCKED result instead of executing with a fabricated account.
    """
    core = DispatchCore()
    core.broker_manager = make_broker_manager(["\u0622\u06af\u0627\u0647"])

    order = make_order()
    plan = build_plan([order], ["acc-1"], ["\u0622\u06af\u0627\u0647"])
    expect(plan.accounts == ["acc-1"], "planner produced account_id strings")

    core.order_engine.execute_by_ins_code = Mock(return_value=ok_result())

    result = core.dispatch(plan)

    expect_result(result, False, "BLOCKED", "id-only account blocks fail-closed")
    expect(
        "No Account object bound for account_id=acc-1" in result.message,
        "message reports the preserved account_id binding",
    )
    expect(
        core.order_engine.execute_by_ins_code.call_count == 0,
        "no execution attempted without a resolved Account",
    )


def test_mixed_id_only_and_resolved_accounts():
    """
    A plan with one resolved Account object and one id-only account:
    the resolved order dispatches, the id-only order is BLOCKED, and the
    final verdict is BLOCKED (fail-closed) — never ERROR/FAILED.
    """
    core = DispatchCore()
    core.broker_manager = make_broker_manager(["\u0622\u06af\u0627\u0647"])

    o0 = make_order("A")
    o1 = make_order("B")
    acc1 = make_account("acc-1")
    plan = build_plan(
        [o0, o1],
        ["acc-1", "acc-2"],
        ["\u0622\u06af\u0627\u0647", "\u0622\u06af\u0627\u0647"],
    )
    plan.accounts = [acc1, "acc-2"]  # acc-2 stays id-only

    dispatched = []

    def fake_execute(broker, provider, ins_code, order, account, live):
        dispatched.append(order.nsc_id)
        return ok_result()

    core.order_engine.execute_by_ins_code = Mock(side_effect=fake_execute)

    result = core.dispatch(plan)

    expect_result(result, False, "BLOCKED", "final verdict BLOCKED")
    expect(dispatched == ["A"], f"only the resolved order dispatched {dispatched}")
    expect(
        "No Account object bound for account_id=acc-2" in result.message,
        "message names the id-only account",
    )
# ---------------------------------------------------------------------------
# Fail-closed behavior (mode is always BLOCKED, never ERROR / FAILED)
# ---------------------------------------------------------------------------


def test_execution_exception_fails_closed():
    """An OrderEngine exception -> final BLOCKED (never ERROR/FAILED)."""
    core = DispatchCore()
    core.broker_manager = make_broker_manager(["\u0622\u06af\u0627\u0647"])

    order = make_order()
    acc = make_account("acc-1")
    plan = attach_accounts(
        build_plan([order], ["acc-1"], ["\u0622\u06af\u0627\u0647"]),
        {"acc-1": acc},
    )

    def boom(*args, **kwargs):
        raise RuntimeError("Test error")

    core.order_engine.execute_by_ins_code = Mock(side_effect=boom)

    result = core.dispatch(plan)

    expect_result(result, False, "BLOCKED", "execution exception fails closed")
    expect("Dispatch failed:" in result.message, "message records the error")


def test_dispatch_level_error_fails_closed():
    """A broker-resolution error -> final BLOCKED (never ERROR/FAILED)."""
    core = DispatchCore()
    manager = Mock()
    manager.get.side_effect = ValueError("Unknown broker")
    core.broker_manager = manager

    order = make_order()
    acc = make_account("acc-1")
    plan = attach_accounts(
        build_plan([order], ["acc-1"], ["\u0622\u06af\u0627\u0647"]),
        {"acc-1": acc},
    )

    result = core.dispatch(plan)

    expect_result(result, False, "BLOCKED", "dispatch-level error fails closed")
    expect("Dispatch failed:" in result.message, "message records the error")


def test_missing_binding_fails_closed():
    """A plan without the planner's binding -> BLOCKED, never guessed."""
    core = DispatchCore()
    core.broker_manager = make_broker_manager(["\u0622\u06af\u0627\u0647"])

    order = make_order()
    acc = make_account("acc-1")
    plan = attach_accounts(
        build_plan([order], ["acc-1"], ["\u0622\u06af\u0627\u0647"]),
        {"acc-1": acc},
    )
    # Simulate a malformed plan without the binding the Planner preserves.
    plan.conditions = {"orders": {}}

    result = core.dispatch(plan)
    expect_result(result, False, "BLOCKED", "missing binding fails closed")


def test_no_mode_error_or_failed():
    """
    No dispatched plan may return ERROR or FAILED: every failure path ends
    in mode="BLOCKED" (fail-closed contract).
    """
    # Path 1: execution exception.
    core = DispatchCore()
    core.broker_manager = make_broker_manager(["\u0622\u06af\u0627\u0647"])
    plan = attach_accounts(
        build_plan([make_order()], ["acc-1"], ["\u0622\u06af\u0627\u0647"]),
        {"acc-1": make_account("acc-1")},
    )
    core.order_engine.execute_by_ins_code = Mock(
        side_effect=RuntimeError("boom")
    )
    r1 = core.dispatch(plan)
    expect(r1.mode not in ("ERROR", "FAILED"), f"exception mode={r1.mode}")
    expect(r1.mode == "BLOCKED", "exception maps to BLOCKED")

    # Path 2: id-only account (real planner string output).
    core2 = DispatchCore()
    core2.broker_manager = make_broker_manager(["\u0622\u06af\u0627\u0647"])
    r2 = core2.dispatch(
        build_plan([make_order()], ["acc-1"], ["\u0622\u06af\u0627\u0647"])
    )
    expect(r2.mode not in ("ERROR", "FAILED"), f"id-only mode={r2.mode}")
    expect(r2.mode == "BLOCKED", "id-only account maps to BLOCKED")


# ---------------------------------------------------------------------------
# Traceability
# ---------------------------------------------------------------------------


def test_dispatch_trace_created():
    core = DispatchCore()
    core.broker_manager = make_broker_manager(["\u0622\u06af\u0627\u0647"])

    plan = attach_accounts(
        build_plan([make_order()], ["acc-1"], ["\u0622\u06af\u0627\u0647"]),
        {"acc-1": make_account("acc-1")},
    )

    def fake_execute(broker, provider, ins_code, order, account, live):
        return ok_result()

    core.order_engine.execute_by_ins_code = Mock(side_effect=fake_execute)

    result = core.dispatch(plan)
    expect(
        result.trace_id is not None and len(result.trace_id) > 0,
        "trace_id generated",
    )
# ---------------------------------------------------------------------------
# BrokerDispatchRequest is the real conduit of the dispatch path
# ---------------------------------------------------------------------------


def test_broker_dispatch_request_is_the_real_conduit():
    """
    The BrokerDispatchRequest envelope (Block 0 contract) is the carrier the
    routing stage builds and the execution stage consumes: it must carry the
    exact (broker_name, order, account, live, trace_id) and instrument.
    """
    from core import dispatch_core as dc

    original_request = dc.BrokerDispatchRequest
    captured = []

    def factory(*args, **kwargs):
        captured.append(kwargs)
        return original_request(*args, **kwargs)

    core = DispatchCore()
    core.broker_manager = make_broker_manager(["broker-a"])

    order = make_order()
    acc = make_account("acc-1")
    plan = attach_accounts(
        build_plan([order], ["acc-1"], ["broker-a"]),
        {"acc-1": acc},
    )

    def fake_execute(broker, provider, ins_code, order, account, live):
        return ok_result()

    core.order_engine.execute_by_ins_code = Mock(side_effect=fake_execute)

    with patch.object(dc, "BrokerDispatchRequest", side_effect=factory):
        result = core.dispatch(plan)

    expect(result.success is True, "dispatch succeeded")
    expect(len(captured) == 1, f"one envelope built (got {len(captured)})")
    if captured:
        env = captured[0]
        expect(env["broker_name"] == "broker-a", "envelope broker_name")
        expect(env["order"] is order, "envelope order object")
        expect(env["account"] is acc, "envelope account object")
        expect(env["live"] is False, "envelope live=False")
        expect(env["trace_id"] == result.trace_id, "envelope trace_id")
        expect(env["instrument"] is not None, "envelope instrument resolved")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main():
    global PASSED, FAILED
    tests = [
        test_dispatch_core_initialization,
        test_low_latency_alias,
        test_dispatch_with_empty_plan,
        test_planner_accounts_are_strings,
        test_real_planner_preserves_exact_binding,
        test_single_order_valid_binding,
        test_single_order_nsc_resolution_used,
        test_dispatch_processes_orders_multi_account_multi_broker,
        test_execution_order_respected,
        test_string_only_accounts_fail_closed,
        test_mixed_id_only_and_resolved_accounts,
        test_execution_exception_fails_closed,
        test_dispatch_level_error_fails_closed,
        test_missing_binding_fails_closed,
        test_no_mode_error_or_failed,
        test_dispatch_trace_created,
        test_broker_dispatch_request_is_the_real_conduit,
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

    print(f"\nAll Block 2 Dispatch Core tests passed. ({len(tests)} tests)")


if __name__ == "__main__":
    main()