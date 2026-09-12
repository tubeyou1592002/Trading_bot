"""Block 4 — Task 3: Connect ExecutionPlan to Dispatch path tests.

Tests for the connection between the ExecutionPlan produced by Task 2
(``connect_trigger_to_planner``) and the existing Dispatch Core entry point
(``DispatchCore.dispatch``).

Covered:
  - The exact ExecutionPlan object from Task 2 reaches dispatch() (identity).
  - The exact DispatchResult returned by dispatch() is preserved.
  - Trigger gate False (no plan) -> dispatch is never called (fail-closed).
  - A ``None`` plan -> dispatch is never called (fail-closed).
  - Full real path: EventTrigger -> ExecutionPlanner -> ExecutionPlan ->
    DispatchCore with the broker/provider/OrderEngine boundary mocked
    (same style as test_dispatch_core.py).

No modification to TradingStateEventTrigger, ExecutionPlanner, or DispatchCore.
No scheduler, timer, polling, broker API, or real order execution.
"""

import sys
import os
from datetime import datetime
from unittest.mock import Mock

sys.path.insert(0, os.path.dirname(__file__))

from core.block4_task2 import connect_trigger_to_planner
from core.block4_task3 import connect_plan_to_dispatch
from core.dispatch_contracts import DispatchResult, ExecutionPlan
from core.dispatch_core import DispatchCore
from core.execution_planner import (
    ExecutionPlanner,
    LogicalOrderInstruction,
    PlannedOrder,
)
from core.trading_state_event_trigger import TradingStateEventTrigger
from models.account import Account
from models.broker_instrument import BrokerInstrument
from models.order import BUY, Order
from models.trading_state import (
    UNVERIFIED,
    VERIFIED_BLOCKED,
    VERIFIED_TRADABLE,
)

NOW = datetime(2026, 9, 11, 9, 0, 0)


# ---------------------------------------------------------------------------
# Test helpers (matching test_dispatch_core.py conventions)
# ---------------------------------------------------------------------------


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


def make_mock_broker(name="broker-a"):
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
    """Return a Mock BrokerManager wired to unique broker/provider mocks."""
    available = {name: make_mock_broker(name) for name in broker_names}
    providers = {name: make_mock_provider() for name in broker_names}

    manager = Mock()
    manager.get.side_effect = lambda name, _a=available: _a[name]
    manager.get_instrument_provider.side_effect = lambda name, _p=providers: _p[name]
    return manager


def make_instruction(
    order=None,
    account_id="acc-1",
    broker_name="broker-a",
    sequence=0,
    plan_id="plan-b4t3",
):
    """Build a LogicalOrderInstruction for the Task 2 connector."""
    if order is None:
        order = make_order()
    planned_order = PlannedOrder(
        order=order,
        account_id=account_id,
        broker_name=broker_name,
        sequence=sequence,
    )
    return LogicalOrderInstruction(plan_id=plan_id, orders=[planned_order])


def attach_accounts(plan, accounts_by_id):
    """Attach resolved Account objects to a planner-produced plan."""
    seen = []
    for seq in plan.execution_order:
        acc_id = plan.conditions["binding"][seq]["account_id"]
        if acc_id not in seen:
            seen.append(acc_id)
    plan.accounts = [accounts_by_id[a] for a in seen]
    return plan


def make_spy_core():
    """DispatchCore whose dispatch() is replaced by a recording stub.

    Returns (core, calls, sentinel): ``calls`` records every plan passed
    to ``dispatch``, and ``sentinel`` is the DispatchResult returned.
    """
    core = DispatchCore()
    sentinel = DispatchResult(success=True, sent=False, mode="READY")
    calls = []

    def fake_dispatch(plan):
        calls.append(plan)
        return sentinel

    core.dispatch = fake_dispatch  # type: ignore
    return core, calls, sentinel


def ok_result():
    res = Mock()
    res.success = True
    res.sent = False
    res.mode = "READY"
    return res
# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_exact_task2_plan_reaches_dispatch():
    """The exact ExecutionPlan from Task 2 is passed to dispatch (identity)."""
    planner = ExecutionPlanner()
    trigger = TradingStateEventTrigger(state=VERIFIED_TRADABLE)
    instruction = make_instruction()

    task2 = connect_trigger_to_planner(trigger, planner, instruction, NOW)
    assert task2["fired"] is True
    plan = task2["execution_plan"]
    assert isinstance(plan, ExecutionPlan)

    core, calls, sentinel = make_spy_core()
    result = connect_plan_to_dispatch(plan, core)

    assert result["dispatch_called"] is True
    assert result["dispatched"] is True
    assert result["execution_plan"] is plan
    assert result["dispatch_result"] is sentinel
    assert len(calls) == 1, f"Expected exactly 1 dispatch call, got {len(calls)}"
    assert calls[0] is plan, "The exact Task 2 ExecutionPlan object must reach dispatch"


def test_dispatch_result_propagated():
    """The DispatchResult returned by dispatch() is preserved unchanged."""
    plan = ExecutionPlan(plan_id="plan-probe")
    core, calls, sentinel = make_spy_core()

    result = connect_plan_to_dispatch(plan, core)

    assert result["dispatched"] is True
    assert result["dispatch_result"] is sentinel
    assert result["dispatch_result"].mode == "READY"


def test_trigger_gate_false_no_dispatch():
    """A non-firing trigger yields no plan, so dispatch is never called."""
    for state in (VERIFIED_BLOCKED, UNVERIFIED):
        planner = ExecutionPlanner()
        task2 = connect_trigger_to_planner(
            TradingStateEventTrigger(state=state),
            planner,
            make_instruction(),
            NOW,
        )
        assert task2["fired"] is False
        assert task2["execution_plan"] is None

        core, calls, _ = make_spy_core()
        result = connect_plan_to_dispatch(task2["execution_plan"], core)

        assert result["dispatched"] is False
        assert result["dispatch_called"] is False
        assert result["execution_plan"] is None
        assert result["dispatch_result"] is None
        assert calls == [], f"State {state} must never reach dispatch"


def test_none_plan_no_dispatch():
    """A None plan never reaches dispatch (fail-closed)."""
    core, calls, _ = make_spy_core()
    result = connect_plan_to_dispatch(None, core)

    assert result["dispatched"] is False
    assert result["dispatch_called"] is False
    assert result["execution_plan"] is None
    assert result["dispatch_result"] is None
    assert calls == []


def test_full_chain_event_to_dispatch_core_real_path():
    """
    End-to-end: EventTrigger -> ExecutionPlanner -> ExecutionPlan ->
    real DispatchCore.dispatch (broker/provider/OrderEngine mocked).

    Proves the Task 2 plan is consumable through the existing Block 2
    Dispatch path, not only through a stub.
    """
    planner = ExecutionPlanner()
    trigger = TradingStateEventTrigger(state=VERIFIED_TRADABLE)
    order = make_order()
    instruction = make_instruction(order=order, account_id="acc-1", broker_name="broker-a")

    task2 = connect_trigger_to_planner(trigger, planner, instruction, NOW)
    assert task2["fired"] is True
    plan = task2["execution_plan"]
    assert isinstance(plan, ExecutionPlan)

    core = DispatchCore()
    core.broker_manager = make_broker_manager(["broker-a"])
    attach_accounts(plan, {"acc-1": make_account("acc-1")})

    def fake_execute(broker, provider, ins_code, order, account, live):
        return ok_result()

    core.order_engine.execute_by_ins_code = Mock(side_effect=fake_execute)

    result = connect_plan_to_dispatch(plan, core)

    assert result["dispatch_called"] is True
    assert result["dispatched"] is True
    assert result["execution_plan"] is plan

    dr = result["dispatch_result"]
    assert dr.success is True
    assert dr.sent is False
    assert dr.trace_id is not None, "Dispatch Core generated a trace_id"


def main():
    tests = [
        test_exact_task2_plan_reaches_dispatch,
        test_dispatch_result_propagated,
        test_trigger_gate_false_no_dispatch,
        test_none_plan_no_dispatch,
        test_full_chain_event_to_dispatch_core_real_path,
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
        f"\nAll Block 4 Task 3 connection tests passed. ({len(tests)} tests)"
    )


if __name__ == "__main__":
    main()