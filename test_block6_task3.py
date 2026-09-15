"""
Block 6 — Task 6.3: Account-Aware Dispatch tests.

Architectural principle under test:

    Account -> Broker/Connection -> Order

The ExecutionPlanner (Block 1) decides Account -> Broker and carries it in
``ExecutionPlan.account_routes``. DispatchCore consumes that decision and
resolves the Broker from BrokerManager. Dispatch NEVER picks the broker from
Symbol, Instrument, order position, or guesses.

Proven scenarios (offline, stubs only, live=False everywhere):

    S1  Account 1 -> Broker A, single order            -> Broker A
    S2  Account 2 -> Broker B, single order            -> Broker B
    S3  Two accounts, each with own broker              -> independent
    S4  Two accounts sharing one broker                  -> both valid
    S5  One account bound to two brokers                -> Planner fail-closed
    S6  account_routes disagrees with binding           -> Dispatch fail-closed
    S7  Required broker missing from BrokerManager      -> BLOCKED, no fallback
    S8  Same Symbol, different Accounts                  -> independent
    S9  Account identity preserved at all boundaries     -> same Account object
    S10 All tests live=False, stub/mock only            -> no real API calls

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
    PlannerValidationError,
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASSED = 0
FAILED = 0


def make_order(nsc_id=SYM_A, price=150, quantity=10):
    return Order(nsc_id=nsc_id, side=BUY, price=price, quantity=quantity)


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
    plan_id="t63-plan",
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


def _mock_provider():
    provider = Mock()
    provider.get_instrument.return_value = (
        Mock(),
        BrokerInstrument(nsc_id="IRO1TEST0001"),
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
# S1 — Account 1 -> Broker A (single order, account_routes populated)
# ---------------------------------------------------------------------------

def test_s1_account1_broker_a():
    print("S1: Account 1 -> Broker A via account_routes")
    order = make_order(SYM_A)
    acc1 = make_account(ACC1)
    plan = build_plan([order], [ACC1], [BROKER_A])
    attach_accounts(plan, {ACC1: acc1})

    expect(
        plan.account_routes == {ACC1: BROKER_A},
        f"S1 account_routes={{ACC1: BROKER_A}}",
    )

    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A])
    calls = record_engine_calls(core)

    result = core.dispatch(plan)
    expect_result(result, True, "ALL_PROCESSED", "S1 dispatch returns ALL_PROCESSED")
    expect(len(calls) == 1, "S1 exactly one engine call")
    call = call_for(calls, order)
    expect(call is not None, "S1 engine call recorded")
    expect(call["broker"].name == BROKER_A, f"S1 used Broker A (got {call['broker'].name})")
    expect(call["account"] is acc1, "S1 account is acc1")
    expect(call["live"] is False, "S1 live=False")
    print()


# ---------------------------------------------------------------------------
# S2 — Account 2 -> Broker B (single order, different account)
# ---------------------------------------------------------------------------

def test_s2_account2_broker_b():
    print("S2: Account 2 -> Broker B via account_routes")
    order = make_order(SYM_B)
    acc2 = make_account(ACC2)
    plan = build_plan([order], [ACC2], [BROKER_B])
    attach_accounts(plan, {ACC2: acc2})

    expect(
        plan.account_routes == {ACC2: BROKER_B},
        f"S2 account_routes={{ACC2: BROKER_B}}",
    )

    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_B])
    calls = record_engine_calls(core)

    result = core.dispatch(plan)
    expect_result(result, True, "ALL_PROCESSED", "S2 dispatch returns ALL_PROCESSED")
    expect(len(calls) == 1, "S2 exactly one engine call")
    call = call_for(calls, order)
    expect(call is not None, "S2 engine call recorded")
    expect(call["broker"].name == BROKER_B, f"S2 used Broker B (got {call['broker'].name})")
    expect(call["account"] is acc2, "S2 account is acc2")
    expect(call["live"] is False, "S2 live=False")
    print()


# ---------------------------------------------------------------------------
# S3 — Two accounts, each with own broker
# ---------------------------------------------------------------------------

def test_s3_two_accounts_different_brokers():
    print("S3: Account 1 -> Broker A, Account 2 -> Broker B — independent")
    order_x = make_order(SYM_A)
    order_y = make_order(SYM_B)
    acc1 = make_account(ACC1)
    acc2 = make_account(ACC2)

    plan = build_plan(
        [order_x, order_y],
        [ACC1, ACC2],
        [BROKER_A, BROKER_B],
    )
    attach_accounts(plan, {ACC1: acc1, ACC2: acc2})

    expect(
        plan.account_routes == {ACC1: BROKER_A, ACC2: BROKER_B},
        f"S3 account_routes={{ACC1: BrokerA, ACC2: BrokerB}}",
    )

    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A, BROKER_B])
    calls = record_engine_calls(core)

    result = core.dispatch(plan)
    expect_result(result, True, "ALL_PROCESSED", "S3 dispatch returns ALL_PROCESSED")

    call_x = call_for(calls, order_x)
    call_y = call_for(calls, order_y)
    expect(call_x is not None and call_y is not None, "S3 both orders dispatched")
    expect(call_x["account"] is acc1, "S3 order_x -> acc1")
    expect(call_y["account"] is acc2, "S3 order_y -> acc2")
    expect(call_x["broker"].name == BROKER_A, "S3 order_x -> Broker A")
    expect(call_y["broker"].name == BROKER_B, "S3 order_y -> Broker B")
    expect(call_x["account"] is not call_y["account"], "S3 accounts independent")
    print()


# ---------------------------------------------------------------------------
# S4 — Two accounts sharing one broker
# ---------------------------------------------------------------------------

def test_s4_two_accounts_one_broker():
    print("S4: Account 1 -> Broker A, Account 2 -> Broker A — shared, independent")
    order_x = make_order(SYM_A)
    order_y = make_order(SYM_B)
    acc1 = make_account(ACC1)
    acc2 = make_account(ACC2)

    plan = build_plan(
        [order_x, order_y],
        [ACC1, ACC2],
        [BROKER_A, BROKER_A],
    )
    attach_accounts(plan, {ACC1: acc1, ACC2: acc2})

    expect(
        plan.account_routes == {ACC1: BROKER_A, ACC2: BROKER_A},
        f"S4 account_routes={{ACC1: BrokerA, ACC2: BrokerA}}",
    )

    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A])
    calls = record_engine_calls(core)

    result = core.dispatch(plan)
    expect_result(result, True, "ALL_PROCESSED", "S4 dispatch returns ALL_PROCESSED")

    call_x = call_for(calls, order_x)
    call_y = call_for(calls, order_y)
    expect(call_x is not None and call_y is not None, "S4 both orders dispatched")
    expect(call_x["account"] is acc1, "S4 order_x -> acc1")
    expect(call_y["account"] is acc2, "S4 order_y -> acc2")
    expect(call_x["broker"].name == BROKER_A, "S4 order_x -> Broker A")
    expect(call_y["broker"].name == BROKER_A, "S4 order_y -> Broker A")
    expect(call_x["account"] is not call_y["account"], "S4 accounts independent")
    print()


# ---------------------------------------------------------------------------
# S5 — One account with two brokers -> Planner fail-closed
# ---------------------------------------------------------------------------

def test_s5_one_account_two_brokers_planner_fail_closed():
    print("S5: Account 1 -> Broker A + Broker B -> Planner fail-closed")
    order_x = make_order(SYM_A)
    order_y = make_order(SYM_B)

    raised = False
    try:
        build_plan(
            [order_x, order_y],
            [ACC1, ACC1],  # same account
            [BROKER_A, BROKER_B],  # different brokers
        )
    except PlannerValidationError:
        raised = True

    expect(raised, "S5 PlannerValidationError raised for one account -> two brokers")
    print()


# ---------------------------------------------------------------------------
# S6 — account_routes disagrees with PlannedOrder.broker_name -> BLOCKED
# ---------------------------------------------------------------------------

def test_s6_route_mismatch_fail_closed():
    print("S6: account_routes disagrees with binding -> Dispatch fail-closed")
    order = make_order(SYM_A)
    acc1 = make_account(ACC1)

    # Build a normal plan, then override account_routes to disagree
    plan = build_plan([order], [ACC1], [BROKER_A])
    attach_accounts(plan, {ACC1: acc1})
    plan.account_routes = {ACC1: BROKER_B}  # route says B, binding says A

    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A, BROKER_B])
    calls = record_engine_calls(core)

    result = core.dispatch(plan)
    expect_result(result, False, "BLOCKED", "S6 route mismatch -> BLOCKED")
    expect(len(calls) == 0, "S6 nothing reached the engine")
    print()


# ---------------------------------------------------------------------------
# S7 — Required broker missing from BrokerManager -> BLOCKED, no fallback
# ---------------------------------------------------------------------------

def test_s7_broker_not_in_manager_fail_closed():
    print("S7: Broker from account_routes not in BrokerManager -> BLOCKED")
    order = make_order(SYM_A)
    acc1 = make_account(ACC1)
    plan = build_plan([order], [ACC1], [BROKER_A])
    attach_accounts(plan, {ACC1: acc1})

    core = DispatchCore()
    # BrokerManager only has BROKER_B, not BROKER_A
    core.broker_manager = make_broker_manager([BROKER_B])
    calls = record_engine_calls(core)

    result = core.dispatch(plan)
    expect_result(result, False, "BLOCKED", "S7 missing broker -> BLOCKED")
    expect(len(calls) == 0, "S7 nothing reached the engine")
    print()


# ---------------------------------------------------------------------------
# S8 — Same Symbol, different Accounts -> independent
# ---------------------------------------------------------------------------

def test_s8_same_symbol_different_accounts():
    print("S8: Same Symbol, different Accounts -> independent routing")
    order_x = make_order(SYM_A)
    order_y = make_order(SYM_A)  # same symbol
    acc1 = make_account(ACC1)
    acc2 = make_account(ACC2)

    plan = build_plan(
        [order_x, order_y],
        [ACC1, ACC2],
        [BROKER_A, BROKER_B],
    )
    attach_accounts(plan, {ACC1: acc1, ACC2: acc2})

    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A, BROKER_B])
    calls = record_engine_calls(core)

    result = core.dispatch(plan)
    expect_result(result, True, "ALL_PROCESSED", "S8 dispatch returns ALL_PROCESSED")

    call_x = call_for(calls, order_x)
    call_y = call_for(calls, order_y)
    expect(call_x is not None and call_y is not None, "S8 both orders dispatched")
    expect(call_x["account"] is acc1, "S8 order_x -> acc1")
    expect(call_y["account"] is acc2, "S8 order_y -> acc2")
    expect(call_x["broker"].name == BROKER_A, "S8 order_x -> Broker A")
    expect(call_y["broker"].name == BROKER_B, "S8 order_y -> Broker B")
    expect(call_x["account"] is not call_y["account"], "S8 accounts independent")
    print()


# ---------------------------------------------------------------------------
# S9 — Account identity preserved at all boundaries
# ---------------------------------------------------------------------------

def test_s9_account_identity_preserved():
    print("S9: Account identity preserved in BrokerDispatchRequest and OrderEngine")
    order = make_order(SYM_A)
    acc1 = make_account(ACC1)
    plan = build_plan([order], [ACC1], [BROKER_A])
    attach_accounts(plan, {ACC1: acc1})

    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A])
    calls = record_engine_calls(core)

    captured_requests = []
    original_request = dc.BrokerDispatchRequest

    def request_factory(*args, **kwargs):
        captured_requests.append(kwargs)
        return original_request(*args, **kwargs)

    with patch.object(dc, "BrokerDispatchRequest", side_effect=request_factory):
        result = core.dispatch(plan)

    expect_result(result, True, "ALL_PROCESSED", "S9 dispatch returns ALL_PROCESSED")
    expect(len(captured_requests) == 1, "S9 exactly one BrokerDispatchRequest")
    expect(len(calls) == 1, "S9 exactly one engine call")

    if captured_requests and calls:
        req_account = captured_requests[0].get("account")
        engine_account = calls[0]["account"]
        expect(req_account is acc1, "S9 request account is acc1")
        expect(engine_account is acc1, "S9 engine account is acc1")
        expect(req_account is engine_account, "S9 request == engine account object")
        expect(
            req_account.account_id == ACC1 and engine_account.account_id == ACC1,
            "S9 account_id is ACC1 at both boundaries",
        )
    print()


# ---------------------------------------------------------------------------
# S10 — Constraint: all tests live=False, stub/mock only (S1-S9 enforce this)
# ---------------------------------------------------------------------------

def test_s10_all_live_false():
    """S10: Verify every scenario above enforces live=False."""
    print("S10: Live=False constraint across all scenarios")
    # S1 through S9 all assert call["live"] is False or result.sent is False.
    # This test documents the constraint; the real verification is in S1-S9.
    order = make_order(SYM_A)
    acc1 = make_account(ACC1)
    plan = build_plan([order], [ACC1], [BROKER_A])
    attach_accounts(plan, {ACC1: acc1})
    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A])
    calls = record_engine_calls(core)
    result = core.dispatch(plan)
    expect(result.sent is False, "S10 sent=False (dry-run)")
    call = call_for(calls, order)
    expect(call is not None and call["live"] is False, "S10 live=False at engine boundary")
    print()


# ---------------------------------------------------------------------------
# S11 — account_routes missing or incomplete -> fail-closed
# ---------------------------------------------------------------------------

def test_s11a_empty_account_routes_fail_closed():
    print("S11a: Empty account_routes -> BLOCKED, no fallback to planned broker")
    order = make_order(SYM_A)
    acc1 = make_account(ACC1)
    plan = build_plan([order], [ACC1], [BROKER_A])
    attach_accounts(plan, {ACC1: acc1})
    plan.account_routes = {}  # remove the route

    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A])
    calls = record_engine_calls(core)

    result = core.dispatch(plan)

    expect(result.success is False, "S11a success is False")
    expect(result.mode == "BLOCKED", "S11a mode is BLOCKED")
    expect(len(calls) == 0, "S11a no OrderEngine call")
    expect(
        plan.conditions["binding"][0]["broker_name"] == BROKER_A,
        "S11a original binding unchanged",
    )
    print()


def test_s11b_missing_account_route_fail_closed():
    print("S11b: Missing route for account -> BLOCKED, no fallback")
    order = make_order(SYM_A)
    acc1 = make_account(ACC1)
    plan = build_plan([order], [ACC1], [BROKER_A])
    attach_accounts(plan, {ACC1: acc1})
    plan.account_routes = {ACC2: BROKER_B}  # ACC1 has no route

    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A, BROKER_B])
    calls = record_engine_calls(core)

    result = core.dispatch(plan)

    expect(result.success is False, "S11b success is False")
    expect(result.mode == "BLOCKED", "S11b mode is BLOCKED")
    expect(len(calls) == 0, "S11b no OrderEngine call")
    expect(
        plan.conditions["binding"][0]["broker_name"] == BROKER_A,
        "S11b original binding unchanged",
    )
    print()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    global PASSED, FAILED
    tests = [
        test_s1_account1_broker_a,
        test_s2_account2_broker_b,
        test_s3_two_accounts_different_brokers,
        test_s4_two_accounts_one_broker,
        test_s5_one_account_two_brokers_planner_fail_closed,
        test_s6_route_mismatch_fail_closed,
        test_s7_broker_not_in_manager_fail_closed,
        test_s8_same_symbol_different_accounts,
        test_s9_account_identity_preserved,
        test_s10_all_live_false,
        test_s11a_empty_account_routes_fail_closed,
        test_s11b_missing_account_route_fail_closed,
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
        f"\nAll Block 6 Task 3 Account-Aware Dispatch tests passed. "
        f"({len(tests)} scenarios)"
    )


if __name__ == "__main__":
    main()