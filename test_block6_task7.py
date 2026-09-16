"""
Block 6 — Task 6.7: Final Integration & Regression.

Proves the full Multi-Account End-to-End path works without breaking
Block 5 or earlier work.

Chain under test:

    ExecutionPlan
    -> Account Binding (plan.conditions["binding"])
    -> Account-Aware Routing (plan.account_routes -> BrokerManager)
    -> DispatchCore.dispatch(plan) -> OrderEngine.execute_by_ins_code
    -> OrderExecutionResult (per order)
    -> Task 6.5 Tracking (ExecutionTracker.register_order / update_order_status)
    -> Task 6.6 Stop/Brake Policy (StopBrakePolicy.observe_order_result)

Proven scenarios (offline, stubs only, live=False everywhere):

    S1  End-to-End: 3 orders / 2 accounts / 2 brokers
    S2  Two orders for one account stay independent
    S3  Same Symbol / Different Accounts — independent
    S4  ACCOUNT Brake End-to-End
    S5  GLOBAL Brake End-to-End
    S6  NONE Policy End-to-End
    S7  Results arrive in different order — identical final state
    S8  Fail-Closed: no unwanted order sent, no prior state corrupted
    S9  Dry-run: live=False everywhere
    S10 Isolation: Account/Broker/Symbol/Order never mix

No network, no real broker, no real order.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import Mock

from core.block5_task3 import StopSignal
from core.block5_task4 import (
    STOPPED_MODE,
    DispatchIntegration,
    DispatchIntegrationError,
)
from core.block6_task6 import (
    StopBrakePolicy,
    StopBrakePolicyError,
    StopPolicy,
)
from core.dispatch_core import DispatchCore
from core.dispatch_contracts import DispatchResult, ExecutionPlan
from core.execution_planner import (
    ExecutionPlanner,
    LogicalOrderInstruction,
    PlannedOrder,
)
from core.execution_tracker import (
    ExecutionStatus,
    ExecutionTracker,
    ExecutionTrackerError,
)
from core.order_engine import OrderExecutionResult
from models.account import Account, AccountValidationError
from models.broker_instrument import BrokerInstrument
from models.order import BUY, SELL, Order


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACC1 = "ACC-1"
ACC2 = "ACC-2"
ACC_UNKNOWN = "ACC-UNKNOWN"
BROKER_A = "broker-a"
BROKER_B = "broker-b"
BROKER_UNKNOWN = "broker-unknown"
SYM_A = "SYM-A"
SYM_B = "SYM-B"
SYM_C = "SYM-C"

ALL_POLICIES = (StopPolicy.NONE, StopPolicy.ACCOUNT, StopPolicy.GLOBAL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def build_plan(orders, account_ids, broker_names, plan_id="t67-plan"):
    """Build an ExecutionPlan through the REAL Block 1 planner."""
    pos = [
        PlannedOrder(
            order=order,
            account_id=account_ids[i],
            broker_name=broker_names[i],
            sequence=i,
        )
        for i, order in enumerate(orders)
    ]
    return ExecutionPlanner().build_plan(
        LogicalOrderInstruction(plan_id=plan_id, orders=pos)
    )


def attach_accounts(plan, accounts_by_id):
    """Attach resolved Account objects in the order of the plan binding."""
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


def ok_order_result(order, broker_name=None):
    """A real per-order ``OrderExecutionResult`` for a successful order."""
    return OrderExecutionResult(
        success=True,
        sent=False,
        mode="READY",
        order=order,
        broker_name=broker_name,
    )


def blocked_order_result(order, broker_name=None):
    """A real per-order ``OrderExecutionResult`` for a blocked order."""
    return OrderExecutionResult(
        success=False,
        sent=False,
        mode="BLOCKED",
        order=order,
        broker_name=broker_name,
    )


def result_by_account(success_accounts):
    """Per-order result fn: success for the listed accounts, blocked otherwise."""
    def result_fn(order, account):
        if account is not None and getattr(account, "account_id", None) in success_accounts:
            return ok_order_result(order)
        return blocked_order_result(order)

    return result_fn


def make_core(result_fn=None, broker_names=(BROKER_A, BROKER_B)):
    """Real DispatchCore with the broker/provider/OrderEngine boundary mocked.

    Returns ``(core, calls)``; each call records the order, its account,
    ``live`` and the produced per-order result.
    """
    core = DispatchCore()
    core.broker_manager = make_broker_manager(list(broker_names))
    calls = []

    def fake_execute(broker, provider, ins_code, order, account, live):
        outcome = (
            result_fn(order, account)
            if result_fn is not None
            else ok_order_result(order)
        )
        calls.append(
            {
                "broker": broker,
                "order": order,
                "account": account,
                "live": live,
                "result": outcome,
            }
        )
        return outcome

    core.order_engine.execute_by_ins_code = Mock(side_effect=fake_execute)
    return core, calls


def make_world(brake_policy=None, result_fn=None, broker_names=None):
    """A fresh (core, calls, tracker, integration) world.

    Returns (core, calls, tracker, integration).
    """
    if broker_names is None:
        broker_names = (BROKER_A, BROKER_B)
    core, calls = make_core(result_fn=result_fn, broker_names=broker_names)
    tracker = ExecutionTracker()
    integration = DispatchIntegration(
        core, tracker=tracker, brake_policy=brake_policy
    )
    return core, calls, tracker, integration


def dispatch_plan(integration, plan, execution_id, core_calls):
    """Dispatch ONE plan; return ``(DispatchResult, the new core calls)``."""
    before = len(core_calls)
    outcome = integration.dispatch(plan, execution_id=execution_id)
    return outcome, core_calls[before:]


def sequence_of(plan, order_obj):
    """The plan sequence of ``order_obj`` (planner sorts orders ascending)."""
    index = next(
        i for i, candidate in enumerate(plan.orders) if candidate is order_obj
    )
    return sorted(plan.execution_order)[index]


def results_by_sequence(plan, calls):
    """Map the per-order results of the DispatchCore path to their sequence."""
    mapping = {}
    for call in calls:
        mapping[sequence_of(plan, call["order"])] = call["result"]
    return mapping


def record_results(integration, execution_id, plan, calls, arrival=None):
    """Feed the per-order results of ONE dispatch to tracking + policy.

    ``arrival`` is the order in which the sequences arrive (default: plan
    order). Returns ``{sequence: ExecutionStatus}``.
    """
    by_sequence = results_by_sequence(plan, calls)
    order = sorted(by_sequence) if arrival is None else list(arrival)
    assert sorted(order) == sorted(by_sequence), (
        f"arrival {order} does not cover sequences {sorted(by_sequence)}"
    )
    return {
        sequence: integration.record_order_result(
            execution_id, sequence, by_sequence[sequence]
        )
        for sequence in order
    }


def statuses(integration, execution_id, sequences):
    """Current per-order statuses of one dispatch execution."""
    return {
        sequence: integration.tracker.get_order_status(execution_id, sequence)
        for sequence in sequences
    }


def accounts_of(integration, execution_id, sequences):
    """Account identity tracked for each order of one execution."""
    return {
        sequence: integration.tracker.get_order_record(
            execution_id, sequence
        ).account_id
        for sequence in sequences
    }


def records_of(integration, execution_id, sequences):
    """The per-order record objects of one dispatch execution."""
    return {
        sequence: integration.tracker.get_order_record(execution_id, sequence)
        for sequence in sequences
    }


def expect_raises(exc_type, func, label):
    """Assert that ``func()`` raises ``exc_type``."""
    try:
        func()
    except exc_type:
        return
    except Exception as exc:
        raise AssertionError(
            f"{label}: expected {exc_type.__name__}, got {exc!r}"
        )
    raise AssertionError(f"{label}: expected {exc_type.__name__}, nothing raised")


# ---------------------------------------------------------------------------
# S1 — End-to-End: 3 orders / 2 accounts / 2 brokers
# ---------------------------------------------------------------------------


def test_s1_e2e_three_orders_two_accounts_two_brokers():
    print("S1: 3 orders, 2 accounts, 2 brokers -> independent E2E")

    order_a = make_order(SYM_A, price=100, quantity=5)   # ACC-1 / broker-a
    order_b = make_order(SYM_B, price=200, quantity=7)   # ACC-2 / broker-b
    order_c = make_order(SYM_C, price=300, quantity=3)   # ACC-1 / broker-a

    plan = build_plan(
        [order_a, order_b, order_c],
        [ACC1, ACC2, ACC1],
        [BROKER_A, BROKER_B, BROKER_A],
    )
    attach_accounts(
        plan, {ACC1: make_account(ACC1), ACC2: make_account(ACC2)}
    )

    core, calls, tracker, integration = make_world(StopPolicy.NONE)

    # --- Dispatch -----------------------------------------------------------
    outcome, batch = dispatch_plan(
        integration, plan, "exec-s1", calls
    )
    assert outcome.success is True
    assert outcome.mode == "ALL_PROCESSED"
    assert outcome.order_count == 3
    assert all(call["live"] is False for call in batch)
    assert len(batch) == 3

    # --- Full chain verification --------------------------------------------
    # 1) Account binding preserved from planning
    binding = plan.conditions["binding"]
    assert binding[0]["account_id"] == ACC1
    assert binding[1]["account_id"] == ACC2
    assert binding[2]["account_id"] == ACC1

    # 2) Routing matches binding
    assert plan.account_routes == {ACC1: BROKER_A, ACC2: BROKER_B}

    # 3) Each order dispatched with correct account/broker
    by_seq = results_by_sequence(plan, batch)
    assert len(by_seq) == 3

    for seq, account_id in ((0, ACC1), (1, ACC2), (2, ACC1)):
        rec = tracker.get_order_record("exec-s1", seq)
        assert rec.account_id == account_id

    # 4) One execution id, three independent order records
    assert set(tracker._records) == {"exec-s1"}
    assert set(tracker.order_records("exec-s1")) == {0, 1, 2}
    assert accounts_of(integration, "exec-s1", (0, 1, 2)) == {
        0: ACC1, 1: ACC2, 2: ACC1,
    }

    # 5) Record identity preserved
    rec0 = tracker.get_order_record("exec-s1", 0)
    rec1 = tracker.get_order_record("exec-s1", 1)
    rec2 = tracker.get_order_record("exec-s1", 2)
    assert rec0 is not rec1 and rec0 is not rec2 and rec1 is not rec2

    # 6) Record results and verify per-order status
    result_statuses = record_results(
        integration, "exec-s1", plan, batch
    )
    assert result_statuses == {
        0: ExecutionStatus.REGISTERED,
        1: ExecutionStatus.REGISTERED,
        2: ExecutionStatus.REGISTERED,
    }

    # 7) Dispatch-level record untouched by per-order results
    assert tracker.get_status("exec-s1") == ExecutionStatus.PENDING

    # 8) Brake policy: no account braked under NONE
    assert integration.stopped_accounts == ()
    assert integration.brake_policy.is_global_stopped is False
    assert integration.brake_policy.should_continue([ACC1, ACC2]) is True

    # 9) Dispatch-level record identity unchanged
    assert records_of(integration, "exec-s1", (0, 1, 2))[0] is rec0
    assert records_of(integration, "exec-s1", (0, 1, 2))[1] is rec1
    assert records_of(integration, "exec-s1", (0, 1, 2))[2] is rec2

    print()


# ---------------------------------------------------------------------------
# S2 — Two orders for one account stay independent
# ---------------------------------------------------------------------------


def test_s2_two_orders_one_account_stay_independent():
    print("S2: 2 orders ACC-1 -> two independent tracks")

    order_a = make_order(SYM_A, price=100, quantity=5)
    order_c = make_order(SYM_C, price=300, quantity=3)

    plan = build_plan(
        [order_a, order_c],
        [ACC1, ACC1],
        [BROKER_A, BROKER_A],
    )
    attach_accounts(plan, {ACC1: make_account(ACC1)})

    core, calls, tracker, integration = make_world(
        StopPolicy.NONE,
        result_fn=lambda order, account: (
            ok_order_result(order) if order is order_a else blocked_order_result(order)
        ),
    )

    outcome, batch = dispatch_plan(integration, plan, "exec-s2", calls)
    assert outcome.sent is False
    assert outcome.order_count == 2
    assert outcome.mode in ("ALL_PROCESSED", "BLOCKED")
    assert len(batch) == 2

    assert accounts_of(integration, "exec-s2", (0, 1)) == {0: ACC1, 1: ACC1}
    assert set(tracker.order_records("exec-s2")) == {0, 1}

    rec0 = tracker.get_order_record("exec-s2", 0)
    rec1 = tracker.get_order_record("exec-s2", 1)
    assert rec0 is not rec1

    result_statuses = record_results(integration, "exec-s2", plan, batch)
    assert result_statuses == {
        0: ExecutionStatus.REGISTERED,
        1: ExecutionStatus.FAILED,
    }
    assert statuses(integration, "exec-s2", (0, 1)) == {
        0: ExecutionStatus.REGISTERED,
        1: ExecutionStatus.FAILED,
    }
    assert tracker.get_status("exec-s2") == ExecutionStatus.PENDING

    print()


# ---------------------------------------------------------------------------
# S3 — Same Symbol / Different Accounts — independent
# ---------------------------------------------------------------------------


def test_s3_same_symbol_different_accounts_independent():
    print("S3: same symbol SYM-A on ACC-1 and ACC-2 -> independent")

    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_A, price=250, quantity=3)

    plan = build_plan(
        [order_a, order_b],
        [ACC1, ACC2],
        [BROKER_A, BROKER_B],
    )
    attach_accounts(
        plan, {ACC1: make_account(ACC1), ACC2: make_account(ACC2)}
    )

    core, calls, tracker, integration = make_world(
        StopPolicy.NONE,
        result_fn=lambda order, account: (
            ok_order_result(order) if order is order_b else blocked_order_result(order)
        ),
    )

    outcome, batch = dispatch_plan(integration, plan, "exec-s3", calls)
    assert outcome.mode in ("ALL_PROCESSED", "BLOCKED")
    assert outcome.order_count == 2
    assert len(batch) == 2

    # Symbol stays the same; accounts are different
    assert plan.orders[0].nsc_id == plan.orders[1].nsc_id == SYM_A

    tracked = accounts_of(integration, "exec-s3", (0, 1))
    assert tracked == {0: ACC1, 1: ACC2}
    assert set(tracked.values()).isdisjoint({SYM_A, BROKER_A, BROKER_B})

    result_statuses = record_results(integration, "exec-s3", plan, batch)
    assert result_statuses == {
        0: ExecutionStatus.FAILED,
        1: ExecutionStatus.REGISTERED,
    }
    assert set(tracker.order_records("exec-s3")) == {0, 1}
    rec0 = tracker.get_order_record("exec-s3", 0)
    rec1 = tracker.get_order_record("exec-s3", 1)
    assert rec0 is not rec1

    print()


# ---------------------------------------------------------------------------
# S4 — ACCOUNT Brake End-to-End
# ---------------------------------------------------------------------------


def test_s4_account_brake_e2e():
    print("S4: ACCOUNT brake: ACC-1 success -> ACC-1 stopped, ACC-2 continues")

    success = {ACC1}
    core, calls, tracker, integration = make_world(
        StopPolicy.ACCOUNT, result_fn=result_by_account(success)
    )

    # --- First round: ACC-1 succeeds, ACC-2 blocked -------------------------
    order_a = make_order(SYM_A, price=100, quantity=5)
    plan_a = build_plan([order_a], [ACC1], [BROKER_A], plan_id="s4-a1")
    attach_accounts(plan_a, {ACC1: make_account(ACC1)})

    order_b = make_order(SYM_B, price=200, quantity=7)
    plan_b = build_plan([order_b], [ACC2], [BROKER_B], plan_id="s4-b1")
    attach_accounts(plan_b, {ACC2: make_account(ACC2)})

    outcome_a, calls_a = dispatch_plan(integration, plan_a, "exec-s4-a1", calls)
    outcome_b, calls_b = dispatch_plan(integration, plan_b, "exec-s4-b1", calls)
    assert outcome_a.mode != STOPPED_MODE
    assert outcome_b.mode != STOPPED_MODE
    assert len(calls) == 2

    # Record results
    res_a = record_results(integration, "exec-s4-a1", plan_a, calls_a)
    res_b = record_results(integration, "exec-s4-b1", plan_b, calls_b)
    assert res_a == {0: ExecutionStatus.REGISTERED}
    assert res_b == {0: ExecutionStatus.FAILED}

    # ACC-1 braked, ACC-2 not
    assert integration.stopped_accounts == (ACC1,)
    assert integration.brake_policy.is_account_stopped(ACC1) is True
    assert integration.brake_policy.is_account_stopped(ACC2) is False
    assert integration.brake_policy.is_global_stopped is False

    # --- Second round: ACC-1 future dispatch stopped, ACC-2 continues -------
    before_calls = len(calls)
    order_a2 = make_order(SYM_A, price=101, quantity=5)
    plan_a2 = build_plan([order_a2], [ACC1], [BROKER_A], plan_id="s4-a2")
    attach_accounts(plan_a2, {ACC1: make_account(ACC1)})

    stopped_a, stopped_calls = dispatch_plan(
        integration, plan_a2, "exec-s4-a2", calls
    )
    assert stopped_a.mode == STOPPED_MODE
    assert stopped_a.success is False and stopped_a.sent is False
    assert stopped_calls == []
    assert "exec-s4-a2" not in tracker._records
    assert len(calls) == before_calls

    # ACC-2 keeps sending
    order_b2 = make_order(SYM_B, price=201, quantity=7)
    plan_b2 = build_plan([order_b2], [ACC2], [BROKER_B], plan_id="s4-b2")
    attach_accounts(plan_b2, {ACC2: make_account(ACC2)})

    allowed, allowed_calls = dispatch_plan(
        integration, plan_b2, "exec-s4-b2", calls
    )
    assert allowed.mode != STOPPED_MODE
    assert len(allowed_calls) == 1
    assert allowed_calls[0]["account"].account_id == ACC2
    assert allowed_calls[0]["broker"].name == BROKER_B
    assert allowed_calls[0]["live"] is False

    res_b2 = record_results(integration, "exec-s4-b2", plan_b2, allowed_calls)
    assert res_b2 == {0: ExecutionStatus.FAILED}  # ACC-2 not in success set

    # --- Verify already-sent orders unchanged -------------------------------
    assert statuses(integration, "exec-s4-a1", (0,)) == {0: ExecutionStatus.REGISTERED}
    assert statuses(integration, "exec-s4-b1", (0,)) == {0: ExecutionStatus.FAILED}

    print()


# ---------------------------------------------------------------------------
# S5 — GLOBAL Brake End-to-End
# ---------------------------------------------------------------------------


def test_s5_global_brake_e2e():
    print("S5: GLOBAL brake: first success stops ALL accounts")

    success = {ACC1}
    core, calls, tracker, integration = make_world(
        StopPolicy.GLOBAL, result_fn=result_by_account(success)
    )

    order_a = make_order(SYM_A, price=100, quantity=5)
    plan_a = build_plan([order_a], [ACC1], [BROKER_A], plan_id="s5-a1")
    attach_accounts(plan_a, {ACC1: make_account(ACC1)})

    order_b = make_order(SYM_B, price=200, quantity=7)
    plan_b = build_plan([order_b], [ACC2], [BROKER_B], plan_id="s5-b1")
    attach_accounts(plan_b, {ACC2: make_account(ACC2)})

    # Dispatch both
    _, calls_a = dispatch_plan(integration, plan_a, "exec-s5-a1", calls)
    _, calls_b = dispatch_plan(integration, plan_b, "exec-s5-b1", calls)
    assert len(calls) == 2

    # Record ACC-1 result: SUCCESS -> GLOBAL brake
    res_a = record_results(integration, "exec-s5-a1", plan_a, calls_a)
    assert res_a == {0: ExecutionStatus.REGISTERED}
    assert integration.brake_policy.is_global_stopped is True
    assert integration.brake_policy.global_signal.activation_count == 1
    assert integration.stopped_accounts == ()

    # Record ACC-2 result: FAILED, but run already braked globally
    res_b = record_results(integration, "exec-s5-b1", plan_b, calls_b)
    assert res_b == {0: ExecutionStatus.FAILED}
    assert integration.brake_policy.global_signal.activation_count == 1

    # --- Future dispatches of ALL accounts stopped ---------------------------
    before_calls = len(calls)

    order_a2 = make_order(SYM_A, price=101, quantity=5)
    plan_a2 = build_plan([order_a2], [ACC1], [BROKER_A], plan_id="s5-a2")
    attach_accounts(plan_a2, {ACC1: make_account(ACC1)})
    stopped_a, stopped_calls_a = dispatch_plan(
        integration, plan_a2, "exec-s5-a2", calls
    )
    assert stopped_a.mode == STOPPED_MODE
    assert stopped_calls_a == []

    order_b2 = make_order(SYM_B, price=201, quantity=7)
    plan_b2 = build_plan([order_b2], [ACC2], [BROKER_B], plan_id="s5-b2")
    attach_accounts(plan_b2, {ACC2: make_account(ACC2)})
    stopped_b, stopped_calls_b = dispatch_plan(
        integration, plan_b2, "exec-s5-b2", calls
    )
    assert stopped_b.mode == STOPPED_MODE
    assert stopped_calls_b == []

    assert len(calls) == before_calls
    assert "exec-s5-a2" not in tracker._records
    assert "exec-s5-b2" not in tracker._records

    # --- Already-sent orders unchanged ---------------------------------------
    assert statuses(integration, "exec-s5-a1", (0,)) == {0: ExecutionStatus.REGISTERED}
    assert statuses(integration, "exec-s5-b1", (0,)) == {0: ExecutionStatus.FAILED}

    print()


# ---------------------------------------------------------------------------
# S6 — NONE Policy End-to-End
# ---------------------------------------------------------------------------


def test_s6_none_policy_e2e():
    print("S6: NONE policy -> no account braked despite all successes")

    core, calls, tracker, integration = make_world(StopPolicy.NONE)

    order_a = make_order(SYM_A, price=100, quantity=5)
    plan_a = build_plan([order_a], [ACC1], [BROKER_A], plan_id="s6-a1")
    attach_accounts(plan_a, {ACC1: make_account(ACC1)})

    order_b = make_order(SYM_B, price=200, quantity=7)
    plan_b = build_plan([order_b], [ACC2], [BROKER_B], plan_id="s6-b1")
    attach_accounts(plan_b, {ACC2: make_account(ACC2)})

    _, calls_a = dispatch_plan(integration, plan_a, "exec-s6-a1", calls)
    _, calls_b = dispatch_plan(integration, plan_b, "exec-s6-b1", calls)
    assert len(calls) == 2

    res_a = record_results(integration, "exec-s6-a1", plan_a, calls_a)
    res_b = record_results(integration, "exec-s6-b1", plan_b, calls_b)
    assert res_a == {0: ExecutionStatus.REGISTERED}
    assert res_b == {0: ExecutionStatus.REGISTERED}

    # Nothing braked
    assert integration.stopped_accounts == ()
    assert integration.brake_policy.is_global_stopped is False
    assert integration.brake_policy.is_account_stopped(ACC1) is False
    assert integration.brake_policy.is_account_stopped(ACC2) is False
    assert integration.brake_policy.account_signal(ACC1) is None
    assert integration.brake_policy.should_continue([ACC1, ACC2]) is True

    # Both accounts keep sending
    order_a2 = make_order(SYM_A, price=101, quantity=5)
    plan_a2 = build_plan([order_a2], [ACC1], [BROKER_A], plan_id="s6-a2")
    attach_accounts(plan_a2, {ACC1: make_account(ACC1)})

    order_b2 = make_order(SYM_B, price=201, quantity=7)
    plan_b2 = build_plan([order_b2], [ACC2], [BROKER_B], plan_id="s6-b2")
    attach_accounts(plan_b2, {ACC2: make_account(ACC2)})

    ok_a2, calls_a2 = dispatch_plan(integration, plan_a2, "exec-s6-a2", calls)
    ok_b2, calls_b2 = dispatch_plan(integration, plan_b2, "exec-s6-b2", calls)
    assert ok_a2.mode != STOPPED_MODE
    assert ok_b2.mode != STOPPED_MODE
    assert len(calls_a2) == 1 and len(calls_b2) == 1
    assert calls_a2[0]["account"].account_id == ACC1
    assert calls_b2[0]["account"].account_id == ACC2

    print()


# ---------------------------------------------------------------------------
# S7 — Results arrive in different order — identical final state
# ---------------------------------------------------------------------------


def test_s7_results_arrive_in_different_order():
    print("S7: scrambled result arrival -> identical final state")

    states = []
    for arrival in ((0, 1, 2), (2, 0, 1), (1, 2, 0)):
        order_a = make_order(SYM_A, price=100, quantity=5)
        order_b = make_order(SYM_B, price=200, quantity=7)
        order_c = make_order(SYM_C, price=300, quantity=3)

        plan = build_plan(
            [order_a, order_b, order_c],
            [ACC1, ACC2, ACC1],
            [BROKER_A, BROKER_B, BROKER_A],
        )
        attach_accounts(
            plan, {ACC1: make_account(ACC1), ACC2: make_account(ACC2)}
        )

        core, calls, tracker, integration = make_world(
            StopPolicy.NONE,
            result_fn=result_by_account({ACC1}),
        )

        _, batch = dispatch_plan(integration, plan, "exec-s7", calls)
        result_statuses = record_results(
            integration, "exec-s7", plan, batch, arrival=arrival
        )

        final_statuses = statuses(integration, "exec-s7", (0, 1, 2))
        final_accounts = accounts_of(integration, "exec-s7", (0, 1, 2))
        stopped = integration.stopped_accounts

        states.append((final_statuses, final_accounts, stopped))

    # All three arrival orders produce the same final state
    assert states[0] == states[1] == states[2]

    # Verify the expected state
    final_statuses, final_accounts, stopped = states[0]
    assert final_statuses == {
        0: ExecutionStatus.REGISTERED,
        1: ExecutionStatus.FAILED,
        2: ExecutionStatus.REGISTERED,
    }
    assert final_accounts == {0: ACC1, 1: ACC2, 2: ACC1}
    assert stopped == ()  # NONE policy

    # --- Also test scrambled arrival under GLOBAL policy --------------------
    for arrival in ((0, 1, 2), (2, 0, 1), (1, 2, 0)):
        order_a = make_order(SYM_A, price=100, quantity=5)
        order_b = make_order(SYM_B, price=200, quantity=7)
        order_c = make_order(SYM_C, price=300, quantity=3)

        plan = build_plan(
            [order_a, order_b, order_c],
            [ACC1, ACC2, ACC1],
            [BROKER_A, BROKER_B, BROKER_A],
        )
        attach_accounts(
            plan, {ACC1: make_account(ACC1), ACC2: make_account(ACC2)}
        )

        core, calls, tracker, integration = make_world(
            StopPolicy.GLOBAL,
            result_fn=result_by_account({ACC1}),
        )

        _, batch = dispatch_plan(integration, plan, "exec-s7g", calls)
        record_results(
            integration, "exec-s7g", plan, batch, arrival=arrival
        )

        # Global is braked regardless of arrival order
        assert integration.brake_policy.is_global_stopped is True
        assert integration.brake_policy.global_signal.activation_count == 1

    print()


# ---------------------------------------------------------------------------
# S8 — Fail-Closed: no unwanted order sent, no prior state corrupted
# ---------------------------------------------------------------------------


def test_s8_fail_closed_no_unwanted_send():
    print("S8: fail-closed: invalid binding/route/result/policy -> nothing sent, state intact")

    # --- Pre-create a valid prior state to prove no corruption ---------------
    prior_core, prior_calls, prior_tracker, prior_integration = make_world(
        StopPolicy.NONE
    )
    prior_order = make_order(SYM_A, price=100, quantity=5)
    prior_plan = build_plan([prior_order], [ACC1], [BROKER_A], plan_id="s8-prior")
    attach_accounts(prior_plan, {ACC1: make_account(ACC1)})

    _, prior_batch = dispatch_plan(
        prior_integration, prior_plan, "exec-s8-prior", prior_calls
    )
    prior_result = record_results(
        prior_integration, "exec-s8-prior", prior_plan, prior_batch
    )
    assert prior_result == {0: ExecutionStatus.REGISTERED}
    prior_records = dict(prior_tracker._order_records)

    # --- Case 1: incomplete account binding -> raises, nothing sent ----------
    order = make_order(SYM_A, price=100, quantity=5)
    bad_plan = build_plan([order], [ACC1], [BROKER_A], plan_id="s8-bind1")
    attach_accounts(bad_plan, {ACC1: make_account(ACC1)})
    bad_plan.conditions["binding"][0].pop("account_id")

    _, bad_calls, bad_tracker, bad_integration = make_world(StopPolicy.NONE)
    expect_raises(
        DispatchIntegrationError,
        lambda: bad_integration.dispatch(bad_plan, execution_id="exec-s8-b1"),
        "S8: incomplete account_id binding",
    )
    assert bad_calls == []
    assert bad_tracker._records == {}
    assert bad_tracker._order_records == {}

    # --- Case 2: blank account_id -> raises, nothing sent -------------------
    order2 = make_order(SYM_A, price=100, quantity=5)
    bad_plan2 = build_plan([order2], [ACC1], [BROKER_A], plan_id="s8-bind2")
    attach_accounts(bad_plan2, {ACC1: make_account(ACC1)})
    bad_plan2.conditions["binding"][0]["account_id"] = "  "

    _, bad_calls2, bad_tracker2, bad_integration2 = make_world(StopPolicy.NONE)
    expect_raises(
        DispatchIntegrationError,
        lambda: bad_integration2.dispatch(bad_plan2, execution_id="exec-s8-b2"),
        "S8: blank account_id binding",
    )
    assert bad_calls2 == []
    assert bad_tracker2._records == {}

    # --- Case 3: unknown broker in binding -> engine not called ---------------
    # The plan uses a broker_name not in the broker_manager
    order3 = make_order(SYM_A, price=100, quantity=5)
    bad_plan3 = build_plan(
        [order3], [ACC1], [BROKER_A], plan_id="s8-broker"
    )
    attach_accounts(bad_plan3, {ACC1: make_account(ACC1)})

    _, bad_calls3, bad_tracker3, bad_integration3 = make_world(
        StopPolicy.NONE,
        broker_names=(BROKER_B,),
    )
    # DispatchCore.dispatch will fail because broker-a is not in the manager
    # The manager only has broker-b; get("broker-a") raises KeyError -> ValueError
    # DispatchCore catches it -> DispatchResult(success=False, mode="BLOCKED)
    outcome3 = bad_integration3.dispatch(bad_plan3, execution_id="exec-s8-b3")
    assert outcome3.success is False
    assert outcome3.mode == "BLOCKED"
    assert bad_calls3 == []
    # Integration registers the execution + order record BEFORE delegating
    # to DispatchCore, so the record exists even when broker resolution fails.
    assert ("exec-s8-b3", 0) in bad_tracker3._order_records

    # --- Case 4: route mismatch (binding says broker-a, routes say broker-b)
    order4 = make_order(SYM_A, price=100, quantity=5)
    bad_plan4 = build_plan(
        [order4], [ACC1], [BROKER_A], plan_id="s8-route"
    )
    attach_accounts(bad_plan4, {ACC1: make_account(ACC1)})
    bad_plan4.account_routes[ACC1] = BROKER_B  # mismatch

    _, bad_calls4, bad_tracker4, bad_integration4 = make_world(StopPolicy.NONE)
    outcome4 = bad_integration4.dispatch(bad_plan4, execution_id="exec-s8-b4")
    assert outcome4.success is False
    assert outcome4.mode == "BLOCKED"
    assert bad_calls4 == []

    # --- Case 5: invalid result type on record_order_result ------------------
    valid_order = make_order(SYM_A, price=100, quantity=5)
    valid_plan = build_plan([valid_order], [ACC1], [BROKER_A], plan_id="s8-rv")
    attach_accounts(valid_plan, {ACC1: make_account(ACC1)})

    _, v_calls, v_tracker, v_integration = make_world(StopPolicy.NONE)
    v_integration.dispatch(valid_plan, execution_id="exec-s8-v")

    before_statuses = statuses(v_integration, "exec-s8-v", (0,))
    for bad_result in (None, "ok", Mock(), 123):
        expect_raises(
            DispatchIntegrationError,
            lambda r=bad_result: v_integration.record_order_result(
                "exec-s8-v", 0, r
            ),
            f"S8: invalid result type {bad_result!r}",
        )
    assert statuses(v_integration, "exec-s8-v", (0,)) == before_statuses

    # --- Case 6: invalid policy value -> raises on construction --------------
    expect_raises(
        DispatchIntegrationError,
        lambda: DispatchIntegration(
            Mock(), tracker=ExecutionTracker(), brake_policy="GLOBAL"
        ),
        "S8: raw-string policy rejected",
    )
    expect_raises(
        DispatchIntegrationError,
        lambda: DispatchIntegration(
            Mock(), tracker=ExecutionTracker(), brake_policy=123
        ),
        "S8: numeric policy rejected",
    )
    expect_raises(
        StopBrakePolicyError,
        lambda: StopBrakePolicy(policy="NONE"),
        "S8: raw-string StopBrakePolicy rejected",
    )

    # --- Case 7: invalid Account model --------------------------------------
    expect_raises(
        AccountValidationError,
        lambda: Account(account_id=""),
        "S8: empty account_id rejected",
    )
    expect_raises(
        AccountValidationError,
        lambda: Account(account_id="   "),
        "S8: blank account_id rejected",
    )
    expect_raises(
        AccountValidationError,
        lambda: Account(account_id=123),
        "S8: non-string account_id rejected",
    )

    # --- Prior state untouched after all of the above -----------------------
    assert prior_integration.last_execution_id == "exec-s8-prior"
    assert statuses(prior_integration, "exec-s8-prior", (0,)) == {
        0: ExecutionStatus.REGISTERED,
    }
    assert prior_tracker._order_records == prior_records

    print()


# ---------------------------------------------------------------------------
# S9 — Dry-run: live=False everywhere in the full chain
# ---------------------------------------------------------------------------


def test_s9_dry_run_everywhere():
    print("S9: live=False at every boundary in the full chain")

    for policy in ALL_POLICIES:
        order_a = make_order(SYM_A, price=100, quantity=5)
        order_b = make_order(SYM_B, price=200, quantity=7)
        core, calls, tracker, integration = make_world(
            policy, result_fn=result_by_account({ACC1})
        )
        plan = build_plan(
            [order_a, order_b],
            [ACC1, ACC2],
            [BROKER_A, BROKER_B],
            plan_id=f"s9-{policy.value}",
        )
        attach_accounts(
            plan, {ACC1: make_account(ACC1), ACC2: make_account(ACC2)}
        )

        _, batch = dispatch_plan(
            integration, plan, f"exec-s9-{policy.value}", calls
        )

        # Every engine call was dry-run
        assert all(call["live"] is False for call in calls)

        # Core itself is dry-run only
        assert core.live_trading_enabled is False

        # Record results
        record_results(
            integration, f"exec-s9-{policy.value}", plan, batch,
            arrival=(1, 0),  # FAILED arrives first
        )

        # What was already sent stays dry-run
        assert all(call["live"] is False for call in calls)
        assert len(calls) == 2

        # The mock results are in dry-run mode (sent=False)
        assert all(call["result"].sent is False for call in calls)

    print()


# ---------------------------------------------------------------------------
# S10 — Isolation: Account/Broker/Symbol/Order never mix
# ---------------------------------------------------------------------------


def test_s10_isolation_account_broker_symbol_order():
    print("S10: no cross-contamination in Account/Broker/Symbol/Order")

    order_a = make_order(SYM_A, price=100, quantity=5)
    order_b = make_order(SYM_B, price=200, quantity=7)
    order_c = make_order(SYM_C, price=300, quantity=3)

    plan = build_plan(
        [order_a, order_b, order_c],
        [ACC1, ACC2, ACC1],
        [BROKER_A, BROKER_B, BROKER_A],
    )
    attach_accounts(
        plan, {ACC1: make_account(ACC1), ACC2: make_account(ACC2)}
    )

    core, calls, tracker, integration = make_world(
        StopPolicy.NONE,
        result_fn=result_by_account({ACC1}),
    )

    outcome, batch = dispatch_plan(integration, plan, "exec-s10", calls)
    assert outcome.mode in ("ALL_PROCESSED", "BLOCKED")
    assert outcome.order_count == 3

    by_seq = results_by_sequence(plan, batch)

    # --- Account isolation: each sequence's account matches binding -----------
    assert accounts_of(integration, "exec-s10", (0, 1, 2)) == {
        0: ACC1,
        1: ACC2,
        2: ACC1,
    }
    assert set(accounts_of(integration, "exec-s10", (0, 1, 2)).values()) == {ACC1, ACC2}
    # Account identity is NEVER a symbol, broker, or order field
    all_identities = set(accounts_of(integration, "exec-s10", (0, 1, 2)).values())
    assert all_identities.isdisjoint({SYM_A, SYM_B, SYM_C, BROKER_A, BROKER_B})

    # --- Broker isolation: each call uses the correct broker for its account --
    seq_to_broker_name = {}
    for call in calls:
        seq = sequence_of(plan, call["order"])
        seq_to_broker_name[seq] = call["broker"].name

    assert seq_to_broker_name[0] == BROKER_A
    assert seq_to_broker_name[1] == BROKER_B
    assert seq_to_broker_name[2] == BROKER_A

    # --- Symbol isolation: each order's symbol stays intact ------------------
    for seq, expected_sym in ((0, SYM_A), (1, SYM_B), (2, SYM_C)):
        assert plan.orders[sorted(plan.execution_order).index(seq)].nsc_id == expected_sym

    # --- Order isolation: per-order quantities and prices are preserved -------
    for seq, expected_price, expected_qty in ((0, 100, 5), (1, 200, 7), (2, 300, 3)):
        idx = sorted(plan.execution_order).index(seq)
        assert plan.orders[idx].price == expected_price
        assert plan.orders[idx].quantity == expected_qty

    # --- Record isolation: each order has its own record ---------------------
    rec0 = tracker.get_order_record("exec-s10", 0)
    rec1 = tracker.get_order_record("exec-s10", 1)
    rec2 = tracker.get_order_record("exec-s10", 2)
    assert rec0 is not rec1 and rec0 is not rec2 and rec1 is not rec2

    # --- Status isolation: results arrive out of order -----------------------
    res_statuses = record_results(
        integration, "exec-s10", plan, batch, arrival=(2, 0, 1)
    )
    assert res_statuses == {
        0: ExecutionStatus.REGISTERED,
        1: ExecutionStatus.FAILED,
        2: ExecutionStatus.REGISTERED,
    }

    # Each result touched exactly one order; others are untouched
    assert tracker.get_order_status("exec-s10", 0) == ExecutionStatus.REGISTERED
    assert tracker.get_order_status("exec-s10", 1) == ExecutionStatus.FAILED
    assert tracker.get_order_status("exec-s10", 2) == ExecutionStatus.REGISTERED

    # Record identity is preserved (not replaced)
    assert tracker.get_order_record("exec-s10", 0) is rec0
    assert tracker.get_order_record("exec-s10", 1) is rec1
    assert tracker.get_order_record("exec-s10", 2) is rec2

    # Dispatch-level record untouched
    assert tracker.get_status("exec-s10") == ExecutionStatus.PENDING

    print()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main():
    tests = [
        test_s1_e2e_three_orders_two_accounts_two_brokers,
        test_s2_two_orders_one_account_stay_independent,
        test_s3_same_symbol_different_accounts_independent,
        test_s4_account_brake_e2e,
        test_s5_global_brake_e2e,
        test_s6_none_policy_e2e,
        test_s7_results_arrive_in_different_order,
        test_s8_fail_closed_no_unwanted_send,
        test_s9_dry_run_everywhere,
        test_s10_isolation_account_broker_symbol_order,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {test.__name__}: {exc}")
        except Exception:
            failed += 1
            print(f"  ERROR {test.__name__}")
            import traceback
            traceback.print_exc()

    print()
    print("=" * 50)
    print(f"SCENARIOS PASSED: {passed}")
    print(f"SCENARIOS FAILED: {failed}")
    print("=" * 50)

    if failed:
        sys.exit(1)

    print(
        f"\nAll Block 6 Task 7 Integration & Regression tests passed. "
        f"({len(tests)} scenarios)"
    )


if __name__ == "__main__":
    main()
