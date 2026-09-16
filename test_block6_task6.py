"""
Block 6 — Task 6.6: Multi-Account Stop/Brake Policy tests.

Architectural principle under test:

    one ExecutionPlan (one account per dispatch unit)
        -> orders executed through the existing DispatchCore / OrderEngine path
        -> each per-order OrderExecutionResult is tracked on its OWN record
           (Task 6.5) and fed to ONE explicit Stop/Brake policy:

               NONE     no brake is ever activated by a per-order result
               ACCOUNT  the first successful REGISTERED result of an account
                        brakes THAT account only
               GLOBAL   the first successful REGISTERED result of ANY account
                        brakes the whole run

Rules verified here:

  * The policy is an explicit value (``StopPolicy.NONE`` / ``ACCOUNT`` /
    ``GLOBAL``); a raw string or any other object is rejected (fail-closed).
  * Only a successful ``REGISTERED`` result activates a brake. A ``FAILED``
    result never stops anything.
  * A brake gates FUTURE dispatches only: orders that were already sent are
    neither cancelled, stopped, nor modified.
  * ``ACCOUNT`` is per-account: braking account A never stops account B, and
    braking account B never stops account A.
  * ``GLOBAL``: the first successful REGISTERED result of ANY account stops
    the future dispatches of ALL accounts.
  * The decision depends only on (policy, account identity, result status) —
    never on an order index nor on the order in which results arrive.
  * ``account_id`` is always the account bound to that order's sequence; it is
    never ``accounts[0]``, a symbol, a broker, an index, or a default.
  * Account-aware tracking (Task 6.5) keeps working: per-order statuses stay
    independent, and a recorded result still touches exactly one order.
  * Fail-closed: an invalid policy value, an invalid / unknown account, or an
    order record without a valid account identity raises before any status or
    brake state changes.
  * Everything stays dry-run (``live=False``); no API, no broker call, no
    live trading, no scheduler is added.

Proven scenarios (offline, stubs only):

    S1   NONE     -> every account keeps dispatching
    S2   ACCOUNT  -> REGISTERED of ACC-1 brakes ACC-1 only; ACC-2 continues
    S3   ACCOUNT  -> REGISTERED of ACC-2 brakes ACC-2 only; ACC-1 continues
    S4   GLOBAL   -> REGISTERED of one account stops the future dispatches of
                     all accounts
    S5   FAILED   -> no brake is activated, for every policy
    S6   already sent orders stay untouched after a brake
    S7   the policy is independent of result arrival order and of order index
    S8   invalid / unknown account identity -> fail-closed
    S9   invalid policy value -> fail-closed
    S10  dry-run preserved and Task 6.5 tracking intact

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


def build_plan(orders, account_ids, broker_names, plan_id="t66-plan"):
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


def account_plan(account_id, order, plan_id, broker_name=None):
    """One single-order plan whose only order belongs to ``account_id``."""
    if broker_name is None:
        broker_name = BROKER_A if account_id == ACC1 else BROKER_B
    plan = build_plan([order], [account_id], [broker_name], plan_id=plan_id)
    return attach_accounts(plan, {account_id: make_account(account_id)})


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


def make_world(brake_policy=None, result_fn=None):
    """A fresh (core, calls, tracker, integration) world.

    ``brake_policy`` is passed through unchanged, so the caller controls
    whether an explicit policy value, a built policy, an invalid value, or
    nothing at all (``None`` -> default ``StopPolicy.NONE``) is used.
    """
    core, calls = make_core(
        result_fn=result_fn, broker_names=(BROKER_A, BROKER_B)
    )
    tracker = ExecutionTracker()
    integration = DispatchIntegration(
        core, tracker=tracker, brake_policy=brake_policy
    )
    return core, calls, tracker, integration
# ---------------------------------------------------------------------------
# Dispatch / record helpers
# ---------------------------------------------------------------------------


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
    order), so a scenario can prove that the policy is arrival-order
    independent. Returns ``{sequence: ExecutionStatus}``.
    """
    by_sequence = results_by_sequence(plan, calls)
    order = sorted(by_sequence) if arrival is None else list(arrival)
    assert sorted(order) == sorted(by_sequence), (
        f"arrival {order} does not cover the sequences {sorted(by_sequence)}"
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
    except Exception as exc:  # pragma: no cover - diagnostic path
        raise AssertionError(
            f"{label}: expected {exc_type.__name__}, got {exc!r}"
        )
    raise AssertionError(f"{label}: expected {exc_type.__name__}, nothing raised")


# ---------------------------------------------------------------------------
# S1 — NONE: every account keeps dispatching
# ---------------------------------------------------------------------------


def test_s1_none_policy_keeps_every_account_sending():
    print("S1: policy NONE -> a successful result of any account brakes nothing")
    core, calls, tracker, integration = make_world(StopPolicy.NONE)
    policy = integration.brake_policy
    assert policy.policy is StopPolicy.NONE

    plan_a = account_plan(ACC1, make_order(SYM_A, price=100, quantity=5), "p1-a")
    plan_b = account_plan(ACC2, make_order(SYM_B, price=200, quantity=7), "p1-b")

    outcome_a, calls_a = dispatch_plan(integration, plan_a, "exec-1a", calls)
    outcome_b, calls_b = dispatch_plan(integration, plan_b, "exec-1b", calls)
    assert outcome_a.mode != STOPPED_MODE
    assert outcome_b.mode != STOPPED_MODE
    assert len(calls) == 2

    # Both accounts register successfully...
    assert record_results(integration, "exec-1a", plan_a, calls_a) == {
        0: ExecutionStatus.REGISTERED
    }
    assert record_results(integration, "exec-1b", plan_b, calls_b) == {
        0: ExecutionStatus.REGISTERED
    }

    # ...and NOTHING is braked by a per-order result.
    assert integration.stopped_accounts == ()
    assert policy.is_global_stopped is False
    assert policy.is_account_stopped(ACC1) is False
    assert policy.is_account_stopped(ACC2) is False
    assert policy.account_signal(ACC1) is None
    assert policy.should_continue([ACC1, ACC2]) is True

    # Every account keeps sending.
    plan_a2 = account_plan(ACC1, make_order(SYM_A, price=101, quantity=5), "p1-a2")
    plan_b2 = account_plan(ACC2, make_order(SYM_B, price=201, quantity=7), "p1-b2")
    outcome_a2, calls_a2 = dispatch_plan(integration, plan_a2, "exec-1a2", calls)
    outcome_b2, calls_b2 = dispatch_plan(integration, plan_b2, "exec-1b2", calls)

    assert outcome_a2.mode != STOPPED_MODE
    assert outcome_b2.mode != STOPPED_MODE
    assert [c["order"] for c in calls_a2] == [plan_a2.orders[0]]
    assert [c["order"] for c in calls_b2] == [plan_b2.orders[0]]
    assert len(calls) == 4

    # The default (no explicit policy) behaves exactly like NONE.
    _, _, _, default_integration = make_world()
    assert default_integration.brake_policy.policy is StopPolicy.NONE
    print()
# ---------------------------------------------------------------------------
# S2 — ACCOUNT: REGISTERED of ACC-1 brakes ACC-1 only; ACC-2 continues
# ---------------------------------------------------------------------------


def test_s2_account_policy_brakes_only_the_registered_account():
    print("S2: policy ACCOUNT -> REGISTERED of ACC-1 brakes ACC-1 only")
    success = {ACC1}
    core, calls, tracker, integration = make_world(
        StopPolicy.ACCOUNT, result_fn=result_by_account(success)
    )
    policy = integration.brake_policy
    assert policy.policy is StopPolicy.ACCOUNT

    plan_a1 = account_plan(ACC1, make_order(SYM_A, price=100, quantity=5), "p2-a1")
    plan_b1 = account_plan(ACC2, make_order(SYM_B, price=200, quantity=7), "p2-b1")

    _, calls_a1 = dispatch_plan(integration, plan_a1, "exec-2a1", calls)
    _, calls_b1 = dispatch_plan(integration, plan_b1, "exec-2b1", calls)
    assert len(calls) == 2, "nothing is braked before any result arrives"
    assert policy.should_continue([ACC1, ACC2]) is True

    # ACC-1 registers successfully; ACC-2's order is blocked.
    assert record_results(integration, "exec-2a1", plan_a1, calls_a1) == {
        0: ExecutionStatus.REGISTERED
    }
    assert record_results(integration, "exec-2b1", plan_b1, calls_b1) == {
        0: ExecutionStatus.FAILED
    }

    # ONLY ACC-1 is braked, and it is braked exactly once.
    assert integration.stopped_accounts == (ACC1,)
    assert policy.stopped_accounts() == (ACC1,)
    assert policy.is_account_stopped(ACC1) is True
    assert policy.is_account_stopped(ACC2) is False
    assert policy.account_signal(ACC1).activation_count == 1
    assert policy.account_signal(ACC2) is None
    assert policy.is_global_stopped is False

    # The gate itself is per-account.
    assert policy.should_continue([ACC1]) is False
    assert policy.should_continue([ACC2]) is True

    # A new dispatch of ACC-1 is bypassed: nothing registered, nothing sent.
    before_calls = len(calls)
    before_records = dict(tracker._order_records)
    plan_a2 = account_plan(ACC1, make_order(SYM_A, price=101, quantity=5), "p2-a2")
    stopped, stopped_calls = dispatch_plan(integration, plan_a2, "exec-2a2", calls)

    assert stopped.mode == STOPPED_MODE
    assert stopped.success is False and stopped.sent is False
    assert stopped_calls == []
    assert len(calls) == before_calls, "no order may be sent for a braked account"
    assert "exec-2a2" not in tracker._records
    assert tracker._order_records == before_records

    # ...while ACC-2 keeps sending, through ITS OWN account and broker.
    # ACC-2's own order now succeeds: it brakes ACC-2 as well, independently.
    success.add(ACC2)
    plan_b2 = account_plan(ACC2, make_order(SYM_B, price=201, quantity=7), "p2-b2")
    allowed, allowed_calls = dispatch_plan(integration, plan_b2, "exec-2b2", calls)

    assert allowed.mode != STOPPED_MODE
    assert [c["order"] for c in allowed_calls] == [plan_b2.orders[0]]
    assert allowed_calls[0]["account"].account_id == ACC2
    assert allowed_calls[0]["broker"].name == BROKER_B
    assert allowed_calls[0]["live"] is False

    assert record_results(integration, "exec-2b2", plan_b2, allowed_calls) == {
        0: ExecutionStatus.REGISTERED
    }
    assert integration.stopped_accounts == (ACC1, ACC2)
    assert policy.account_signal(ACC2).activation_count == 1
    assert policy.account_signal(ACC1).activation_count == 1

    # Each account is stopped through its OWN gate; both are now bypassed.
    plan_a3 = account_plan(ACC1, make_order(SYM_A, price=102, quantity=5), "p2-a3")
    plan_b3 = account_plan(ACC2, make_order(SYM_B, price=202, quantity=7), "p2-b3")
    for plan, execution_id in ((plan_a3, "exec-2a3"), (plan_b3, "exec-2b3")):
        stopped_again, stopped_calls = dispatch_plan(
            integration, plan, execution_id, calls
        )
        assert stopped_again.mode == STOPPED_MODE
        assert stopped_calls == []
        assert execution_id not in tracker._records
    print()


# ---------------------------------------------------------------------------
# S3 — ACCOUNT: REGISTERED of ACC-2 brakes ACC-2 only; ACC-1 continues
# ---------------------------------------------------------------------------


def test_s3_account_policy_is_symmetric():
    print("S3: policy ACCOUNT -> REGISTERED of ACC-2 brakes ACC-2 only")
    core, calls, tracker, integration = make_world(
        StopPolicy.ACCOUNT, result_fn=result_by_account({ACC2})
    )
    policy = integration.brake_policy

    plan_a1 = account_plan(ACC1, make_order(SYM_A, price=110, quantity=4), "p3-a1")
    plan_b1 = account_plan(ACC2, make_order(SYM_B, price=210, quantity=6), "p3-b1")

    _, calls_a1 = dispatch_plan(integration, plan_a1, "exec-3a1", calls)
    _, calls_b1 = dispatch_plan(integration, plan_b1, "exec-3b1", calls)

    # ACC-1 fails, ACC-2 registers successfully.
    assert record_results(integration, "exec-3a1", plan_a1, calls_a1) == {
        0: ExecutionStatus.FAILED
    }
    assert record_results(integration, "exec-3b1", plan_b1, calls_b1) == {
        0: ExecutionStatus.REGISTERED
    }

    assert integration.stopped_accounts == (ACC2,)
    assert policy.is_account_stopped(ACC2) is True
    assert policy.is_account_stopped(ACC1) is False
    assert policy.should_continue([ACC2]) is False
    assert policy.should_continue([ACC1]) is True

    # ACC-2's new dispatch is bypassed...
    before_calls = len(calls)
    plan_b2 = account_plan(ACC2, make_order(SYM_B, price=211, quantity=6), "p3-b2")
    stopped, stopped_calls = dispatch_plan(integration, plan_b2, "exec-3b2", calls)

    assert stopped.mode == STOPPED_MODE
    assert stopped_calls == []
    assert len(calls) == before_calls
    assert "exec-3b2" not in tracker._records
    assert "exec-3b2" not in tracker._order_records

    # ...while ACC-1 keeps sending.
    plan_a2 = account_plan(ACC1, make_order(SYM_A, price=111, quantity=4), "p3-a2")
    allowed, allowed_calls = dispatch_plan(integration, plan_a2, "exec-3a2", calls)

    assert allowed.mode != STOPPED_MODE
    assert allowed_calls[0]["account"].account_id == ACC1
    assert allowed_calls[0]["broker"].name == BROKER_A
    assert ("exec-3a2", 0) in tracker._order_records
    assert statuses(integration, "exec-3a2", (0,)) == {
        0: ExecutionStatus.PENDING
    }
    print()
# ---------------------------------------------------------------------------
# S4 — GLOBAL: REGISTERED of one account stops the future dispatches of ALL
# ---------------------------------------------------------------------------


def test_s4_global_policy_brakes_every_account():
    print("S4: policy GLOBAL -> REGISTERED of one account stops every account")
    for success_account, other_account in ((ACC1, ACC2), (ACC2, ACC1)):
        success = {success_account}
        core, calls, tracker, integration = make_world(
            StopPolicy.GLOBAL, result_fn=result_by_account(success)
        )
        policy = integration.brake_policy
        assert policy.policy is StopPolicy.GLOBAL

        plan_first = account_plan(
            success_account, make_order(SYM_A, price=100, quantity=5), "p4-first"
        )
        plan_other = account_plan(
            other_account, make_order(SYM_B, price=200, quantity=7), "p4-other"
        )

        _, calls_first = dispatch_plan(integration, plan_first, "exec-4-first", calls)
        _, calls_other = dispatch_plan(integration, plan_other, "exec-4-other", calls)
        assert policy.should_continue([ACC1, ACC2]) is True, "nothing braked yet"
        assert policy.is_global_stopped is False

        # The FIRST registered order of ANY account brakes the whole run.
        assert record_results(integration, "exec-4-first", plan_first, calls_first) == {
            0: ExecutionStatus.REGISTERED
        }
        assert policy.is_global_stopped is True
        assert policy.global_signal.activation_count == 1
        assert policy.should_continue([ACC1]) is False
        assert policy.should_continue([ACC2]) is False
        assert policy.should_continue([success_account, other_account]) is False

        # GLOBAL keeps no per-account gate: the run is braked as a whole.
        assert integration.stopped_accounts == ()
        assert policy.account_signal(ACC1) is None
        assert policy.account_signal(ACC2) is None

        # A second result never re-activates the (latched) global gate.
        assert record_results(integration, "exec-4-other", plan_other, calls_other) == {
            0: ExecutionStatus.FAILED
        }
        assert policy.global_signal.activation_count == 1

        # Future dispatches of EVERY account are bypassed.
        before_calls = len(calls)
        for account_id, execution_id in ((ACC1, "exec-4-a2"), (ACC2, "exec-4-b2")):
            plan = account_plan(
                account_id, make_order(SYM_A, price=101, quantity=5), f"p4-{account_id}"
            )
            stopped, stopped_calls = dispatch_plan(
                integration, plan, execution_id, calls
            )
            assert stopped.mode == STOPPED_MODE
            assert stopped.success is False and stopped.sent is False
            assert stopped_calls == []
            assert execution_id not in tracker._records
        assert len(calls) == before_calls, "no order may be sent at all"

        # Even a plan that carries no order is not sent once the run is braked.
        empty = ExecutionPlan()
        stopped_empty = integration.dispatch(empty, execution_id="exec-4-empty")
        assert stopped_empty.mode == STOPPED_MODE
        assert "exec-4-empty" not in tracker._records
    print()


# ---------------------------------------------------------------------------
# S5 — FAILED never activates a brake
# ---------------------------------------------------------------------------


def test_s5_failed_result_never_activates_a_brake():
    print("S5: a FAILED result never activates a brake (NONE / ACCOUNT / GLOBAL)")
    for policy_value in ALL_POLICIES:
        tag = policy_value.value
        core, calls, tracker, integration = make_world(
            policy_value,
            result_fn=lambda order, account: blocked_order_result(order),
        )
        policy = integration.brake_policy
        assert policy.policy is policy_value

        plan_a = account_plan(ACC1, make_order(SYM_A, price=100, quantity=5), f"p5-{tag}-a")
        plan_b = account_plan(ACC2, make_order(SYM_B, price=200, quantity=7), f"p5-{tag}-b")
        _, calls_a = dispatch_plan(integration, plan_a, f"exec-5{tag}a", calls)
        _, calls_b = dispatch_plan(integration, plan_b, f"exec-5{tag}b", calls)

        # Every order of every account is blocked.
        assert record_results(integration, f"exec-5{tag}a", plan_a, calls_a) == {
            0: ExecutionStatus.FAILED
        }
        assert record_results(integration, f"exec-5{tag}b", plan_b, calls_b) == {
            0: ExecutionStatus.FAILED
        }

        # No brake was activated by any of them.
        assert integration.stopped_accounts == ()
        assert policy.is_global_stopped is False
        assert policy.is_account_stopped(ACC1) is False
        assert policy.is_account_stopped(ACC2) is False
        assert policy.should_continue([ACC1, ACC2]) is True

        # Both accounts keep dispatching.
        plan_a2 = account_plan(ACC1, make_order(SYM_A, price=101, quantity=5), f"p5-{tag}-a2")
        plan_b2 = account_plan(ACC2, make_order(SYM_B, price=201, quantity=7), f"p5-{tag}-b2")
        outcome_a2, calls_a2 = dispatch_plan(integration, plan_a2, f"exec-5{tag}a2", calls)
        outcome_b2, calls_b2 = dispatch_plan(integration, plan_b2, f"exec-5{tag}b2", calls)

        assert outcome_a2.mode != STOPPED_MODE
        assert outcome_b2.mode != STOPPED_MODE
        assert len(calls_a2) == 1 and len(calls_b2) == 1
        assert calls_a2[0]["account"].account_id == ACC1
        assert calls_b2[0]["account"].account_id == ACC2
    print()
# ---------------------------------------------------------------------------
# S6 — orders that were already sent stay untouched by a brake
# ---------------------------------------------------------------------------


def test_s6_orders_already_sent_stay_untouched_by_a_brake():
    print("S6: a brake gates FUTURE dispatches only")
    core, calls, tracker, integration = make_world(
        StopPolicy.ACCOUNT, result_fn=result_by_account({ACC1})
    )
    plan_a1 = account_plan(ACC1, make_order(SYM_A, price=100, quantity=5), "p6-a1")
    plan_b1 = account_plan(ACC2, make_order(SYM_B, price=200, quantity=7), "p6-b1")

    outcome_a1, calls_a1 = dispatch_plan(integration, plan_a1, "exec-6a1", calls)
    outcome_b1, calls_b1 = dispatch_plan(integration, plan_b1, "exec-6b1", calls)
    assert outcome_a1.mode != STOPPED_MODE and outcome_b1.mode != STOPPED_MODE

    # Both dispatches were issued — and are remembered as PENDING — BEFORE any
    # result arrived.
    assert tracker.get_status("exec-6a1") is ExecutionStatus.PENDING
    assert tracker.get_status("exec-6b1") is ExecutionStatus.PENDING

    # ACC-1's result is a success (brakes ACC-1); ACC-2's is a failure.
    record_results(integration, "exec-6a1", plan_a1, calls_a1)
    record_results(integration, "exec-6b1", plan_b1, calls_b1)
    assert integration.stopped_accounts == (ACC1,)

    # Snapshot everything that was already sent / recorded / resolved.
    record_a1 = records_of(integration, "exec-6a1", (0,))
    record_b1 = records_of(integration, "exec-6b1", (0,))
    sent_orders = [c["order"] for c in calls]
    sent_accounts = [c["account"].account_id for c in calls]
    engine_calls = core.order_engine.execute_by_ins_code.call_count
    broker_lookups = core.broker_manager.get.call_count
    dispatch_records = dict(tracker._records)

    # A new dispatch of the braked account is bypassed.
    plan_a2 = account_plan(ACC1, make_order(SYM_A, price=101, quantity=5), "p6-a2")
    stopped, stopped_calls = dispatch_plan(integration, plan_a2, "exec-6a2", calls)
    assert stopped.mode == STOPPED_MODE
    assert stopped_calls == []

    # Nothing that was already sent changed: same orders, same accounts, and
    # the Dispatch Core — hence the OrderEngine and the broker layer — was not
    # touched at all. (There is no cancel / modify path in this stack, so "not
    # invoked again" is the strongest available proof.)
    assert [c["order"] for c in calls] == sent_orders
    assert [c["account"].account_id for c in calls] == sent_accounts
    assert core.order_engine.execute_by_ins_code.call_count == engine_calls
    assert core.broker_manager.get.call_count == broker_lookups
    assert tracker._records == dispatch_records

    # Their per-order records are the very same objects, with the same status.
    assert records_of(integration, "exec-6a1", (0,))[0] is record_a1[0]
    assert records_of(integration, "exec-6b1", (0,))[0] is record_b1[0]
    assert tracker.get_order_status("exec-6a1", 0) is ExecutionStatus.REGISTERED
    assert tracker.get_order_status("exec-6b1", 0) is ExecutionStatus.FAILED
    assert tracker.get_order_record("exec-6b1", 0).account_id == ACC2

    # The braked set is unchanged: ACC-2 is still free to send.
    assert integration.stopped_accounts == (ACC1,)
    plan_b2 = account_plan(ACC2, make_order(SYM_B, price=201, quantity=7), "p6-b2")
    allowed, allowed_calls = dispatch_plan(integration, plan_b2, "exec-6b2", calls)
    assert allowed.mode != STOPPED_MODE
    assert len(allowed_calls) == 1
    print()
# ---------------------------------------------------------------------------
# S7 — the policy ignores the arrival order of results and the order index
# ---------------------------------------------------------------------------


def test_s7_policy_is_independent_of_arrival_order_and_index():
    print("S7: the decision depends only on (policy, account, result status)")

    # --- ACCOUNT: both arrival orders end in the same state --------------
    states = []
    for arrival in ((0, 1), (1, 0)):
        order_a = make_order(SYM_A, price=100, quantity=5)
        order_b = make_order(SYM_B, price=200, quantity=7)
        core, calls, tracker, integration = make_world(
            StopPolicy.ACCOUNT, result_fn=result_by_account({ACC1})
        )
        plan = build_plan(
            [order_a, order_b], [ACC1, ACC2], [BROKER_A, BROKER_B], plan_id="p7-mix"
        )
        attach_accounts(plan, {ACC1: make_account(ACC1), ACC2: make_account(ACC2)})
        _, batch = dispatch_plan(integration, plan, "exec-7-mix", calls)

        results = record_results(
            integration, "exec-7-mix", plan, batch, arrival=arrival
        )
        states.append((integration.stopped_accounts, results))

    assert states[0] == states[1], "arrival order changed the outcome"
    assert states[0][0] == (ACC1,)
    assert states[0][1] == {
        0: ExecutionStatus.REGISTERED,
        1: ExecutionStatus.FAILED,
    }

    # --- ACCOUNT: the order index does not influence the decision --------
    observed_sequences = []
    braked_sets = []
    for orders, accounts, brokers in (
        (
            [
                make_order(SYM_A, price=100, quantity=5),
                make_order(SYM_B, price=200, quantity=7),
            ],
            [ACC1, ACC2],
            [BROKER_A, BROKER_B],
        ),
        (
            [
                make_order(SYM_B, price=200, quantity=7),
                make_order(SYM_A, price=100, quantity=5),
            ],
            [ACC2, ACC1],
            [BROKER_B, BROKER_A],
        ),
    ):
        core, calls, tracker, integration = make_world(
            StopPolicy.ACCOUNT, result_fn=result_by_account({ACC1})
        )
        plan = build_plan(orders, accounts, brokers, plan_id="p7-index")
        attach_accounts(plan, {ACC1: make_account(ACC1), ACC2: make_account(ACC2)})
        _, batch = dispatch_plan(integration, plan, "exec-7-index", calls)
        record_results(integration, "exec-7-index", plan, batch)

        acc1_order = next(
            order
            for order in plan.orders
            if plan.conditions["binding"][sequence_of(plan, order)]["account_id"]
            == ACC1
        )
        observed_sequences.append(sequence_of(plan, acc1_order))
        braked_sets.append(integration.stopped_accounts)
        # The account that succeeded is the braked one, wherever it sits.
        assert integration.stopped_accounts == (ACC1,)

    assert observed_sequences == [0, 1], "the ACC-1 order moved between plans"
    assert braked_sets[0] == braked_sets[1] == (ACC1,)

# --- GLOBAL: the FIRST success brakes the run, in either order -------
    for arrival in ((0, 1), (1, 0)):
        order_a = make_order(SYM_A, price=100, quantity=5)
        order_b = make_order(SYM_B, price=200, quantity=7)
        core, calls, tracker, integration = make_world(
            StopPolicy.GLOBAL, result_fn=result_by_account({ACC1})
        )
        policy = integration.brake_policy
        plan = build_plan(
            [order_a, order_b], [ACC1, ACC2], [BROKER_A, BROKER_B], plan_id="p7-g"
        )
        attach_accounts(plan, {ACC1: make_account(ACC1), ACC2: make_account(ACC2)})
        _, batch = dispatch_plan(integration, plan, "exec-7-g", calls)

        by_sequence = results_by_sequence(plan, batch)

        # Which arrival carries the success differs between the two runs; the
        # policy outcome must not: the run is braked exactly from the moment
        # the first success has been seen, and never re-activates afterwards.
        seen_success = False
        for sequence in arrival:
            expected = (
                ExecutionStatus.REGISTERED
                if by_sequence[sequence].success
                else ExecutionStatus.FAILED
            )
            assert (
                integration.record_order_result(
                    "exec-7-g", sequence, by_sequence[sequence]
                )
                is expected
            )
            seen_success = seen_success or by_sequence[sequence].success

            assert policy.is_global_stopped is seen_success
            assert policy.global_signal.activation_count == (
                1 if seen_success else 0
            )
            assert policy.should_continue([ACC1, ACC2]) is (not seen_success)

        assert seen_success is True, "one of the two orders succeeds"
        assert policy.global_signal.activation_count == 1

        # A repeated result of an already seen order changes nothing either.
        success_sequence = next(
            s for s in arrival if by_sequence[s].success
        )
        assert (
            integration.record_order_result(
                "exec-7-g", success_sequence, by_sequence[success_sequence]
            )
            is ExecutionStatus.REGISTERED
        )
        assert policy.global_signal.activation_count == 1
        assert policy.is_global_stopped is True
    print()
# ---------------------------------------------------------------------------
# S8 — invalid / unknown account identity -> fail-closed
# ---------------------------------------------------------------------------


def test_s8_invalid_or_unknown_account_fails_closed():
    print("S8: invalid / unknown account identity -> fail-closed")
    core, calls, tracker, integration = make_world(
        StopPolicy.ACCOUNT, result_fn=result_by_account({ACC1})
    )
    policy = integration.brake_policy
    order = make_order(SYM_A, price=100, quantity=5)
    plan = account_plan(ACC1, order, "p8-a1")
    _, batch = dispatch_plan(integration, plan, "exec-8a1", calls)

    # --- the policy layer rejects an invalid account identity ------------
    for bad in (None, "", "   ", 123, object(), ["ACC-1"]):
        expect_raises(
            StopBrakePolicyError,
            lambda b=bad: policy.validate_account(b),
            f"S8 validate_account({bad!r})",
        )
        expect_raises(
            StopBrakePolicyError,
            lambda b=bad: policy.is_account_stopped(b),
            f"S8 is_account_stopped({bad!r})",
        )
        expect_raises(
            StopBrakePolicyError,
            lambda b=bad: policy.account_signal(b),
            f"S8 account_signal({bad!r})",
        )
        expect_raises(
            StopBrakePolicyError,
            lambda b=bad: policy.should_continue([b]),
            f"S8 should_continue([{bad!r}])",
        )
        expect_raises(
            StopBrakePolicyError,
            lambda b=bad: policy.observe_order_result(b, ok_order_result(order)),
            f"S8 observe_order_result({bad!r})",
        )

    # A collection is required, and the result must be an order result.
    expect_raises(
        StopBrakePolicyError,
        lambda: policy.should_continue(ACC1),
        "S8 should_continue(a bare string)",
    )
    expect_raises(
        StopBrakePolicyError,
        lambda: policy.should_continue(123),
        "S8 should_continue(non-collection)",
    )
    expect_raises(
        StopBrakePolicyError,
        lambda: policy.observe_order_result(ACC1, "REGISTERED"),
        "S8 observe_order_result(wrong result type)",
    )
    expect_raises(
        StopBrakePolicyError,
        lambda: policy.observe_order_result(
            ACC1, DispatchResult(success=True, sent=False, mode="ALL_PROCESSED")
        ),
        "S8 observe_order_result(DispatchResult is not an order result)",
    )

    # Nothing was braked and no status moved.
    assert integration.stopped_accounts == ()
    assert policy.is_global_stopped is False
    assert statuses(integration, "exec-8a1", (0,)) == {0: ExecutionStatus.PENDING}
    assert policy.should_continue([ACC1]) is True

    # --- an order record without a valid account identity is fail-closed --
    record = tracker.get_order_record("exec-8a1", 0)
    record.account_id = None
    expect_raises(
        DispatchIntegrationError,
        lambda: integration.record_order_result(
            "exec-8a1", 0, ok_order_result(order)
        ),
        "S8 record without account identity",
    )
    record.account_id = "   "
    expect_raises(
        DispatchIntegrationError,
        lambda: integration.record_order_result(
            "exec-8a1", 0, ok_order_result(order)
        ),
        "S8 record with blank account identity",
    )
    assert statuses(integration, "exec-8a1", (0,)) == {0: ExecutionStatus.PENDING}
    assert integration.stopped_accounts == ()
    record.account_id = ACC1  # restored

    # --- unknown execution / sequence -> fail-closed ---------------------
    expect_raises(
        ExecutionTrackerError,
        lambda: integration.record_order_result(
            "never-issued", 0, ok_order_result(order)
        ),
        "S8 unknown execution",
    )
    expect_raises(
        ExecutionTrackerError,
        lambda: integration.record_order_result(
            "exec-8a1", 7, ok_order_result(order)
        ),
        "S8 unknown sequence",
    )
    expect_raises(
        DispatchIntegrationError,
        lambda: integration.record_order_result("exec-8a1", 0, "ok"),
        "S8 wrong result type on the integration",
    )
    assert integration.stopped_accounts == ()
    assert statuses(integration, "exec-8a1", (0,)) == {0: ExecutionStatus.PENDING}

    # The good path still works afterwards.
    assert (
        integration.record_order_result("exec-8a1", 0, ok_order_result(order))
        is ExecutionStatus.REGISTERED
    )
    assert integration.stopped_accounts == (ACC1,)
    print()
# ---------------------------------------------------------------------------
# S9 — an invalid policy value fails closed
# ---------------------------------------------------------------------------


def test_s9_invalid_policy_fails_closed():
    print("S9: the policy must be an explicit StopPolicy member (fail-closed)")

    core, calls, tracker, _ = make_world(StopPolicy.NONE)
    order = make_order(SYM_A, price=100, quantity=5)

    # NOTE: StopPolicy is a ``str`` Enum, so ``StopPolicy.ACCOUNT == "ACCOUNT"``
    # is True — yet ONLY the enum member is accepted. The contrast below makes
    # the "explicit value" rule of this task visible.
    assert StopPolicy.ACCOUNT == "ACCOUNT"

    # --- construction rejects every non-member policy value ---------------
    for bad in (
        "ACCOUNT",                  # a raw string, even if it "looks" valid
        "GLOBAL",
        "NONE",
        "",
        None,
        123,
        True,
        StopPolicy,                 # the enum CLASS, not a member
        StopPolicy.GLOBAL.value,    # a plain str, not the enum member
    ):
        expect_raises(
            StopBrakePolicyError,
            lambda b=bad: StopBrakePolicy(policy=b),
            f"S9 StopBrakePolicy(policy={bad!r})",
        )

    # A disabled or foreign global gate can never brake anything -> rejected.
    expect_raises(
        StopBrakePolicyError,
        lambda: StopBrakePolicy(
            StopPolicy.GLOBAL, global_signal=StopSignal(enabled=False)
        ),
        "S9 disabled global gate",
    )
    expect_raises(
        StopBrakePolicyError,
        lambda: StopBrakePolicy(StopPolicy.GLOBAL, global_signal=object()),
        "S9 foreign global gate",
    )

    # The valid form still works: an explicit member + an enabled gate.
    shared = StopSignal(enabled=True)
    built = StopBrakePolicy(StopPolicy.GLOBAL, global_signal=shared)
    assert built.policy is StopPolicy.GLOBAL
    assert built.global_signal is shared

    # --- the integration wiring is fail-closed too -------------------------
    expect_raises(
        DispatchIntegrationError,
        lambda: DispatchIntegration(
            core, tracker=tracker, brake_policy="GLOBAL"
        ),
        "S9 integration with a raw-string policy",
    )
    expect_raises(
        DispatchIntegrationError,
        lambda: DispatchIntegration(
            core, tracker=tracker, brake_policy=123
        ),
        "S9 integration with a numeric policy",
    )

    # Omitted -> the explicit default NONE. A member -> wrapped. A built
    # policy -> used as-is (shared gates, e.g. one run-wide GLOBAL gate).
    omitted = DispatchIntegration(core, tracker=tracker)
    assert omitted.brake_policy.policy is StopPolicy.NONE
    assert omitted.stopped_accounts == ()
    assert DispatchIntegration(
        core, tracker=tracker, brake_policy=StopPolicy.ACCOUNT
    ).brake_policy.policy is StopPolicy.ACCOUNT
    assert (
        DispatchIntegration(
            core, tracker=tracker, brake_policy=built
        ).brake_policy
        is built
    )

    # --- a policy corrupted AFTER construction fails closed on every use ---
    policy = StopBrakePolicy(StopPolicy.NONE)
    policy.policy = "ACCOUNT"  # simulate a mutated attribute
    expect_raises(
        StopBrakePolicyError,
        lambda: policy.observe_order_result(ACC1, ok_order_result(order)),
        "S9 corrupted policy on observe_order_result",
    )
    expect_raises(
        StopBrakePolicyError,
        lambda: policy.should_continue([ACC1]),
        "S9 corrupted policy on should_continue",
    )
    expect_raises(
        StopBrakePolicyError,
        lambda: policy.stopped_accounts(),
        "S9 corrupted policy on stopped_accounts",
    )

    # Nothing was braked and nothing was tracked by any of the above.
    assert calls == []
    assert tracker._records == {}
    assert tracker._order_records == {}
    print()
# ---------------------------------------------------------------------------
# S10 — dry-run preserved and Task 6.5 tracking intact, for every policy
# ---------------------------------------------------------------------------


def test_s10_dry_run_preserved_and_task65_tracking_intact():
    print("S10: every policy stays dry-run and leaves Task 6.5 tracking intact")

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
            plan_id=f"p10-{policy.value}",
        )
        attach_accounts(
            plan, {ACC1: make_account(ACC1), ACC2: make_account(ACC2)}
        )
        execution_id = f"exec-10-{policy.value}"

        _, batch = dispatch_plan(integration, plan, execution_id, calls)
        results = results_by_sequence(plan, batch)
        seq_a = sequence_of(plan, order_a)
        seq_b = sequence_of(plan, order_b)

        # The FAILED result arrives FIRST, the success afterwards: the
        # arrival order must not matter, and each result must touch ONLY
        # its own order record (Task 6.5 stays intact under the policy).
        assert integration.record_order_result(
            execution_id, seq_b, results[seq_b]
        ) is ExecutionStatus.FAILED
        assert integration.record_order_result(
            execution_id, seq_a, results[seq_a]
        ) is ExecutionStatus.REGISTERED
        assert statuses(integration, execution_id, (seq_a, seq_b)) == {
            seq_a: ExecutionStatus.REGISTERED,
            seq_b: ExecutionStatus.FAILED,
        }
        records = records_of(integration, execution_id, (seq_a, seq_b))
        assert records[seq_a].account_id == ACC1
        assert records[seq_b].account_id == ACC2

        # The brake state is exactly the policy's explicit decision.
        if policy is StopPolicy.NONE:
            assert integration.stopped_accounts == ()
            assert integration.brake_policy.is_global_stopped is False
            assert integration.brake_policy.should_continue([ACC2]) is True
        elif policy is StopPolicy.ACCOUNT:
            assert integration.stopped_accounts == (ACC1,)
            assert integration.brake_policy.is_global_stopped is False
            assert integration.brake_policy.should_continue([ACC2]) is True
        else:  # StopPolicy.GLOBAL
            assert integration.brake_policy.is_global_stopped is True
            assert integration.brake_policy.should_continue([ACC2]) is False

        # --- a FUTURE dispatch of the still-running account -------------------
        follow_id = f"exec-10-follow-{policy.value}"
        order_c = make_order(SYM_A, price=120, quantity=3)
        follow_plan = account_plan(ACC2, order_c, f"p10-follow-{policy.value}")
        follow_outcome, follow_calls = dispatch_plan(
            integration, follow_plan, follow_id, calls
        )
        if policy is StopPolicy.GLOBAL:
            # Braked: bypassed BEFORE anything is sent or registered.
            assert follow_outcome.mode == STOPPED_MODE
            assert follow_calls == []
            assert follow_id not in tracker._records
        else:
            # The still-running account keeps sending (dry-run, tracked).
            assert follow_outcome.mode != STOPPED_MODE
            assert len(follow_calls) == 1
            assert follow_id in tracker._records
            follow_seq = sequence_of(follow_plan, order_c)
            follow_results = results_by_sequence(follow_plan, follow_calls)
            assert integration.record_order_result(
                follow_id, follow_seq, follow_results[follow_seq]
            ) is ExecutionStatus.FAILED  # result_by_account blocks ACC2
            # A FAILED result never brakes anything.
            assert integration.stopped_accounts == (
                () if policy is StopPolicy.NONE else (ACC1,)
            )
            assert statuses(integration, follow_id, (follow_seq,)) == {
                follow_seq: ExecutionStatus.FAILED
            }

        # --- what was already sent is untouched -------------------------------
        # No order was ever sent twice (no re-send / cancel / modify path).
        sent_orders = [c["order"] for c in calls]
        assert len(sent_orders) == len({id(o) for o in sent_orders})
        assert statuses(integration, execution_id, (seq_a, seq_b)) == {
            seq_a: ExecutionStatus.REGISTERED,
            seq_b: ExecutionStatus.FAILED,
        }
        assert (
            records_of(integration, execution_id, (seq_a, seq_b))[seq_a]
            is records[seq_a]
        )
        assert (
            records_of(integration, execution_id, (seq_b,))[seq_b]
            is records[seq_b]
        )

    # Dry-run end to end: the engine was NEVER asked to go live, for any
    # policy, and no API / broker call / scheduler was added.
    assert all(call["live"] is False for call in calls)
    print()
# ---------------------------------------------------------------------------
# Runner (pytest-free execution: python test_block6_task6.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    scenarios = [
        test_s1_none_policy_keeps_every_account_sending,
        test_s2_account_policy_brakes_only_the_registered_account,
        test_s3_account_policy_is_symmetric,
        test_s4_global_policy_brakes_every_account,
        test_s5_failed_result_never_activates_a_brake,
        test_s6_orders_already_sent_stay_untouched_by_a_brake,
        test_s7_policy_is_independent_of_arrival_order_and_index,
        test_s8_invalid_or_unknown_account_fails_closed,
        test_s9_invalid_policy_fails_closed,
        test_s10_dry_run_preserved_and_task65_tracking_intact,
    ]
    failures = 0
    for scenario in scenarios:
        try:
            scenario()
        except Exception as exc:  # pragma: no cover - diagnostic path
            failures += 1
            print(f"FAILED  {scenario.__name__}: {exc!r}")
        else:
            print(f"PASSED  {scenario.__name__}")
    print(f"SCENARIOS PASSED: {len(scenarios) - failures} / FAILED: {failures}")
    sys.exit(1 if failures else 0)