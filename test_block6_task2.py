"""
Block 6 — Task 6.2: Account Context propagation tests.

Architectural principle under test:

    The Account identity of an order is exactly the identity bound to
    that order by the Planner (Block 1). The execution path
    (ExecutionPlan -> DispatchCore -> BrokerDispatchRequest ->
    OrderEngine) must carry it unchanged: no layer may guess it,
    re-derive it from Symbol/Instrument/Broker, or replace it with
    another Account.

Proven scenarios (offline, stubs only, live=False everywhere):

    S1  Account 1 -> Symbol A: identity reaches the engine boundary.
    S2  Account 1 -> Symbol A + Account 2 -> Symbol B: contexts stay
        independent; the per-sequence binding wins over the
        plan.accounts list order.
    S3  No replacement: envelopes and engine calls carry the exact
        bound Account object; dispatch never mutates the plan.
    S4  Unknown / id-only / unidentified account ids fail closed: the
        order is BLOCKED (never silently bound to another Account);
        an id that is not bound in the plan raises ValueError.
    S5  The engine itself never guesses: Account=None or a bare
        account_id string is rejected; context is not derived from
        an identical Symbol.
    S6  Dry-run boundary unchanged (live=False, sent=False).

No network, no real broker, no real order. This file follows the
Block 2 test conventions (test_dispatch_core.py).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import Mock, patch

from core import dispatch_core as dc
from core.dispatch_core import DispatchCore
from core.execution_planner import (
    ExecutionPlanner,
    LogicalOrderInstruction,
    PlannedOrder,
)
from core.order_engine import OrderEngine
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import BUY, Order


PASSED = 0
FAILED = 0

ACC1 = "ACC-100"
ACC2 = "ACC-200"
BROKER_A = "broker-a"
BROKER_B = "broker-b"
SYM_A = "SYM-A"
SYM_B = "SYM-B"


def make_order(nsc_id=SYM_A, price=150, quantity=10):
    return Order(
        nsc_id=nsc_id,
        side=BUY,
        price=price,
        quantity=quantity,
    )


def make_account(account_id):
    """Account built through the Task 6.1 standard identity constructor."""
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


def make_unidentified_snapshot():
    """Legacy-style balance snapshot with no identity assigned (account_id=None)."""
    return Account(
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


def build_plan(orders, account_ids, broker_names, execution_order=None, plan_id="t62-plan"):
    """
    Build an ExecutionPlan through the REAL Block 1 planner so every test
    exercises the actual ExecutionPlanner -> ExecutionPlan -> DispatchCore
    path (per-sequence binding under plan.conditions["binding"]).
    """
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
    """
    Attach the bound Account objects to the plan exactly as a caller that
    has resolved them (integration layer / Block 6) would do, preserving
    the dedup order the Planner used (first appearance along execution_order).
    """
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
    """Return a manager mock wired to unique broker/provider mocks per name."""
    available = {name: _mock_broker(name) for name in broker_names}
    providers = {name: _mock_provider() for name in broker_names}

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


def record_engine_calls(core):
    """
    Replace the engine-boundary method with a recorder that captures every
    execute_by_ins_code call (the OrderEngine boundary) and returns the
    calls list. Recording only — behavior stays a successful READY result.
    """
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
    """Return the recorded engine call for a specific order object (or None)."""
    for c in calls:
        if c["order"] is order_obj:
            return c
    return None


def capture_envelopes():
    """
    Capture every BrokerDispatchRequest built by the routing stage while
    keeping the real envelope class (mirrors the Block 2 conduit test).
    """
    original_request = dc.BrokerDispatchRequest
    captured = []

    def factory(*args, **kwargs):
        captured.append(kwargs)
        return original_request(*args, **kwargs)

    return captured, factory


def test_scenario_1_identity_preserved():
    print("S1: Account 1 -> Symbol A identity preserved end-to-end")
    order = make_order(SYM_A)
    acc1 = make_account(ACC1)
    plan = build_plan([order], [ACC1], [BROKER_A])
    attach_accounts(plan, {ACC1: acc1})
    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A])
    calls = record_engine_calls(core)
    captured, factory = capture_envelopes()

    with patch.object(dc, "BrokerDispatchRequest", side_effect=factory):
        result = core.dispatch(plan)

    expect_result(result, True, "ALL_PROCESSED", "S1 dispatch returns ALL_PROCESSED")
    expect(len(captured) == 1, "S1 exactly one BrokerDispatchRequest built")
    expect(
        captured[0].get("account") is acc1,
        "S1 envelope carries the exact bound Account object",
    )
    expect(
        captured[0].get("account").account_id == ACC1,
        "S1 envelope account identity is ACC1",
    )
    expect(
        captured[0].get("order") is order,
        "S1 envelope pairs the exact planned order with that Account",
    )
    expect(len(calls) == 1, "S1 exactly one OrderEngine boundary call")
    call = call_for(calls, order)
    expect(call is not None, "S1 engine call recorded for Symbol A order")
    expect(
        call["account"] is acc1,
        "S1 engine receives the same Account object bound in the plan",
    )
    expect(call["account"].account_id == ACC1, "S1 engine call identity is ACC1")
    expect(call["live"] is False, "S1 live=False at engine boundary")
    print()


def test_scenario_2_two_accounts_independent():
    print("S2: Account 1 -> Symbol A and Account 2 -> Symbol B stay independent")
    order_a = make_order(SYM_A)
    order_b = make_order(SYM_B)
    acc1 = make_account(ACC1)
    acc2 = make_account(ACC2)
    plan = build_plan([order_a, order_b], [ACC1, ACC2], [BROKER_A, BROKER_B])
    attach_accounts(plan, {ACC1: acc1, ACC2: acc2})
    expect(
        plan.accounts == [acc1, acc2],
        "S2 plan.accounts dedup keeps first-appearance order [ACC1, ACC2]",
    )
    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A, BROKER_B])
    calls = record_engine_calls(core)
    captured, factory = capture_envelopes()

    with patch.object(dc, "BrokerDispatchRequest", side_effect=factory):
        result = core.dispatch(plan)

    expect_result(result, True, "ALL_PROCESSED", "S2 dispatch returns ALL_PROCESSED")
    expect(len(captured) == 2, "S2 exactly two envelopes built")
    call_a = call_for(calls, order_a)
    call_b = call_for(calls, order_b)
    expect(call_a is not None and call_b is not None, "S2 both orders reached the engine")
    expect(
        call_a["account"] is acc1 and call_a["account"].account_id == ACC1,
        "S2 Symbol A order carries Account 1",
    )
    expect(
        call_b["account"] is acc2 and call_b["account"].account_id == ACC2,
        "S2 Symbol B order carries Account 2",
    )
    expect(
        call_a["account"] is not call_b["account"],
        "S2 the two orders never share one Account object",
    )
    env_a = [e for e in captured if e.get("order") is order_a][0]
    env_b = [e for e in captured if e.get("order") is order_b][0]
    expect(
        env_a["account"] is acc1 and env_b["account"] is acc2,
        "S2 envelopes carry per-order Account objects",
    )
    expect(
        env_a["broker_name"] == BROKER_A and env_b["broker_name"] == BROKER_B,
        "S2 each envelope keeps its own broker path",
    )
    print()


def test_scenario_3_no_replacement():
    print("S3: Account 1 is never replaced by Account 2 anywhere in the path")
    order_a = make_order(SYM_A)
    order_b = make_order(SYM_B)
    acc1 = make_account(ACC1)
    acc2 = make_account(ACC2)
    plan = build_plan([order_a, order_b], [ACC1, ACC2], [BROKER_A, BROKER_B])
    attach_accounts(plan, {ACC1: acc1, ACC2: acc2})
    binding_before = {
        seq: dict(plan.conditions["binding"][seq]) for seq in plan.execution_order
    }
    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A, BROKER_B])
    calls = record_engine_calls(core)
    captured, factory = capture_envelopes()

    with patch.object(dc, "BrokerDispatchRequest", side_effect=factory):
        result = core.dispatch(plan)

    expect_result(result, True, "ALL_PROCESSED", "S3 dispatch returns ALL_PROCESSED")
    binding_after = {
        seq: dict(plan.conditions["binding"][seq]) for seq in plan.execution_order
    }
    expect(
        binding_before == binding_after,
        "S3 dispatch did not mutate the per-sequence Account binding",
    )
    expect(
        plan.accounts == [acc1, acc2],
        "S3 plan.accounts list untouched by dispatch",
    )
    call_a = call_for(calls, order_a)
    call_b = call_for(calls, order_b)
    expect(
        call_a["account"] is acc1 and call_a["account"].account_id == ACC1,
        "S3 Account 1 still bound to Symbol A after dispatch",
    )
    expect(
        call_b["account"] is acc2 and call_b["account"].account_id == ACC2,
        "S3 Account 2 still bound to Symbol B after dispatch",
    )
    expect(
        call_a["account"] is not acc2 and call_b["account"] is not acc1,
        "S3 no cross-contamination between the two Accounts",
    )
    env_a = [e for e in captured if e.get("order") is order_a][0]
    env_b = [e for e in captured if e.get("order") is order_b][0]
    expect(
        env_a["account"].account_id == ACC1 and env_b["account"].account_id == ACC2,
        "S3 envelope account identities unchanged",
    )
    expect(
        env_a["order"] is order_a and env_b["order"] is order_b,
        "S3 envelope order pairing unchanged",
    )
    print()


def test_scenario_4_fail_closed():
    print("S4: unknown / id-only / unidentified identities fail closed")
    order = make_order(SYM_A)
    acc2 = make_account(ACC2)

    def expect_blocked(label, accounts_override):
        plan = build_plan([order], [ACC1], [BROKER_A])
        plan.accounts = accounts_override
        core = DispatchCore()
        core.broker_manager = make_broker_manager([BROKER_A])
        calls = record_engine_calls(core)
        result = core.dispatch(plan)
        expect(
            result.success is False and result.mode == "BLOCKED",
            f"{label} fail-closed BLOCKED (success={result.success}, mode={result.mode})",
        )
        expect(len(calls) == 0, f"{label} nothing reached the OrderEngine")
        expect(
            plan.conditions["binding"][plan.execution_order[0]]["account_id"] == ACC1,
            f"{label} original binding preserved (no re-binding)",
        )
        return plan

    # (a) Stale / mis-typed attachment: plan.accounts holds a non-Account entry.
    expect_blocked("S4a wrong-type entry:", ["not-an-account-object"])

    # (b) Known id, but plan.accounts holds a DIFFERENT Account object:
    # dispatch must not silently bind the wrong Account.
    expect_blocked("S4b mismatched Account object:", [acc2])

    # (c) A legacy balance snapshot without identity (account_id=None) can
    # never be bound as the execution account.
    expect_blocked("S4c unidentified snapshot:", [make_unidentified_snapshot()])

    # (d) The real Block 1 planner shape: plan.accounts holds only the
    # account_id string. The binding stays preserved, no Account is
    # invented, and execution is blocked fail-closed.
    plan = expect_blocked("S4d id-only binding:", [ACC1])
    expect(
        isinstance(plan.accounts[0], str),
        "S4d plan still carries the id-only binding (no invented Account)",
    )

    # (e) An account_id that is not bound in the plan at all: ValueError is
    # caught by dispatch's fail-closed contract -> BLOCKED, engine untouched.
    plan = build_plan([order], ["ACC-UNBOUND"], [BROKER_A])
    plan.accounts = [make_account(ACC1), make_account(ACC2)]
    core = DispatchCore()
    core.broker_manager = make_broker_manager([BROKER_A])
    calls = record_engine_calls(core)
    result = core.dispatch(plan)
    expect(
        result.success is False and result.mode == "BLOCKED",
        "S4e unbound account_id -> fail-closed BLOCKED",
    )
    expect(len(calls) == 0, "S4e nothing reached the OrderEngine")
    print()


def test_scenario_5_engine_never_guesses():
    print("S5: OrderEngine refuses to guess an Account or use a default")
    order = make_order(SYM_A)
    engine = OrderEngine()

    # (a) account=None is rejected, never defaulted.
    rejected = None
    try:
        engine.execute_by_ins_code(
            _mock_broker(BROKER_A),
            _mock_provider(),
            "IRO1TEST0001",
            order,
            None,
            live=False,
        )
    except Exception as exc:  # noqa: BLE001
        rejected = exc
    expect(rejected is not None, "S5a engine rejects account=None (no default)")

    # (b) a bare account_id string is not an Account: rejected, not guessed.
    rejected = None
    try:
        engine.execute_by_ins_code(
            _mock_broker(BROKER_A),
            _mock_provider(),
            "IRO1TEST0001",
            order,
            ACC1,
            live=False,
        )
    except Exception as exc:  # noqa: BLE001
        rejected = exc
    expect(rejected is not None, "S5b engine rejects a bare account_id string")

    # (c) identity is not derived from an identical Symbol: two orders with
    # the SAME nsc_id but different accounts stay distinct at the boundary.
    acc1 = make_account(ACC1)
    acc2 = make_account(ACC2)
    order_x = make_order(SYM_A)  # same symbol...
    order_y = make_order(SYM_A)  # ...for both orders
    plan = build_plan([order_x, order_y], [ACC1, ACC2], [BROKER_A, BROKER_B])
    attach_accounts(plan, {ACC1: acc1, ACC2: acc2})
    core = DispatchCore()
    core.broker_manager = (make_broker_manager([BROKER_A, BROKER_B]))
    calls = record_engine_calls(core)
    core.dispatch(plan)
    cx = call_for(calls, order_x)
    cy = call_for(calls, order_y)
    expect(cx is not None and cy is not None, "S5c both same-symbol orders dispatched")
    expect(
        cx["account"] is acc1 and cy["account"] is acc2,
        "S5c identical Symbols keep their distinct Account identities",
    )
    print()


def test_scenario_6_dry_run_boundary_unchanged():
    print("S6: dry-run boundary unchanged (live=False, nothing really sent)")
    order = make_order(SYM_A)
    acc1 = make_account(ACC1)
    plan = build_plan([order], [ACC1], [BROKER_A])
    attach_accounts(plan, {ACC1: acc1})
    core = DispatchCore()
    manager = make_broker_manager([BROKER_A])
    core.broker_manager = (manager)
    calls = record_engine_calls(core)
    result = core.dispatch(plan)
    expect_result(result, True, "ALL_PROCESSED", "S6 ALL_PROCESSED result in dry-run")
    call = call_for(calls, order)
    expect(call["account"] is acc1, "S6 account context intact at the boundary")
    expect(call["live"] is False, "S6 live=False propagated")
    expect(result.sent is False, "S6 nothing really sent (sent=False)")
    broker = manager.get(BROKER_A)
    broker.place_order.assert_not_called()
    broker.submit_order.assert_not_called()
    print()


def main():
    test_scenario_1_identity_preserved()
    test_scenario_2_two_accounts_independent()
    test_scenario_3_no_replacement()
    test_scenario_4_fail_closed()
    test_scenario_5_engine_never_guesses()
    test_scenario_6_dry_run_boundary_unchanged()

    print(f"\nPASSED: {PASSED}   FAILED: {FAILED}")
    if FAILED:
        sys.exit(1)


if __name__ == "__main__":
    main()
