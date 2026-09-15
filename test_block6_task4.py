"""
Block 6 — Task 6.4: Multi-Account Execution tests.

Architectural principle under test:

    ExecutionPlan (one plan)
        -> contains many orders, each bound to its own account and broker
        -> DispatchCore dispatches each order through the existing OrderEngine path
        -> Account identity, symbol, quantity, price, and broker route stay isolated

The ExecutionPlanner (Block 1) decides Account -> Broker and carries it in
``ExecutionPlan.account_routes``. DispatchCore consumes that decision and
resolves the Broker from BrokerManager. Dispatch NEVER picks the broker from
Symbol, Instrument, order position, or guesses.

Proven scenarios (offline, stubs only, live=False everywhere):

    S1  Two accounts, two symbols, two brokers -> both dispatched
    S2  Multiple orders for one account -> all processed independently
    S3  Same symbol, different accounts -> no cross-contamination
    S4  Different accounts, same broker -> accounts stay independent
    S5  One order fails in engine -> subsequent orders still dispatched
    S6  Plan-level failure -> entire plan BLOCKED, no order dispatched
    S7  Execution order preserved -> calls match plan.execution_order
    S8  Data isolation -> exact (order, account, broker, symbol, qty, price)
    S9  Account route integrity -> all orders for one account use its route
    S10 All tests live=False, stub/mock only -> no real API calls

No network, no real broker, no real order.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import Mock, patch

from core import dispatch_core as dc
from core.dispatch_core import DispatchCore
from core.dispatch_contracts import ExecutionPlan
from core.execution_planner import (
    ExecutionPlanner,
    LogicalOrderInstruction,
    PlannedOrder,
)
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import BUY, Order


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACC1 = "ACC-1"
ACC2 = "ACC-2"
BROKER_A = "broker-a"
BROKER_B = "broker-b"
SYM_A = "SYM-A"
SYM_B = "SYM-B"
SYM_C = "SYM-C"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASSED = 0
FAILED = 0


def make_order(nsc_id=SYM_A, side=BUY, price=150, quantity=10):
    return Order(nsc_id=nsc_id, side=side, price=price, quantity=quantity)


def make_account(account_id):
    return Account(
        account_id=account_id,
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


def build_plan(
    orders,
    account_ids,
    broker_names,
    execution_order=None,
    plan_id="t64-plan",
):
    """Build an ExecutionPlan through the REAL Block 1 planner."""
    if execution_order is None:
        execution_order = list(range(len(orders)))
    pos = [
        PlannedOrder(
            order=orders[i],
            account_id=account_ids[i],
            broker_name=broker_names[i],
            sequence=execution_order[i],
        )
        for i in range(len(orders))
    ]
    return ExecutionPlanner().build_plan(
        LogicalOrderInstruction(plan_id=plan_id, orders=pos)
    )


def attach_accounts(plan, accounts_by_id):
    seen = []
    for seq in plan.execution_order:
        acc_id = plan.conditions["binding"][seq]["account_id"]
        if acc_id not in seen:
            seen.append(acc_id)
    plan.accounts = [accounts_by_id[a] for a in seen]
    return plan


def _mock_broker(name):
    broker = Mock()
    broker.name = name
    return broker


def _mock_provider(nsc_id=SYM_A):
    provider = Mock()
    provider.get_instrument.return_value = (
        Mock(),
        BrokerInstrument(nsc_id=nsc_id),
    )
    return provider


def make_broker_manager(broker_names):
    available = {name: _mock_broker(name) for name in broker_names}
    providers = {name: _mock_provider() for name in broker_names}
    manager = Mock()
    manager.get.side_effect = lambda name, _a=available: _a[name]
    manager.get_instrument_provider.side_effect = (
        lambda name, _p=providers: _p[name]
    )
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


def record_engine_calls(core):
    """Replace execute_by_ins_code with a recorder, return the calls list."""
    calls = []

    def fake_execute(broker, provider, ins_code, order, account, live):
        calls.append(
            {
                "broker": broker,
                "provider": provider,
                "ins_code": ins_code,
                "order": order,
                "account": account,
                "live": live,
            }
        )
        return ok_result()

    core.order_engine.execute_by_ins_code = Mock(side_effect=fake_execute)
    return calls


def call_for(calls, order_obj):
    for c in calls:
        if c["order"] is order_obj:
            return c
    return None


# ---------------------------------------------------------------------------
# S1 — Two Accounts / Two Symbols / Two Brokers
# ---------------------------------------------------------------------------

def test_s1_two_accounts_two_symbols_two_brokers():
    print("S1: Account 1 -> Symbol A -> Broker A, Account 2 -> Symbol B -> Broker B")
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_B, price=200, quantity=7)
    acc1 = make_account(ACC1)
    acc2 = make_account(ACC2)

    plan = build_plan(
        [order_a, order_b],
        [ACC1, ACC2],
        [BROKER_A, BROKER_B],
    )
    attach_accounts(plan, {ACC1: acc1, ACC2: acc2})

    expect(plan.account_routes == {ACC1: BROKER_A, ACC2: BROKER_B}, "S1 routes")
    expect(len(plan.orders) == 2, "S1 two orders in one plan")

    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A, BROKER_B])
    calls = record_engine_calls(core)

    result = core.dispatch(plan)

    expect_result(result, True, "ALL_PROCESSED", "S1 dispatch returns ALL_PROCESSED")
    expect(len(calls) == 2, "S1 exactly two engine calls")
    call_a = call_for(calls, order_a)
    call_b = call_for(calls, order_b)
    expect(call_a is not None and call_b is not None, "S1 both orders dispatched")
    expect(call_a["account"] is acc1, "S1 order_a -> acc1")
    expect(call_a["broker"].name == BROKER_A, "S1 order_a -> broker-a")
    expect(call_b["account"] is acc2, "S1 order_b -> acc2")
    expect(call_b["broker"].name == BROKER_B, "S1 order_b -> broker-b")
    expect(call_a["live"] is False and call_b["live"] is False, "S1 live=False")
    print()


# ---------------------------------------------------------------------------
# S2 — Multiple Orders for One Account
# ---------------------------------------------------------------------------

def test_s2_multiple_orders_one_account():
    print("S2: Account 1 -> Symbol A, Account 1 -> Symbol B, Account 2 -> Symbol C")
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_B, price=200, quantity=7)
    order_c = make_order(SYM_C, price=300, quantity=9)
    acc1 = make_account(ACC1)
    acc2 = make_account(ACC2)

    plan = build_plan(
        [order_a, order_b, order_c],
        [ACC1, ACC1, ACC2],
        [BROKER_A, BROKER_A, BROKER_B],
    )
    attach_accounts(plan, {ACC1: acc1, ACC2: acc2})

    expect(plan.account_routes == {ACC1: BROKER_A, ACC2: BROKER_B}, "S2 routes")

    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A, BROKER_B])
    calls = record_engine_calls(core)

    result = core.dispatch(plan)

    expect_result(result, True, "ALL_PROCESSED", "S2 dispatch returns ALL_PROCESSED")
    expect(len(calls) == 3, "S2 exactly three engine calls")
    call_a = call_for(calls, order_a)
    call_b = call_for(calls, order_b)
    call_c = call_for(calls, order_c)
    expect(call_a is not None and call_b is not None and call_c is not None, "S2 all dispatched")
    expect(call_a["account"] is acc1 and call_b["account"] is acc1, "S2 two orders -> acc1")
    expect(call_a["broker"].name == BROKER_A and call_b["broker"].name == BROKER_A, "S2 both acc1 orders -> broker-a")
    expect(call_c["account"] is acc2 and call_c["broker"].name == BROKER_B, "S2 order_c -> acc2/broker-b")
    print()


# ---------------------------------------------------------------------------
# S3 — Same Symbol / Different Accounts
# ---------------------------------------------------------------------------

def test_s3_same_symbol_different_accounts():
    print("S3: Account 1 -> Symbol A -> Broker A, Account 2 -> Symbol A -> Broker B")
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_A, price=200, quantity=7)
    acc1 = make_account(ACC1)
    acc2 = make_account(ACC2)

    plan = build_plan(
        [order_a, order_b],
        [ACC1, ACC2],
        [BROKER_A, BROKER_B],
    )
    attach_accounts(plan, {ACC1: acc1, ACC2: acc2})

    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A, BROKER_B])
    calls = record_engine_calls(core)

    result = core.dispatch(plan)

    expect_result(result, True, "ALL_PROCESSED", "S3 dispatch returns ALL_PROCESSED")
    expect(len(calls) == 2, "S3 exactly two engine calls")
    call_a = call_for(calls, order_a)
    call_b = call_for(calls, order_b)
    expect(call_a is not None and call_b is not None, "S3 both orders dispatched")
    expect(call_a["account"] is acc1, "S3 order_a -> acc1")
    expect(call_a["broker"].name == BROKER_A, "S3 order_a -> broker-a")
    expect(call_b["account"] is acc2, "S3 order_b -> acc2")
    expect(call_b["broker"].name == BROKER_B, "S3 order_b -> broker-b")
    expect(call_a["ins_code"] == SYM_A and call_b["ins_code"] == SYM_A, "S3 same symbol preserved")
    print()


# ---------------------------------------------------------------------------
# S4 — Different Accounts / Same Broker
# ---------------------------------------------------------------------------

def test_s4_different_accounts_same_broker():
    print("S4: Account 1 -> Broker A, Account 2 -> Broker A (accounts stay independent)")
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_B, price=200, quantity=7)
    acc1 = make_account(ACC1)
    acc2 = make_account(ACC2)

    plan = build_plan(
        [order_a, order_b],
        [ACC1, ACC2],
        [BROKER_A, BROKER_A],
    )
    attach_accounts(plan, {ACC1: acc1, ACC2: acc2})

    expect(plan.account_routes == {ACC1: BROKER_A, ACC2: BROKER_A}, "S4 routes")

    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A])
    calls = record_engine_calls(core)

    result = core.dispatch(plan)

    expect_result(result, True, "ALL_PROCESSED", "S4 dispatch returns ALL_PROCESSED")
    expect(len(calls) == 2, "S4 exactly two engine calls")
    call_a = call_for(calls, order_a)
    call_b = call_for(calls, order_b)
    expect(call_a is not None and call_b is not None, "S4 both orders dispatched")
    expect(call_a["account"] is acc1, "S4 order_a -> acc1")
    expect(call_b["account"] is acc2, "S4 order_b -> acc2")
    expect(call_a["broker"] is call_b["broker"], "S4 same broker instance")
    expect(call_a["broker"].name == BROKER_A and call_b["broker"].name == BROKER_A, "S4 broker-a used")
    print()


# ---------------------------------------------------------------------------
# S5 — Order Failure Isolation
# ---------------------------------------------------------------------------

def test_s5_order_failure_isolation():
    print("S5: Order 1 fails in engine -> Order 2 still dispatched")
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_B, price=200, quantity=7)
    acc1 = make_account(ACC1)
    acc2 = make_account(ACC2)

    plan = build_plan(
        [order_a, order_b],
        [ACC1, ACC2],
        [BROKER_A, BROKER_B],
    )
    attach_accounts(plan, {ACC1: acc1, ACC2: acc2})

    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A, BROKER_B])

    dispatched = []
    fail_first = [True]

    def fake_execute(broker, provider, ins_code, order, account, live):
        dispatched.append((order.nsc_id, account.account_id, broker.name))
        if fail_first[0]:
            fail_first[0] = False
            res = Mock()
            res.success = False
            res.sent = False
            res.mode = "BLOCKED"
            res.order = order
            res.broker_name = broker.name
            res.message = "Simulated order failure"
            return res
        return ok_result()

    core.order_engine.execute_by_ins_code = Mock(side_effect=fake_execute)

    result = core.dispatch(plan)

    expect(len(dispatched) == 2, "S5 both orders dispatched despite first failure")
    expect(dispatched == [("SYM-A", ACC1, BROKER_A), ("SYM-B", ACC2, BROKER_B)], "S5 exact dispatch order")
    expect(result.success is False, "S5 final verdict is BLOCKED (fail-closed)")
    expect(result.mode == "BLOCKED", "S5 final mode is BLOCKED")
    print()


# ---------------------------------------------------------------------------
# S6 — Plan-level Failure
# ---------------------------------------------------------------------------

def test_s6_plan_level_failure():
    print("S6: Missing account route -> entire plan BLOCKED, no order dispatched")
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_B, price=200, quantity=7)
    acc1 = make_account(ACC1)
    acc2 = make_account(ACC2)

    plan = build_plan(
        [order_a, order_b],
        [ACC1, ACC2],
        [BROKER_A, BROKER_B],
    )
    attach_accounts(plan, {ACC1: acc1, ACC2: acc2})
    plan.account_routes = {}  # remove the route -> plan-level failure

    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A, BROKER_B])
    calls = record_engine_calls(core)

    result = core.dispatch(plan)

    expect_result(result, False, "BLOCKED", "S6 entire plan BLOCKED")
    expect(len(calls) == 0, "S6 no OrderEngine call for any order")
    print()


# ---------------------------------------------------------------------------
# S7 — Execution Order
# ---------------------------------------------------------------------------

def test_s7_execution_order():
    print("S7: Engine calls match plan.execution_order exactly")
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_B, price=200, quantity=7)
    order_c = make_order(SYM_C, price=300, quantity=9)
    acc1 = make_account(ACC1)
    acc2 = make_account(ACC2)

    plan = build_plan(
        [order_a, order_b, order_c],
        [ACC1, ACC2, ACC1],
        [BROKER_A, BROKER_B, BROKER_A],
        execution_order=[2, 0, 1],  # C(seq2), A(seq0), B(seq1) -> sorted: seq0=B, seq1=C, seq2=A
    )
    attach_accounts(plan, {ACC1: acc1, ACC2: acc2})

    expect(plan.execution_order == [0, 1, 2], "S7 execution_order sorted ascending")

    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A, BROKER_B])
    calls = record_engine_calls(core)

    result = core.dispatch(plan)

    expect_result(result, True, "ALL_PROCESSED", "S7 dispatch returns ALL_PROCESSED")
    expect(
        [c["ins_code"] for c in calls] == [SYM_B, SYM_C, SYM_A],
        "S7 call order matches sorted execution_order",
    )
    expect(
        [c["account"].account_id for c in calls] == [ACC2, ACC1, ACC1],
        "S7 accounts match sorted execution_order",
    )
    expect(
        [c["broker"].name for c in calls] == [BROKER_B, BROKER_A, BROKER_A],
        "S7 brokers match sorted execution_order",
    )
    print()


# ---------------------------------------------------------------------------
# S8 — Data Isolation
# ---------------------------------------------------------------------------

def test_s8_data_isolation():
    print("S8: Each engine call carries exact (order, account, broker, symbol, qty, price)")
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_B, price=200, quantity=7)
    order_c = make_order(SYM_C, price=300, quantity=9)
    acc1 = make_account(ACC1)
    acc2 = make_account(ACC2)

    plan = build_plan(
        [order_a, order_b, order_c],
        [ACC1, ACC2, ACC1],
        [BROKER_A, BROKER_B, BROKER_A],
    )
    attach_accounts(plan, {ACC1: acc1, ACC2: acc2})

    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A, BROKER_B])
    calls = record_engine_calls(core)

    result = core.dispatch(plan)

    expect(len(calls) == 3, "S8 exactly three engine calls")
    call_a = call_for(calls, order_a)
    call_b = call_for(calls, order_b)
    call_c = call_for(calls, order_c)
    expect(call_a is not None and call_b is not None and call_c is not None, "S8 all calls recorded")
    if call_a is not None:
        expect(call_a["order"] is order_a, "S8 order_a object exact")
        expect(call_a["order"].nsc_id == SYM_A, "S8 order_a symbol")
        expect(call_a["order"].price == 100 and call_a["order"].quantity == 5, "S8 order_a price/qty")
        expect(call_a["account"] is acc1, "S8 order_a account")
        expect(call_a["broker"].name == BROKER_A, "S8 order_a broker")
    if call_b is not None:
        expect(call_b["order"] is order_b, "S8 order_b object exact")
        expect(call_b["order"].nsc_id == SYM_B, "S8 order_b symbol")
        expect(call_b["order"].price == 200 and call_b["order"].quantity == 7, "S8 order_b price/qty")
        expect(call_b["account"] is acc2, "S8 order_b account")
        expect(call_b["broker"].name == BROKER_B, "S8 order_b broker")
    if call_c is not None:
        expect(call_c["order"] is order_c, "S8 order_c object exact")
        expect(call_c["order"].nsc_id == SYM_C, "S8 order_c symbol")
        expect(call_c["order"].price == 300 and call_c["order"].quantity == 9, "S8 order_c price/qty")
        expect(call_c["account"] is acc1, "S8 order_c account")
        expect(call_c["broker"].name == BROKER_A, "S8 order_c broker")
    print()


# ---------------------------------------------------------------------------
# S9 — Account Route Integrity
# ---------------------------------------------------------------------------

def test_s9_account_route_integrity():
    print("S9: All orders for one account use that account's route")
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_B, price=200, quantity=7)
    order_c = make_order(SYM_C, price=300, quantity=9)
    acc1 = make_account(ACC1)
    acc2 = make_account(ACC2)

    plan = build_plan(
        [order_a, order_b, order_c],
        [ACC1, ACC1, ACC2],
        [BROKER_A, BROKER_A, BROKER_B],
    )
    attach_accounts(plan, {ACC1: acc1, ACC2: acc2})

    expect(plan.account_routes == {ACC1: BROKER_A, ACC2: BROKER_B}, "S9 routes")

    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A, BROKER_B])
    calls = record_engine_calls(core)

    result = core.dispatch(plan)

    expect(len(calls) == 3, "S9 exactly three engine calls")
    call_a = call_for(calls, order_a)
    call_b = call_for(calls, order_b)
    call_c = call_for(calls, order_c)
    expect(call_a["account"] is acc1 and call_b["account"] is acc1, "S9 acc1 orders -> acc1")
    expect(call_c["account"] is acc2, "S9 acc2 order -> acc2")
    expect(call_a["broker"].name == BROKER_A and call_b["broker"].name == BROKER_A, "S9 acc1 orders -> broker-a")
    expect(call_c["broker"].name == BROKER_B, "S9 acc2 order -> broker-b")
    print()


# ---------------------------------------------------------------------------
# S10 — Dry Run
# ---------------------------------------------------------------------------

def test_s10_all_live_false():
    print("S10: All tests use live=False, no real broker API calls")
    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_B, price=200, quantity=7)
    acc1 = make_account(ACC1)
    acc2 = make_account(ACC2)

    plan = build_plan(
        [order_a, order_b],
        [ACC1, ACC2],
        [BROKER_A, BROKER_B],
    )
    attach_accounts(plan, {ACC1: acc1, ACC2: acc2})

    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A, BROKER_B])
    calls = record_engine_calls(core)

    result = core.dispatch(plan)

    expect_result(result, True, "ALL_PROCESSED", "S10 dispatch returns ALL_PROCESSED")
    expect(all(c["live"] is False for c in calls), "S10 live=False on every call")
    expect(core.live_trading_enabled is False, "S10 live trading stays disabled")
    print()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    global PASSED, FAILED
    tests = [
        test_s1_two_accounts_two_symbols_two_brokers,
        test_s2_multiple_orders_one_account,
        test_s3_same_symbol_different_accounts,
        test_s4_different_accounts_same_broker,
        test_s5_order_failure_isolation,
        test_s6_plan_level_failure,
        test_s7_execution_order,
        test_s8_data_isolation,
        test_s9_account_route_integrity,
        test_s10_all_live_false,
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

    print(
        f"\nAll Block 6 Task 4 Multi-Account Execution tests passed. "
        f"({len(tests)} scenarios)"
    )


if __name__ == "__main__":
    main()
